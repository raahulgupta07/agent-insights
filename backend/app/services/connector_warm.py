"""Hot Start — pre-warm a user's Power BI model so the first real query is fast.

Power BI's 40-84s cost is Microsoft loading the semantic model into memory (cold).
Once ANY query runs, MS keeps the model warm for minutes. So on agent open we fire a
cheap query per dataset (in the user's own client) to make the model hot. Fully
per-user, PBI-only, background, throttled, 429-abort, fail-soft — worst case it does
nothing; it never blocks a page or a query.

Flag: HYBRID_HOT_START (default OFF).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# (data_source_id, user_id) -> monotonic time of last warm. Under the 300s DAX-cache
# TTL so a re-open inside the hot window is a no-op. Module-level (per worker).
_WARMED: dict = {}
_WARM_TTL = 240.0
_PER_QUERY_TIMEOUT = 20.0
_MAX_DATASETS = 12


def _is_pbi(client: Any) -> bool:
    try:
        n = type(client).__name__.lower()
        return "powerbi" in n or "power_bi" in n
    except Exception:
        return False


async def warm_agent(data_source_id: str, org_id: str, user_id: str) -> None:
    """Warm every Power BI dataset this user's agent can query. Self-contained:
    opens its own DB session, builds the user's own clients, fires one cheap query
    per dataset. Never raises. Throttled per (data_source, user)."""
    from app.settings.hybrid_flags import flags
    if not getattr(flags, "HOT_START", False):
        return
    key = (str(data_source_id), str(user_id))
    now = time.monotonic()
    last = _WARMED.get(key)
    if last is not None and (now - last) < _WARM_TTL:
        return  # still hot — skip
    _WARMED[key] = now  # stamp BEFORE work so a concurrent open can't double-fire

    try:
        from app.dependencies import async_session_maker
        from app.settings.hybrid_flags import load_overrides_from_db
        from app.services.data_source_service import DataSourceService
        from app.models.data_source import DataSource
        from app.models.user import User
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with async_session_maker() as db:
            try:
                await load_overrides_from_db(db)
            except Exception:
                pass
            ds = (await db.execute(
                select(DataSource).options(selectinload(DataSource.connections))
                .where(DataSource.id == str(data_source_id))
            )).scalar_one_or_none()
            user = (await db.execute(
                select(User).where(User.id == str(user_id))
            )).scalar_one_or_none()
            if ds is None or user is None:
                return
            clients = await DataSourceService().construct_clients(db, ds, user)
            total = 0
            for _k, client in (clients or {}).items():
                if not _is_pbi(client):
                    continue
                total += await _warm_client(client)
            if total:
                logger.info("hot_start: warmed %d Power BI datasets (ds=%s user=%s)",
                            total, data_source_id, user_id)
    except Exception:
        logger.warning("hot_start: warm_agent failed for %s", data_source_id, exc_info=True)


async def _warm_client(client: Any) -> int:
    """Fire one cheap query per distinct dataset in the client's offline index to
    load each model into Microsoft's engine. Returns the count warmed. 429 aborts
    the whole pass (respect the 120-query/min cap). Fail-soft per dataset."""
    idx = getattr(client, "_table_index", {}) or {}
    ds_ids = list({e.get("datasetId") for e in idx.values() if isinstance(e, dict) and e.get("datasetId")})
    warmed = 0
    for dsid in ds_ids[:_MAX_DATASETS]:
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    client.execute_query, 'EVALUATE ROW("_w", 1)', dataset_id=dsid, max_rows=1
                ),
                timeout=_PER_QUERY_TIMEOUT,
            )
            warmed += 1
        except asyncio.TimeoutError:
            continue
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "too many requests" in str(e).lower():
                break  # rate-limited → stop warming, stay fail-soft
            continue
    return warmed


def schedule_warm(data_source_id: str, org_id: str, user_id: str) -> None:
    """Fire-and-forget the warm as a background task (never blocks the caller).
    Safe to call from a request handler; swallows all errors."""
    try:
        asyncio.create_task(warm_agent(str(data_source_id), str(org_id), str(user_id)))
    except Exception:
        logger.debug("hot_start: schedule_warm could not create task", exc_info=True)


# ---------------------------------------------------------------------------
# Headline stats — the model's own measures, computed per-user so the Overview
# can show real numbers before the user types. Cached per (data_source, user).
# ---------------------------------------------------------------------------
import re as _re

_HEADLINE: dict = {}
_HEADLINE_TTL = 300.0
_MAX_HEADLINE = 6
_HEADLINE_NAME = _re.compile(
    r"count|total|number|\bno\.?\b|amount|revenue|sales|progress|\brate\b|ratio|"
    r"average|\bavg\b|\bsum\b|percent|%|score|active|members?",
    _re.I,
)
_SKIP_DATASET = _re.compile(r"usage metrics", _re.I)


def _fmt_value(name: str, v: Any) -> str:
    try:
        f = float(v)
        low = name.lower()
        is_pct = ("%" in name) or ("progress" in low) or ("rate" in low) or ("ratio" in low) or ("percent" in low)
        if is_pct and abs(f) <= 1.0:
            return f"{f * 100:.0f}%"
        if abs(f - round(f)) < 1e-9:
            return f"{int(round(f)):,}"
        return f"{f:,.1f}"
    except Exception:
        return str(v)[:40]


async def compute_headline(data_source_id: str, org_id: str, user_id: str, force: bool = False) -> dict:
    """Return the user's headline KPIs: {status, items:[{label,value}]}. Runs the
    model's own measures (per dataset, on the user's client), cached per
    (data_source, user). Flag-gated, PBI-only, fail-soft. status: ready|off|error."""
    from app.settings.hybrid_flags import flags
    if not getattr(flags, "HOT_START", False):
        return {"status": "off", "items": []}
    key = (str(data_source_id), str(user_id))
    now = time.monotonic()
    if not force:
        ent = _HEADLINE.get(key)
        if ent is not None and ent[0] > now:
            return {"status": "ready", "items": ent[1]}
    try:
        from app.dependencies import async_session_maker
        from app.settings.hybrid_flags import load_overrides_from_db
        from app.services.data_source_service import DataSourceService
        from app.models.data_source import DataSource
        from app.models.user import User
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        items: list = []
        async with async_session_maker() as db:
            try:
                await load_overrides_from_db(db)
            except Exception:
                pass
            ds = (await db.execute(
                select(DataSource).options(selectinload(DataSource.connections))
                .where(DataSource.id == str(data_source_id))
            )).scalar_one_or_none()
            user = (await db.execute(select(User).where(User.id == str(user_id)))).scalar_one_or_none()
            if ds is None or user is None:
                return {"status": "error", "items": []}
            clients = await DataSourceService().construct_clients(db, ds, user)
            for _k, client in (clients or {}).items():
                if not _is_pbi(client):
                    continue
                idx = getattr(client, "_table_index", {}) or {}
                ds_names: dict = {}
                for tname, e in idx.items():
                    if isinstance(e, dict) and e.get("datasetId") and "/" in tname:
                        ds_names.setdefault(e["datasetId"], tname.split("/")[0])
                measures = (getattr(client, "_model_meta", {}) or {}).get("measures") or []
                for m in measures:
                    if len(items) >= _MAX_HEADLINE:
                        break
                    nm = m.get("name")
                    dsid = m.get("datasetId")
                    if not nm or not dsid or not _HEADLINE_NAME.search(nm):
                        continue
                    if _SKIP_DATASET.search(ds_names.get(dsid, "") or ""):
                        continue
                    try:
                        df = await asyncio.wait_for(
                            asyncio.to_thread(
                                client.execute_query,
                                f'EVALUATE ROW("v", [{nm}])', dataset_id=dsid, max_rows=1,
                            ),
                            timeout=_PER_QUERY_TIMEOUT,
                        )
                        if df is not None and len(df):
                            val = list(df.iloc[0].values)[0]
                            if val is not None:
                                items.append({"label": nm, "value": _fmt_value(nm, val)})
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:  # noqa: BLE001
                        if "429" in str(e) or "too many requests" in str(e).lower():
                            break
                        continue
        _HEADLINE[key] = (now + _HEADLINE_TTL, items)
        return {"status": "ready", "items": items}
    except Exception:
        logger.warning("hot_start: compute_headline failed for %s", data_source_id, exc_info=True)
        return {"status": "error", "items": []}


def invalidate_headline(data_source_id: str) -> None:
    """Drop cached headlines for a data source (any user). Call on sync."""
    try:
        for k in [k for k in _HEADLINE if k[0] == str(data_source_id)]:
            _HEADLINE.pop(k, None)
    except Exception:
        pass
