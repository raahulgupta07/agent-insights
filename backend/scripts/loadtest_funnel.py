#!/usr/bin/env python3
"""Funnel load test — Phase 9 DECISION GATE instrument.

Fires N concurrent completion requests at a running CityAgent Analytics
instance, then reads ``GET /api/funnel/stats`` to report cache-hit-rate and
latency percentiles. Use it to tune ``LLM_MAX_CONCURRENCY`` / ``DB_POOL_*`` and
to make the Slice-1 gate call ("is cache-hit + cost acceptable?").

This talks to a BOOTED instance over HTTP — it does NOT import the app, so it
runs from anywhere with ``httpx`` installed (already a backend dep).

Env / flags (all overridable):
  BASE_URL      default http://localhost:3007
  DASH_TOKEN     bearer token (login once, paste it)        [required]
  ORG_ID        X-Organization-Id header                   [required]
  REPORT_ID     report to post completions into            [required]
  QUESTION      the question text (repeat it to exercise the cache)
  CONCURRENCY   max in-flight requests   (default 100)
  TOTAL         total requests to send   (default 200)
  WARM_FIRST    if "1", send ONE request first + wait, so the rest hit cache

Typical run (after onboarding + one manual successful ask to seed the cache):
  DASH_TOKEN=... ORG_ID=... REPORT_ID=... QUESTION="top 10 outlets by sales" \
    CONCURRENCY=100 TOTAL=200 python backend/scripts/loadtest_funnel.py

Numbers are wall-clock per request as seen by the client (network + server).
Server-side per-tier latency comes from /api/funnel/stats (elapsed_ms).
"""
from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from typing import List, Optional

try:
    import httpx
except Exception:  # pragma: no cover - dep guard
    print("ERROR: httpx not installed (it is a backend dependency — run inside the app env).", file=sys.stderr)
    raise SystemExit(2)


def _env(name: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
    val = os.environ.get(name, default)
    if required and not val:
        print(f"ERROR: env {name} is required", file=sys.stderr)
        raise SystemExit(2)
    return val


BASE_URL = (_env("BASE_URL", "http://localhost:3007") or "").rstrip("/")
TOKEN = _env("DASH_TOKEN", required=True)
ORG_ID = _env("ORG_ID", required=True)
REPORT_ID = _env("REPORT_ID", required=True)
QUESTION = _env("QUESTION", "top 10 outlets by sales")
CONCURRENCY = int(_env("CONCURRENCY", "100"))
TOTAL = int(_env("TOTAL", "200"))
WARM_FIRST = _env("WARM_FIRST", "0") == "1"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "X-Organization-Id": ORG_ID,
    "Content-Type": "application/json",
}
COMPLETIONS_URL = f"{BASE_URL}/api/reports/{REPORT_ID}/completions"
STATS_URL = f"{BASE_URL}/api/funnel/stats?days=1"


async def _one(client: "httpx.AsyncClient", sem: asyncio.Semaphore, idx: int) -> dict:
    payload = {"prompt": {"content": QUESTION}, "stream": False}
    async with sem:
        t0 = time.monotonic()
        try:
            r = await client.post(COMPLETIONS_URL, json=payload, headers=HEADERS, timeout=300.0)
            ok = r.status_code < 400
            return {"idx": idx, "ms": (time.monotonic() - t0) * 1000.0, "status": r.status_code, "ok": ok}
        except Exception as e:  # noqa: BLE001 - record, don't crash the run
            return {"idx": idx, "ms": (time.monotonic() - t0) * 1000.0, "status": 0, "ok": False, "err": str(e)}


def _pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


async def _fetch_stats(client: "httpx.AsyncClient") -> Optional[dict]:
    try:
        r = await client.get(STATS_URL, headers=HEADERS, timeout=30.0)
        if r.status_code < 400:
            return r.json()
        return {"_error": f"stats HTTP {r.status_code}", "_body": r.text[:300]}
    except Exception as e:  # noqa: BLE001
        return {"_error": str(e)}


async def main() -> int:
    print(f"== funnel load test ==")
    print(f"target   {COMPLETIONS_URL}")
    print(f"total    {TOTAL}   concurrency {CONCURRENCY}   warm_first {WARM_FIRST}")
    print(f"question {QUESTION!r}")

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        before = await _fetch_stats(client)

        if WARM_FIRST:
            print("warming cache with 1 request ...")
            w = await _one(client, asyncio.Semaphore(1), -1)
            print(f"  warm req: status={w['status']} {w['ms']:.0f}ms")
            await asyncio.sleep(1.0)

        t0 = time.monotonic()
        results = await asyncio.gather(*[_one(client, sem, i) for i in range(TOTAL)])
        wall = time.monotonic() - t0

        after = await _fetch_stats(client)

    oks = [r for r in results if r["ok"]]
    fails = [r for r in results if not r["ok"]]
    lat = [r["ms"] for r in oks]

    print("\n-- client-side --")
    print(f"  ok {len(oks)}/{TOTAL}   fail {len(fails)}   wall {wall:.1f}s   throughput {TOTAL / wall:.1f} req/s")
    if lat:
        print(f"  latency ms: p50 {_pct(lat,50):.0f}  p95 {_pct(lat,95):.0f}  p99 {_pct(lat,99):.0f}  max {max(lat):.0f}")
    if fails:
        codes = {}
        for f in fails:
            codes[f["status"]] = codes.get(f["status"], 0) + 1
        print(f"  failures by status: {codes}")
        ex = next((f for f in fails if f.get("err")), None)
        if ex:
            print(f"  sample error: {ex['err'][:200]}")

    print("\n-- server funnel stats (/api/funnel/stats) --")
    print(f"  before: {before}")
    print(f"  after : {after}")

    # gate hint
    try:
        hr = after.get("cache_hit_rate") if isinstance(after, dict) else None
        if hr is not None:
            print(f"\nGATE: cache_hit_rate={hr}  (target high enough that LLM cost is acceptable)")
    except Exception:
        pass

    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
