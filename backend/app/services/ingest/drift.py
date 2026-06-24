"""Schema / statistical drift baselining for ingested tables.

Pure-Python, stdlib only, no DB access. Every public function NEVER raises:
on error it returns a safe default and logs via logging.getLogger(__name__).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return ""


def make_baseline(
    table: str,
    *,
    columns: list | None = None,
    profile: dict | None = None,
) -> dict:
    try:
        cols_out: list[dict] = []
        stats: dict = {}

        # Seed columns from explicit columns arg.
        for c in columns or []:
            try:
                name = c.get("name") if isinstance(c, dict) else None
                if name is None:
                    continue
                dtype = c.get("dtype") if isinstance(c, dict) else None
                cols_out.append({"name": str(name), "dtype": str(dtype) if dtype is not None else ""})
            except Exception:
                continue

        # Pull (or supplement) columns + stats from a profile dict.
        if isinstance(profile, dict):
            known = {c["name"] for c in cols_out}
            for c in profile.get("columns") or []:
                try:
                    name = c.get("name")
                    if name is None:
                        continue
                    name = str(name)
                    if name not in known:
                        cols_out.append({"name": name, "dtype": str(c.get("dtype", ""))})
                        known.add(name)
                    stats[name] = {
                        "distinct": c.get("distinct"),
                        "null_pct": c.get("null_pct"),
                    }
                except Exception:
                    continue

        return {
            "table": str(table),
            "columns": cols_out,
            "stats": stats,
            "made_at": _now_iso(),
        }
    except Exception:
        logger.exception("drift.make_baseline failed for %s", table)
        return {"table": str(table), "columns": [], "stats": {}, "made_at": _now_iso()}


def _coltypes(snap: dict) -> dict:
    out = {}
    try:
        for c in snap.get("columns") or []:
            try:
                out[str(c.get("name"))] = str(c.get("dtype", ""))
            except Exception:
                continue
    except Exception:
        pass
    return out


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def compare_baseline(old: dict, new: dict) -> dict:
    try:
        if not old or not isinstance(old, dict) or not (old.get("columns")):
            return {"verdict": "new", "changes": []}
        new = new or {}

        old_t, new_t = _coltypes(old), _coltypes(new)
        changes: list[str] = []

        added = sorted(set(new_t) - set(old_t))
        removed = sorted(set(old_t) - set(new_t))
        retyped = sorted(
            n for n in (set(old_t) & set(new_t)) if old_t[n] != new_t[n]
        )
        for n in added:
            changes.append(f"column added: {n}")
        for n in removed:
            changes.append(f"column removed: {n}")
        for n in retyped:
            changes.append(f"column retyped: {n} {old_t[n]} -> {new_t[n]}")

        if changes:
            return {"verdict": "schema_drift", "changes": changes}

        old_s = old.get("stats") or {}
        new_s = new.get("stats") or {}
        stat_changes: list[str] = []
        for col in old_s:
            os_, ns_ = old_s.get(col) or {}, new_s.get(col) or {}
            onp, nnp = _num(os_.get("null_pct")), _num(ns_.get("null_pct"))
            if onp is not None and nnp is not None and abs(nnp - onp) > 0.25:
                stat_changes.append(f"null_pct drift: {col} {onp} -> {nnp}")
                continue
            od, nd = _num(os_.get("distinct")), _num(ns_.get("distinct"))
            if od is not None and nd is not None:
                base = od if od else 1.0
                if abs(nd - od) / abs(base) > 0.5:
                    stat_changes.append(f"distinct drift: {col} {od} -> {nd}")

        if stat_changes:
            return {"verdict": "stat_drift", "changes": stat_changes}
        return {"verdict": "same", "changes": []}
    except Exception:
        logger.exception("drift.compare_baseline failed")
        return {"verdict": "same", "changes": []}
