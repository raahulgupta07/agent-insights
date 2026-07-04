"""Discover a Fabric warehouse SQL endpoint from a shared FOCI refresh token.

The unified Microsoft sign-in (HYBRID_MS_UNIFIED_SIGNIN) mints ONE FOCI refresh
token that redeems both Power BI and Fabric. Power BI needs only the token, but
the Fabric SQL client (`MsFabricClient`) also needs the warehouse SQL endpoint
hostname — which the token does NOT carry. This module redeems the token for the
Fabric REST API (control plane) and reads the SQL endpoint from the account's
workspaces → warehouses / lakehouses, so the Fabric Data Agent can be built with
NO extra sign-in and NO manually-typed endpoint.

All blocking `requests` — call via `asyncio.to_thread`. Fully fail-soft: returns
None on any error so it can never break the Power BI half of the sign-in. Never
logs the token.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_FABRIC_API = "https://api.fabric.microsoft.com/v1"


def _endpoint_of(item: dict, kind: str) -> Optional[str]:
    """Read the SQL endpoint hostname off a Fabric item. Warehouses expose it at
    properties.connectionString; lakehouses at
    properties.sqlEndpointProperties.connectionString."""
    props = (item or {}).get("properties") or {}
    cs = props.get("connectionString")
    if not cs:
        sep = props.get("sqlEndpointProperties") or {}
        cs = sep.get("connectionString")
    return (str(cs).strip() or None) if cs else None


def discover_fabric_endpoint(tenant_id: str, refresh_token: str) -> Optional[dict]:
    """Return the FIRST reachable Fabric warehouse/lakehouse SQL endpoint for the
    signed-in account, or None if the account has none (→ caller skips building a
    Fabric agent, so there's no dead agent).

    Returns ``{"server_hostname", "database", "workspace", "n_warehouses"}``.
    """
    from app.services import powerbi_device_code as dc
    try:
        tok = dc.refresh_to_access_token(
            tenant_id or "organizations", refresh_token, dc.SCOPE_FABRIC_REST
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("fabric discovery: token redeem failed: %s", e)
        return None
    if not tok.get("ok") or not tok.get("access_token"):
        logger.info("fabric discovery: no Fabric-REST token (%s)", tok.get("error"))
        return None

    headers = {"Authorization": "Bearer " + tok["access_token"]}
    try:
        wr = requests.get(_FABRIC_API + "/workspaces", headers=headers, timeout=30)
        if wr.status_code >= 300:
            logger.info("fabric discovery: workspaces HTTP %s", wr.status_code)
            return None
        workspaces = (wr.json() or {}).get("value") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("fabric discovery: list workspaces failed: %s", e)
        return None

    total = 0
    first: Optional[dict] = None
    for w in workspaces:
        wid = w.get("id")
        wname = w.get("displayName")
        if not wid:
            continue
        for kind in ("warehouses", "lakehouses"):
            try:
                r = requests.get(
                    f"{_FABRIC_API}/workspaces/{wid}/{kind}", headers=headers, timeout=30
                )
                if r.status_code >= 300:
                    continue
                items = (r.json() or {}).get("value") or []
            except Exception:  # noqa: BLE001
                continue
            for it in items:
                host = _endpoint_of(it, kind)
                if not host:
                    continue
                total += 1
                if first is None:
                    first = {
                        "server_hostname": host,
                        "database": it.get("displayName"),
                        "workspace": wname,
                    }
    if not first:
        return None
    first["n_warehouses"] = total
    return first
