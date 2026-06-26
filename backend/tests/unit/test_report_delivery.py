"""Unit tests for the universal report-delivery layer
(``app.services.report_delivery``).

Deterministic, NO-DB, NO-LLM, NO-network — safe for CI. We only exercise the
pure / sync surface:
- ``extract.sanitize_chat_content`` / ``extract.split_intro_and_insights`` /
  ``extract._normalize_result``  (the DB-backed ``extract_result`` /
  ``latest_narrative`` are NOT tested here).
- ``template.table_html`` / ``insights_html`` / ``sql_block`` / ``skeleton``.
- ``contract.register_renderer`` / ``get_renderer`` / ``list_modes`` and the
  plain dataclasses.

No event loop, no async, no app conftest fixtures are required.
"""

from __future__ import annotations

from app.services.report_delivery import extract, template, contract


# --------------------------------------------------------------------------
# 1. sanitize_chat_content
# --------------------------------------------------------------------------

def test_sanitize_strips_all_chat_artifacts():
    raw = (
        "**🧠 Planning (unknown) ✓**\n\n"
        "Here are the real sales results for Q3.\n\n"
        "```python\nprint('tool code that must vanish')\n```\n\n"
        "| Artist | Revenue |\n"
        "| --- | --- |\n"
        "| Foo | 100 |\n"
        "| Bar | 200 |\n\n"
        "The full detail is visible in the interactive table generated above.\n\n"
        "def generate_df(conn):\n"
        "    return conn.execute('SELECT 1')\n"
    )
    out = extract.sanitize_chat_content(raw)

    # real prose survives
    assert "Here are the real sales results for Q3." in out

    # planning marker gone
    assert "🧠" not in out
    assert "Planning" not in out

    # fenced code gone
    assert "```" not in out
    assert "tool code that must vanish" not in out

    # generate_df tail gone
    assert "generate_df" not in out
    assert "SELECT 1" not in out

    # markdown pipe table gone
    assert "| Artist |" not in out
    assert "Foo" not in out and "Bar" not in out

    # "table generated above" reference gone
    assert "generated above" not in out
    assert "interactive table" not in out


def test_sanitize_empty_and_none():
    assert extract.sanitize_chat_content(None) == ""
    assert extract.sanitize_chat_content("") == ""
    assert extract.sanitize_chat_content("   ") == ""


# --------------------------------------------------------------------------
# 2. split_intro_and_insights
# --------------------------------------------------------------------------

def test_split_intro_and_insights():
    narrative = (
        "I'll query the warehouse for the numbers.\n\n"
        "This report breaks down revenue by region for the quarter.\n\n"
        "Analysis\n\n"
        "**Leader** The North region drove the largest share of revenue this "
        "quarter, climbing well past every other territory.\n\n"
        "**Laggard** The South region underperformed against its target by a "
        "wide and concerning margin all quarter long.\n\n"
        "Query Result\n"
    )
    intro, insights = extract.split_intro_and_insights(narrative)

    # intro is non-empty and not the planning preamble
    assert intro
    assert "I'll query" not in intro
    assert "revenue by region" in intro

    # insights is a list of (title, body) tuples
    assert isinstance(insights, list)
    assert len(insights) >= 2
    titles = [t for t, _ in insights]
    assert "Leader" in titles
    assert "Laggard" in titles
    for title, body in insights:
        assert isinstance(title, str) and title
        assert isinstance(body, str) and len(body) > 15


def test_split_converts_bold_to_b_tag():
    narrative = (
        "Summary paragraph with a **bolded** word in it for the intro.\n\n"
        "Analysis\n\n"
        "**Key Point** The metric moved by a **huge** amount versus the prior "
        "period and deserves attention from the team right away.\n"
    )
    intro, insights = extract.split_intro_and_insights(narrative)

    # bold in intro becomes <b>
    assert "<b>bolded</b>" in intro
    assert "**" not in intro

    # bold inside an insight body becomes <b>
    assert insights
    _, body = insights[0]
    assert "<b>huge</b>" in body
    assert "**" not in body


# --------------------------------------------------------------------------
# 3. _normalize_result
# --------------------------------------------------------------------------

def test_normalize_dict_columns_objects():
    data = {
        "rows": [{"X": 1, "Y": 2}, {"X": 3, "Y": 4}],
        "columns": [{"field": "X"}, {"field": "Y"}],
    }
    out = extract._normalize_result(data, None)
    assert out is not None
    assert out["columns"] == ["X", "Y"]          # plain strings
    assert out["rows"] == data["rows"]
    assert out["sql"] is None


