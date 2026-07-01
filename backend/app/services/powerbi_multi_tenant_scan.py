"""Scan EVERY reachable Entra tenant for a Power BI user, merged into one catalog.

A user's Power BI / Fabric workspaces can be spread across MULTIPLE tenants: their
home Entra tenant plus any tenant where they're a B2B guest. A single
``PowerBIUserClient`` only ever sees the ONE tenant baked into its credentials, so
scanning one connection misses everything in the guest tenants.

This helper takes the user's email + password, uses
:func:`app.services.powerbi_tenant_discovery.discover_tenants` to enumerate every
tenant the identity can reach, then scans each tenant with its own
``PowerBIUserClient`` and returns a MERGED list of tables tagged (in metadata) by
their origin tenant. The caller persists the merged list as the user's overlay.

Fail-soft throughout: one tenant that fails auth/scan (e.g. ROPC blocked in that
tenant) never kills the others — its error is recorded and the rest still return.
This function never raises; it returns partial results with per-tenant errors.

Mirrors the style of ``powerbi_tenant_discovery.py`` — a pure service function, no
FastAPI, no DB writes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional

from app.services.powerbi_tenant_discovery import discover_tenants
from app.data_sources.clients.powerbi_user_client import PowerBIUserClient

_MAX_WORKERS = 4


def _scan_one_tenant(
    tenant: Dict,
    username: str,
    password: str,
    client_id: Optional[str],
) -> Dict:
    """Scan a single tenant. Never raises — returns a per-tenant result dict."""
    tenant_id = tenant.get("id")
    tenant_name = tenant.get("name") or "(tenant)"
    try:
        client = PowerBIUserClient(
            tenant_id=tenant_id,
            username=username,
            password=password,
            client_id=client_id,
        )
        tables = client.get_schemas() or []
        # Tag every table with its origin tenant (metadata only — no name change).
        for t in tables:
            md = getattr(t, "metadata_json", None)
            if not isinstance(md, dict):
                md = {}
                t.metadata_json = md
            pbi = md.get("powerbi")
            if not isinstance(pbi, dict):
                pbi = {}
                md["powerbi"] = pbi
            pbi["tenantId"] = tenant_id
            pbi["tenantName"] = tenant_name
        return {
            "id": tenant_id,
            "name": tenant_name,
            "domain": tenant.get("domain"),
            "ok": True,
            "table_count": len(tables),
            "error": None,
            "tables": tables,
        }
    except Exception as e:  # noqa: BLE001 — fail-soft; one bad tenant must not sink the rest
        return {
            "id": tenant_id,
            "name": tenant_name,
            "domain": tenant.get("domain"),
            "ok": False,
            "table_count": 0,
            "error": str(e),
            "tables": [],
        }


def scan_all_tenants(username: str, password: str, client_id: Optional[str] = None) -> dict:
    """Discover every reachable tenant, scan each, return a merged tenant-tagged catalog.

    Returns ``{"tenants": [...], "tables": [<merged Table objects>], "table_count": int}``.
    Never raises: discovery failure surfaces as a single failed pseudo-tenant so the
    caller always gets a well-formed dict.
    """
    try:
        tenants = discover_tenants(username, password)
    except Exception as e:  # noqa: BLE001 — discovery is the only place we can't recover from
        return {
            "tenants": [{"id": None, "name": "(discovery)", "domain": None,
                         "ok": False, "table_count": 0, "error": str(e)}],
            "tables": [],
            "table_count": 0,
        }

    results: List[Dict] = []
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futures = [
            pool.submit(_scan_one_tenant, t, username, password, client_id)
            for t in tenants
        ]
        for fut in as_completed(futures):
            results.append(fut.result())

    merged_tables: list = []
    tenant_summaries: List[Dict] = []
    for r in results:
        merged_tables.extend(r.pop("tables", []))
        tenant_summaries.append(r)

    return {
        "tenants": tenant_summaries,
        "tables": merged_tables,
        "table_count": len(merged_tables),
    }
