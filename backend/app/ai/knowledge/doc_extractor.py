"""Auto-configure-from-doc extractor (AUTOMAP).

Parses an uploaded *definitions spreadsheet* (.xlsx) and/or an *explanation
deck* (.pptx), builds a single text digest, asks the configured LLM (OpenRouter)
to extract a structured proposal, and fuzzy-matches the proposed column names
against a target data source's live schema (its ``DataSourceTable`` rows).

The proposal shape returned to the route::

    {
        "column_descriptions": [
            {"column": "...", "description": "...",
             "matched": bool, "table_id": str|None, "table_name": str|None,
             "matched_column": str|None, "match_kind": "exact|ci|strip|fuzzy|none"}
        ],
        "instructions":  [{"content": "...", "category": "..."}],
        "examples":      [{"question": "...", "answer": "...", "sql": "..."}],
        "compliance":    [{"content": "..."}],
        "unmatched_columns": ["..."],   # proposed columns with no schema match
        "schema_columns":    ["table.col", ...],  # what the live schema offered
        "source": "llm" | "fallback",
        "warnings": ["..."],
    }

Design rules (mirror the rest of the hybrid layer):
- Never raise into the route on *content* problems — return a dict with an
  ``error`` key so the route can answer a helpful 422. Hard programmer errors
  (bad args) may still raise.
- The parser libs (``openpyxl`` / ``python-pptx``) may NOT be installed in the
  runtime container. Imports are wrapped; a missing lib yields a clear
  ``{"error": "openpyxl not installed"}`` style result.
- LLM is OpenRouter-only via the repo idiom
  ``LLM(model, usage_session_maker=...).inference(prompt, usage_scope=...)``.
- Deterministic OFFLINE fallback: if no LLM/model is available, parse a 2-column
  definitions sheet directly into ``column_descriptions`` so the feature still
  works without a model.
"""

import difflib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSource
from app.models.datasource_table import DataSourceTable
from app.models.file import File as FileModel

logger = logging.getLogger(__name__)

# Cap how much digest text we send to the model (cheap + bounded).
_MAX_DIGEST_CHARS = 16000
# difflib fuzzy-match cutoff.
_FUZZY_CUTOFF = 0.6


# --------------------------------------------------------------------------- #
# File-path resolution (mirrors data_source_from_file._resolve_upload_path)
# --------------------------------------------------------------------------- #
def _resolve_upload_path(stored_path: str) -> Optional[str]:
    """Resolve the on-disk absolute path for an uploaded file, traversal-safe.

    Uploaded files live flat under ``<cwd>/uploads/files/<basename>`` (see
    routes/file.py). In-container that is ``/app/backend/uploads/files/``.
    Returns the path if it exists, else None.
    """
    if not stored_path:
        return None
    base = os.path.basename(stored_path)
    candidate = os.path.join(os.getcwd(), "uploads", "files", base)
    if os.path.exists(candidate):
        return candidate
    rel = os.path.join(os.getcwd(), stored_path)
    if os.path.exists(rel):
        return rel
    if os.path.isabs(stored_path) and os.path.exists(stored_path):
        return stored_path
    return None


# --------------------------------------------------------------------------- #
# Parsers (libs may be missing — fail soft with a clear error dict)
# --------------------------------------------------------------------------- #
def _parse_xlsx(path: str) -> Dict[str, Any]:
    """Parse an .xlsx into {digest, rows} or {error}.

    ``rows`` is a list of (left, right) 2-col pairs harvested from every sheet
    (used by the offline fallback as column -> definition). ``digest`` is a
    readable text rendering of the workbook for the LLM.
    """
    try:
        import openpyxl  # type: ignore
    except Exception:
        return {"error": "openpyxl not installed"}

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        return {"error": f"could not read spreadsheet: {e}"}

    lines: List[str] = []
    pairs: List[Tuple[str, str]] = []
    try:
        for ws in wb.worksheets:
            lines.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                cells = [
                    str(c).strip() for c in row
                    if c is not None and str(c).strip() != ""
                ]
                if not cells:
                    continue
                lines.append(" | ".join(cells))
                # 2-col definition pair (col name -> definition).
                if len(cells) >= 2 and cells[0]:
                    pairs.append((cells[0], cells[1]))
    finally:
        try:
            wb.close()
        except Exception:
            pass

    return {"digest": "\n".join(lines), "pairs": pairs}


