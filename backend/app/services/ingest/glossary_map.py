"""Import v2 (P2, HYBRID_AUTO_MAP_GLOSSARY): map a STANDALONE glossary file.

`smart_upload.looks_like_glossary` + `from-file`'s `_route_glossary_sheets`
already route a glossary *sheet that lives inside a data file* into a KnowledgeDoc.
This module handles the other case: a glossary/definitions file uploaded ON ITS
OWN (e.g. ``Definitions.xlsx``) — which previously just became a junk queryable
source. Here we:

  1. parse it term -> definition,
  2. ingest the whole thing as a KnowledgeDoc (pending, review-gated), and
  3. fuzzy-match each term onto the columns of the org's EXISTING data sources
     and fill any blank `SemanticColumn.meaning` rows with ``status='pending'``
     (never overwrites an approved/non-blank meaning).

Everything is fail-soft: no public entry point raises into the ingest request.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_TERMS = 500
_FUZZY_CUTOFF = 0.82


def _norm(name: str) -> str:
    """Normalize a column/term name for matching: lower, alnum-only."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").strip().lower())


def extract_glossary_terms(frames: "dict") -> Dict[str, str]:
    """Parse {sheet -> DataFrame} glossary frames into {term: definition}.

    Uses the first label-ish column as the term and the next non-empty column as
    the definition. Conservative + fail-soft -> returns {} on any doubt.
    """
    terms: Dict[str, str] = {}
    try:
        from app.services.ingest import smart_upload

        for sheet, df in (frames or {}).items():
            try:
                if df is None or df.shape[1] < 2 or len(df) == 0:
                    continue
                if not smart_upload.looks_like_glossary(df, sheet_name=str(sheet)):
                    continue
                cols = list(df.columns)
                term_col, def_col = cols[0], cols[1]
                for _, row in df.iterrows():
                    term = str(row.get(term_col, "") or "").strip()
                    definition = str(row.get(def_col, "") or "").strip()
                    if not term or not definition or term.lower() == "nan":
                        continue
                    terms.setdefault(term, definition)
                    if len(terms) >= _MAX_TERMS:
                        return terms
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        logger.warning("glossary_map.extract_glossary_terms failed", exc_info=True)
    return terms


def is_glossary_file(frames: "dict") -> bool:
    """True when the WHOLE file reads as a glossary (every non-empty sheet looks
    like a definitions sheet). Conservative — one real data sheet -> False."""
    try:
        from app.services.ingest import smart_upload

        seen = 0
        for sheet, df in (frames or {}).items():
            if df is None or len(df) == 0:
                continue
            seen += 1
            if not smart_upload.looks_like_glossary(df, sheet_name=str(sheet)):
                return False
        return seen > 0
    except Exception:  # noqa: BLE001
        return False


def _glossary_markdown(terms: Dict[str, str], *, title: str) -> str:
    lines = [f"# {title}", "", "| Term | Definition |", "| --- | --- |"]
    for term, definition in terms.items():
        t = term.replace("|", "\\|")
        d = definition.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {t} | {d} |")
    return "\n".join(lines)


async def map_glossary_to_org(
    db, *, organization, terms: Dict[str, str], source_filename: str,
) -> dict:
    """Ingest the glossary as a KnowledgeDoc and fuzzy-fill blank SemanticColumn
    meanings across the org's data sources. Returns a summary; never raises.

    Returns ``{"doc_id", "terms": n, "columns_mapped": m, "tables_touched": k}``.
    """
    summary = {"doc_id": None, "terms": len(terms), "columns_mapped": 0, "tables_touched": 0}
    if not terms:
        return summary
    try:
        from sqlalchemy import select
        from app.ai.knowledge.docs_index import ingest_doc
        from app.models.semantic_table import SemanticColumn, SemanticTable

        # 1) KnowledgeDoc (pending) so the agent can read the whole glossary.
        try:
            title = f"{source_filename or 'Glossary'} — definitions"
            res = await ingest_doc(
                db, organization=organization, title=title,
                body=_glossary_markdown(terms, title=title), source="upload",
            )
            summary["doc_id"] = (res or {}).get("doc_id")
        except Exception:  # noqa: BLE001
            logger.warning("glossary_map: KnowledgeDoc ingest failed", exc_info=True)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

        # 2) fuzzy-map terms onto existing blank column meanings (pending).
        norm_terms = {_norm(t): (t, d) for t, d in terms.items() if _norm(t)}
        if not norm_terms:
            return summary
        term_keys = list(norm_terms.keys())

        rows = (
            await db.execute(
                select(SemanticColumn)
                .join(SemanticTable, SemanticColumn.semantic_table_id == SemanticTable.id)
                .where(SemanticTable.organization_id == str(organization.id))
            )
        ).scalars().all()

        touched_tables = set()
        for col in rows:
            try:
                # never overwrite a filled / approved meaning
                if (col.meaning or "").strip() or str(col.status) == "approved":
                    continue
                ck = _norm(col.name)
                if not ck:
                    continue
                if ck in norm_terms:
                    match = ck
                else:
                    near = difflib.get_close_matches(ck, term_keys, n=1, cutoff=_FUZZY_CUTOFF)
                    match = near[0] if near else None
                if not match:
                    continue
                _term, definition = norm_terms[match]
                col.meaning = definition[:2000]
                col.status = "pending"
                summary["columns_mapped"] += 1
                touched_tables.add(col.semantic_table_id)
            except Exception:  # noqa: BLE001
                continue

        summary["tables_touched"] = len(touched_tables)
        if summary["columns_mapped"]:
            await db.commit()
            logger.info(
                "glossary_map: mapped %d column meanings from %d terms (%s)",
                summary["columns_mapped"], len(terms), source_filename,
            )
    except Exception:  # noqa: BLE001
        logger.warning("glossary_map.map_glossary_to_org failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return summary
