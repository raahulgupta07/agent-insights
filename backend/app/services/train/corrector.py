"""Pipeline v1 (P6): the CORRECTION LOOP.

A user instruction updates ONE definition; every dependent golden is then
regenerated and re-evaluated. One correction fixes all affected SQL.

The instruction is parsed deterministically (reusing the logic-doc filter parser)
so a correction like::

    New User means Status=Completed, Call Outcome=Successful,
    Related Brand Relationship: Type=User,
    Related Brand Relationship: Status=New. Expected total = 644.

→ finds/creates the "New User" definition, rewrites its predicate, optionally
updates its expected number, regenerates its golden, re-runs the eval gate, and
re-approves only if it now matches. Never raises.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_EXPECTED_RE = re.compile(r"expected[^0-9]*([0-9][0-9,\s]*)", re.IGNORECASE)


def _expected_override(text: str) -> Optional[int]:
    m = _EXPECTED_RE.search(text or "")
    if not m:
        return None
    try:
        return int(re.sub(r"[,\s]", "", m.group(1)))
    except Exception:  # noqa: BLE001
        return None


async def _match_definition_name(db, org_id: str, text: str):
    """Find which existing definition the instruction targets (name appears in
    text, longest match wins). Returns the AgentDefinition or None."""
    from sqlalchemy import select
    from app.models.agent_definition import AgentDefinition

    defs = (
        await db.execute(
            select(AgentDefinition).where(
                AgentDefinition.organization_id == org_id,
                AgentDefinition.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    low = (text or "").lower()
    hits = [d for d in defs if d.name and d.name.lower() in low]
    hits.sort(key=lambda d: len(d.name), reverse=True)
    return (hits[0], defs) if hits else (None, defs)


async def apply_correction(
    db, *, organization, data_source_id: str, instruction: str,
) -> Dict:
    """Parse instruction -> update the matched definition -> regenerate + re-eval
    its golden. Returns a summary dict. Never raises."""
    from app.services.ingest.logic_parser import _filters_from_logic
    from app.services.train import registry as R, golden_gen as G, eval_gate as E

    summary: Dict = {"definition": None, "updated": False, "verdict": None,
                     "actual": None, "expected": None}
    try:
        org_id = str(organization.id)
        target, _all = await _match_definition_name(db, org_id, instruction)
        if target is None:
            summary["error"] = "no matching definition name found in instruction"
            return summary

        # Clean the natural-language instruction before deterministic parsing so
        # the "<name> means …" preamble and the "Expected total = N" clause don't
        # become bogus "column=value" filters.
        clean = _EXPECTED_RE.sub("", instruction)            # drop expected clause
        clean = re.sub(r"(?i)^.*?\b(means|is|=)\b[: ]*", "", clean, count=1) \
            if re.search(r"(?i)\bmeans\b", clean) else clean  # drop "<name> means"
        filters = _filters_from_logic(clean)
        predicate, cols = R.build_predicate(filters)
        if not predicate:
            summary["error"] = "could not parse a predicate from the instruction"
            return summary

        exp_override = _expected_override(instruction)

        # update the ONE definition (single source of truth)
        target.sql_predicate = predicate
        target.filters = filters
        target.columns_used = cols
        if exp_override is not None:
            target.expected = [{"scope": "total", "value": exp_override}]
        target.logic_text = instruction.strip()[:1000]
        target.status = "pending"  # re-enters review after a change
        await db.commit()
        summary["definition"] = target.name
        summary["updated"] = True

        # regenerate + re-eval the affected definition's golden
        cands = await G.generate_for_definitions(
            db, data_source_id=data_source_id, definitions=[target]
        )
        res = await E.evaluate(db, data_source_id=data_source_id, candidates=cands)
        if res["approved"]:
            c = res["approved"][0]
            summary.update(verdict="match", actual=c["actual"], expected=c["expected"],
                           sql=c["sql"])
        elif res["held"]:
            c = res["held"][0]
            summary.update(verdict=c.get("verdict"), actual=c.get("actual"),
                           expected=c.get("expected"), sql=c.get("sql"))
        logger.info("corrector: '%s' -> %s (actual=%s expected=%s)",
                    target.name, summary["verdict"], summary["actual"], summary["expected"])
    except Exception:  # noqa: BLE001
        logger.warning("corrector.apply_correction failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        summary["error"] = "correction failed"
    return summary
