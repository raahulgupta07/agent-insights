"""
Sequential model bench for CityAgent Analytics.
================================================

Runs ONE fixed question through the live agent, one model at a time, against a
fixed data source, and prints a comparison table (latency / tokens / tool-steps
/ artifact / answer). No app code is touched — pure HTTP against the running API.

Each target model is registered (idempotently) as a custom LLMModel under the
OpenRouter provider, then passed per-completion via prompt.model_id (the DB row
id — NOT the provider string; that's how the completion endpoint resolves it).

Run INSIDE the container (it has httpx + reaches the API on localhost:3000):

    docker cp backend/scripts/model_bench.py ca-app:/tmp/model_bench.py
    docker exec -e DASH_ADMIN_EMAIL=admin@cityagent.io \
                -e DASH_ADMIN_PASSWORD='CityAgent#2026' \
                ca-app /opt/venv/bin/python /tmp/model_bench.py

Env:
    DASH_BASE_URL      default http://localhost:3000
    DASH_ADMIN_EMAIL   admin login
    DASH_ADMIN_PASSWORD
    BENCH_DS_ID        optional: pin the data source id (else auto-pick chinook)
    BENCH_QUESTION     optional: override the question
    BENCH_MODELS       optional: comma list to override the default model set
    BENCH_TIMEOUT      optional: per-completion seconds (default 600)
"""

import os
import sys
import time
import json
import asyncio

import httpx


def clear_caches(org_id: str) -> str:
    """Wipe serve-caches for the org so each model actually runs the agent (not a cache hit)."""
    try:
        import main  # noqa: F401  (registers ORM + settings)
        from sqlalchemy import text
        from app.settings.database import create_async_session_factory

        async def _go():
            n = 0
            S = create_async_session_factory()
            async with S() as db:
                for t in ("answer_cache", "query_cache", "code_cache"):
                    r = await db.execute(text(f"DELETE FROM {t} WHERE organization_id = :o"), {"o": org_id})
                    n += r.rowcount or 0
                await db.commit()
            return n

        return f"cleared {asyncio.run(_go())} cache rows"
    except Exception as e:  # noqa: BLE001
        return f"cache-clear FAILED: {type(e).__name__}: {e}"

BASE = os.environ.get("DASH_BASE_URL", "http://localhost:3000").rstrip("/")
EMAIL = os.environ.get("DASH_ADMIN_EMAIL")
PASSWORD = os.environ.get("DASH_ADMIN_PASSWORD")
TIMEOUT = float(os.environ.get("BENCH_TIMEOUT", "600"))

QUESTION = os.environ.get(
    "BENCH_QUESTION",
    "Who are the top 5 artists by revenue in 2023 versus 2024, and show the trend?",
)

