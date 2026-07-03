"""Unit tests — Shared Memory leak firewall + access gate (P1).

Run: python -m pytest backend/tests/test_shared_memory_firewall.py -q
No DB, no network — pure functions.
"""
from app.services.knowledge import sanitize as S
from app.services.knowledge import access as A
from app.services.knowledge import scope_resolver as R


# --- sanitize: DATA must NOT survive; STRUCTURE must ------------------------

def test_template_parameterizes_literals():
    r = S.sanitize_template("EVALUATE FILTER(projects, projects[status]=\"Discontinued\" && projects[year]=2024)")
    assert r.ok
    assert "Discontinued" not in r.content
    assert "2024" not in r.content
    assert "{value}" in r.content
    assert "projects" in r.content  # table/column names are structure -> kept


def test_result_rows_dropped():
    payload = {
        "table": "projects",
        "meaning": "project status rollup",
        "rows": [{"status": "On Track", "n": 100}, {"status": "Discontinued", "n": 37}],
        "total": 258,
    }
    r = S.sanitize_content(payload)
    assert r.ok
    assert "rows" not in r.content and "total" not in r.content   # data keys dropped
    assert r.content["table"] == "projects"                        # structure kept
    assert "Discontinued" not in str(r.content)
    assert "258" not in str(r.content)


def test_bare_data_value_string_dropped():
    assert S.sanitize_content("Discontinued").ok is False or S.sanitize_content("2026-01-01").ok is False
    assert S.looks_like_data_value("2026-01-01")
    assert S.looks_like_data_value("1,234,567")
    assert not S.looks_like_data_value("project_status")


def test_guid_and_email_redacted():
    txt = "owner a1b2c3d4-e5f6-7788-99aa-bbccddeeff00 emailed jane@acme.com"
    clean, n = S.redact_text(txt)
    assert n >= 2 and "acme.com" not in clean and "a1b2c3d4" not in clean


def test_mistake_shape_survives_but_no_values():
    payload = {
        "kind": "mistake",
        "error_class": "cannot find table",
        "fix_shape": "use bare DAX table name, not Dataset/Table",
        "query_template": "EVALUATE TOPN(1, 'Sales'[Region] = \"North\")",
    }
    r = S.sanitize_content(payload)
    assert r.ok
    assert "North" not in str(r.content)
    assert r.content["error_class"] == "cannot find table"


# --- access gate: intersection + private isolation -------------------------

MODEL_PM = {"scope_kind": "model", "scope_key": "ad16d612"}
MODEL_X = {"scope_kind": "model", "scope_key": "zzz-other"}


def test_shared_visible_only_within_intersection():
    # U2 holds ProjectMgmt only
    u2_scopes = [MODEL_PM]
    row = {"scope_kind": "model", "scope_key": "ad16d612"}
    assert A.can_view(row, "u2", u2_scopes) is True
    # U4 does not hold ProjectMgmt
    u4_scopes = [MODEL_X]
    assert A.can_view(row, "u4", u4_scopes) is False


def test_private_never_crosses_users():
    row = {"scope_kind": "user", "scope_key": "u1"}
    assert A.can_view(row, "u1", []) is True     # owner sees own
    assert A.can_view(row, "u2", [MODEL_PM]) is False  # nobody else


def test_visible_pairs_include_own_private():
    pairs = A.visible_scope_pairs("u2", [MODEL_PM])
    assert ("model", "ad16d612") in pairs
    assert ("user", "u2") in pairs


def test_resolver_model_scope_matches_access():
    class T:
        def __init__(s, name, meta): s.name = name; s.metadata_json = meta
    tables = [T("projects", {"powerbi": {"datasetId": "ad16d612"}})]
    class DS: type = "powerbi_user"
    scopes = R.resolve_agent_scopes(DS(), tables)
    assert scopes == [{"scope_kind": "model", "scope_key": "ad16d612"}]
    # a learning captured under this scope is visible to a holder, not to others
    row = {"scope_kind": "model", "scope_key": "ad16d612"}
    assert A.can_view(row, "holder", scopes) is True
    assert A.can_view(row, "outsider", []) is False