def test_normalize_list_of_dicts_infers_columns():
    data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    out = extract._normalize_result(data, None)
    assert out is not None
    assert out["columns"] == ["a", "b"]
    assert out["rows"] == data


def test_normalize_extracts_select_from_python_wrapper():
    code = (
        "def generate_df(conn):\n"
        '    sql = """SELECT name, revenue FROM sales ORDER BY revenue DESC"""\n'
        "    return conn.execute(sql)\n"
    )
    data = [{"name": "A", "revenue": 10}]
    out = extract._normalize_result(data, code)
    assert out is not None
    assert out["sql"] == "SELECT name, revenue FROM sales ORDER BY revenue DESC"


def test_normalize_bare_select_code():
    out = extract._normalize_result(
        [{"n": 1}], "SELECT n FROM t"
    )
    assert out is not None
    assert out["sql"] == "SELECT n FROM t"


def test_normalize_returns_none_for_empty():
    assert extract._normalize_result({"rows": [], "columns": ["X"]}, None) is None
    assert extract._normalize_result([], None) is None
    assert extract._normalize_result({}, None) is None
    assert extract._normalize_result("not-json-{", None) is None


# --------------------------------------------------------------------------
# 4. template.table_html
# --------------------------------------------------------------------------

def test_table_html_row_count_and_money_format():
    rows = [{"Artist": f"A{i}", "Revenue": float(i)} for i in range(3)]
    result = {"columns": ["Artist", "Revenue"], "rows": rows}
    out = template.table_html(result)

    assert "<table" in out
    # 1 header <tr> + 3 body <tr> = 4
    assert out.count("<tr") == 4
    # money column formatted with $
    assert "$0.00" in out
    assert "$1.00" in out
    # no overflow note for a small table
    assert "more rows" not in out


def test_table_html_caps_at_50_with_more_note():
    rows = [{"Revenue": float(i)} for i in range(60)]
    result = {"columns": ["Revenue"], "rows": rows}
    out = template.table_html(result)

    # 1 header + 50 capped body rows = 51
    assert out.count("<tr") == 51
    assert "+10 more rows" in out


def test_table_html_empty():
    assert template.table_html({}) == ""
    assert template.table_html({"rows": []}) == ""


# --------------------------------------------------------------------------
# 5. skeleton + insights_html + sql_block fragments
# --------------------------------------------------------------------------

def test_insights_html_fragment():
    out = template.insights_html([("Leader", "did great things this quarter")])
    assert "Key insights" in out
    assert "Leader" in out
    assert "did great things this quarter" in out
    assert template.insights_html([]) == ""


def test_sql_block_fragment():
    out = template.sql_block("SELECT 1")
    assert "View SQL" in out
    assert "SELECT 1" in out
    assert template.sql_block(None) == ""


def test_skeleton_escapes_title_and_embeds_inner():
    out = template.skeleton(
        title="Q3 <Sales> & More",
        meta="generated today",
        inner_html="<p id='inner'>BODY</p>",
        report_url="https://example.com/r/1",
        footer="auto footer",
    )
    # title HTML-escaped
    assert "Q3 &lt;Sales&gt; &amp; More" in out
    assert "<Sales>" not in out
    # inner html embedded raw
    assert "<p id='inner'>BODY</p>" in out
    # report link rendered
    assert "Open report" in out
    assert "https://example.com/r/1" in out
    # footer present
    assert "auto footer" in out


# --------------------------------------------------------------------------
# 6. contract registry
# --------------------------------------------------------------------------

def test_register_and_get_renderer():
    mode = "test_dummy"

    def _dummy(ctx: contract.DeliveryContext) -> contract.DeliveryParts:
        return contract.DeliveryParts(body_html="<p>dummy</p>")

    contract.register_renderer(mode, _dummy)
    assert contract.get_renderer(mode) is _dummy
    assert mode in contract.list_modes()
    # list_modes is sorted
    assert contract.list_modes() == sorted(contract.list_modes())

    # the renderer actually builds parts from a plain context (no DB)
    ctx = contract.DeliveryContext(report_id="r1", organization_id="o1")
    parts = contract.get_renderer(mode)(ctx)
    assert isinstance(parts, contract.DeliveryParts)
    assert parts.body_html == "<p>dummy</p>"
    assert parts.inline_images == []
    assert parts.attachments == []


def test_get_renderer_missing_returns_none():
    assert contract.get_renderer("no_such_mode_xyz") is None
