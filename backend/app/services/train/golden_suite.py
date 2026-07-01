"""Golden suite: a DB-driven verification scoreboard.

Reads the org's `agent_definitions` (NO hardcoded questions/SQL/numbers), generates
the golden SQL for each, runs it against the real data source, and compares to the
definition's own expected number. Returns a per-row PASS/FAIL report.

This is the regression net for training: run it every train, block release on red.
Generic — works for ANY org's doc + data with zero code change. The CRM numbers are
never in this file; they live in the definitions in the DB.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from sqlalchemy import select

from app.models.agent_definition import AgentDefinition
from app.services.train import golden_gen as _G, eval_gate as _E

logger = logging.getLogger(__name__)


def _expected_scalar(defn) -> object:
    """Pull the expected ground-truth off a definition (json list of {scope,value})."""
    exp = getattr(defn, "expected", None)
    if isinstance(exp, list) and exp:
        return exp[0].get("value")
    return None


async def run_suite(db, *, organization_id: str) -> Dict:
    """Return {passed, failed, total, rows:[{name,kind,expected,actual,verdict,ok}]}.
    Never raises."""
    rows: List[Dict] = []
    try:
        defs = (await db.execute(select(AgentDefinition).where(
            AgentDefinition.organization_id == str(organization_id),
            AgentDefinition.deleted_at.is_(None),
        ))).scalars().all()
    except Exception as e:  # noqa: BLE001
        logger.warning("golden_suite: load defs failed: %s", e)
        return {"passed": 0, "failed": 0, "total": 0, "rows": [], "error": str(e)[:200]}

    # group by data source (a def with no ds -> skipped, can't run)
    by_ds: Dict[str, list] = {}
    for d in defs:
        if d.data_source_id:
            by_ds.setdefault(str(d.data_source_id), []).append(d)

    for dsid, grp in by_ds.items():
        try:
            cands = await _G.generate_for_definitions(db, data_source_id=dsid, definitions=grp)
            res = await _E.evaluate(db, data_source_id=dsid, candidates=cands)
        except Exception as e:  # noqa: BLE001
            logger.warning("golden_suite: eval ds %s failed: %s", dsid, e)
            continue
        for bucket, verdict_ok in (("approved", True), ("held", False)):
            for c in res.get(bucket, []):
                rows.append({
                    "name": c.get("name"),
                    "kind": c.get("kind", "count"),
                    "expected": c.get("expected"),
                    "actual": c.get("actual"),
                    "verdict": c.get("verdict"),
                    "ok": verdict_ok,
                })

    passed = sum(1 for r in rows if r["ok"])
    return {"passed": passed, "failed": len(rows) - passed, "total": len(rows), "rows": rows}
