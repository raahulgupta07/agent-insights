"""NEWPIPE P6 — quality gate over the durable dlt warehouse.

Runs cheap expectations BEFORE the data is trusted for training, so a bad/partial
ingest becomes a surfaced DEGRADED signal instead of a silent fabrication source.

HARD checks (fail → block/DEGRADED): row_count>0, unique _row_key, key cols not-null.
SOFT checks (warn only): cols <5% filled (don't build a KPI on them).
Reads the per-org file-backed DuckDB written by ``dlt_ingest``. Never raises.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# cols whose emptiness must NOT silently pass — tune per dataset; generic defaults
_DEFAULT_KEY_COLS: List[str] = []


def run_quality_gate(
    org_id: str,
    table: str,
    *,
    key_cols: Optional[List[str]] = None,
    expected_periods: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Return ``{passed, hard_fail, checks:[{name,sev,ok,detail}], stats}``. Never raises."""
    from app.services.ingest.dlt_ingest import WAREHOUSE_ROOT

    result: Dict[str, Any] = {
        "passed": True, "hard_fail": 0, "checks": [], "stats": {}, "error": None,
    }
    checks = result["checks"]

    def add(name: str, sev: str, ok: bool, detail: str):
        checks.append({"name": name, "sev": sev, "ok": bool(ok), "detail": detail})

    try:
        import duckdb

        db_path = os.path.join(WAREHOUSE_ROOT, str(org_id), "warehouse.duckdb")
        con = duckdb.connect(db_path, read_only=True)
        T = f"crm.{table}"

        total = con.execute(f"SELECT count(*) FROM {T}").fetchone()[0]
        result["stats"]["rows"] = int(total)
        add("row_count>0", "HARD", total > 0, f"{total} rows")

        # unique row key (idempotency integrity)
        try:
            dup = con.execute(
                f"SELECT count(*)-count(DISTINCT _row_key) FROM {T}"
            ).fetchone()[0]
            add("unique _row_key", "HARD", dup == 0, f"{dup} collisions")
        except Exception as e:  # noqa: BLE001
            add("unique _row_key", "HARD", False, f"no _row_key ({e})")

        # period coverage (if caller declares expected months)
        if expected_periods:
            got = {
                r[0] for r in con.execute(
                    f"SELECT DISTINCT _source_period FROM {T}"
                ).fetchall()
            }
            missing = sorted(set(expected_periods) - got)
            add("period coverage", "HARD", not missing,
                f"have {sorted(got)} missing {missing or 'none'}")

        # key cols not-null
        for c in (key_cols or _DEFAULT_KEY_COLS):
            try:
                nn = con.execute(
                    f"SELECT count(*) FROM {T} WHERE \"{c}\" IS NULL OR \"{c}\"=''"
                ).fetchone()[0]
                add(f"not-null:{c}", "HARD", nn == 0, f"{nn} empty")
            except Exception:  # noqa: BLE001
                add(f"not-null:{c}", "SOFT", False, "column absent")

        # SOFT: near-empty cols (don't KPI on them)
        try:
            cols = [r[0] for r in con.execute(f"DESCRIBE {T}").fetchall()
                    if not str(r[0]).startswith("_")]
            empties = []
            for c in cols:
                nn = con.execute(
                    f"SELECT count(*) FROM {T} WHERE \"{c}\" IS NOT NULL AND \"{c}\"!=''"
                ).fetchone()[0]
                if total and nn / total < 0.05:
                    empties.append(c)
            add("no-KPI-on-empty", "SOFT", True,
                f"{len(empties)} cols <5% fill: {', '.join(e[:24] for e in empties)}")
            result["stats"]["empty_cols"] = empties
        except Exception:  # noqa: BLE001
            pass

        con.close()
        result["hard_fail"] = sum(
            1 for c in checks if c["sev"] == "HARD" and not c["ok"]
        )
        result["passed"] = result["hard_fail"] == 0
        logger.info(
            "quality_gate: org=%s table=%s passed=%s hard_fail=%s",
            org_id, table, result["passed"], result["hard_fail"],
        )
    except Exception as e:  # noqa: BLE001
        result["error"] = str(e)
        result["passed"] = False  # fail-closed: can't verify -> don't trust
        logger.warning("quality_gate failed: %s", e, exc_info=True)
    return result
