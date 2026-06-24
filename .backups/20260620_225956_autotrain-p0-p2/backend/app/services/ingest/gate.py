"""Ingest gate: cheap quality score -> promote or quarantine.

Pure (no DB). Mirrors dash's defensive threshold: only quarantine clearly-bad
tiny tables; real CRM/finance data (many rows) always passes.
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def score_dataframe(df: pd.DataFrame) -> dict:
    """Return {score:0-100, rows, cols, issues:[...], verdict:'promote'|'quarantine'}.

    quarantine only when score < 10 AND rows < 5 (defensive; never blocks real data).
    """
    issues: list[str] = []
    try:
        if df is None or df.empty:
            return {"score": 0, "rows": 0, "cols": 0, "issues": ["empty"], "verdict": "quarantine"}

        rows, cols = df.shape
        score = 100

        # unnamed columns
        unnamed = sum(1 for c in df.columns if str(c).strip().lower().startswith("unnamed"))
        if unnamed:
            score -= min(30, unnamed * 10)
            issues.append(f"{unnamed} unnamed columns")

        # null density
        null_pct = float(df.isna().mean().mean()) if cols else 1.0
        if null_pct > 0.5:
            score -= 30
            issues.append(f"{null_pct:.0%} null")

        # duplicate columns
        dupes = len(df.columns) - len(set(map(str, df.columns)))
        if dupes:
            score -= 10
            issues.append(f"{dupes} duplicate column names")

        score = max(0, score)
        verdict = "quarantine" if (score < 10 and rows < 5) else "promote"
        return {"score": score, "rows": rows, "cols": cols, "issues": issues, "verdict": verdict}
    except Exception:
        logger.exception("score_dataframe failed")
        return {"score": 0, "rows": 0, "cols": 0, "issues": ["error"], "verdict": "quarantine"}
