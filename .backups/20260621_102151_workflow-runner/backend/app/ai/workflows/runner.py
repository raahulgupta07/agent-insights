"""Pure workflow engine: fan a work-list through a stage with a verifier gate.

`run_pipeline` NEVER raises -> always returns a summary dict + a per-item log.
The orchestration (sequence, retries, pass/skip/fail bookkeeping) is fully
deterministic code; only the caller-supplied `stage_fn` / `judge_fn` may call
the LLM. Concurrency is bounded (asyncio.Semaphore) purely to cap parallelism —
it never changes the per-item verdict.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


def _short(value, limit: int = 160) -> str:
    """Best-effort compact string for an item / result in the log."""
    try:
        s = str(value)
    except Exception:
        return "<unrepr>"
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _result_summary(result) -> str:
    """One-line summary of a stage result (dict -> key counts; else str)."""
    if isinstance(result, dict):
        parts = []
        for k in ("table", "semantics", "metrics", "qa", "errors"):
            if k in result:
                v = result[k]
                if isinstance(v, (list, tuple, set)):
                    parts.append(f"{k}={len(v)}")
                else:
                    parts.append(f"{k}={_short(v, 40)}")
        if parts:
            return ", ".join(parts)
    return _short(result, 120)


async def run_pipeline(
    *,
    items: list,
    stage_fn: Callable[[object], Awaitable[object]],
    judge_fn: Optional[Callable[[object, object], Awaitable[dict]]] = None,
    max_concurrency: int = 4,
    max_retries: int = 1,
    label: str = "workflow",
) -> dict:
    """Run `stage_fn` over `items`, gating each result with `judge_fn`.

    For each item, attempt up to (1 + max_retries) times:
      - result = await stage_fn(item)
      - if judge_fn: verdict = await judge_fn(item, result) -> {"ok", "reason"}
          ok      -> 'passed' (keep result, stop)
          not ok  -> retry; after retries exhausted -> 'skipped' (gate rejected)
      - stage_fn raising -> retry; after retries exhausted -> 'failed' (error)

    Returns:
      {label, processed, passed, skipped, failed, log: [...], results: [...]}
    where `results` holds the kept results of 'passed' items and each log entry
    is {item, status, attempts, reason, result_summary}. Never raises.
    """
    items = list(items or [])
    try:
        cap = max(1, int(max_concurrency or 1))
    except Exception:
        cap = 1
    try:
        retries = max(0, int(max_retries or 0))
    except Exception:
        retries = 0
    attempts_allowed = 1 + retries

    sem = asyncio.Semaphore(cap)
    log: list = [None] * len(items)
    results: list = [None] * len(items)

    async def _process(idx: int, item) -> None:
        status = "failed"
        reason = ""
        kept = None
        attempt = 0
        async with sem:
            for attempt in range(1, attempts_allowed + 1):
                # --- run the worker --------------------------------------
                try:
                    result = await stage_fn(item)
                except Exception as e:  # noqa: BLE001
                    status = "failed"
                    reason = f"stage error: {_short(e, 200)}"
                    logger.debug("pipeline %s: stage_fn raised", label, exc_info=True)
                    continue  # retry (or exhaust -> stays 'failed')

                # --- gate the result -------------------------------------
                if judge_fn is None:
                    status, reason, kept = "passed", "no judge", result
                    break
                try:
                    verdict = await judge_fn(item, result)
                except Exception as e:  # judge should fail-soft; belt+suspenders
                    logger.debug("pipeline %s: judge_fn raised", label, exc_info=True)
                    verdict = {"ok": True, "reason": f"judge error -> pass-through ({_short(e, 80)})"}
                ok = bool(isinstance(verdict, dict) and verdict.get("ok"))
                reason = (isinstance(verdict, dict) and str(verdict.get("reason", ""))) or ""
                if ok:
                    status, kept = "passed", result
                    break
                # gate rejected -> retry; if no retries left this becomes 'skipped'
                status = "skipped"

        results[idx] = kept if status == "passed" else None
        log[idx] = {
            "item": _short(item),
            "status": status,
            "attempts": attempt,
            "reason": reason,
            "result_summary": _result_summary(kept) if status == "passed" else "",
        }

    try:
        await asyncio.gather(*(_process(i, it) for i, it in enumerate(items)))
    except Exception:  # gather should never surface (each task is guarded)
        logger.exception("pipeline %s: gather failed", label)

    clean_log = [e for e in log if e is not None]
    passed_results = [results[i] for i, e in enumerate(log) if e and e["status"] == "passed"]
    counts = {"passed": 0, "skipped": 0, "failed": 0}
    for e in clean_log:
        counts[e["status"]] = counts.get(e["status"], 0) + 1

    return {
        "label": label,
        "processed": len(clean_log),
        "passed": counts["passed"],
        "skipped": counts["skipped"],
        "failed": counts["failed"],
        "log": clean_log,
        "results": passed_results,
    }


# ---------------------------------------------------------------------------
# Verifier factories
# ---------------------------------------------------------------------------

def llm_judge(model, *, criteria: str):
    """Build an async judge_fn(item, result) -> {"ok", "reason"} via ONE LLM call.

    Fail-soft: any error (no model, LLM failure, unparsable reply) -> pass-through
    so a flaky judge never blocks the pipeline.
    """

    async def _judge(item, result) -> dict:
        if model is None:
            return {"ok": True, "reason": "judge error -> pass-through (no model)"}
        try:
            from app.ai.llm.llm import LLM
            from app.dependencies import async_session_maker

            prompt = (
                f"You verify a step. Criteria: {criteria}\n"
                f"Item: {item}\n"
                f"Result: {result}\n"
                "Reply exactly 'PASS: <reason>' or 'FAIL: <reason>'."
            )
            llm = LLM(model, usage_session_maker=async_session_maker)
            raw = await asyncio.to_thread(llm.inference, prompt)
        except Exception as e:  # noqa: BLE001
            logger.debug("llm_judge: inference failed", exc_info=True)
            return {"ok": True, "reason": f"judge error -> pass-through ({_short(e, 80)})"}

        text = (raw or "").strip()
        head = text.lstrip().lower()
        if head.startswith("pass"):
            return {"ok": True, "reason": _short(text, 200)}
        if head.startswith("fail"):
            return {"ok": False, "reason": _short(text, 200)}
        # Unparsable -> don't block.
        return {"ok": True, "reason": f"judge error -> pass-through (unparsed: {_short(text, 80)})"}

    return _judge


def produced_knowledge_judge():
    """Deterministic gate: ok iff the result produced any knowledge.

    'Knowledge' = a non-empty `semantics`, `metrics`, or `qa` on the result dict.
    """

    async def _judge(item, result) -> dict:
        try:
            sem = (result or {}).get("semantics") if isinstance(result, dict) else None
            met = (result or {}).get("metrics") if isinstance(result, dict) else None
            qa = (result or {}).get("qa") if isinstance(result, dict) else None
        except Exception:
            sem = met = qa = None
        if sem or met or qa:
            n_sem = len(sem) if isinstance(sem, (list, tuple, set)) else (sem or 0)
            n_met = len(met) if isinstance(met, (list, tuple, set)) else (met or 0)
            n_qa = qa if isinstance(qa, int) else (len(qa) if isinstance(qa, (list, tuple, set)) else 0)
            return {
                "ok": True,
                "reason": f"produced knowledge (semantics={n_sem}, metrics={n_met}, qa={n_qa})",
            }
        return {"ok": False, "reason": "no knowledge produced (no semantics/metrics/qa)"}

    return _judge
