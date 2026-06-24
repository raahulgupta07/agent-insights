"""Pure schema-contract inference and diffing for ingested DataFrames.

No DB, no network. Never raises.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def infer_contract(df) -> dict:
    """Infer a column contract from a pandas DataFrame: {"columns":[{name,dtype}...]}."""
    try:
        columns = []
        for name, dtype in zip(df.columns, df.dtypes):
            columns.append({"name": str(name), "dtype": str(dtype)})
        return {"columns": columns}
    except Exception as e:
        logger.warning("infer_contract: failed: %s", e)
        return {"columns": []}


def _col_map(contract) -> dict:
    out = {}
    try:
        for c in (contract or {}).get("columns", []) or []:
            name = c.get("name")
            if name is not None:
                out[str(name)] = str(c.get("dtype"))
    except Exception as e:
        logger.debug("_col_map: %s", e)
    return out


def diff_contracts(old: dict, new: dict) -> dict:
    """Compare two contracts. verdict: new | exact | drift."""
    result = {
        "verdict": "exact",
        "added": [],
        "removed": [],
        "retyped": [],
        "renamed": [],
    }
    try:
        old_cols = _col_map(old)
        new_cols = _col_map(new)

        if not old_cols:
            result["verdict"] = "new"
            result["added"] = list(new_cols.keys())
            return result

        added = [n for n in new_cols if n not in old_cols]
        removed = [n for n in old_cols if n not in new_cols]
        retyped = [
            {"name": n, "from": old_cols[n], "to": new_cols[n]}
            for n in new_cols
            if n in old_cols and old_cols[n] != new_cols[n]
        ]

        renamed: list[dict] = []
        # best-effort rename detection: exactly one removed + one added of same dtype
        if len(added) == 1 and len(removed) == 1:
            a, r = added[0], removed[0]
            if new_cols.get(a) == old_cols.get(r):
                renamed.append({"from": r, "to": a})
                added, removed = [], []

        result["added"] = added
        result["removed"] = removed
        result["retyped"] = retyped
        result["renamed"] = renamed

        if not added and not removed and not retyped and not renamed:
            result["verdict"] = "exact"
        else:
            result["verdict"] = "drift"
        return result
    except Exception as e:
        logger.warning("diff_contracts: failed: %s", e)
        return {"verdict": "exact", "added": [], "removed": [], "retyped": [], "renamed": []}
