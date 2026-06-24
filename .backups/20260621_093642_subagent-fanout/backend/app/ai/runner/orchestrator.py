"""Orchestrator-worker fan-out for subagents.

A complex/multi-source question is decomposed into <=N focused sub-questions;
each is handed to a clean-context research WORKER (``run_subtask``) that:

  1. asks the LLM for ONE read-only SELECT (+ which client key to run it on),
  2. runs it against ``ds_clients[key].execute_query(sql)`` (one retry on error,
     feeding the error back to the LLM),
  3. asks the LLM to distill the returned rows into a concise answer.

The orchestrator (``run_fanout``) fans the workers out concurrently behind a
Semaphore (the concurrency cap + bounded per-worker steps = the cost guard) and
then synthesizes the worker findings into one final answer.

GENUINE subagents: clean per-worker context, own data access, distilled return.
NOT full AgentV2 — no plan/execute/reflect loop, no nested tool use.

Everything here is async and NEVER raises: every public coroutine returns a safe
dict/list and logs failures via the module logger. The LLM ``inference`` call is
sync, so it is offloaded with ``asyncio.to_thread`` to avoid blocking the loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Reuse the robust JSON parse style from autotrain/qa_gen.py.
_FORBIDDEN_RE = re.compile(
    r"(?i)\b(insert|update|delete|drop|alter|truncate|create|grant)\b"
)
_FENCE_RE = re.compile(r"```[a-zA-Z]*\s*|\s*```")
_SELECT_RE = re.compile(r"(?is)^\s*(?:with\b.+?\)\s*)?select\b")

_MAX_ROWS = 50            # rows fed back to the LLM for distillation
_ANSWER_CAP = 1500        # max chars of a worker / synthesis answer
_DEFAULT_CAP = 4          # default max workers / sub-questions


# --------------------------------------------------------------------------- #
# JSON parsing (robust, mirrors autotrain/qa_gen.py)                          #
# --------------------------------------------------------------------------- #
def _strip_fences(s: Any) -> str:
    if not isinstance(s, str):
        return ""
    return _FENCE_RE.sub("", s).strip()


def _extract_json(raw: Any):
    """Best-effort extraction of the first JSON array/object from raw text."""
    if not isinstance(raw, str):
        return None
    text = _strip_fences(raw)
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        return None
    start = min(starts)
    open_ch = text[start]
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    end = -1
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    candidate = text[start:end] if end != -1 else text[start:]
    repaired = re.sub(r",(\s*[\]}])", r"\1", candidate)  # trailing-comma repair
    for attempt in (candidate, repaired):
        try:
            return json.loads(attempt)
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _is_read_only_select(sql: str) -> bool:
    """True only for a single read-only SELECT (or WITH ... SELECT)."""
    if not isinstance(sql, str) or not sql.strip():
        return False
    if _FORBIDDEN_RE.search(sql):
        return False
    return bool(_SELECT_RE.match(sql.strip()))


def _pick_client(ds_clients: Dict[str, Any], key: Optional[str]):
    """Resolve a client by key; fall back to the first available client."""
    if not ds_clients:
        return None
    if key:
        client = ds_clients.get(key)
        if client is not None:
            return client
        # case-insensitive / prefix match (clients are often keyed "name:id")
        kl = str(key).strip().lower()
        for k, v in ds_clients.items():
            ks = str(k).lower()
            if ks == kl or ks.startswith(f"{kl}:") or kl.startswith(f"{ks}:"):
                return v
    try:
        return next(iter(ds_clients.values()))
    except Exception:
        return None


def _build_schema_hint(data_sources_or_clients) -> str:
    """Best-effort "table: col, col" lines (cap ~30 tables). Fail-soft -> ""."""
    lines: List[str] = []
    seen: set = set()

    def _add_table(name: str, cols: List[str]):
        if not name or name in seen:
            return
        seen.add(name)
        col_str = ", ".join([c for c in cols if c][:25])
        lines.append(f"{name}: {col_str}" if col_str else f"{name}")

    try:
        # dict of clients -> use get_schemas() per client (cheap-ish, best-effort)
        if isinstance(data_sources_or_clients, dict):
            for client in data_sources_or_clients.values():
                if len(lines) >= 30:
                    break
                try:
                    tables = client.get_schemas() if hasattr(client, "get_schemas") else []
                except Exception:
                    tables = []
                for t in tables or []:
                    if len(lines) >= 30:
                        break
                    name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
                    cols_raw = getattr(t, "columns", None)
                    if cols_raw is None and isinstance(t, dict):
                        cols_raw = t.get("columns")
                    cols = []
                    for c in (cols_raw or []):
                        cn = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else None)
                        if cn:
                            cols.append(str(cn))
                    if name:
                        _add_table(str(name), cols)
            return "\n".join(lines)

        # iterable of DataSource -> read its DataSourceTable rows
        for ds in (data_sources_or_clients or []):
            if len(lines) >= 30:
                break
            tables = getattr(ds, "tables", None) or []
            for dst in tables:
                if len(lines) >= 30:
                    break
                # Skip inactive tables when the flag is present.
                if getattr(dst, "is_active", True) is False:
                    continue
                name = getattr(dst, "name", None)
                cols: List[str] = []
                try:
                    prompt_table = dst.to_prompt_table()
                    name = getattr(prompt_table, "name", None) or name
                    for c in getattr(prompt_table, "columns", None) or []:
                        cn = getattr(c, "name", None)
                        if cn:
                            cols.append(str(cn))
                except Exception:
                    # legacy/raw columns JSON fallback
                    for c in (getattr(dst, "columns", None) or []):
                        cn = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
                        if cn:
                            cols.append(str(cn))
                if name:
                    _add_table(str(name), cols)
    except Exception as e:  # pragma: no cover - fail-soft
        logger.debug("subagent _build_schema_hint failed: %s", e)
        return "\n".join(lines)

    return "\n".join(lines)


async def _llm_infer(model, prompt: str) -> str:
    """Offload the sync LLM.inference onto a thread. Never raises -> ''."""
    try:
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        def _run() -> str:
            llm = LLM(model, usage_session_maker=async_session_maker)
            return llm.inference(
                prompt,
                usage_scope="subagent",
                should_record=True,
            )

        out = await asyncio.to_thread(_run)
        return out if isinstance(out, str) else (str(out) if out is not None else "")
    except Exception as e:
        logger.warning("subagent LLM inference failed: %s", e)
        return ""


async def _run_query(client, sql: str):
    """Run sync execute_query off-thread. Returns (ok, df_or_none, error_str)."""
    try:
        df = await asyncio.to_thread(client.execute_query, sql)
        return True, df, ""
    except Exception as e:
        return False, None, str(e)


def _df_preview(df) -> str:
    """Compact JSON-ish preview of df.head(_MAX_ROWS). Fail-soft -> ''."""
    try:
        head = df.head(_MAX_ROWS)
        records = head.to_dict(orient="records")
        text = json.dumps(records, default=str)
        return text[:6000]
    except Exception:
        try:
            return str(df)[:6000]
        except Exception:
            return ""


# --------------------------------------------------------------------------- #
# worker                                                                       #
# --------------------------------------------------------------------------- #
async def run_subtask(
    *,
    sub_question: str,
    model,
    ds_clients: Dict[str, Any],
    schema_hint: str = "",
    max_steps: int = 2,
) -> dict:
    """Mini-analyst for ONE focused question.

    Bounded: <=2 LLM calls + <=2 queries. Returns a safe dict; never raises.
    """
    result = {
        "question": sub_question,
        "answer": "",
        "sql": "",
        "ok": False,
        "error": "",
    }
    ds_clients = ds_clients or {}
    keys = list(ds_clients.keys())

    # No data access at all -> LLM best-effort answer, ok=False.
    if not keys:
        prompt = (
            "You are a research assistant. Answer the question as best you can "
            "from general knowledge; you have NO data access for this run.\n\n"
            f"Question: {sub_question}\n\n"
            "Give a short, direct answer (<= 600 chars). If you genuinely cannot "
            "answer without data, say so plainly."
        )
        ans = await _llm_infer(model, prompt)
        result["answer"] = (ans or "No data source was available to answer this sub-question.")[:_ANSWER_CAP]
        result["error"] = "no data clients available"
        return result

    # ---- step 1: LLM emits ONE read-only SELECT + client key ---------------- #
    schema_block = f"\nAvailable tables (schema hint):\n{schema_hint}\n" if schema_hint else ""
    sql_prompt = (
        "You are a careful SQL analyst answering ONE focused question by querying "
        "a SQL data source.\n"
        f"Available client keys: {keys}\n"
        f"{schema_block}\n"
        f"Question: {sub_question}\n\n"
        "Emit ONE read-only SELECT (a single statement; you MAY use a leading "
        "WITH ... clause). Do NOT use INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/"
        "CREATE/GRANT. Use only the table/column names from the schema hint when "
        "given.\n"
        'Respond ONLY with a JSON object: {"sql": "SELECT ...", "client": "<one of the keys>"}.'
    )
    raw = await _llm_infer(model, sql_prompt)
    parsed = _extract_json(raw)
    sql = ""
    client_key = None
    if isinstance(parsed, dict):
        sql = _strip_fences(parsed.get("sql") or parsed.get("query") or "")
        client_key = parsed.get("client") or parsed.get("client_key") or parsed.get("key")

    df = None
    last_error = ""
    if sql and _is_read_only_select(sql):
        client = _pick_client(ds_clients, client_key)
        if client is None or not hasattr(client, "execute_query"):
            last_error = "no usable client resolved"
        else:
            result["sql"] = sql
            ok, df, err = await _run_query(client, sql)
            if not ok:
                last_error = err
                # ---- one retry: feed the error back to the LLM ------------- #
                retry_prompt = (
                    "Your previous SQL failed. Fix it and return a corrected "
                    "single read-only SELECT.\n"
                    f"Available client keys: {keys}\n"
                    f"{schema_block}\n"
                    f"Question: {sub_question}\n"
                    f"Previous SQL:\n{sql}\n"
                    f"Error:\n{err}\n\n"
                    'Respond ONLY with JSON: {"sql": "SELECT ...", "client": "<key>"}.'
                )
                raw2 = await _llm_infer(model, retry_prompt)
                parsed2 = _extract_json(raw2)
                if isinstance(parsed2, dict):
                    sql2 = _strip_fences(parsed2.get("sql") or parsed2.get("query") or "")
                    key2 = parsed2.get("client") or parsed2.get("client_key") or client_key
                    if sql2 and _is_read_only_select(sql2):
                        client2 = _pick_client(ds_clients, key2)
                        if client2 is not None and hasattr(client2, "execute_query"):
                            result["sql"] = sql2
                            ok2, df2, err2 = await _run_query(client2, sql2)
                            if ok2:
                                df = df2
                                last_error = ""
                            else:
                                last_error = err2
    else:
        last_error = "no read-only SELECT could be produced"

    # ---- step 2: distill rows -> concise answer ----------------------------- #
    if df is not None:
        preview = _df_preview(df)
        distill_prompt = (
            "You are a data analyst. Using ONLY the query result below, answer the "
            "question concisely and concretely (cite the actual numbers / names).\n\n"
            f"Question: {sub_question}\n"
            f"SQL used:\n{result['sql']}\n"
            f"Result rows (up to {_MAX_ROWS}, JSON):\n{preview}\n\n"
            "Answer in <= 1500 characters. Do not invent values not present in the rows."
        )
        ans = await _llm_infer(model, distill_prompt)
        if ans:
            result["answer"] = ans[:_ANSWER_CAP]
            result["ok"] = True
            result["error"] = ""
            return result
        last_error = last_error or "distillation produced no answer"

    # ---- fallback: LLM best-effort, ok=False -------------------------------- #
    fallback_prompt = (
        "You are a research assistant. A SQL query for this sub-question did not "
        "succeed. Give your best brief answer from general reasoning and note that "
        "it is not grounded in the data.\n\n"
        f"Question: {sub_question}\n"
        f"(SQL issue: {last_error or 'unknown'})\n\n"
        "Answer in <= 600 chars."
    )
    ans = await _llm_infer(model, fallback_prompt)
    result["answer"] = (ans or "Could not answer this sub-question from the data.")[:_ANSWER_CAP]
    result["ok"] = False
    result["error"] = last_error or "query did not succeed"
    return result


# --------------------------------------------------------------------------- #
# decompose                                                                    #
# --------------------------------------------------------------------------- #
async def decompose(
    *,
    question: str,
    model,
    schema_hint: str = "",
    max_parts: int = 4,
) -> List[str]:
    """Split a complex/multi-source question into <=max_parts focused subs.

    Simple question -> [question]. Robust JSON array parse. Never raises.
    """
    q = (question or "").strip()
    if not q:
        return [question]
    try:
        schema_block = f"\nAvailable tables (schema hint):\n{schema_hint}\n" if schema_hint else ""
        prompt = (
            "You are an analysis planner. Break the user's question into the SMALLEST "
            "set of focused, self-contained sub-questions that can each be answered by "
            "a single SQL query. If the question is already simple/atomic, return it "
            "unchanged as the only element.\n"
            f"Return at most {max_parts} sub-questions.\n"
            f"{schema_block}\n"
            f"Question: {q}\n\n"
            'Respond ONLY with a JSON array of strings, e.g. ["sub-question 1", "sub-question 2"].'
        )
        raw = await _llm_infer(model, prompt)
        parsed = _extract_json(raw)
        subs: List[str] = []
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str) and item.strip():
                    subs.append(item.strip())
                elif isinstance(item, dict):
                    v = item.get("question") or item.get("sub_question") or item.get("q")
                    if isinstance(v, str) and v.strip():
                        subs.append(v.strip())
        if not subs:
            return [q]
        return subs[: max(1, max_parts)]
    except Exception as e:
        logger.warning("subagent decompose failed: %s", e)
        return [q]


# --------------------------------------------------------------------------- #
# orchestrator                                                                 #
# --------------------------------------------------------------------------- #
async def run_fanout(
    *,
    db=None,
    organization,
    user=None,
    model,
    ds_clients: Dict[str, Any],
    data_sources=None,
    question: str,
    max_workers: int = 4,
    max_steps: int = 2,
) -> dict:
    """Decompose -> fan out workers (capped) -> synthesize one final answer.

    Never raises; returns a safe dict.
    """
    ds_clients = ds_clients or {}
    out = {
        "answer": "",
        "subtasks": [],
        "workers": 0,
        "errors": [],
    }
    try:
        # 1) schema hint (prefer the richer DataSource path, else clients) ----- #
        schema_hint = ""
        try:
            if data_sources:
                schema_hint = _build_schema_hint(data_sources)
            if not schema_hint and ds_clients:
                schema_hint = _build_schema_hint(ds_clients)
        except Exception as e:
            logger.debug("subagent schema hint build failed: %s", e)
            schema_hint = ""

        # 2) decompose, cap to max_workers ------------------------------------ #
        cap = max(1, min(int(max_workers or _DEFAULT_CAP), _DEFAULT_CAP))
        subs = await decompose(
            question=question, model=model, schema_hint=schema_hint, max_parts=cap
        )
        subs = subs[:cap]
        out["workers"] = len(subs)

        # 3) fan out with a concurrency cap (the cost guard) ------------------ #
        sem = asyncio.Semaphore(min(cap, 4))

        async def _guarded(sub_q: str) -> dict:
            async with sem:
                return await run_subtask(
                    sub_question=sub_q,
                    model=model,
                    ds_clients=ds_clients,
                    schema_hint=schema_hint,
                    max_steps=max_steps,
                )

        gathered = await asyncio.gather(
            *[_guarded(s) for s in subs], return_exceptions=True
        )
        subtasks: List[dict] = []
        for sub_q, res in zip(subs, gathered):
            if isinstance(res, Exception):
                logger.warning("subagent worker raised: %s", res)
                subtasks.append(
                    {
                        "question": sub_q,
                        "answer": "",
                        "sql": "",
                        "ok": False,
                        "error": str(res),
                    }
                )
            else:
                subtasks.append(res)
        out["subtasks"] = subtasks
        out["errors"] = [t["error"] for t in subtasks if t.get("error")]

        # 4) synthesize ------------------------------------------------------- #
        findings_lines = []
        for i, t in enumerate(subtasks, 1):
            status = "ok" if t.get("ok") else "partial/failed"
            findings_lines.append(
                f"[Finding {i}] ({status}) Q: {t.get('question', '')}\n"
                f"A: {t.get('answer', '')}"
            )
        findings = "\n\n".join(findings_lines) if findings_lines else "(no findings)"

        synth_prompt = (
            "You are the lead analyst. Combine the sub-findings from your research "
            "workers into ONE coherent, concise answer to the original question. "
            "Cite which sub-finding each part comes from (e.g. 'per Finding 1'). If a "
            "finding failed or is uncertain, say so rather than inventing data.\n\n"
            f"Original question: {question}\n\n"
            f"Worker sub-findings:\n{findings}\n\n"
            "Final answer (<= 1500 characters):"
        )
        final = await _llm_infer(model, synth_prompt)
        if not final:
            # Fall back to concatenating the worker answers so we still return something.
            final = "\n\n".join(
                [f"- {t.get('question','')}: {t.get('answer','')}" for t in subtasks]
            )
        out["answer"] = (final or "")[:_ANSWER_CAP]
        return out
    except Exception as e:  # pragma: no cover - top-level safety net
        logger.exception("subagent run_fanout failed: %s", e)
        out["errors"].append(str(e))
        if not out["answer"]:
            out["answer"] = ""
        return out
