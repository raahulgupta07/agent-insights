"""Shared HTML skeleton + small render helpers for report emails.

The assembler owns the skeleton (title bar, intro slot, body slot, footer); a
mode renderer only produces the inner pieces. Inline styles only — email clients
don't load <style>/external CSS. Warm clay palette to match the app.
"""
from __future__ import annotations

import html as _h
import re
from typing import Optional

ACCENT = "#C2541E"
INK = "#222"
MUTED = "#9a958c"
LINE = "#eee"

# columns whose values read better right-aligned / money-formatted
_NUM_HINT = re.compile(r"(revenue|amount|total|price|cost|sales|qty|quantity|count|sold|value|sum|avg|rate|pct|percent)", re.I)
_MONEY_HINT = re.compile(r"(revenue|amount|total|price|cost|sales|value|spend)", re.I)


def _is_num_col(name: str) -> bool:
    return bool(_NUM_HINT.search(name or ""))


def _fmt_cell(col: str, v) -> str:
    if v is None:
        return ""
    if _MONEY_HINT.search(col or ""):
        try:
            return f"${float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    return str(v)


def table_html(result: dict, max_rows: int = 50) -> str:
    """Render {columns, rows} into a zebra-striped inline-styled HTML table."""
    if not result or not result.get("rows"):
        return ""
    rows = result["rows"]
    cols = result.get("columns") or (list(rows[0].keys()) if isinstance(rows[0], dict) else [])
    pretty = {c: re.sub(r"(?<!^)(?=[A-Z])", " ", str(c)).replace("_", " ").strip() for c in cols}

    def align(c):
        return "right" if _is_num_col(c) else "left"

    head = "".join(
        f"<th style='padding:8px 12px;border-bottom:2px solid #333;text-align:{align(c)};"
        f"font-size:13px;white-space:nowrap'>{_h.escape(pretty.get(c, str(c)))}</th>"
        for c in cols
    )
    body = ""
    for i, r in enumerate(rows[:max_rows]):
        bg = "#fafafa" if i % 2 else "#fff"
        if isinstance(r, dict):
            tds = "".join(
                f"<td style='padding:7px 12px;border-bottom:1px solid {LINE};text-align:{align(c)};font-size:13px'>"
                f"{_h.escape(_fmt_cell(c, r.get(c)))}</td>"
                for c in cols
            )
        else:
            tds = "".join(
                f"<td style='padding:7px 12px;border-bottom:1px solid {LINE};font-size:13px'>{_h.escape(str(v))}</td>"
                for v in r
            )
        body += f"<tr style='background:{bg}'>{tds}</tr>"
    extra = ""
    if len(rows) > max_rows:
        extra = f"<p style='font-size:11px;color:{MUTED};margin:6px 0 0'>+{len(rows) - max_rows} more rows</p>"
    return (
        "<table style='border-collapse:collapse;width:100%;max-width:600px;"
        "font-family:Segoe UI,Arial,sans-serif'>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{extra}"
    )


def insights_html(insights: list[tuple[str, str]]) -> str:
    if not insights:
        return ""
    items = "".join(
        f"<li style='margin:0 0 10px'><b style='color:#1a1a1a'>{_h.escape(t)}.</b> {d}</li>"
        for t, d in insights
    )
    return (
        f"<h3 style='margin:24px 0 8px;font-size:15px;border-bottom:1px solid {LINE};"
        "padding-bottom:4px;font-family:Segoe UI,Arial,sans-serif'>Key insights</h3>"
        f"<ul style='margin:0;padding-left:18px;font-size:13.5px;line-height:1.5'>{items}</ul>"
    )


def sql_block(sql: Optional[str]) -> str:
    if not sql:
        return ""
    return (
        "<details style='margin-top:14px'>"
        f"<summary style='cursor:pointer;color:{MUTED};font-size:12px'>View SQL</summary>"
        "<pre style='background:#f6f8fa;border:1px solid #eee;border-radius:6px;padding:10px;"
        f"font-size:12px;overflow:auto;white-space:pre'>{_h.escape(sql)}</pre></details>"
    )


def skeleton(*, title: str, meta: str, inner_html: str, report_url: Optional[str], footer: str) -> str:
    """Wrap a renderer's inner_html in the shared shell."""
    link = ""
    if report_url:
        link = (
            f"<a href='{_h.escape(report_url)}' style='display:inline-block;margin-top:16px;"
            f"color:{ACCENT};font-size:13px;text-decoration:none'>Open report ↗</a>"
        )
    return (
        "<div style=\"font-family:Segoe UI,Arial,sans-serif;color:%s;max-width:640px;"
        "margin:0 auto;padding:8px 4px;line-height:1.5\">"
        "<h2 style='margin:0 0 2px;font-size:20px'>%s</h2>"
        "<p style='margin:0 0 18px;color:%s;font-size:13px'>%s</p>"
        "%s%s"
        "<p style='margin:22px 0 0;color:#aaa;font-size:11px'>%s</p>"
        "</div>"
    ) % (INK, _h.escape(title), MUTED, _h.escape(meta), inner_html, link, _h.escape(footer))