def _parse_pptx(path: str) -> Dict[str, Any]:
    """Parse a .pptx into {digest} or {error}. All slide text, in order."""
    try:
        from pptx import Presentation  # type: ignore
    except Exception:
        return {"error": "python-pptx not installed"}

    try:
        prs = Presentation(path)
    except Exception as e:
        return {"error": f"could not read presentation: {e}"}

    lines: List[str] = []
    for idx, slide in enumerate(prs.slides, start=1):
        lines.append(f"# Slide {idx}")
        for shape in slide.shapes:
            text = getattr(shape, "text", None)
            if text and text.strip():
                lines.append(text.strip())
            # Tables on a slide (column->definition decks).
            if getattr(shape, "has_table", False):
                try:
                    for trow in shape.table.rows:
                        cells = [c.text.strip() for c in trow.cells if c.text]
                        if cells:
                            lines.append(" | ".join(cells))
                except Exception:
                    pass
    return {"digest": "\n".join(lines)}


def _parse_file(path: str) -> Dict[str, Any]:
    """Dispatch on extension. Returns {digest,pairs?} or {error}."""
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        return _parse_xlsx(path)
    if ext in (".pptx",):
        return _parse_pptx(path)
    return {"error": f"unsupported file type '{ext}' (need .xlsx or .pptx)"}


# --------------------------------------------------------------------------- #
# Schema loading + fuzzy column matching
# --------------------------------------------------------------------------- #
async def _load_schema_columns(
    db: AsyncSession, data_source_id: str
) -> List[Dict[str, Any]]:
    """Load the live columns of a data source's active tables.

    Returns a flat list of
    ``{"table_id", "table_name", "column", "dtype"}`` from each
    ``DataSourceTable.columns`` JSON (list of ``{name, dtype, description?}``).
    Falls back to the ConnectionTable schema columns when the legacy
    ``columns`` JSON is empty.
    """
    res = await db.execute(
        select(DataSourceTable).where(
            DataSourceTable.datasource_id == str(data_source_id),
            DataSourceTable.is_active == True,  # noqa: E712
        )
    )
    out: List[Dict[str, Any]] = []
    for t in res.scalars().all():
        cols = t.columns or []
        if not cols:
            # Fall back to the prompt-table view (ConnectionTable-backed).
            try:
                pt = t.to_prompt_table()
                cols = [
                    {"name": c.name, "dtype": getattr(c, "dtype", None)}
                    for c in (pt.columns or [])
                ]
            except Exception:
                cols = []
        for c in cols:
            if not isinstance(c, dict):
                continue
            name = c.get("name")
            if not name:
                continue
            out.append({
                "table_id": str(t.id),
                "table_name": t.name,
                "column": name,
                "dtype": c.get("dtype"),
            })
    return out


