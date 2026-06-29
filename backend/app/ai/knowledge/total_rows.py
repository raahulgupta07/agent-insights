"""Pre-aggregated total-row detection (Ingest Task T2).

Some uploaded spreadsheets/CSVs carry **already-summed** subtotal rows mixed in
with the detail rows — e.g. a column ``site`` holds per-site values PLUS rows
where ``site = 'ALL Total'`` that are the sum across every site.  A naive
``SUM(value)`` over the whole table then double-counts (the subtotal + the
detail rows it summed) → 1200 instead of 1000.

This module detects those rows at ingest *profiling* time (the DataFrame is
already in hand), records conservative markers into the
``DataSourceTable.metadata_json['total_row_markers']`` (plus an estimated
``total_row_count``), and auto-emits a guardrail :class:`Instruction` the agent
reads so it can exclude them (``WHERE site NOT ILIKE '%total%'``).

Gate: ``flags.TOTAL_ROW``.  When OFF this module is a pure no-op.  Pure pandas,
no eval/exec, no SQL execution of the emitted text.  Fail-soft on every step —
ingest is never broken.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Heuristic tuning knobs (conservative by design)
# ---------------------------------------------------------------------------
# "Strong" tokens are unambiguous roll-up labels → flag on the value alone.
_STRONG_TOKENS = {"total", "all total", "grand total", "subtotal",
                  "sub total", "overall", "grand_total"}
# "Weak" tokens are common real values too ('all', 'sum') → only flag when the
# row also has the rolled-up SHAPE (other dimensions blank).
_WEAK_TOKENS = {"all", "sum", "any", "everything"}
# A matched value flagging >= this share of rows is almost certainly real data
# (or the whole column is that value) → never flag it.
_MAX_ROW_SHARE = 0.60
# A column is only a candidate "dimension" when its distinct count stays under
# this cap (totals live in low-cardinality group keys, not free-text/ids).
_DIM_MAX_DISTINCT = 200
# Fraction of OTHER dimension cells that must be blank in matched rows for a
# weak-token (or borderline) match to qualify as a rolled-up row.
_BLANK_SIBLING_FRAC = 0.80
# Never scan absurdly large frames row-by-row; a head sample is enough to spot
# the labels and estimate the count.
_MAX_SCAN_ROWS = 200_000


def _norm(v: Any) -> str:
    """casefold + strip + collapse internal whitespace for token compare."""
    s = str(v).strip().casefold()
    return re.sub(r"\s+", " ", s)


def _is_blankish(v: Any) -> bool:
    try:
        import pandas as pd  # local import keeps module import cheap
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return True
    except Exception:  # noqa: BLE001
        if v is None:
            return True
    s = str(v).strip()
    return s == "" or s.lower() in {"nan", "none", "null"}


def _looks_total(norm_val: str) -> Optional[str]:
    """Return 'strong' / 'weak' / None for a normalized cell value."""
    if not norm_val:
        return None
    if norm_val in _STRONG_TOKENS:
        return "strong"
    # contains 'total'/'subtotal'/'grand total' as a word → strong
    if re.search(r"\b(grand\s+total|sub\s*total|total|overall)\b", norm_val):
        return "strong"
    if norm_val in _WEAK_TOKENS:
        return "weak"
    return None


def detect_total_rows(df) -> List[Dict[str, Any]]:
    """Detect likely pre-aggregated total/subtotal rows in a DataFrame.

    Returns a list of marker dicts (possibly empty), each::

        {
            "column": "site",
            "values": ["ALL Total"],          # the literal total labels seen
            "matched_rows": 131,              # rows flagged via this column
            "confidence": "high" | "suggestion",
            "reason": "low-cardinality dimension matched roll-up label",
        }

    Pure pandas, never raises.  Conservative: a value is only flagged when it
    matches a roll-up token, sits in a low-cardinality dimension column, covers
    a *plausible* (< 60%) share of rows, and — for weak tokens — the matched
    rows also have other dimension columns blank (the rolled-up shape).
    """
    markers: List[Dict[str, Any]] = []
    try:
        import pandas as pd  # noqa: F401
    except Exception:  # noqa: BLE001
        return markers

    try:
        if df is None or len(df) == 0 or len(getattr(df, "columns", [])) == 0:
            return markers

        n_total = len(df)
        scan = df.head(_MAX_SCAN_ROWS) if n_total > _MAX_SCAN_ROWS else df
        n = len(scan)
        if n == 0:
            return markers

        # A double-count risk only exists if there's something to sum.
        has_measure = False
        dim_cols: List[str] = []
        for col in scan.columns:
            ser = scan[col]
            dtype = str(ser.dtype).lower()
            is_numeric = any(t in dtype for t in
                             ("int", "float", "numeric", "decimal", "double", "real"))
            if is_numeric and "datetime" not in dtype:
                has_measure = True
                continue
            if "datetime" in dtype or "date" in dtype:
                continue
            try:
                distinct = int(ser.nunique(dropna=True))
            except Exception:  # noqa: BLE001
                continue
            # low-cardinality, non-id-like categorical = candidate dimension
            if 0 < distinct <= min(_DIM_MAX_DISTINCT, max(2, int(n * 0.5))):
                dim_cols.append(col)

        if not has_measure or not dim_cols:
            return markers

        flagged_index = set()  # union of row positions flagged across columns

        for col in dim_cols:
            ser = scan[col]
            norm = ser.map(_norm)
            # group matched literal labels by their original spelling
            hits: Dict[str, set] = {}   # original value -> set(row positions)
            strengths: Dict[str, str] = {}
            for pos, (orig, nv) in enumerate(zip(ser.tolist(), norm.tolist())):
                strength = _looks_total(nv)
                if strength is None:
                    continue
                key = "" if _is_blankish(orig) else str(orig)
                if not key:
                    continue
                hits.setdefault(key, set()).add(pos)
                # strong wins over weak if a label hits both somehow
                if strengths.get(key) != "strong":
                    strengths[key] = strength

            if not hits:
                continue

            other_dims = [c for c in dim_cols if c != col]
            values: List[str] = []
            col_rows = set()
            confidence = "suggestion"
            for label, positions in hits.items():
                share = len(positions) / n
                if share >= _MAX_ROW_SHARE:
                    continue  # too big a slice → almost certainly real data
                strength = strengths.get(label, "weak")

                qualifies = strength == "strong"
                if not qualifies and other_dims:
                    # weak token: require the rolled-up shape (siblings blank)
                    blank_cells = 0
                    total_cells = 0
                    for pos in positions:
                        for oc in other_dims:
                            total_cells += 1
                            try:
                                if _is_blankish(scan[oc].iloc[pos]):
                                    blank_cells += 1
                            except Exception:  # noqa: BLE001
                                pass
                    if total_cells and (blank_cells / total_cells) >= _BLANK_SIBLING_FRAC:
                        qualifies = True
                elif not qualifies and not other_dims:
                    # single-dimension table + weak token → leave as suggestion
                    qualifies = True

                if not qualifies:
                    continue
                values.append(label)
                col_rows |= positions
                if strength == "strong":
                    confidence = "high"

            if values:
                # scale the sampled count back up to the full frame
                est_rows = len(col_rows)
                if n_total > n and n:
                    est_rows = int(round(est_rows * (n_total / n)))
                markers.append({
                    "column": col,
                    "values": sorted(set(values)),
                    "matched_rows": est_rows,
                    "confidence": confidence,
                    "reason": "low-cardinality dimension matched roll-up label"
                              + ("" if confidence == "high"
                                 else " with blank sibling dimensions"),
                })
                flagged_index |= col_rows

        return markers
    except Exception as e:  # noqa: BLE001
        logger.debug("detect_total_rows: %s", e)
        return markers


def estimate_total_row_count(markers: List[Dict[str, Any]]) -> int:
    """Upper-bound estimate of flagged rows (sum across column markers).

    Markers from different columns may overlap on the same physical rows, so
    this is an estimate, not an exact distinct count — good enough to surface in
    the guardrail text.
    """
    try:
        return int(sum(int(m.get("matched_rows", 0)) for m in markers))
    except Exception:  # noqa: BLE001
        return 0


def build_guardrail_text(table_name: str, markers: List[Dict[str, Any]]) -> str:
    """Render a human-readable guardrail / training instruction from markers.

    Example::

        Table 'sales': exclude pre-aggregated total rows before SUM/COUNT/AVG —
        131 rows are subtotals. Filter: WHERE site NOT ILIKE '%total%'
        (site IN ('ALL Total')). Counting these double-counts the detail rows.
    """
    if not markers:
        return ""
    filters: List[str] = []
    notes: List[str] = []
    total_rows = estimate_total_row_count(markers)
    for m in markers:
        col = m.get("column")
        vals = m.get("values") or []
        if not col:
            continue
        # ILIKE '%total%' catches the common case; the explicit IN(...) pins the
        # exact literals we actually saw (covers 'ALL'/'SUM' that ILIKE misses).
        quoted = ", ".join("'" + str(v).replace("'", "''") + "'" for v in vals)
        clause = f"{col} NOT ILIKE '%total%'"
        if quoted:
            clause += f" AND {col} NOT IN ({quoted})"
        filters.append(clause)
        tag = "" if m.get("confidence") == "high" else " (suspected)"
        notes.append(f"{col}={vals}{tag}")
    where = " AND ".join(filters)
    head = (
        f"Table '{table_name}' contains PRE-AGGREGATED total/subtotal rows "
        f"(~{total_rows} rows: {'; '.join(notes)}). "
        "Exclude them before any SUM/COUNT/AVG or you will double-count the "
        "detail rows they already summarise."
    )
    if where:
        head += f" Filter them out, e.g.: WHERE {where}."
    return head


# ---------------------------------------------------------------------------
# Ingest orchestration — wired from the file-ingest route after schema sync.
# ---------------------------------------------------------------------------

async def apply_total_row_detection(
    db,
    *,
    organization,
    data_source,
    abs_path: str,
    sheet_names: Optional[Any] = None,
    merged_paths: Optional[List[dict]] = None,
) -> dict:
    """Detect total rows for an uploaded spreadsheet/CSV and persist findings.

    For every active :class:`DataSourceTable` of ``data_source`` whose frame we
    can re-read, run :func:`detect_total_rows`, write the markers into
    ``table.metadata_json['total_row_markers']`` (+ ``total_row_count``), and —
    if anything was found — emit ONE guardrail :class:`Instruction` (org-scoped,
    linked to this data source) the agent reads.

    Gate: ``flags.TOTAL_ROW``.  Returns a small summary dict.  NEVER raises and
    never lets a failure escape into the ingest path.
    """
    summary: Dict[str, Any] = {"tables": 0, "markers": 0, "instruction_id": None}
    try:
        from app.settings.hybrid_flags import flags
        if not flags.TOTAL_ROW:
            return summary
    except Exception:  # noqa: BLE001
        return summary

    try:
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified
        from app.data_sources.clients.spreadsheet_client import SpreadsheetClient
        from app.models.datasource_table import DataSourceTable

        # Re-read the file into {table_name: df}, EXACTLY the slug the ingest path
        # used (SpreadsheetClient._safe_table_name), so frames line up with rows.
        try:
            client = SpreadsheetClient(
                path=abs_path,
                sheet_names=sheet_names,
                merged_paths=list(merged_paths or []),
            )
            frames = client._load_frames()  # {table_name: DataFrame}
        except Exception as e:  # noqa: BLE001
            logger.warning("total_rows: could not load frames from %s: %s", abs_path, e)
            return summary

        if not frames:
            return summary

        # Load this source's tables once.
        rows = (await db.execute(
            select(DataSourceTable).filter(
                DataSourceTable.datasource_id == str(data_source.id)
            )
        )).scalars().all()
        by_name = {str(t.name): t for t in rows}

        guardrails: List[str] = []
        for tbl_name, df in frames.items():
            try:
                markers = detect_total_rows(df)
            except Exception:  # noqa: BLE001
                markers = []
            if not markers:
                continue

            tbl = by_name.get(str(tbl_name))
            est = estimate_total_row_count(markers)
            if tbl is not None:
                try:
                    meta = tbl.metadata_json if isinstance(tbl.metadata_json, dict) else {}
                    meta = dict(meta)
                    meta["total_row_markers"] = markers
                    meta["total_row_count"] = est
                    tbl.metadata_json = meta
                    flag_modified(tbl, "metadata_json")
                except Exception as e:  # noqa: BLE001
                    logger.debug("total_rows: persist marker for %s failed: %s", tbl_name, e)

            summary["markers"] += len(markers)
            summary["tables"] += 1
            guardrails.append(build_guardrail_text(str(tbl_name), markers))

        if not guardrails:
            return summary

        # Emit ONE guardrail Instruction (mirrors build_data_asset's direct add).
        inst_id = await _emit_guardrail_instruction(
            db, organization=organization, data_source=data_source,
            guardrails=[g for g in guardrails if g],
        )
        summary["instruction_id"] = inst_id

        try:
            await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("total_rows: commit failed: %s", e)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return summary
    except Exception as e:  # noqa: BLE001
        logger.warning("apply_total_row_detection: %s", e, exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return summary


async def _emit_guardrail_instruction(db, *, organization, data_source,
                                      guardrails: List[str]) -> Optional[str]:
    """Create a published, data-source-scoped guardrail Instruction.

    Reuses the same direct-add path build_data_asset uses (no approval build),
    with category 'data_quality' + ai_source 'total_row_detector' so it is
    discoverable.  Linked to ``data_source`` so it only loads for this source.
    Fail-soft → returns the new id or None.
    """
    try:
        from app.models.instruction import Instruction
        from app.models.data_source import DataSource  # noqa: F401

        text_body = (
            "DATA QUALITY GUARDRAIL — pre-aggregated total rows.\n"
            + "\n".join(f"- {g}" for g in guardrails)
        )
        inst = Instruction(
            text=text_body,
            title="Exclude pre-aggregated total rows",
            source_type="ai",
            status="published",
            load_mode="always",
            category="data_quality",
            ai_source="total_row_detector",
            trigger_reason="ingest_total_row_detection",
            organization_id=str(organization.id),
            structured_data={"kind": "total_row_guardrail",
                             "data_source_id": str(data_source.id)},
        )
        db.add(inst)
        await db.flush()
        # New (transient) instruction → assigning the collection won't lazy-load.
        try:
            inst.data_sources = [data_source]
        except Exception as e:  # noqa: BLE001
            logger.debug("total_rows: link instruction->data_source failed: %s", e)
        return str(inst.id)
    except Exception as e:  # noqa: BLE001
        logger.warning("total_rows: emit guardrail instruction failed: %s", e)
        return None
