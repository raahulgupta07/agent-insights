"""
Confirmation registry for tool confirmations.

Allows tools to pause execution and wait for user approval via the frontend.

Cross-worker (prod-hardening): under ``uvicorn --workers N`` the HTTP
``/confirm/{id}`` callback may land on a worker that does NOT own the awaiting
Future. The owning worker keeps its in-proc Future as the fast path; a
non-owning worker that receives the callback publishes the response to a
short-lived Redis key which the owning worker polls. All Redis use is fail-soft
and OPT-IN via ``REDIS_URL`` — when it is unset the code path is byte-identical
to the original single-process behavior (create Future, wait, auto-approve on
timeout). The 5s auto-approve timeout semantics are unchanged; only *resolution*
is made cross-worker.
"""

import asyncio
import json
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

PENDING_CONFIRMATIONS: Dict[str, asyncio.Future] = {}

# Short-lived Redis key carrying a cross-worker resolution. TTL is comfortably
# longer than any confirmation timeout so a slightly-late poll still sees it.
_CONFIRM_KEY = "hybrid:confirm:result:{}"
_CONFIRM_TTL = 30  # seconds

_redis = None
_redis_init = False


def _redis_enabled() -> bool:
    return bool(os.environ.get("REDIS_URL"))


async def _get_redis():
    """Lazily connect to Redis (reusing the repo's redis.asyncio dep). Returns a
    client, or None → in-proc-only fallback."""
    global _redis, _redis_init
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
        _redis = client
        logger.info("confirmation: using Redis-backed cross-worker resolution")
    except Exception as e:  # noqa: BLE001 - never raise into the agent loop
        logger.warning("confirmation: Redis unavailable (%s); single-process only", e)
        _redis = None
    return _redis


async def _redis_poll(confirmation_id: str) -> Optional[dict]:
    """Poll the cross-worker Redis result key until it appears. Bounded by the
    caller's ``asyncio.wait`` timeout (this loops forever otherwise). Returns the
    response dict, or None on any Redis error (→ caller's timeout auto-approves)."""
    client = await _get_redis()
    if client is None:
        # Configured but unreachable — block so the wall-clock timeout wins.
        await asyncio.sleep(_CONFIRM_TTL * 2)
        return None
    key = _CONFIRM_KEY.format(confirmation_id)
    while True:
        try:
            raw = await client.get(key)
        except Exception as e:  # noqa: BLE001
            logger.warning("confirmation: redis poll error %s", e)
            return None
        if raw is not None:
            try:
                await client.delete(key)
            except Exception:  # noqa: BLE001
                pass
            try:
                return json.loads(raw)
            except Exception:  # noqa: BLE001
                return {"approved": True}
        await asyncio.sleep(0.2)


async def wait_for_confirmation(confirmation_id: str, timeout: float = 5.0) -> dict:
    """Wait for a user confirmation response, auto-approving on timeout."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    PENDING_CONFIRMATIONS[confirmation_id] = future
    logger.info(f"Confirmation {confirmation_id}: waiting (timeout={timeout}s, pending={len(PENDING_CONFIRMATIONS)})")
    try:
        if not _redis_enabled():
            # Single-process fast path — byte-identical to the original.
            try:
                result = await asyncio.wait_for(future, timeout=timeout)
                logger.info(f"Confirmation {confirmation_id}: resolved by user — {result}")
                return result
            except asyncio.TimeoutError:
                logger.info(f"Confirmation {confirmation_id}: timed out, auto-approving")
                return {"approved": True}

        # Multi-worker: race the local Future against a Redis poll, same timeout.
        fut_task = asyncio.ensure_future(future)
        poll_task = asyncio.ensure_future(_redis_poll(confirmation_id))
        try:
            done, pending = await asyncio.wait(
                {fut_task, poll_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if fut_task in done and not fut_task.cancelled():
                try:
                    result = fut_task.result()
                    logger.info(f"Confirmation {confirmation_id}: resolved locally — {result}")
                    return result
                except Exception:  # noqa: BLE001
                    pass
            if poll_task in done and not poll_task.cancelled():
                try:
                    r = poll_task.result()
                    if r is not None:
                        logger.info(f"Confirmation {confirmation_id}: resolved cross-worker — {r}")
                        return r
                except Exception:  # noqa: BLE001
                    pass
            logger.info(f"Confirmation {confirmation_id}: timed out, auto-approving")
            return {"approved": True}
        finally:
            for t in (fut_task, poll_task):
                if not t.done():
                    t.cancel()
    finally:
        PENDING_CONFIRMATIONS.pop(confirmation_id, None)


def _schedule_publish(confirmation_id: str, response: dict) -> bool:
    """Fire-and-forget publish of a cross-worker resolution. Returns True if it
    was scheduled onto a running loop (the /confirm route is always async)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    loop.create_task(_publish_confirm(confirmation_id, response))
    return True


async def _publish_confirm(confirmation_id: str, response: dict) -> None:
    client = await _get_redis()
    if client is None:
        return
    try:
        await client.setex(
            _CONFIRM_KEY.format(confirmation_id), _CONFIRM_TTL, json.dumps(response)
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("confirmation: redis publish error %s", e)


def resolve_confirmation(confirmation_id: str, response: dict) -> bool:
    """Resolve a pending confirmation. Returns True if found and resolved.

    Fast path: the awaiting Future lives on THIS worker → set it directly.
    Cross-worker: when Redis is configured but the Future isn't local, publish
    the response so the owning worker's poll picks it up, and report success
    optimistically (the key TTLs out if nothing consumes it)."""
    future = PENDING_CONFIRMATIONS.get(confirmation_id)
    if future is not None and not future.done():
        future.set_result(response)
        logger.info(f"Confirmation {confirmation_id}: resolved with {response}")
        return True
    if _redis_enabled() and _schedule_publish(confirmation_id, response):
        logger.info(
            f"Confirmation {confirmation_id}: not local; published to Redis for owning worker"
        )
        return True
    logger.warning(f"Confirmation {confirmation_id}: not found or already done (pending={list(PENDING_CONFIRMATIONS.keys())})")
    return False