def _match_column(
    proposed: str, schema_cols: List[Dict[str, Any]]
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Match a proposed column name to a schema column.

    Tries exact -> case-insensitive -> stripped/normalized -> difflib fuzzy.
    Returns (schema_col_dict | None, match_kind).
    """
    if not proposed:
        return None, "none"

    def _norm(s: str) -> str:
        return "".join(ch for ch in s.lower().strip() if ch.isalnum())

    # 1. exact
    for sc in schema_cols:
        if sc["column"] == proposed:
            return sc, "exact"
    # 2. case-insensitive
    pl = proposed.lower().strip()
    for sc in schema_cols:
        if sc["column"].lower().strip() == pl:
            return sc, "ci"
    # 3. normalized (strip spaces/underscores/punct)
    pn = _norm(proposed)
    if pn:
        for sc in schema_cols:
            if _norm(sc["column"]) == pn:
                return sc, "strip"
    # 4. difflib fuzzy
    names = [sc["column"] for sc in schema_cols]
    close = difflib.get_close_matches(proposed, names, n=1, cutoff=_FUZZY_CUTOFF)
    if close:
        for sc in schema_cols:
            if sc["column"] == close[0]:
                return sc, "fuzzy"
    return None, "none"


# --------------------------------------------------------------------------- #
# LLM extraction
# --------------------------------------------------------------------------- #
def _build_prompt(digest: str, schema_cols: List[Dict[str, Any]]) -> str:
    schema_lines = "\n".join(
        f"- {c['table_name']}.{c['column']}" + (f" ({c['dtype']})" if c.get("dtype") else "")
        for c in schema_cols[:200]
    ) or "(no schema columns available)"
    return (
        "You are a data-catalog assistant. You are given (A) the LIVE SCHEMA of a "
        "data source and (B) the text of business definition/explanation documents "
        "(a definitions spreadsheet and/or an explanation deck).\n\n"
        "Extract a STRICT JSON object with EXACTLY these keys:\n"
        '  "column_descriptions": [{"column": "<name as it appears in the docs>", '
        '"description": "<plain-English meaning>"}],\n'
        '  "instructions": [{"content": "<always-on rule / KPI formula / business '
        'rule>", "category": "<kpi|business_rule|compliance|general>"}],\n'
        '  "examples": [{"question": "<natural-language question>", "answer": '
        '"<short answer>", "sql": "<SQL if derivable, else empty string>"}],\n'
        '  "compliance": [{"content": "<compliance / governance rule>"}]\n\n'
        "Rules: Prefer column names that resemble the live schema below. Only emit "
        "facts grounded in the documents. If a section has nothing, return an empty "
        "array for it. Output ONLY the JSON object, no prose, no markdown fences.\n\n"
        "=== LIVE SCHEMA ===\n"
        f"{schema_lines}\n\n"
        "=== DOCUMENTS ===\n"
        f"{digest[:_MAX_DIGEST_CHARS]}\n"
    )


def _coerce_proposal(raw: str) -> Optional[Dict[str, Any]]:
    """Parse the model's reply into the proposal dict; None on junk."""
    if not raw:
        return None
    text = raw.strip()
    # Strip markdown fences if present.
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
    # Trim to the outermost JSON object.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        obj = json.loads(text, strict=False)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


async def _llm_extract(
    db: AsyncSession,
    organization,
    digest: str,
    schema_cols: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """One cheap OpenRouter call. Returns the raw proposal dict or None.

    Mirrors the ambiguity-gate / knowledge-proposer idiom exactly.
    """
    try:
        from app.services.llm_service import LLMService

        model = await LLMService().get_default_model(db, organization, None, is_small=True)
        if model is None:
            return None

        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        prompt = _build_prompt(digest, schema_cols)
        raw = (
            LLM(model, usage_session_maker=async_session_maker).inference(
                prompt, usage_scope="auto_configure_doc"
            )
            or ""
        )
        return _coerce_proposal(raw)
    except Exception as e:
        logger.warning("doc_extractor LLM extract failed: %s", e)
        return None


# --------------------------------------------------------------------------- #
# Offline deterministic fallback
# --------------------------------------------------------------------------- #
def _fallback_from_pairs(pairs: List[Tuple[str, str]]) -> Dict[str, Any]:
    """Build a proposal from a 2-col definitions sheet without an LLM.

    Drops an obvious header row (e.g. 'Column' | 'Definition').
    """
    cds: List[Dict[str, str]] = []
    seen = set()
    for left, right in pairs:
        l, r = (left or "").strip(), (right or "").strip()
        if not l or not r:
            continue
        if l.lower() in ("column", "field", "name", "column name") and \
                r.lower() in ("definition", "description", "meaning", "desc"):
            continue  # header
        key = l.lower()
        if key in seen:
            continue
        seen.add(key)
        cds.append({"column": l, "description": r})
    return {
        "column_descriptions": cds,
        "instructions": [],
        "examples": [],
        "compliance": [],
    }


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
async def extract_proposal(
    db: AsyncSession,
    *,
    organization,
    file_ids: List[str],
    data_source_id: str,
) -> Dict[str, Any]:
    """Parse the docs, extract a proposal, fuzzy-match to the live schema.

    Returns the proposal dict described in the module docstring, or a dict with
    an ``error`` key (route returns 422) for content problems.
    """
    warnings: List[str] = []

    # 1. Validate the target data source (org-scoped).
    ds_res = await db.execute(
        select(DataSource).where(
            DataSource.id == str(data_source_id),
            DataSource.organization_id == organization.id,
        )
    )
    if ds_res.scalar_one_or_none() is None:
        return {"error": "data source not found in this organization"}

    if not file_ids:
        return {"error": "no file_ids provided"}

    # 2. Resolve + parse each file, merging digests/pairs.
    digests: List[str] = []
    pairs: List[Tuple[str, str]] = []
    for fid in file_ids:
        f_res = await db.execute(
            select(FileModel).where(
                FileModel.id == str(fid),
                FileModel.organization_id == organization.id,
            )
        )
        file = f_res.scalar_one_or_none()
        if file is None:
            warnings.append(f"file {fid} not found in org")
            continue
        abs_path = _resolve_upload_path(file.path or "")
        if not abs_path:
            warnings.append(f"file {fid} content missing on disk")
            continue
        parsed = _parse_file(abs_path)
        if "error" in parsed:
            # A missing parser lib is a hard, helpful error for the whole call.
            if "not installed" in parsed["error"]:
                return {"error": parsed["error"]}
            warnings.append(f"file {fid}: {parsed['error']}")
            continue
        if parsed.get("digest"):
            digests.append(parsed["digest"])
        if parsed.get("pairs"):
            pairs.extend(parsed["pairs"])

    digest = "\n\n".join(digests).strip()
    if not digest and not pairs:
        return {"error": "no readable content found in the uploaded files",
                "warnings": warnings}

    # 3. Load the live schema columns to match against.
    schema_cols = await _load_schema_columns(db, data_source_id)

    # 4. LLM extraction, with offline fallback.
    proposal = await _llm_extract(db, organization, digest, schema_cols)
    source = "llm"
    if proposal is None:
        proposal = _fallback_from_pairs(pairs)
        source = "fallback"
        if not pairs:
            warnings.append(
                "no LLM available and no 2-column definitions sheet to parse"
            )

    # 5. Normalize the proposal shape defensively.
    raw_cds = proposal.get("column_descriptions") or []
    raw_instr = proposal.get("instructions") or []
    raw_examples = proposal.get("examples") or []
    raw_compliance = proposal.get("compliance") or []

    # 6. Fuzzy-match each proposed column to the live schema.
    column_descriptions: List[Dict[str, Any]] = []
    unmatched: List[str] = []
    for item in raw_cds:
        if not isinstance(item, dict):
            continue
        col = (item.get("column") or "").strip()
        desc = (item.get("description") or "").strip()
        if not col:
            continue
        match, kind = _match_column(col, schema_cols)
        entry = {
            "column": col,
            "description": desc,
            "matched": match is not None,
            "match_kind": kind,
            "table_id": match["table_id"] if match else None,
            "table_name": match["table_name"] if match else None,
            "matched_column": match["column"] if match else None,
        }
        column_descriptions.append(entry)
        if match is None:
            unmatched.append(col)

    instructions = [
        {"content": (i.get("content") or "").strip(),
         "category": (i.get("category") or "general").strip()}
        for i in raw_instr if isinstance(i, dict) and (i.get("content") or "").strip()
    ]
    examples = [
        {"question": (e.get("question") or "").strip(),
         "answer": (e.get("answer") or "").strip(),
         "sql": (e.get("sql") or "").strip()}
        for e in raw_examples
        if isinstance(e, dict) and (e.get("question") or "").strip()
    ]
    compliance = [
        {"content": (c.get("content") or "").strip()}
        for c in raw_compliance if isinstance(c, dict) and (c.get("content") or "").strip()
    ]

    return {
        "column_descriptions": column_descriptions,
        "instructions": instructions,
        "examples": examples,
        "compliance": compliance,
        "unmatched_columns": unmatched,
        "schema_columns": [f"{c['table_name']}.{c['column']}" for c in schema_cols],
        "source": source,
        "warnings": warnings,
    }