DEFAULT_MODELS = [
    "z-ai/glm-5.2",
    "moonshotai/kimi-k2.7-code",
    "google/gemini-3.5-flash",
    "minimax/minimax-m3",
    "moonshotai/kimi-k2.6",
]
MODELS = [m.strip() for m in os.environ.get("BENCH_MODELS", "").split(",") if m.strip()] or DEFAULT_MODELS


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def login(c: httpx.Client) -> dict:
    r = c.post(
        "/api/auth/jwt/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status_code != 200:
        die(f"login failed {r.status_code}: {r.text}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def resolve_org(c: httpx.Client, auth: dict) -> str:
    r = c.get("/api/users/whoami", headers=auth)
    if r.status_code != 200:
        die(f"whoami failed {r.status_code}: {r.text}")
    me = r.json()
    for k in ("organization_id", "organizations", "memberships"):
        v = me.get(k)
        if isinstance(v, str):
            return v
        if isinstance(v, list) and v:
            first = v[0]
            if isinstance(first, dict):
                return first.get("organization_id") or first.get("id")
            return first
    die(f"could not resolve org id from whoami: {me}")


def get_openrouter_provider(c: httpx.Client, h: dict) -> str:
    r = c.get("/api/llm/providers", headers=h)
    if r.status_code != 200:
        die(f"list providers failed {r.status_code}: {r.text}")
    provs = r.json()
    for p in provs:
        if str(p.get("name", "")).lower() == "openrouter":
            return p["id"]
    # fall back to the first custom provider
    for p in provs:
        if p.get("provider_type") == "custom":
            return p["id"]
    die(f"no OpenRouter/custom provider found among {[p.get('name') for p in provs]}")


def ensure_models(c: httpx.Client, h: dict, provider_id: str) -> dict:
    """Return {provider_model_string: db_row_id} for every target model, creating rows as needed."""
    r = c.get("/api/llm/models", headers=h)
    if r.status_code != 200:
        die(f"list models failed {r.status_code}: {r.text}")
    existing = {m["model_id"]: m["id"] for m in r.json()}
    out = {}
    for ms in MODELS:
        if ms in existing:
            out[ms] = existing[ms]
            print(f"  model exists: {ms} -> {existing[ms]}")
            continue
        body = {
            "name": f"bench: {ms}",
            "model_id": ms,
            "provider_id": provider_id,
            "is_custom": True,
        }
        rr = c.post("/api/llm/models", headers=h, json=body)
        if rr.status_code not in (200, 201):
            print(f"  WARN register failed {ms}: {rr.status_code} {rr.text[:200]}")
            continue
        out[ms] = rr.json()["id"]
        print(f"  registered: {ms} -> {out[ms]}")
    return out


def pick_data_source(c: httpx.Client, h: dict) -> tuple[str, str]:
    pinned = os.environ.get("BENCH_DS_ID")
    r = c.get("/api/data_sources", headers=h)
    if r.status_code != 200:
        die(f"list data_sources failed {r.status_code}: {r.text}")
    dss = r.json()
    if not dss:
        die("no data sources exist — add the chinook demo first")
    if pinned:
        for d in dss:
            if d["id"] == pinned:
                return d["id"], d.get("name", "?")
        die(f"BENCH_DS_ID {pinned} not found")
    for d in dss:
        name = str(d.get("name", "")).lower()
        if "music" in name or "chinook" in name:
            return d["id"], d.get("name")
    return dss[0]["id"], dss[0].get("name")  # fallback: first


def extract_result(c: httpx.Client, h: dict, report_id: str) -> dict:
    """Pull the last system completion's answer + step/error signals."""
    r = c.get(f"/api/reports/{report_id}/completions", headers=h)
    if r.status_code != 200:
        return {"answer": None, "error": f"poll failed {r.status_code}", "steps": 0,
                "tool_steps": 0, "errored": True, "served_by": None, "model": None}
    data = r.json()
    comps = data.get("completions") if isinstance(data, dict) else data
    comps = comps or []
    # last system completion (carries the agent output blocks)
    system = None
    for comp in comps:
        if comp.get("role") == "system" or (comp.get("completion_blocks") or []):
            system = comp
    if system is None and comps:
        system = comps[-1]
    system = system or {}
    blocks = system.get("completion_blocks") or []
    answer = None
    last_err = None
    tool_steps = 0
    error_blocks = 0
    for b in blocks:
        if b.get("status") == "error":
            error_blocks += 1
            last_err = b.get("title") or (b.get("plan_decision") or {}).get("reasoning")
        if b.get("tool_execution"):
            tool_steps += 1
        c_ = b.get("content")
        pd = b.get("plan_decision") or {}
        if c_:
            answer = c_
        elif pd.get("final_answer"):
            answer = pd["final_answer"]
    if not answer:
        answer = system.get("content") or system.get("completion") or system.get("summary")
    # "errored" only when the run produced NO usable answer despite an error block
    errored = bool(error_blocks) and not answer
    return {
        "answer": answer,
        "error": last_err if errored else None,
        "steps": len(blocks),
        "tool_steps": tool_steps,
        "errored": errored,
        "served_by": system.get("served_by"),
        "model": system.get("model"),
    }


def run_one(c: httpx.Client, h: dict, ds_id: str, model_string: str, model_db_id: str) -> dict:
    # fresh report per model
    r = c.post("/api/reports", headers=h, json={"title": f"bench {model_string}", "data_sources": [ds_id]})
    if r.status_code not in (200, 201):
        return {"model": model_string, "ok": False, "latency": 0, "err": f"report create {r.status_code}: {r.text[:200]}"}
    report_id = r.json()["id"]

    # Unique trailing reference tag per run => distinct cache key (normalize_question
    # only strips TRAILING punctuation, so an alphanumeric token in the tail survives)
    # => forces a REAL agent run instead of an answer_cache hit, with no cross-model
    # contamination and no clear/write-back race. Same analytical task for all models.
    nonce = f"{abs(hash(model_string)) % 100000:05d}{int(time.time()) % 100000:05d}"
    question = f"{QUESTION} (analysis ref {nonce})"
    payload = {
        "prompt": {"content": question, "model_id": model_db_id, "mode": "chat"},
        "stream": True,
    }
    sse_headers = {**h, "Accept": "text/event-stream"}
    t0 = time.time()
    events = 0
    try:
        # The live agent is driven by consuming the SSE stream to its end.
        with c.stream("POST", f"/api/reports/{report_id}/completions",
                      headers=sse_headers, json=payload, timeout=TIMEOUT) as resp:
            if resp.status_code not in (200, 201):
                body = resp.read().decode("utf-8", "replace")
                return {"model": model_string, "ok": False, "latency": round(time.time() - t0, 1),
                        "err": f"completion {resp.status_code}: {body[:300]}", "report_id": report_id}
            for line in resp.iter_lines():
                if line:
                    events += 1
            print(f"    [debug] stream status={resp.status_code} events={events}", flush=True)
    except Exception as e:  # noqa: BLE001
        return {"model": model_string, "ok": False, "latency": round(time.time() - t0, 1),
                "err": f"stream exception: {type(e).__name__}: {e}", "report_id": report_id}
    latency = round(time.time() - t0, 1)

    res = extract_result(c, h, report_id)
    res["sse_events"] = events
    return {
        "model": model_string,
        "ran_model": res.get("model"),
        "ok": not res["errored"] and bool(res["answer"]),
        "latency": latency,
        "steps": res["steps"],
        "tool_steps": res["tool_steps"],
        "errored": res["errored"],
        "served_by": res["served_by"],
        "answer": (res["answer"] if isinstance(res["answer"], str) else json.dumps(res["answer"], default=str) if res["answer"] else "").strip(),
        "report_id": report_id,
        "err": res["error"],
    }


def main() -> None:
    if not (EMAIL and PASSWORD):
        die("set DASH_ADMIN_EMAIL and DASH_ADMIN_PASSWORD")
    print(f"== model bench == base={BASE}")
    print(f"   question: {QUESTION}")
    print(f"   models:   {MODELS}\n")

    with httpx.Client(base_url=BASE, timeout=60) as c:
        auth = login(c)
        org_id = resolve_org(c, auth)
        h = {**auth, "X-Organization-Id": str(org_id)}
        print(f"   org: {org_id}")

        provider_id = get_openrouter_provider(c, h)
        print(f"   provider(OpenRouter): {provider_id}")
        print("   registering models...")
        model_ids = ensure_models(c, h, provider_id)
        if not model_ids:
            die("no usable models registered")

        ds_id, ds_name = pick_data_source(c, h)
        print(f"   data source: {ds_name} ({ds_id})\n")

        results = []
        for ms in MODELS:
            if ms not in model_ids:
                results.append({"model": ms, "ok": False, "latency": 0, "err": "not registered (model id likely invalid on OpenRouter)"})
                print(f"--- SKIP {ms} (not registered)")
                continue
            print(f"--- RUN {ms} ...  ({clear_caches(org_id)})", flush=True)
            res = run_one(c, h, ds_id, ms, model_ids[ms])
            results.append(res)
            tag = "OK " if res.get("ok") else "FAIL"
            print(f"    {tag} {res['latency']}s  steps={res.get('steps','-')} tools={res.get('tool_steps','-')}"
                  f" served_by={res.get('served_by')} err={res.get('err')}")
            if res.get("answer"):
                print(f"    answer: {res['answer'][:280]}")
            print()

    # comparison table
    print("\n================ COMPARISON ================")
    hdr = f"{'model':<26} {'ok':<5} {'lat(s)':<7} {'steps':<6} {'tools':<6} {'served_by':<12} note"
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        note = r.get("err") or ("answered" if r.get("answer") else "no answer")
        print(f"{r['model']:<26} {str(r.get('ok')):<5} {str(r.get('latency')):<7} "
              f"{str(r.get('steps','-')):<6} {str(r.get('tool_steps','-')):<6} "
              f"{str(r.get('served_by') or '-'):<12} {str(note)[:60]}")
    print("\n--- JSON ---")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
