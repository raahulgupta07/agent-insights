"""
Global outbound-LLM concurrency limiter (Phase 9 scale-harden, unit A)
======================================================================

Caps the number of *concurrent* outbound streaming LLM calls to OpenRouter so
a single box can't fan out unbounded under load. DocSensei load tests measured
the LLM concurrency cap as the real ceiling under load, so this is the
highest-value scaling lever.

Default behaviour is a strict NO-OP: unless ``LLM_MAX_CONCURRENCY`` is set to a
positive int, ``get_llm_semaphore()`` returns ``None`` and ``llm_slot()`` is a
transparent passthrough. With the flag unset the code path is byte-identical to
upstream (no semaphore is ever constructed, no acquire/release happens).

Dependency-free by design (only stdlib ``asyncio`` / ``contextlib`` / ``os``).
We deliberately do NOT import ``app.settings.hybrid_flags`` — we only mirror its
env-reading style.

Usage (callers always wrap, regardless of config)::

    from app.ai.llm.concurrency import llm_slot

    async with llm_slot():
        stream = await client.create(...)
        async for chunk in stream:
            ...

Implementation notes:
    * ``asyncio.Semaphore`` binds to the event loop it was created on. We cache
      the semaphore plus the loop it was built on, and rebuild it transparently
      if the running loop changed (multi-worker / per-test event loops).
    * The cap is read once at first construction. Changing the env var at
      runtime only takes effect after ``_reset_for_tests()`` (intended for
      tests; production reads it once at process start, which is what we want).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

# Module-level cache. The semaphore is lazily constructed on first use and is
# rebuilt if the running event loop differs from the one it was bound to.
_sem: Optional[asyncio.Semaphore] = None
_sem_loop: Optional[asyncio.AbstractEventLoop] = None


def _read_limit() -> Optional[int]:
    """Read ``LLM_MAX_CONCURRENCY`` as a positive int, else ``None``.

    Returns ``None`` (meaning: no limiting / passthrough) when the env var is
    unset, empty, non-integer, or <= 0. This keeps the default path identical
    to upstream.
    """
    raw = os.environ.get("LLM_MAX_CONCURRENCY")
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def get_llm_semaphore() -> Optional[asyncio.Semaphore]:
    """Return the process-wide LLM semaphore, or ``None`` if limiting is off.

    Lazily builds (and caches) the semaphore on first use. If the running event
    loop differs from the one the cached semaphore was bound to, the semaphore
    is rebuilt for the current loop (matters for tests and multi-worker setups).
    """
    global _sem, _sem_loop

    limit = _read_limit()
    if limit is None:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside a running loop. We can't safely bind a semaphore to a
        # loop here; construct one anyway (it will bind to whichever loop first
        # uses it). It will be rebuilt by the loop-guard above if needed.
        loop = None

    if _sem is None or (loop is not None and _sem_loop is not loop):
        _sem = asyncio.Semaphore(limit)
        _sem_loop = loop

    return _sem


@asynccontextmanager
async def llm_slot():
    """Hold one concurrency slot for the duration of the ``with`` block.

    If limiting is disabled (``get_llm_semaphore()`` is ``None``) this is a
    transparent no-op: it just yields without acquiring anything. Callers can
    therefore always wrap their network call in ``async with llm_slot():``
    regardless of whether the cap is configured.
    """
    sem = get_llm_semaphore()
    if sem is None:
        yield
        return
    async with sem:
        yield


def _reset_for_tests() -> None:
    """Clear the cached semaphore + bound loop. For tests only."""
    global _sem, _sem_loop
    _sem = None
    _sem_loop = None
