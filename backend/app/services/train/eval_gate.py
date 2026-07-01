"""Pipeline v1 (P5): the EVAL GATE.

Runs each generated golden (P4) against the real data and compares the result to
the definition's expected ground-truth number. A query is APPROVED only when it
matches; a mismatch or missing-expected -> HELD with a diff. This is the
"never silently wrong" guarantee.

Execution reuses the data source's own client (SpreadsheetClient for uploads),
so the gate runs the exact engine the agent would. Never raises.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


async def _client_for_source(db, data_source_id: str):
    """Build the query client for a (spreadsheet) data source from its connection
    config. Returns a client with `.execute_query(sql)` or None."""
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.data_source import DataSource
        from app.data_sources.clients.spreadsheet_client import SpreadsheetClient

        ds = (
            await db.execute(
                select(DataSource)
                .options(selectinload(DataSource.connections))
                .where(DataSource.id == str(data_source_id))
            )
        ).scalar_one_or_none()
        if ds is None or not ds.connections:
            return None
        conn = ds.connections[0]
        cfg = conn.config
        if isinstance(cfg, str):
            cfg = json.loads(cfg) if cfg else {}
        cfg = cfg or {}
        if (conn.type or "") != "spreadsheet":
            return None
        return SpreadsheetClient(
            path=cfg.get("path"),
            sheet_names=cfg.get("sheet_names"),
            file_id=cfg.get("file_id"),
            merged_paths=cfg.get("merged_paths"),
        )
    except Exception:  # noqa: BLE001
        logger.warning("eval_gate._client_for_source failed", exc_info=True)
        return None


def _scalar(df) -> Optional[int]:
    try:
        if df is None or len(df) == 0:
            return None
        v = df.iloc[0, 0]
        return int(v)
    except Exception:  # noqa: BLE001
        return None


def _rate(num: Optional[int], den: Optional[int]) -> Optional[float]:
    try:
        if num is None or not den:
            return None
        return round(100.0 * float(num) / float(den), 2)
    except Exception:  # noqa: BLE001
        return None


def _evaluate_ratio(client, c: Dict, item: Dict, approved: List, held: List) -> None:
    """Ratio candidate (P8): run num_sql + den_sql, verify BOTH counts vs ground
    truth (stronger than % alone), compute the display rate. Match -> approved,
    else held with a diff. Populates + files `item`; never raises."""
    try:
        num_actual = _scalar(client.execute_query(c["num_sql"]))
        den_actual = _scalar(client.execute_query(c["den_sql"]))
    except Exception as e:  # noqa: BLE001
        item["actual"] = None
        item["verdict"] = "error"
        item["error"] = str(e)[:200]
        held.append(item)
        return
    exp = c.get("expected") or {}
    num_exp = exp.get("num") if isinstance(exp, dict) else None
    den_exp = exp.get("den") if isinstance(exp, dict) else None
    item["actual"] = {"num": num_actual, "den": den_actual,
                      "rate": _rate(num_actual, den_actual)}
    if num_exp is None or den_exp is None:
        item["verdict"] = "unverified"  # no ground truth for both -> never auto-approve
        held.append(item)
        return
    both_match = (
        num_actual is not None and den_actual is not None
        and int(num_actual) == int(num_exp) and int(den_actual) == int(den_exp)
    )
    if both_match:
        item["verdict"] = "match"
        approved.append(item)
    else:
        item["verdict"] = "mismatch"
        item["diff"] = {
            "expected": {"num": num_exp, "den": den_exp,
                         "rate": _rate(num_exp, den_exp)},
            "actual": item["actual"],
        }
        held.append(item)


async def evaluate(db, *, data_source_id: str, candidates: List[Dict]) -> Dict:
    """Run + verify each candidate. Returns
    {"approved": [...], "held": [...]}; each item carries actual/expected/verdict.
    Never raises."""
    approved: List[Dict] = []
    held: List[Dict] = []
    client = await _client_for_source(db, data_source_id)
    if client is None:
        logger.warning("eval_gate: no client for ds %s -> all held", data_source_id)
        for c in candidates or []:
            held.append({**c, "actual": None, "verdict": "no_client"})
        return {"approved": approved, "held": held}

    for c in candidates or []:
        item = dict(c)
        try:
            if c.get("metric_kind") == "ratio":
                _evaluate_ratio(client, c, item, approved, held)
                continue
            df = client.execute_query(c["sql"])
            actual = _scalar(df)
            item["actual"] = actual
            exp = c.get("expected")
            if exp is None:
                item["verdict"] = "unverified"  # no ground truth -> never auto-approve
                held.append(item)
            elif actual is not None and int(actual) == int(exp):
                item["verdict"] = "match"
                approved.append(item)
            else:
                item["verdict"] = "mismatch"
                item["diff"] = {"expected": exp, "actual": actual}
                held.append(item)
        except Exception as e:  # noqa: BLE001
            item["actual"] = None
            item["verdict"] = "error"
            item["error"] = str(e)[:200]
            held.append(item)
    logger.info("eval_gate: %d approved, %d held (ds %s)",
                len(approved), len(held), data_source_id)
    return {"approved": approved, "held": held}
