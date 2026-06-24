"""Per-user concurrency cap for skill-script execution.

Each user may have at most ``SKILL_MAX_CONCURRENT_PER_USER`` skill scripts
running at once. A request that would exceed the cap is rejected fast
(SkillRunBusyError) rather than queued, so one user cannot starve the shared
executor pool.

Two backends, same ``user_run_slot`` API:

* **Redis** (when ``REDIS_URL`` is set and reachable) — a per-user sorted set of
  live slots scored by expiry. The cap holds across ALL api/worker replicas, and
  a crashed run's slot auto-expires (leak-safe). This is the Tier-2 path.
* **In-process semaphore** (fallback) — correct on a single process only. Used
  when Redis is absent/unreachable so dev + single-box deploys keep working.

The slot TTL is ``SKILL_EXEC_TIMEOUT_S`` + buffer, so a slot can never outlive
the run it guards even if a worker dies mid-execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SkillRunBusyError(Exception):
    """Raised when a user is already at their concurrent skill-run cap."""


_DEFAULT_CAP = 2


def _cap() -> int:
    raw = os.environ.get("SKILL_MAX_CONCURRENT_PER_USER")
    if not raw:
        return _DEFAULT_CAP
    try:
        n = int(raw)
        return n if n > 0 else _DEFAULT_CAP
    except (TypeError, ValueError):
        return _DEFAULT_CAP


def _slot_ttl() -> int:
    raw = os.environ.get("SKILL_EXEC_TIMEOUT_S")
    try:
        n = int(raw) if raw else 60
    except (TypeError, ValueError):
        n = 60
    return max(5, n) + 10  # buffer so the slot outlives the run, then expires


# --------------------------------------------------------------------------- #
# Redis backend (Tier-2; shared across replicas)
# --------------------------------------------------------------------------- #
# Atomic acquire: drop expired slots, count live ones, add ours only if < cap.
_ACQUIRE_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local cap = tonumber(ARGV[3])
local slot = ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
local n = redis.call('ZCARD', key)
if n < cap then
  redis.call('ZADD', key, now + ttl, slot)
  redis.call('EXPIRE', key, ttl + 5)
  return 1
else
  return 0
end
"""

_redis = None
_redis_init = False
_acquire_sha = None


async def _get_redis():
    """Lazily connect to Redis. Returns a client or None (→ in-proc fallback)."""
    global _redis, _redis_init, _acquire_sha
    if _redis_init:
        return _redis
    _redis_init = True
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
        await client.ping()
        _acquire_sha = await client.script_load(_ACQUIRE_LUA)
        _redis = client
        logger.info("run_guard: using Redis-backed per-user concurrency cap")
    except Exception as e:
        logger.warning("run_guard: Redis unavailable (%s); using in-proc cap", e)
        _redis = None
    return _redis


async def _redis_acquire(client, key: str) -> Optional[str]:
    global _acquire_sha
    slot = uuid.uuid4().hex
    now = time.time()
    try:
        ok = await client.evalsha(
            _acquire_sha, 1, key, now, _slot_ttl(), _cap(), slot
        )
    except Exception:
        # Script cache lost (e.g. failover) — reload once and retry.
        try:
            _acquire_sha = await client.script_load(_ACQUIRE_LUA)
            ok = await client.evalsha(
                _acquire_sha, 1, key, now, _slot_ttl(), _cap(), slot
            )
        except Exception as e:
            raise RuntimeError(f"redis acquire failed: {e}")
    return slot if int(ok) == 1 else None


# --------------------------------------------------------------------------- #
# In-process backend (fallback; single process only)
# --------------------------------------------------------------------------- #
_user_sems: Dict[str, asyncio.Semaphore] = {}
_registry_lock = asyncio.Lock()


async def _get_sem(key: str) -> asyncio.Semaphore:
    sem = _user_sems.get(key)
    if sem is not None:
        return sem
    async with _registry_lock:
        sem = _user_sems.get(key)
        if sem is None:
            sem = asyncio.Semaphore(_cap())
            _user_sems[key] = sem
        return sem


@asynccontextmanager
async def user_run_slot(user_id):
    """Acquire a run slot for ``user_id`` or raise SkillRunBusyError immediately.

    Usage:
        async with user_run_slot(user_id):
            ... run the script ...
    """
    key_id = str(user_id or "anonymous")
    client = await _get_redis()

    if client is not None:
        rkey = f"skillrun:cap:{key_id}"
        try:
            slot = await _redis_acquire(client, rkey)
        except Exception as e:
            # Redis hiccup mid-flight — fail open to in-proc rather than block.
            logger.warning("run_guard: redis acquire error (%s); in-proc fallback", e)
            slot = None
            client = None
        if client is not None:
            if slot is None:
                raise SkillRunBusyError(
                    f"User already running the max concurrent skill scripts ({_cap()})."
                )
            try:
                yield
            finally:
                try:
                    await client.zrem(rkey, slot)
                except Exception:
                    pass  # slot will TTL-expire even if release fails
            return

    # ---- in-process fallback ----
    sem = await _get_sem(key_id)
    if sem.locked() and sem._value <= 0:
        raise SkillRunBusyError(
            f"User already running the max concurrent skill scripts ({_cap()})."
        )
    try:
        await asyncio.wait_for(sem.acquire(), timeout=0.01)
    except asyncio.TimeoutError:
        raise SkillRunBusyError(
            f"User already running the max concurrent skill scripts ({_cap()})."
        )
    try:
        yield
    finally:
        sem.release()
