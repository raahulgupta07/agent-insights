"""table_card — Unified Table Card (+ approved Shared-Memory overlay).

Today the planner sees every context layer for a table piecemeal (schema from one
builder, semantic meaning from another, code-enrich / data-quality from
metadata_json, freshness/owner/PII from governance). This module MERGES all of
them into ONE structured card per table, then OVERLAYS approved Shared-Memory
corrections/mistakes on top so the agent reads a single "corrected baseline"
(the OpenAI data-agent pattern) rather than reconstructing it every turn.

Contract:
  * ``build_table_card`` — async, fail-soft merge → compact dict.
  * ``render_card``      — pure, dict → ONE tight text block for the planner.
  * ``overlay_memory``   — pure, fold recall_items() corrections into the card.

Design rules (CLAUDE.md):
  * Gate on ``flags.TABLE_CARD`` (HYBRID_TABLE_CARD). OFF → callers no-op.
  * NEVER raises — every stage guarded; a missing layer degrades to less card.
  * Additive: reads existing stores (DataSourceTable / SemanticTable / metadata),
    writes nothing. Does not touch any shared/context/agent file.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select

from app.settings.hybrid_flags import flags

logger = logging.getLogger("app.services.knowledge.table_card")

# Bound the card so it can never balloon the planner prompt.
_MAX_COLUMNS = 40
_MAX_VALUES = 6
_MAX_FORMULAS = 12
_MAX_CORRECTIONS = 12


# ---------------------------------------------------------------------------
# small attr helpers (accept ORM row OR plain dict OR bare string)
# ---------------------------------------------------------------------------

def _attr(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _table_name(table: Any) -> str:
    if isinstance(table, str):
        return table.strip()
    return str(_attr(table, "name", "") or "").strip()


def _meta(obj: Any) -> dict:
    m = _attr(obj, "metadata_json")
    return m if isinstance(m, dict) else {}


def _raw_columns(table: Any) -> list[dict]:
    """The column dict list, from DataSourceTable.columns or its ConnectionTable."""
    cols = _attr(table, "columns")
    if not cols:
        ct = _attr(table, "connection_table")
        if ct is not None:
            cols = _attr(ct, "columns")
    out: list[dict] = []
    for c in cols or []:
        if isinstance(c, dict):
            out.append(c)
        else:  # ORM column-ish object
            out.append({
                "name": _attr(c, "name", ""),
                "dtype": _attr(c, "dtype", _attr(c, "type", "")),
                "metadata": _attr(c, "metadata", {}),
            })
    return out


# ---------------------------------------------------------------------------
# semantic layer (approved only)
# ---------------------------------------------------------------------------

async def _load_semantic(db, organization_id: str, ds_id: str, table_name: str):
    """Return (SemanticTable | None, {col_name: meaning}, [pii_col_names])."""
    try:
        from app.models.semantic_table import SemanticTable, SemanticColumn

        stmt = (
            select(SemanticTable)
            .where(SemanticTable.organization_id == str(organization_id))
            .where(SemanticTable.data_source_id == str(ds_id))
            .where(SemanticTable.table_name == table_name)
            .where(SemanticTable.status == "approved")
        )
        try:  # bi-temporal: only currently-valid rows (no-op when flag OFF)
            from app.ai.brain import bitemporal
            cond = bitemporal.current_condition(SemanticTable)
            if cond is not None:
                stmt = stmt.where(cond)
        except Exception:
            pass
        st = (await db.execute(stmt)).scalars().first()
        if st is None:
            return None, {}, []

        meanings: dict[str, str] = {}
        pii_cols: list[str] = []
        cols = (await db.execute(
            select(SemanticColumn)
            .where(SemanticColumn.semantic_table_id == str(st.id))
            .where(SemanticColumn.status == "approved")
        )).scalars().all()
        for c in cols:
            if getattr(c, "pii", False):
                pii_cols.append(c.name)
            if c.meaning and str(c.meaning).strip():
                meanings[c.name] = str(c.meaning).strip()
        return st, meanings, pii_cols
    except Exception as e:  # pragma: no cover
        logger.debug("table_card: semantic load failed for %s: %s", table_name, e)
        return None, {}, []


def _freshness_label(sem_table: Any, ds_last_synced: Any) -> str:
    """Staleness label from governance fields (mirrors the semantic builder)."""
    try:
        from datetime import datetime, timezone, timedelta
        refreshed = _attr(sem_table, "last_refreshed_at") or ds_last_synced
        if not refreshed:
            return ""
        ref = refreshed if getattr(refreshed, "tzinfo", None) else refreshed.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ref
        days = max(0, int(age.total_seconds() // 86400))
        sla = _attr(sem_table, "freshness_sla_hours")
        if sla and age > timedelta(hours=int(sla)):
            return f"stale {days}d"
        return "fresh" if days == 0 else f"{days}d old"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# public: build
# ---------------------------------------------------------------------------

async def build_table_card(
    db,
    *,
    organization_id: str,
    data_source: Any,
    table: Any,
) -> dict:
    """Merge every available context layer for ONE table into a compact dict.

    Fail-soft: whatever exists is folded in; missing layers are simply absent.
    Returns ``{}`` when the flag is OFF or the table has no name.
    """
    if not flags.TABLE_CARD:
        return {}
    try:
        return await _build_table_card(
            db, organization_id=organization_id, data_source=data_source, table=table
        )
    except Exception as e:  # pragma: no cover — never raise into a builder
        logger.debug("table_card.build_table_card failed: %s", e)
        return {}


async def _build_table_card(db, *, organization_id, data_source, table) -> dict:
    table_name = _table_name(table)
    if not table_name:
        return {}
    ds_id = str(_attr(data_source, "id", data_source) or "")

    meta = _meta(table)
    pipeline = meta.get("pipeline_logic") if isinstance(meta.get("pipeline_logic"), dict) else {}
    dq = meta.get("data_quality") if isinstance(meta.get("data_quality"), dict) else {}

    sem_table, meanings, pii_cols = await _load_semantic(
        db, organization_id, ds_id, table_name
    )

    # --- columns: schema + example values (learn-from-data) + meaning ---------
    columns: list[dict] = []
    for c in _raw_columns(table)[:_MAX_COLUMNS]:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        cmeta = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
        vals = cmeta.get("values")
        if isinstance(vals, list):
            vals = [str(v) for v in vals[:_MAX_VALUES]]
        else:
            vals = []
        columns.append({
            "name": name,
            "dtype": str(c.get("dtype") or c.get("type") or "").strip(),
            "meaning": meanings.get(name, ""),
            "values": vals,
            "pii": name in pii_cols,
        })

    # --- freshness / owner / PII ---------------------------------------------
    ds_last_synced = _attr(data_source, "last_synced_at")
    freshness = _freshness_label(sem_table, ds_last_synced)

    card: dict = {
        "table": table_name,
        "description": (_attr(sem_table, "description") or "").strip(),
        "use_cases": [
            str(u) for u in (_attr(sem_table, "use_cases") or []) if str(u).strip()
        ],
        "grain": str(pipeline.get("grain") or "").strip(),
        "formulas": [
            f for f in (pipeline.get("formulas") or [])[:_MAX_FORMULAS]
            if isinstance(f, dict) and f.get("col")
        ],
        "population": str(pipeline.get("population") or "").strip(),
        "data_quality": dq,
        "columns": columns,
        "owner": (_attr(sem_table, "owner") or "").strip(),
        "pii": bool(_attr(sem_table, "pii", False)) or bool(pii_cols),
        "pii_columns": pii_cols,
        "freshness": freshness,
        "corrections": [],   # filled by overlay_memory()
    }
    return card


# ---------------------------------------------------------------------------
# public: memory overlay (pure)
# ---------------------------------------------------------------------------

def _correction_line(row: Any) -> str:
    """Render one AgentKnowledge row as a correction line (mirrors retrieve._line)."""
    try:
        from app.services.knowledge.retrieve import _line
        return _line(row)
    except Exception:
        title = (_attr(row, "title") or _attr(row, "kind") or "").strip()
        return f"- {title}: {_attr(row, 'text') or ''}".strip()


def _mentions_table(row: Any, table_name: str) -> bool:
    tl = table_name.lower()
    for part in (_attr(row, "title"), _attr(row, "text")):
        if part and tl in str(part).lower():
            return True
    c = _attr(row, "content_json")
    if isinstance(c, dict):
        for v in c.values():
            if isinstance(v, str) and tl in v.lower():
                return True
    return False


def overlay_memory(card: dict, recall_items: list[Any]) -> dict:
    """Fold approved Shared-Memory corrections/mistakes onto the card.

    ``recall_items`` = already scope-filtered AgentKnowledge rows from
    ``services.knowledge.retrieve.recall_items`` (access already enforced there).
    We keep the ones that apply to THIS table: mistakes (a correction that always
    applies to the scope) and any item that names this table. Pure — mutates a
    shallow copy and returns it. Never raises.
    """
    if not isinstance(card, dict) or not card:
        return card
    try:
        table_name = str(card.get("table") or "")
        picked: list[str] = []
        seen: set[str] = set()
        for r in recall_items or []:
            kind = _attr(r, "kind")
            # mistakes are corrective-by-nature; other kinds must name the table
            if kind != "mistake" and not (table_name and _mentions_table(r, table_name)):
                continue
            line = _correction_line(r)
            if line and line not in seen:
                seen.add(line)
                picked.append(line)
            if len(picked) >= _MAX_CORRECTIONS:
                break
        out = dict(card)
        out["corrections"] = picked
        return out
    except Exception as e:  # pragma: no cover
        logger.debug("table_card.overlay_memory failed: %s", e)
        return card


# ---------------------------------------------------------------------------
# public: render (pure)
# ---------------------------------------------------------------------------

def render_card(card: dict) -> str:
    """One tight text block for planner injection. Empty string on empty card."""
    if not isinstance(card, dict) or not card.get("table"):
        return ""
    try:
        t = card
        lines: list[str] = [f"<table_card name=\"{t['table']}\">"]
        if t.get("description"):
            lines.append(f"  desc: {t['description']}")
        if t.get("grain"):
            lines.append(f"  grain: {t['grain']}")
        if t.get("population"):
            lines.append(f"  population: {t['population']}")
        if t.get("use_cases"):
            lines.append("  use cases: " + ", ".join(t["use_cases"]))

        # governance
        gparts: list[str] = []
        if t.get("owner"):
            gparts.append(f"owner={t['owner']}")
        if t.get("freshness"):
            gparts.append(t["freshness"])
        if t.get("pii_columns"):
            gparts.append("PII: " + ", ".join(t["pii_columns"]))
        elif t.get("pii"):
            gparts.append("PII table")
        if gparts:
            lines.append("  governance: " + " · ".join(gparts))

        # formulas
        for f in t.get("formulas") or []:
            expr = str(f.get("expr") or "").strip()
            if f.get("col") and expr:
                lines.append(f"  formula {f['col']} = {expr}")

        # data quality (findings only)
        dq = t.get("data_quality") or {}
        if isinstance(dq, dict):
            findings = dq.get("findings") or dq.get("issues")
            if isinstance(findings, list) and findings:
                lines.append("  data quality: " + "; ".join(str(x) for x in findings[:4]))

        # columns
        for c in t.get("columns") or []:
            seg = f"  - {c['name']}"
            if c.get("dtype"):
                seg += f" ({c['dtype']})"
            if c.get("meaning"):
                seg += f" -> {c['meaning']}"
            if c.get("pii"):
                seg += " [PII]"
            if c.get("values"):
                seg += "  e.g. " + ", ".join(c["values"])
            lines.append(seg)

        # corrected baseline (overlay) — LAST so it's the strongest signal
        if t.get("corrections"):
            lines.append("  Corrections (always apply):")
            for line in t["corrections"]:
                lines.append("    " + line.lstrip("- ").rstrip())

        lines.append("</table_card>")
        return "\n".join(lines)
    except Exception as e:  # pragma: no cover
        logger.debug("table_card.render_card failed: %s", e)
        return ""
