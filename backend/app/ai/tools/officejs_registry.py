"""Pending-result registry for the write_officejs_code tool.

The tool emits an excel_action on tool.partial, then awaits a Future keyed by
tool_call_id. The taskpane posts the result back via POST /completions/.../tool-results/{id},
which resolves the Future so the tool can emit tool.end.

Cross-worker (prod-hardening): under ``uvicorn --workers N`` the HTTP
tool-result callback may land on a worker that does NOT own the awaiting Future.
The owning worker keeps its in-proc Future as the fast path; a non-owning worker
publishes the result to a short-lived Redis key. Because the await side lives in
``officejs_bridge.await_result`` (which just awaits the Future returned by
``register``), each registration ALSO starts a small Redis watcher that mirrors
a cross-worker result back onto the local Future — so the bridge is unchanged.
All Redis use is fail-soft and OPT-IN via ``REDIS_URL``; when it is unset the
behavior is byte-identical to the original single-process registry.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_OFFICEJS_KEY = "hybrid:officejs:result:{}"
_OFFICEJS_TTL = 120  # seconds; > the tool's ~55s await window

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
        logger.info("officejs_registry: using Redis-backed cross-worker resolution")
    except Exception as e:  # noqa: BLE001 - never raise into the agent loop
        logger.warning("officejs_registry: Redis unavailable (%s); single-process only", e)
        _redis = None
    return _redis


async def _publish_officejs(tool_call_id: str, result: Dict[str, Any]) -> None:
    client = await _get_redis()
    if client is None:
        return
    try:
        await client.setex(
            _OFFICEJS_KEY.format(tool_call_id), _OFFICEJS_TTL, json.dumps(result)
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("officejs_registry: redis publish error %s", e)


def _schedule_publish_officejs(tool_call_id: str, result: Dict[str, Any]) -> bool:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    loop.create_task(_publish_officejs(tool_call_id, result))
    return True


class PendingOfficeJsRegistry:
    def __init__(self) -> None:
        self._futures: Dict[str, asyncio.Future] = {}
        self._watchers: Dict[str, asyncio.Task] = {}

    def register(self, tool_call_id: str) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._futures[tool_call_id] = fut
        # Cross-worker: mirror a result published by another worker back onto
        # this local Future. No-op / not started when REDIS_URL is unset.
        if _redis_enabled():
            try:
                self._watchers[tool_call_id] = loop.create_task(
                    self._watch_redis(tool_call_id)
                )
            except Exception:  # noqa: BLE001
                pass
        return fut

    def _resolve_local(self, tool_call_id: str, result: Dict[str, Any]) -> bool:
        fut = self._futures.get(tool_call_id)
        if not fut or fut.done():
            return False
        try:
            fut.set_result(result)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to resolve officejs future %s: %s", tool_call_id, e)
            return False
        return True

    def resolve(self, tool_call_id: str, result: Dict[str, Any]) -> bool:
        if self._resolve_local(tool_call_id, result):
            return True
        # Not owned by this worker → publish so the owning worker's watcher
        # picks it up; report success optimistically (key TTLs out otherwise).
        if _redis_enabled() and _schedule_publish_officejs(tool_call_id, result):
            return True
        return False

    async def _watch_redis(self, tool_call_id: str) -> None:
        """Poll the cross-worker result key and mirror it onto the local Future.
        Exits when the Future is resolved/forgotten or on any Redis error."""
        client = await _get_redis()
        if client is None:
            return
        key = _OFFICEJS_KEY.format(tool_call_id)
        while True:
            fut = self._futures.get(tool_call_id)
            if fut is None or fut.done():
                return
            try:
                raw = await client.get(key)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning("officejs_registry: redis watch error %s", e)
                return
            if raw is not None:
                try:
                    await client.delete(key)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    result = json.loads(raw)
                except Exception:  # noqa: BLE001
                    result = {"success": False, "error": "bad redis payload"}
                self._resolve_local(tool_call_id, result)
                return
            await asyncio.sleep(0.25)

    def forget(self, tool_call_id: str) -> None:
        self._futures.pop(tool_call_id, None)
        watcher = self._watchers.pop(tool_call_id, None)
        if watcher is not None and not watcher.done():
            watcher.cancel()

    def has(self, tool_call_id: str) -> bool:
        return tool_call_id in self._futures


pending_officejs_registry = PendingOfficeJsRegistry()
