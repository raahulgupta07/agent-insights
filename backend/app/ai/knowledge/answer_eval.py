"""NEWPIPE P11 — answer-time eval gate.

Before a KPI number ships, re-run the GOVERNED measure independently and compare
to what the answer claims. Mismatch -> DEGRADED (block / surface), never a silent
wrong number. This is the last line of defence for accuracy.

Two surfaces:
- ``verify_claim`` — re-run a governed WHERE-filter count on the durable dlt
  warehouse and compare to a claimed integer (proven path; used by the pipeline).
- The agent-facing path stays ``flags.VERIFIED_METRICS`` (resolve_metric re-executes
  a locked metric's sql_calc + emits a drift_note); this module is the warehouse-side
  twin for governed count measures that live as filters rather than sql_calc rows.

Fail-soft / fail-closed: on any error the verdict is ``ok=False`` (do not trust).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def verify_claim(
    org_id: str,
    table: str,
    where_filter: str,
    claimed_value: int,
) -> Dict[str, Any]:
    """Re-run ``SELECT count(*) WHERE <filter>`` on the durable warehouse and
    compare to ``claimed_value``.

    Returns ``{ok, truth, claimed, verdict, error}`` where verdict ∈
    {"ship","DEGRADED"}. Never raises.
    """
    from app.services.ingest.dlt_ingest import WAREHOUSE_ROOT

    out: Dict[str, Any] = {
        "ok": False, "truth": None, "claimed": claimed_value,
        "verdict": "DEGRADED", "error": None,
    }
    try:
        import duckdb

        db_path = os.path.join(WAREHOUSE_ROOT, str(org_id), "warehouse.duckdb")
        con = duckdb.connect(db_path, read_only=True)
        truth = con.execute(
            f"SELECT count(*) FROM crm.{table} WHERE {where_filter}"
        ).fetchone()[0]
        con.close()
        out["truth"] = int(truth)
        match = int(truth) == int(claimed_value)
        out["ok"] = match
        out["verdict"] = "ship" if match else "DEGRADED"
        if not match:
            logger.warning(
                "answer_eval BLOCK: org=%s table=%s claimed=%s truth=%s",
                org_id, table, claimed_value, truth,
            )
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)  # fail-closed: ok stays False
        logger.warning("answer_eval failed: %s", e, exc_info=True)
    return out


def gate_answer(
    org_id: str,
    table: str,
    claims: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Batch gate: ``claims = {name: {"filter": str, "claimed": int}}``.

    Returns ``{passed, shipped, blocked, results:{name: verify_claim(...)}}``.
    A single blocked claim -> ``passed=False`` (the whole answer is DEGRADED).
    """
    results: Dict[str, Any] = {}
    blocked = 0
    for name, c in (claims or {}).items():
        v = verify_claim(org_id, table, c.get("filter", "1=0"), int(c.get("claimed", -1)))
        results[name] = v
        if not v["ok"]:
            blocked += 1
    total = len(results)
    return {
        "passed": blocked == 0 and total > 0,
        "shipped": total - blocked,
        "blocked": blocked,
        "results": results,
    }
