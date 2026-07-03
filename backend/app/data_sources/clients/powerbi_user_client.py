"""Power BI Semantic Model — user-login (delegated) variant.

Same engine as :class:`PowerBIClient` (REST executeQueries / DAX, semantic-model
discovery, measures-as-schema), but authenticates as a USER via the OAuth2
Resource-Owner-Password (ROPC) grant — Entra email + password — instead of a
service principal (client_credentials).

This mirrors how ``ms_fabric_user`` subclasses ``ms_fabric``: override ONLY the
token acquisition (``connect``); inherit discovery, DAX execution, schema and
prompt formatting untouched.

Auth precedence inside ``connect``:
  1. a pre-supplied delegated ``access_token`` (device-code / external flow) — just
     open the session (this path already exists in the base client);
  2. ROPC: POST grant_type=password with username + password + a public client_id.

ROPC constraints (surfaced as a clear error, never a silent failure):
  - the account must NOT have MFA enabled, and the tenant must permit ROPC /
    legacy auth. If blocked, Azure returns AADSTS50076/50079 (MFA) or
    AADSTS7000218 — ``connect`` raises with the raw AADSTS code so the UI can tell
    the user to switch to device-code or a service principal.

Read-only: the client only ever issues DAX EVALUATE / discovery calls.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

import requests

from app.ai.prompt_formatters import Table, TableColumn
from app.data_sources.clients.powerbi_client import (
    PowerBIClient,
    _clean_table_display_name,
)

logger = logging.getLogger(__name__)

# Microsoft Azure PowerShell — a well-known Microsoft FOCI public client that
# permits the ROPC (password) grant. Used only to mint a delegated user token;
# no secret required. Overridable per-connection via ``oauth_client_id``.
_DEFAULT_PUBLIC_CLIENT = "1950a258-227b-4e31-a9cf-717495945fc2"


class PowerBIUserClient(PowerBIClient):
    """Power BI semantic models queried as a signed-in user (ROPC / delegated)."""

    def __init__(
        self,
        tenant_id: str = None,
        username: str = None,
        password: str = None,
        client_id: str = None,
        access_token: str = None,
        refresh_token: str = None,
        **kwargs,
    ):
        # Base client stores tenant_id/client_id/client_secret/access_token. We
        # reuse tenant_id + access_token; carry user creds for the ROPC override.
        super().__init__(
            tenant_id=tenant_id,
            client_id=client_id or _DEFAULT_PUBLIC_CLIENT,
            client_secret=None,
            access_token=access_token,
        )
        self.username = username
        self.password = password
        # device-code sign-in stores a refresh_token instead of a password; used
        # to mint a fresh access token (rotating the refresh token) on connect.
        self.refresh_token = refresh_token
        # public client used for the password grant (separate from base client_id
        # semantics, which for SP is the app registration id)
        self._public_client_id = client_id or _DEFAULT_PUBLIC_CLIENT

    @property
    def description(self) -> str:
        base = "Power BI Semantic Model (user sign-in / DAX executeQueries)."
        try:
            return base + self.system_prompt()
        except Exception:  # noqa: BLE001 — description must never raise
            return base

    def connect(self):
        """Authenticate as the user via ROPC and open the HTTP session.

        Reuses a cached token / delegated access_token if present (base-client
        behaviour). Otherwise performs the password grant.
        """
        # already connected, or a delegated token was provided -> base handles it
        if (self._http and self._access_token) or self._access_token:
            return super().connect()

        # device-code path: exchange a stored refresh_token for a fresh access
        # token (and rotate the refresh token). Preferred over ROPC — MFA-safe.
        if self.refresh_token and self.tenant_id:
            auth_url = self.AUTH_URL.format(tenant_id=self.tenant_id)
            resp = requests.post(
                auth_url,
                data={
                    "grant_type": "refresh_token",
                    "client_id": self._public_client_id,
                    "refresh_token": self.refresh_token,
                    "scope": self.SCOPE + " offline_access",
                },
                timeout=30,
            )
            if resp.status_code >= 300:
                detail = ""
                try:
                    j = resp.json()
                    detail = f"{j.get('error')}: {j.get('error_description', '')[:300]}"
                except Exception:  # noqa: BLE001
                    detail = resp.text[:300]
                raise RuntimeError(
                    f"Power BI refresh-token sign-in failed: {detail} "
                    "(re-run device-code sign-in to get a fresh token.)"
                )
            body = resp.json()
            token = body.get("access_token")
            if not token:
                raise RuntimeError("Power BI refresh-token grant did not return an access token.")
            self._access_token = token
            # rotate the refresh token if Entra issued a new one
            if body.get("refresh_token"):
                self.refresh_token = body["refresh_token"]
            self._http = requests.Session()
            return

        if not (self.username and self.password and self.tenant_id):
            raise RuntimeError(
                "Power BI user login requires tenant_id, username and password "
                "(or a delegated access_token)."
            )

        auth_url = self.AUTH_URL.format(tenant_id=self.tenant_id)
        payload = {
            "grant_type": "password",
            "client_id": self._public_client_id,
            "username": self.username,
            "password": self.password,
            "scope": self.SCOPE,
        }
        resp = requests.post(auth_url, data=payload, timeout=30)
        if resp.status_code >= 300:
            # surface the raw AADSTS code so the caller can branch (MFA -> device
            # code, ROPC blocked -> service principal)
            detail = ""
            try:
                j = resp.json()
                detail = f"{j.get('error')}: {j.get('error_description', '')[:300]}"
            except Exception:  # noqa: BLE001
                detail = resp.text[:300]
            hint = ""
            if "AADSTS50076" in detail or "AADSTS50079" in detail:
                hint = " (MFA is required on this account — use device-code or a service principal.)"
            elif "AADSTS7000218" in detail or "AADSTS65001" in detail:
                hint = " (Tenant blocks ROPC / consent missing — use a service principal.)"
            raise RuntimeError(f"Power BI user authentication failed: {detail}{hint}")

        token = resp.json().get("access_token")
        if not token:
            raise RuntimeError("Power BI user authentication did not return an access token.")

        self._access_token = token
        self._http = requests.Session()

    # ------------------------------------------------------------------
    # Report / App-based dataset discovery
    #
    # A user whose Power BI access comes via a SHARED REPORT or an APP gets an
    # EMPTY /datasets list (they aren't a workspace member), so the normal
    # get_schemas() finds 0 tables. But the REPORTS they can see carry a
    # datasetId + datasetWorkspaceId — following those back to the dataset, and
    # probing executeQueries, surfaces the datasets they can actually query.
    # ------------------------------------------------------------------

    _DISCOVERY_TIMEOUT = 40

    def _get_json(self, url: str) -> Optional[dict]:
        """GET a Power BI REST URL, returning parsed JSON or None (fail-soft)."""
        try:
            resp = self._http.get(url, headers=self._build_headers(), timeout=self._DISCOVERY_TIMEOUT)
        except Exception:  # noqa: BLE001 — network hiccup, skip this source
            return None
        if resp.status_code >= 300:
            return None
        try:
            return resp.json() or {}
        except Exception:  # noqa: BLE001
            return None

    def test_connection(self) -> Dict:
        """Test the user-sign-in connection via the SAME discovery path the agent
        actually queries through (My-Workspace + apps + groups) — NOT the base
        client's service-principal group-scope probe.

        A user's queryable datasets frequently live in "My Workspace" (no group),
        which the inherited ``test_connection`` never checks (it only probes
        ``/groups/{ws}/datasets``). That yields a false "none of the datasets are
        queryable" even though the agent queries them fine. Here we run
        ``discover_via_reports`` (the exact classification used at sync) and pass
        when at least one dataset is queryable.
        """
        try:
            self.connect()
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": f"Sign-in failed: {e}", "connectivity": False}
        try:
            disc = self.discover_via_reports() or {}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "message": f"Connected, but dataset discovery failed: {e}", "connectivity": True}
        queryable = disc.get("queryable") or []
        view_only = disc.get("view_only") or []
        if queryable:
            return {
                "success": True,
                "message": f"Connected to Power BI as this account. {len(queryable)} queryable dataset(s) available.",
                "datasets": len(queryable),
            }
        if view_only:
            return {
                "success": False,
                "message": (
                    f"Connected, but the {len(view_only)} visible dataset(s) are view-only "
                    f"(no Build permission). Ask the dataset owner to grant you Build access."
                ),
                "connectivity": True,
            }
        return {
            "success": False,
            "message": "Connected, but no queryable Power BI datasets are shared with this account.",
            "connectivity": True,
        }

    def _probe_queryable(self, dataset_id: str, workspace_id: Optional[str]) -> str:
        """Probe whether the user can run DAX against a dataset.

        Tries the My-Workspace scope first, then the group scope if the first
        attempt returns 401/404 and a workspace_id is known. Returns one of
        "queryable" (HTTP 200), "view_only" (HTTP 401 — no Build permission),
        or "unreachable" (404 / other / hard error).
        """
        body = {
            "queries": [{"query": 'EVALUATE ROW("ok",1)'}],
            "serializerSettings": {"includeNulls": True},
        }

        def _post(url: str) -> Optional[int]:
            # Retry transient failures + 429 throttling — a full report sweep probes
            # many datasets fast and Power BI rate-limits, which would otherwise
            # misclassify a genuinely-queryable dataset as "unreachable".
            import time as _t
            for _attempt in range(3):
                try:
                    resp = self._http.post(
                        url, json=body, headers=self._build_headers(), timeout=self._DISCOVERY_TIMEOUT
                    )
                except Exception:  # noqa: BLE001
                    _t.sleep(1.5)
                    continue
                if resp.status_code == 429:
                    try:
                        wait = float(resp.headers.get("Retry-After", 3)) or 3
                    except (TypeError, ValueError):
                        wait = 3
                    _t.sleep(min(wait, 10))
                    continue
                return resp.status_code
            return None

        # My-Workspace scope
        status = _post(f"{self.BASE_URL}/datasets/{dataset_id}/executeQueries")
        if status == 200:
            return "queryable"

        # Group scope (only if the first attempt didn't clearly succeed)
        if workspace_id and status in (401, 404, None):
            g_status = _post(
                f"{self.BASE_URL}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries"
            )
            if g_status == 200:
                return "queryable"
            if g_status == 401:
                return "view_only"
            if g_status is not None:
                status = g_status

        if status == 401:
            return "view_only"
        return "unreachable"

    def _exec_dax_rows(self, ds_id: str, ws_id: Optional[str], query: str) -> Optional[list]:
        """Run a DAX query against a dataset (My-Workspace scope, then group scope)
        and return the result rows, or None on failure. Fail-soft."""
        body = {"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}}
        urls = [f"{self.BASE_URL}/datasets/{ds_id}/executeQueries"]
        if ws_id:
            urls.append(f"{self.BASE_URL}/groups/{ws_id}/datasets/{ds_id}/executeQueries")
        for url in urls:
            try:
                r = self._http.post(url, json=body, headers=self._build_headers(),
                                    timeout=self._DISCOVERY_TIMEOUT)
                if r.status_code == 200:
                    return r.json()["results"][0]["tables"][0]["rows"]
            except Exception:  # noqa: BLE001
                continue
        return None

    def _enumerate_tables_via_info_view(self, ds_id: str, ws_id: Optional[str]) -> list:
        """Enumerate a queryable dataset's real tables + columns via INFO.VIEW.*.

        INFO.TABLES()/DMV are blocked (400/401) for non-admins, but INFO.VIEW.TABLES()
        and INFO.VIEW.COLUMNS() are permitted for a user with Build permission — this
        is the reliable schema path (vs brute-guessing table names). Returns a list of
        {"name": str, "columns": [{"name": str, "dataType": str}]}. Empty on failure.
        """
        trows = self._exec_dax_rows(
            ds_id, ws_id,
            'EVALUATE SELECTCOLUMNS(FILTER(INFO.VIEW.TABLES(), NOT [IsHidden]), "t", [Name])',
        )
        if not trows:
            return []
        names = [str(list(r.values())[0]) for r in trows if list(r.values())[0]]
        crows = self._exec_dax_rows(
            ds_id, ws_id,
            'EVALUATE SELECTCOLUMNS(INFO.VIEW.COLUMNS(), "t", [Table], "c", [Name], "d", [DataType])',
        ) or []
        cols_by: Dict[str, list] = {}
        for r in crows:
            vals = list(r.values())
            if len(vals) < 2:
                continue
            tname, cname = str(vals[0]), str(vals[1])
            dt = str(vals[2]) if len(vals) > 2 and vals[2] is not None else "unknown"
            if tname and cname:
                cols_by.setdefault(tname, []).append({"name": cname, "dataType": dt})
        out = []
        for n in names:
            # skip Power BI internal auto date/time tables
            if n.startswith("DateTableTemplate") or n.startswith("LocalDateTable"):
                continue
            out.append({"name": n, "columns": cols_by.get(n, [])})
        return out

    def _collect_reports(self) -> List[dict]:
        """Enumerate reports the user can see across My Workspace + apps + groups.

        Each returned report dict carries at least ``datasetId`` and
        ``datasetWorkspaceId`` when Power BI provides them. Fail-soft per source:
        a failing source simply contributes nothing.
        """
        reports: List[dict] = []

        # 1. My Workspace reports
        my = self._get_json(f"{self.BASE_URL}/reports")
        if my:
            reports.extend(my.get("value") or [])

        # 2. App reports
        apps = self._get_json(f"{self.BASE_URL}/apps")
        for app in (apps or {}).get("value") or []:
            app_id = app.get("id")
            if not app_id:
                continue
            app_reports = self._get_json(f"{self.BASE_URL}/apps/{app_id}/reports")
            if app_reports:
                reports.extend(app_reports.get("value") or [])

        # 3. Group (workspace) reports
        groups = self._get_json(f"{self.BASE_URL}/groups")
        for grp in (groups or {}).get("value") or []:
            gid = grp.get("id")
            if not gid:
                continue
            grp_reports = self._get_json(f"{self.BASE_URL}/groups/{gid}/reports")
            if grp_reports:
                # groups/{id}/reports omits datasetWorkspaceId → default to the group id
                for rpt in grp_reports.get("value") or []:
                    rpt.setdefault("datasetWorkspaceId", gid)
                    reports.extend([rpt])

        return reports

    def discover_via_reports(self) -> dict:
        """Discover queryable datasets via the reports/apps the user can see.

        Returns::

            {
              "queryable": [Table, ...],
              "view_only": [{"name":.., "dataset_id":.., "reason":".."}, ...],
              "counts": {"reports":N, "queryable":X, "view_only":Y},
            }

        Never raises — returns an empty-but-well-formed dict on hard error.
        Computed once per instance and cached (both get_report_based_tables and
        the get_schemas view_only summary read the same cache — no double scan).
        """
        cached = getattr(self, "_report_discovery_cache", None)
        if cached is not None:
            return cached
        result = self._discover_via_reports_uncached()
        self._report_discovery_cache = result
        return result

    def _discover_via_reports_uncached(self) -> dict:
        try:
            self.connect()

            reports = self._collect_reports()

            # Dedupe datasetId -> {name, workspace_id}
            ds_map: Dict[str, Dict[str, Optional[str]]] = {}
            for rpt in reports:
                ds_id = rpt.get("datasetId")
                if not ds_id:
                    continue
                if ds_id not in ds_map:
                    ds_map[ds_id] = {
                        "name": rpt.get("name") or ds_id,
                        "workspace_id": rpt.get("datasetWorkspaceId"),
                    }
                elif not ds_map[ds_id].get("workspace_id") and rpt.get("datasetWorkspaceId"):
                    ds_map[ds_id]["workspace_id"] = rpt.get("datasetWorkspaceId")

            queryable_tables: List[Table] = []
            view_only: List[dict] = []

            for ds_id, info in ds_map.items():
                ds_name = info["name"]
                ws_id = info["workspace_id"]
                verdict = self._probe_queryable(ds_id, ws_id)

                if verdict == "view_only":
                    view_only.append(
                        {"name": ds_name, "dataset_id": ds_id, "reason": "no build permission"}
                    )
                    continue
                if verdict != "queryable":
                    continue

                # Queryable → enumerate real tables + columns via INFO.VIEW.* (the
                # reliable path; INFO.TABLES/DMV are blocked for non-admins). Fall
                # back to the parent's brute-guess probe only if INFO.VIEW yields
                # nothing.
                tables = self._enumerate_tables_via_info_view(ds_id, ws_id)
                if not tables:
                    try:
                        tables, _rels = self._brute_discover_tables(ws_id, ds_id)
                    except Exception:  # noqa: BLE001
                        tables = []

                for tbl in tables:
                    tbl_name = tbl.get("name") or ""
                    if not tbl_name:
                        continue
                    tbl_display = _clean_table_display_name(tbl_name)
                    columns: List[TableColumn] = []
                    for col in tbl.get("columns") or []:
                        col_name = col.get("name") or ""
                        if col_name:
                            columns.append(
                                TableColumn(
                                    name=col_name,
                                    dtype=col.get("dataType") or "unknown",
                                    description=None,
                                    metadata={"role": "column"},
                                )
                            )
                    queryable_tables.append(
                        Table(
                            name=f"{ds_name}/{tbl_display}",
                            description=None,
                            columns=columns,
                            pks=[],
                            fks=[],
                            is_active=True,
                            metadata_json={
                                "powerbi": {
                                    "datasetId": ds_id,
                                    "workspaceId": ws_id,
                                    "datasetName": ds_name,
                                    "tableName": tbl_name,
                                    "queryable": True,
                                    "discoveredVia": "reports",
                                }
                            },
                        )
                    )

            return {
                "queryable": queryable_tables,
                "view_only": view_only,
                "counts": {
                    "reports": len(reports),
                    "queryable": len(queryable_tables),
                    "view_only": len(view_only),
                },
            }
        except Exception:  # noqa: BLE001 — discovery must never raise
            logger.warning("powerbi.discover_via_reports failed", exc_info=True)
            return {
                "queryable": [],
                "view_only": [],
                "counts": {"reports": 0, "queryable": 0, "view_only": 0},
            }

    def get_report_based_tables(self) -> List[Table]:
        """Convenience: the queryable Table objects from report/app discovery.

        This is what the sync path calls to add datasets a user can reach only
        through shared reports / apps (their /datasets list is empty).
        """
        return self.discover_via_reports()["queryable"]

    def get_schemas(self) -> List[Table]:
        """Parent /datasets discovery, plus report/app-based tables when the
        CONNECTOR_JOURNEY_V2 flag is on.

        Flag OFF (or any error) → returns the parent result byte-identical, so
        a user whose datasets ARE visible sees no change. Flag ON → merges the
        report-based queryable tables (deduped by Table.name) so users whose
        only access is via shared reports/apps still get queryable tables. The
        view_only summary is stashed on ``self._last_view_only`` (best-effort).
        """
        base = super().get_schemas()
        try:
            from app.settings.hybrid_flags import flags

            if not flags.CONNECTOR_JOURNEY_V2:
                return base
        except Exception:  # noqa: BLE001
            return base

        try:
            discovery = self.discover_via_reports()
            report_tables = discovery.get("queryable") or []
            self._last_view_only = discovery.get("view_only") or []
            seen = {t.name for t in base}
            return list(base) + [t for t in report_tables if t.name not in seen]
        except Exception:  # noqa: BLE001 — never break schema discovery
            self._last_view_only = []
            return base
