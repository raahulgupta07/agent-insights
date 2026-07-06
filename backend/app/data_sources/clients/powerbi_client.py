from app.data_sources.clients.base import DataSourceClient
from app.ai.prompt_formatters import Table, TableColumn, ForeignKey, ServiceFormatter
from typing import Any, List, Dict, Optional, Tuple
import requests
import pandas as pd
import re
import time
import logging
from urllib.parse import unquote

logger = logging.getLogger(__name__)


class PowerBIRateLimitError(RuntimeError):
    """Raised when Power BI returns HTTP 429 and retries are exhausted.

    Distinct type so the create_data tool can surface a clean 'rate-limited,
    retry shortly' message instead of a raw HTTP dump.
    """
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


# Storage modes that are queryable via the REST executeQueries DAX API.
_QUERYABLE_STORAGE_MODES = {"Import", "PremiumFiles", "Abf", "DirectQuery"}


def _is_dataset_queryable(ds: Dict) -> bool:
    """
    Whether a Power BI dataset can be queried via the REST executeQueries DAX API.

    On-prem-gateway-required datasets and AAS-live datasets connect fine but
    every DAX query 400s, so we tag them as not queryable at scan time.
    """
    storage_mode = ds.get("storageMode") or ds.get("targetStorageMode")
    if ds.get("isOnPremGatewayRequired") is True:
        return False
    return storage_mode in _QUERYABLE_STORAGE_MODES


# Common analytics table names to brute-probe when COLUMNSTATISTICS + REST /tables
# both come back empty (lakehouse/warehouse-backed datasets).
_COMMON_TABLE_NAMES = [
    "sales", "Sales", "orders", "Orders", "order_lines", "Order_Lines",
    "customers", "Customers", "customer", "Customer",
    "products", "Products", "product", "Product",
    "inventory", "Inventory", "stock", "Stock",
    "transactions", "Transactions", "transaction", "Transaction",
    "fact", "Fact", "facts", "Facts",
    "dim_date", "Dim_Date", "date", "Date", "calendar", "Calendar", "dates", "Dates",
    "dim_product", "Dim_Product", "dim_customer", "Dim_Customer", "dim_store", "Dim_Store",
    "store", "Store", "stores", "Stores",
    "employees", "Employees", "employee", "Employee",
    "users", "Users", "user", "User",
    "accounts", "Accounts", "account", "Account",
    "invoices", "Invoices", "invoice", "Invoice",
    "payments", "Payments", "payment", "Payment",
    "items", "Items", "item", "Item",
    "categories", "Categories", "category", "Category",
    "suppliers", "Suppliers", "supplier", "Supplier",
    "regions", "Regions", "region", "Region",
    "dimension", "Dimension", "measures", "Measures",
    "data", "Data", "Table",
]
# De-dup preserving order.
_COMMON_TABLE_NAMES = list(dict.fromkeys(_COMMON_TABLE_NAMES))


def _clean_table_display_name(table_name: str) -> str:
    """
    Clean up Power BI table names for display.

    SharePoint-connected tables have ugly URL-based names like:
    'https://tenant-my sharepoint com/personal/user/Documents/file xlsx'

    This extracts a cleaner display name (e.g., 'file' or 'Documents_file').
    """
    if not table_name:
        return table_name

    # Detect SharePoint/OneDrive URL patterns (dots already replaced with spaces by Power BI)
    if "sharepoint" in table_name.lower() or table_name.startswith("http"):
        # Try to extract the last meaningful segment from the path
        # Replace spaces back to dots for URL parsing, then decode
        normalized = table_name.replace(" ", ".")

        # Remove protocol and domain
        path = re.sub(r'^https?://[^/]+/', '', normalized)

        # Split by / and get meaningful segments
        segments = [s for s in path.split('/') if s and s.lower() not in ('personal', 'documents', 'sites')]

        if segments:
            # Get the last segment (usually the file name)
            last = segments[-1]
            # Remove file extension if present
            last = re.sub(r'\.(xlsx|xls|csv|txt)$', '', last, flags=re.IGNORECASE)
            # Clean up any remaining encoded chars
            last = unquote(last)
            # Replace dots/underscores with spaces, then clean up
            last = re.sub(r'[._]+', ' ', last).strip()

            if last:
                return last

    return table_name


class PowerBIQueryError(RuntimeError):
    """A Power BI query failure carrying BOTH a technical detail (for the agent's
    self-correction retry) and a clean human message + category (for the final
    user-facing answer). ``str(err)`` == the technical detail so existing retry
    logic that reads the exception text still gets something useful and readable —
    never the raw JSON blob.
    """

    def __init__(self, technical: str, human: str, category: str):
        super().__init__(technical)
        self.technical = technical
        self.human = human
        self.category = category  # no_access | not_found | invalid_dax | too_much_data | throttled | auth | unknown


def _humanize_pbi_error(status: int, text: str):
    """Parse a Power BI executeQueries error body into (technical, human, category).

    ``technical`` = the useful DAX detail message (e.g. "A single value for column
    'created_at' cannot be determined...") with the JSON envelope stripped — good for
    the retry loop. ``human`` = a plain sentence for the end user, no codes/JSON.
    Never raises.
    """
    detail = ""
    try:
        import json as _json
        body = _json.loads(text) if text and text.strip().startswith("{") else {}
        err = (body.get("error") or {})
        pbi = (err.get("pbi.error") or {})
        for d in (pbi.get("details") or []):
            dv = ((d or {}).get("detail") or {}).get("value")
            if dv and "code" not in str(d.get("code", "")).lower() or dv:
                if dv:
                    detail = str(dv)
                    break
        if not detail:
            detail = str(err.get("message") or "").strip()
    except Exception:  # noqa: BLE001
        detail = ""
    low = (detail or text or "").lower()

    if status in (401,) or "unauthorized" in low or "token" in low and "expired" in low:
        return (detail or "authentication failed",
                "You're not signed in to Power BI or your session expired — please reconnect your account.",
                "auth")
    if status in (403,) or "forbidden" in low or "does not have" in low and "permission" in low or "build permission" in low:
        return (detail or "forbidden",
                "You can see this report but don't have permission to query its data. Ask the data owner for Build access to this Power BI model.",
                "no_access")
    if "cannot find table" in low or "cannot find" in low and "table" in low:
        return (detail or "table not found",
                "I couldn't find that table in the model — it may have been renamed or you may not have access to it.",
                "not_found")
    if "single value" in low and "cannot be determined" in low:
        return (detail, "", "invalid_dax")  # keep technical for auto-fix; no user message (retry handles it)
    if status == 429 or "throttl" in low or "too many requests" in low:
        return (detail or "throttled",
                "Power BI is busy right now — retrying automatically.",
                "throttled")
    if "more than" in low and ("rows" in low or "result table" in low):
        return (detail or "result too large",
                "That question returns too much data to show at once — I'll summarise it or you can add a filter.",
                "too_much_data")
    if status >= 400:
        return (detail or f"query failed (HTTP {status})",
                "I couldn't build a reliable query for that. Try rephrasing — for example, name the exact metric, table, or time range.",
                "invalid_dax")
    return (detail or "unknown error", "Something went wrong reading the data. Please try again.", "unknown")


class PowerBIClient(DataSourceClient):
    """
    Power BI client for discovering semantic models and executing DAX queries.

    Auto-discovers all workspaces, datasets (semantic models), and reports
    that the service principal has access to.
    """

    BASE_URL = "https://api.powerbi.com/v1.0/myorg"
    AUTH_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    SCOPE = "https://analysis.windows.net/powerbi/api/.default"

    # Process-local DAX result cache (flag CONNECTOR_ROBUSTNESS). The slow part of
    # a Power BI query is Microsoft's executeQueries engine (40-84s). Identical DAX
    # against the same dataset returns identical data, so we memoize it briefly:
    # this collapses the agent's intra-completion retry loop (the old "5 attempts"
    # flakiness) and back-to-back repeat questions to <1ms. Bounded by TTL + size so
    # it never serves meaningfully-stale data (PBI models change slowly) and never
    # grows unbounded. Class-level so every PBI client instance in the worker shares
    # it. Key includes tenant_id + dataset_id (globally-unique GUID) so it can never
    # cross tenants/users. OFF by default -> byte-identical to prior behavior.
    _dax_cache: Dict[str, tuple] = {}
    _DAX_CACHE_TTL = 300.0
    _DAX_CACHE_MAX = 256

    def __init__(
        self,
        tenant_id: str = None,
        client_id: str = None,
        client_secret: str = None,
        access_token: str = None,
    ):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret

        self._access_token: Optional[str] = access_token
        self._http: Optional[requests.Session] = None
        # Offline table → {datasetId, workspaceId} index (P4). Populated at
        # construct time from the connection's cached ConnectionTable metadata
        # so execute_query(table_name) resolves IDs WITHOUT a live get_schemas()
        # discovery call (which rate-limits / triggers 429). Keyed by both the
        # full "Dataset/Table" name and the bare DAX table name.
        self._table_index: Dict[str, Dict[str, Optional[str]]] = {}
        # Model metadata for grounding DAX generation: relationships (the join graph)
        # and measures (the preferred query surface). Populated from INFO.VIEW.* at
        # discovery / offline-index install, rendered into system_prompt().
        self._model_meta: Dict[str, Any] = {"relationships": [], "measures": []}

    def set_model_meta(self, meta: Dict[str, Any]) -> None:
        """Install model metadata {relationships:[...], measures:[...]} for grounding."""
        if isinstance(meta, dict):
            self._model_meta = {
                "relationships": list(meta.get("relationships") or []),
                "measures": list(meta.get("measures") or []),
            }

    def fetch_model_metadata(self, dataset_ids) -> Dict[str, Any]:
        """Fetch relationships + measures for the given dataset IDs via INFO.VIEW.*.

        Returns {"relationships":[{from,to,fromCard,toCard,active,crossFilter}...],
        "measures":[{name,table}...]}. Uses executeQueries (same token, delegated-user
        friendly). Fail-soft per dataset — a dataset that rejects INFO.VIEW just
        contributes nothing. Never raises.
        """
        rels: List[dict] = []
        meas: List[dict] = []
        for ds_id in (dataset_ids or []):
            if not ds_id:
                continue
            try:
                rdf = self.execute_query(
                    "EVALUATE INFO.VIEW.RELATIONSHIPS()", dataset_id=ds_id, max_rows=200
                )
                for _, r in rdf.iterrows():
                    d = {str(k).split("[")[-1].rstrip("]"): v for k, v in r.items()}
                    ft = d.get("FromTable") or d.get("FromFullName") or d.get("From")
                    tt = d.get("ToTable") or d.get("ToFullName") or d.get("To")
                    if not ft or not tt:
                        continue
                    rels.append({
                        "from": f"{ft}[{d.get('FromColumn','')}]",
                        "to": f"{tt}[{d.get('ToColumn','')}]",
                        "fromCard": d.get("FromCardinality"),
                        "toCard": d.get("ToCardinality"),
                        "active": d.get("IsActive"),
                        "crossFilter": d.get("CrossFilteringBehavior"),
                    })
            except Exception:  # noqa: BLE001
                pass
            try:
                mdf = self.execute_query(
                    "EVALUATE INFO.VIEW.MEASURES()", dataset_id=ds_id, max_rows=500
                )
                for _, r in mdf.iterrows():
                    d = {str(k).split("[")[-1].rstrip("]"): v for k, v in r.items()}
                    nm = d.get("Name") or d.get("Measure")
                    if nm:
                        meas.append({"name": str(nm), "table": str(d.get("Table") or ""), "datasetId": ds_id})
            except Exception:  # noqa: BLE001
                pass
        return {"relationships": rels, "measures": meas}

    def _model_meta_prompt(self) -> str:
        """Render the relationships + measures section for the system prompt. Empty
        string when nothing is known (so behaviour is unchanged for models we never
        fetched)."""
        rels = (self._model_meta or {}).get("relationships") or []
        meas = (self._model_meta or {}).get("measures") or []
        if not rels and not meas:
            return ""
        parts = ["\n### MODEL METADATA (use for grounding — do not invent)\n"]
        if meas:
            parts.append("MEASURES (prefer these over raw-column aggregations):")
            for m in meas[:60]:
                tbl = f" [{m['table']}]" if m.get("table") else ""
                parts.append(f"  - [{m['name']}]{tbl}")
            parts.append("")
        if rels:
            parts.append("RELATIONSHIPS (the ONLY valid join paths — never combine unrelated tables):")
            for r in rels[:60]:
                act = "" if str(r.get("active")).lower() in ("true", "1", "yes") else " (INACTIVE — needs USERELATIONSHIP)"
                parts.append(f"  - {r['from']} -> {r['to']}{act}")
            parts.append("")
        return "\n".join(parts)

    def set_table_index(self, mapping: Dict[str, Dict[str, Optional[str]]]) -> None:
        """Install an offline name → {datasetId, workspaceId} map (P4).

        Accepts entries keyed by full "Dataset/Table" and/or bare table name.
        Best-effort: silently ignores malformed input.
        """
        if not isinstance(mapping, dict):
            return
        for name, ids in mapping.items():
            if not name or not isinstance(ids, dict):
                continue
            ds_id = ids.get("datasetId") or ids.get("dataset_id")
            ws_id = ids.get("workspaceId") or ids.get("workspace_id")
            if not ds_id:
                continue
            entry = {"datasetId": ds_id, "workspaceId": ws_id}
            self._table_index[name] = entry
            # Also index by the bare DAX table name (after last '/').
            if "/" in name:
                self._table_index.setdefault(name.split("/")[-1], entry)

    def _lookup_ids_offline(self, table_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Resolve (dataset_id, workspace_id) from the offline index. (None, None) on miss."""
        if not table_name:
            return None, None
        entry = self._table_index.get(table_name)
        if not entry and "/" in table_name:
            entry = self._table_index.get(table_name.split("/")[-1])
        if entry:
            return entry.get("datasetId"), entry.get("workspaceId")
        return None, None

    def _sanitize_dax(self, query: str) -> str:
        """Rewrite any synthetic ``Dataset/Table`` name inside a DAX string to the
        bare, single-quoted table name DAX actually accepts.

        The schema exposes each table as ``Dataset/Table`` for display/lookup, but
        DAX has NO dataset qualifier — ``EVALUATE 'Dataset/Table'`` fails with HTTP
        400 "Cannot find table 'Dataset/Table'". LLMs copy the display name into the
        query anyway. Rather than hope the prompt prevents it, we fix it mechanically
        here: for every full name in the offline index, replace both the quoted
        (``'Dataset/Table'``) and bare (``Dataset/Table``) forms with the bare
        single-quoted table name (``'Table'``). Longest-first so a name that is a
        prefix of another can't partially match. No-op when the index is empty or the
        query contains no ``/`` qualifier. Never raises.
        """
        try:
            if not query or "/" not in query or not self._table_index:
                return query
            full_names = [k for k in self._table_index.keys() if "/" in k]
            if not full_names:
                return query
            import re as _re
            out = query
            for full in sorted(full_names, key=len, reverse=True):
                bare = full.split("/")[-1]
                repl = f"'{bare}'"
                # 'Dataset/Table' (already quoted) -> 'Table'
                out = out.replace(f"'{full}'", repl)
                # bare Dataset/Table (unquoted) -> 'Table' (word-ish boundary)
                out = _re.sub(
                    r"(?<!['\w])" + _re.escape(full) + r"(?!['\w])",
                    repl,
                    out,
                )
            return out
        except Exception:  # noqa: BLE001 — sanitize must never break a query
            return query

    def connect(self):
        """
        Authenticate with Azure AD and obtain an access token for Power BI API.
        Reuses cached token if already authenticated.
        """
        if self._http and self._access_token:
            return

        # If a delegated access_token was provided, just set up the session
        if self._access_token:
            self._http = requests.Session()
            return

        auth_url = self.AUTH_URL.format(tenant_id=self.tenant_id)
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": self.SCOPE,
        }

        resp = requests.post(auth_url, data=payload, timeout=30)
        if resp.status_code >= 300:
            raise RuntimeError(f"Failed to authenticate with Azure AD: HTTP {resp.status_code} {resp.text}")

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("Authentication did not return access token")

        self._access_token = token
        self._http = requests.Session()

    def test_connection(self) -> Dict:
        # Phase 1: Authenticate
        try:
            self.connect()
        except Exception as e:
            return {
                "success": False,
                "message": f"Authentication failed: {e}",
            }

        # Phase 2: Get first page of workspaces only (don't follow pagination)
        try:
            headers = self._build_headers()
            resp = self._http.get(f"{self.BASE_URL}/groups", headers=headers, timeout=30)
            if resp.status_code >= 300:
                raise RuntimeError(f"HTTP {resp.status_code} {resp.text}")
            workspaces = (resp.json() or {}).get("value") or []
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to list workspaces: {e}",
            }

        if not workspaces:
            return {
                "success": False,
                "message": "Connected but no workspaces found. Ensure the service principal has access to at least one workspace.",
            }

        # Phase 3: Get datasets from first workspace only
        first_ws = workspaces[0]
        first_ws_id = first_ws.get("id")
        try:
            ds_list = self.list_datasets(first_ws_id)
        except Exception as e:
            return {
                "success": False,
                "message": f"Connected but failed to list datasets: {e}",
                "connectivity": True,
            }

        if not ds_list:
            return {
                "success": False,
                "message": f"Connected to {len(workspaces)}+ workspace(s) but no datasets found in first workspace. Ensure the service principal is a Member/Contributor of your workspaces.",
                "connectivity": True,
            }

        # Phase 4: verify query access. A dataset with ZERO tables rejects any
        # DAX EVALUATE ("DAX Evaluate queries work only on databases which have
        # at least one table"), so probing only the FIRST dataset yields a false
        # failure when that dataset happens to be empty / report-only / a push
        # dataset — even though other datasets are perfectly queryable. Probe the
        # datasets in order and succeed as soon as ANY one is queryable; only fail
        # if none are.
        probe_error = ""
        probed = 0
        for ds in ds_list[:8]:
            ds_id = ds["id"]
            ds_name = ds.get("name") or ds_id
            probed += 1
            try:
                url = f"{self.BASE_URL}/groups/{first_ws_id}/datasets/{ds_id}/executeQueries"
                body = {
                    "queries": [{"query": "EVALUATE ROW(\"test\", 1)"}],
                    "serializerSettings": {"includeNulls": True},
                }
                resp = self._http.post(url, json=body, headers=headers, timeout=30)
                if resp.status_code < 300:
                    return {
                        "success": True,
                        "message": f"Connected to Power BI. Found {len(workspaces)}+ workspace(s), {len(ds_list)} dataset(s); dataset '{ds_name}' is queryable.",
                        "workspaces": len(workspaces),
                        "datasets": len(ds_list),
                    }
                # Not queryable — capture Power BI's detail for the final error.
                detail_msg = ""
                try:
                    err = resp.json().get("error", {})
                    pbi_err = err.get("pbi.error", {})
                    for d in pbi_err.get("details", []):
                        val = (d.get("detail") or {}).get("value", "")
                        if val:
                            detail_msg = val
                            break
                except Exception:
                    pass
                probe_error = detail_msg or f"HTTP {resp.status_code} on dataset '{ds_name}'"
            except Exception as e:  # noqa: BLE001
                probe_error = f"dataset '{ds_name}': {e}"

        # No probed dataset was queryable.
        return {
            "success": False,
            "message": (
                f"Connected, but none of the first {probed} dataset(s) are queryable. "
                f"Last error: {probe_error}. Empty / report-only datasets reject DAX; "
                f"ensure at least one dataset has tables and the account has Build permission."
            ),
            "connectivity": True,
        }

    def list_workspaces(self) -> List[Dict]:
        """
        List all workspaces (groups) the service principal has access to.
        """
        self.connect()
        url = f"{self.BASE_URL}/groups"
        headers = self._build_headers()

        results: List[Dict] = []
        while url:
            resp = self._http.get(url, headers=headers, timeout=30)
            if resp.status_code >= 300:
                raise RuntimeError(f"Failed to list workspaces: HTTP {resp.status_code} {resp.text}")

            payload = resp.json() or {}
            items = payload.get("value") or []
            for ws in items:
                results.append({
                    "id": ws.get("id"),
                    "name": ws.get("name"),
                    "type": ws.get("type"),
                    "isOnDedicatedCapacity": ws.get("isOnDedicatedCapacity"),
                })
            url = payload.get("@odata.nextLink")

        return results

    def list_datasets(self, workspace_id: str) -> List[Dict]:
        """
        List all datasets (semantic models) in a workspace.
        """
        self.connect()
        url = f"{self.BASE_URL}/groups/{workspace_id}/datasets"
        headers = self._build_headers()

        results: List[Dict] = []
        while url:
            resp = self._http.get(url, headers=headers, timeout=30)
            if resp.status_code >= 300:
                raise RuntimeError(f"Failed to list datasets: HTTP {resp.status_code} {resp.text}")

            payload = resp.json() or {}
            items = payload.get("value") or []
            for ds in items:
                results.append({
                    "id": ds.get("id"),
                    "name": ds.get("name"),
                    "configuredBy": ds.get("configuredBy"),
                    "isRefreshable": ds.get("isRefreshable"),
                    "isOnPremGatewayRequired": ds.get("isOnPremGatewayRequired"),
                    "storageMode": ds.get("storageMode") or ds.get("targetStorageMode"),
                    "targetStorageMode": ds.get("targetStorageMode"),
                    "webUrl": ds.get("webUrl"),
                })
            url = payload.get("@odata.nextLink")

        return results

    def list_reports(self, workspace_id: str) -> List[Dict]:
        """
        List all reports in a workspace.
        """
        self.connect()
        url = f"{self.BASE_URL}/groups/{workspace_id}/reports"
        headers = self._build_headers()

        results: List[Dict] = []
        while url:
            resp = self._http.get(url, headers=headers, timeout=30)
            if resp.status_code >= 300:
                raise RuntimeError(f"Failed to list reports: HTTP {resp.status_code} {resp.text}")

            payload = resp.json() or {}
            items = payload.get("value") or []
            for rpt in items:
                results.append({
                    "id": rpt.get("id"),
                    "name": rpt.get("name"),
                    "datasetId": rpt.get("datasetId"),
                    "webUrl": rpt.get("webUrl"),
                    "reportType": rpt.get("reportType"),
                })
            url = payload.get("@odata.nextLink")

        return results

    def get_dataset_tables(self, workspace_id: str, dataset_id: str) -> tuple:
        """
        Get tables and columns for a single dataset.
        Uses COLUMNSTATISTICS (no relationships) with REST API fallback.
        For bulk discovery with relationships, use _batch_admin_scan() instead.

        Returns:
            tuple: (tables_list, relationships_list)
        """
        self.connect()
        headers = self._build_headers()

        # Try COLUMNSTATISTICS first (works for most datasets without admin perms)
        tables, empty_db = self._get_tables_via_column_stats(workspace_id, dataset_id)
        if tables:
            return tables, []
        # Genuinely empty database (e.g. staging lakehouse/warehouse with 0 tables) —
        # nothing to find. Skip the REST + brute probes to avoid wasted calls / 429.
        if empty_db:
            return [], []

        # Fallback: REST API /tables (only works for Push datasets)
        url = f"{self.BASE_URL}/groups/{workspace_id}/datasets/{dataset_id}/tables"
        resp = self._http.get(url, headers=headers, timeout=30)
        if resp.status_code < 300:
            rest_tables = (resp.json() or {}).get("value") or []
            if rest_tables and any(t.get("columns") for t in rest_tables):
                return rest_tables, []

        # Last resort: brute-probe common table names (lakehouse/warehouse datasets)
        tables, _ = self._brute_discover_tables(workspace_id, dataset_id)
        if tables:
            return tables, []

        return [], []

    def _get_tables_via_column_stats(self, workspace_id: str, dataset_id: str) -> tuple:
        """
        Get table/column metadata using DAX COLUMNSTATISTICS() function.
        Works for most imported and DirectQuery datasets.

        Returns:
            tuple: (tables_list, empty_db) — ``empty_db`` True when the dataset is a
            genuinely empty database (0 tables), so the caller can skip the REST /
            brute-probe fallbacks (which would just waste calls and risk HTTP 429).
        """
        import logging

        try:
            # COLUMNSTATISTICS() returns: Table Name, Column Name, Min, Max, Cardinality, Max Length
            stats_dax = "EVALUATE COLUMNSTATISTICS()"
            stats_df = self._execute_dax_internal(workspace_id, dataset_id, stats_dax)
            if stats_df.empty:
                return [], False

            # Build tables structure from column stats
            tables_dict: Dict[str, Dict] = {}

            for _, row in stats_df.iterrows():
                table_name = str(row.get("Table Name", ""))
                col_name = str(row.get("Column Name", ""))

                if not table_name or not col_name:
                    continue

                # Skip internal/system tables
                if table_name.startswith("DateTableTemplate") or table_name.startswith("LocalDateTable"):
                    continue

                if table_name not in tables_dict:
                    tables_dict[table_name] = {"name": table_name, "columns": [], "measures": []}

                tables_dict[table_name]["columns"].append({
                    "name": col_name,
                    "dataType": "unknown",  # COLUMNSTATISTICS doesn't return data type
                })

            # No relationships available via COLUMNSTATISTICS
            return list(tables_dict.values()), False

        except Exception as e:
            msg = str(e)
            # "DAX Evaluate queries work only on databases which have at least one
            # table" = the dataset is an empty database, not a blocked one → don't
            # bother with the REST/brute fallbacks.
            empty_db = "at least one table" in msg
            # An empty dataset is expected noise (many per-user tenants carry blank
            # models) — log it at debug so it doesn't spam WARN. Real failures stay
            # at warning.
            if empty_db:
                logging.debug(f"COLUMNSTATISTICS: dataset {dataset_id} is empty (no tables), skipping")
            else:
                logging.warning(f"COLUMNSTATISTICS failed for dataset {dataset_id}: {e}")
            return [], empty_db

    def _brute_discover_tables(self, workspace_id: str, dataset_id: str) -> tuple:
        """
        Last-resort table discovery: probe a list of common table names with
        `EVALUATE TOPN(1, 'Name')`. HTTP 200 = the table exists and its columns
        (DataFrame column names, stripped of the `Name[col]` bracket wrapping)
        give the column names. Any error on a candidate = skip it (fail-soft).

        For lakehouse/warehouse-backed datasets that reject COLUMNSTATISTICS and
        aren't Push datasets (so REST /tables is empty).

        Returns:
            tuple: (tables_list, relationships_list) - relationships always empty
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        # If Power BI starts returning 429 (120 req/min/user cap), stop probing
        # immediately — hammering ~40 more names guarantees a rate-limit storm.
        rate_limited = threading.Event()

        def _probe(name: str) -> Optional[Dict]:
            if rate_limited.is_set():
                return None
            try:
                dax = f"EVALUATE TOPN(1, '{name}')"
                df = self._execute_dax_internal(workspace_id, dataset_id, dax)
            except Exception as e:
                if "429" in str(e):
                    rate_limited.set()
                return None

            columns = []
            for raw_col in df.columns:
                if "[" in raw_col and "]" in raw_col:
                    col = raw_col[raw_col.index("[") + 1:raw_col.index("]")]
                else:
                    col = raw_col
                if col:
                    columns.append({"name": col, "dataType": "unknown"})

            return {"name": name, "columns": columns, "measures": []}

        tables_list = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_probe, name): name for name in _COMMON_TABLE_NAMES}
            for fut in as_completed(futures):
                try:
                    result = fut.result()
                except Exception:
                    result = None
                if result:
                    tables_list.append(result)

        return tables_list, []

    def _get_tables_via_admin_scan(self, workspace_id: str, dataset_id: str) -> tuple:
        """
        Get table/column metadata using the Admin Scanner API.
        Requires the service principal to have admin permissions.

        Returns:
            tuple: (tables_list, relationships_list)
        """
        import time
        import logging

        try:
            headers = self._build_headers()

            # Step 1: Initiate workspace scan with datasetSchema=true
            scan_url = f"{self.BASE_URL}/admin/workspaces/getInfo?datasetSchema=true"
            body = {"workspaces": [workspace_id]}

            resp = self._http.post(scan_url, json=body, headers=headers, timeout=30)
            if resp.status_code >= 300:
                logging.warning(f"Admin scan initiation failed: HTTP {resp.status_code} {resp.text}")
                return [], []

            scan_data = resp.json() or {}
            scan_id = scan_data.get("id")
            if not scan_id:
                logging.warning("Admin scan did not return scan ID")
                return [], []

            # Step 2: Poll for scan completion (max 30 seconds)
            status_url = f"{self.BASE_URL}/admin/workspaces/scanStatus/{scan_id}"
            for _ in range(15):
                time.sleep(2)
                status_resp = self._http.get(status_url, headers=headers, timeout=30)
                if status_resp.status_code >= 300:
                    continue
                status_data = status_resp.json() or {}
                if status_data.get("status") == "Succeeded":
                    break
            else:
                logging.warning(f"Admin scan timed out for workspace {workspace_id}")
                return [], []

            # Step 3: Get scan results
            result_url = f"{self.BASE_URL}/admin/workspaces/scanResult/{scan_id}"
            result_resp = self._http.get(result_url, headers=headers, timeout=60)
            if result_resp.status_code >= 300:
                logging.warning(f"Failed to get scan results: HTTP {result_resp.status_code}")
                return [], []

            result_data = result_resp.json() or {}
            workspaces = result_data.get("workspaces") or []

            # Find the dataset in the scan results
            for ws in workspaces:
                for ds in ws.get("datasets") or []:
                    if ds.get("id") == dataset_id:
                        return self._parse_admin_scan_tables(ds)

            return [], []

        except Exception as e:
            logging.warning(f"Failed to get tables via admin scan for dataset {dataset_id}: {e}")
            return [], []

    def _parse_admin_scan_tables(self, dataset: Dict) -> tuple:
        """Parse tables/columns/measures/relationships from Admin Scanner API response.

        Returns:
            tuple: (tables_list, relationships_list)
        """
        tables_dict: Dict[str, Dict] = {}

        for tbl in dataset.get("tables") or []:
            tbl_name = tbl.get("name") or ""
            if not tbl_name or tbl.get("isHidden"):
                continue

            if tbl_name not in tables_dict:
                tables_dict[tbl_name] = {"name": tbl_name, "columns": [], "measures": []}

            # Add columns
            for col in tbl.get("columns") or []:
                col_name = col.get("name") or ""
                if col_name and not col.get("isHidden"):
                    tables_dict[tbl_name]["columns"].append({
                        "name": col_name,
                        "dataType": col.get("dataType") or "unknown",
                    })

            # Add measures
            for measure in tbl.get("measures") or []:
                measure_name = measure.get("name") or ""
                if measure_name and not measure.get("isHidden"):
                    tables_dict[tbl_name]["measures"].append({
                        "name": measure_name,
                        "expression": measure.get("expression") or "",
                    })

        # Extract relationships
        relationships = []
        for rel in dataset.get("relationships") or []:
            from_table = rel.get("fromTable") or ""
            from_column = rel.get("fromColumn") or ""
            to_table = rel.get("toTable") or ""
            to_column = rel.get("toColumn") or ""
            if from_table and from_column and to_table and to_column:
                relationships.append({
                    "fromTable": from_table,
                    "fromColumn": from_column,
                    "toTable": to_table,
                    "toColumn": to_column,
                    "crossFilteringBehavior": rel.get("crossFilteringBehavior"),
                })

        return list(tables_dict.values()), relationships

    def _batch_admin_scan(self, workspace_ids: List[str]) -> Dict[str, Dict]:
        """
        Batch admin scan: up to 100 workspaces per request.
        Returns dict keyed by dataset_id -> (tables, relationships) from _parse_admin_scan_tables.
        """
        import time
        import logging

        self.connect()
        headers = self._build_headers()
        # ds_id -> (tables, relationships)
        results: Dict[str, tuple] = {}

        # Batch in chunks of 100 (API limit)
        for i in range(0, len(workspace_ids), 100):
            batch = workspace_ids[i:i + 100]

            try:
                scan_url = f"{self.BASE_URL}/admin/workspaces/getInfo?datasetSchema=true"
                resp = self._http.post(scan_url, json={"workspaces": batch}, headers=headers, timeout=30)
                if resp.status_code >= 300:
                    logging.debug(f"Batch admin scan failed: HTTP {resp.status_code}")
                    continue

                scan_id = (resp.json() or {}).get("id")
                if not scan_id:
                    continue

                # Poll for completion (max 60s for batch)
                status_url = f"{self.BASE_URL}/admin/workspaces/scanStatus/{scan_id}"
                succeeded = False
                for _ in range(30):
                    time.sleep(2)
                    status_resp = self._http.get(status_url, headers=headers, timeout=30)
                    if status_resp.status_code < 300:
                        if (status_resp.json() or {}).get("status") == "Succeeded":
                            succeeded = True
                            break
                if not succeeded:
                    continue

                # Fetch results
                result_url = f"{self.BASE_URL}/admin/workspaces/scanResult/{scan_id}"
                result_resp = self._http.get(result_url, headers=headers, timeout=60)
                if result_resp.status_code >= 300:
                    continue

                for ws in (result_resp.json() or {}).get("workspaces") or []:
                    for ds in ws.get("datasets") or []:
                        ds_id = ds.get("id")
                        if ds_id:
                            results[ds_id] = self._parse_admin_scan_tables(ds)

            except Exception as e:
                logging.debug(f"Batch admin scan error: {e}")
                continue

        return results

    def get_schemas(self) -> List[Table]:
        """
        Build Table objects representing all internal tables across all datasets.
        Each internal Power BI table becomes one DASH Table named "{Dataset}/{Table}".

        Strategy:
        1. Fetch datasets and reports for all workspaces in parallel
        2. Try batch admin scan (up to 100 workspaces per call) — gets tables + relationships
        3. For datasets not covered by admin scan, fall back to parallel COLUMNSTATISTICS
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import logging

        workspaces = self.list_workspaces()
        tables: List[Table] = []

        # Phase 1: Fetch datasets and reports for all workspaces in parallel
        ws_datasets: Dict[str, List[Dict]] = {}  # ws_id -> datasets
        ws_reports: Dict[str, List[Dict]] = {}    # ws_id -> reports

        with ThreadPoolExecutor(max_workers=10) as pool:
            ds_futures = {pool.submit(self.list_datasets, ws["id"]): ws for ws in workspaces}
            rpt_futures = {pool.submit(self.list_reports, ws["id"]): ws for ws in workspaces}

            for fut in as_completed(ds_futures):
                ws = ds_futures[fut]
                try:
                    ws_datasets[ws["id"]] = fut.result()
                except Exception:
                    ws_datasets[ws["id"]] = []

            for fut in as_completed(rpt_futures):
                ws = rpt_futures[fut]
                try:
                    ws_reports[ws["id"]] = fut.result()
                except Exception:
                    ws_reports[ws["id"]] = []

        # Collect all (workspace, dataset) pairs
        all_ds_tasks: List[Tuple[Dict, Dict, str]] = []
        for ws in workspaces:
            ws_id = ws.get("id")
            for ds in ws_datasets.get(ws_id, []):
                all_ds_tasks.append((ws, ds, ws_id))

        # Phase 2: Try batch admin scan for all workspaces (tables + relationships in bulk)
        ws_ids = [ws["id"] for ws in workspaces]
        admin_scan_results: Dict[str, tuple] = {}  # ds_id -> (tables, relationships)
        try:
            admin_scan_results = self._batch_admin_scan(ws_ids)
        except Exception as e:
            logging.debug(f"Batch admin scan unavailable, falling back to COLUMNSTATISTICS: {e}")

        # Phase 3: For datasets not covered by admin scan, use parallel COLUMNSTATISTICS
        ds_table_results: Dict[str, tuple] = {}  # "ws_id:ds_id" -> (tables, relationships)
        fallback_tasks = []

        for ws, ds, ws_id in all_ds_tasks:
            ds_id = ds.get("id")
            key = f"{ws_id}:{ds_id}"
            if ds_id in admin_scan_results:
                ds_table_results[key] = admin_scan_results[ds_id]
            else:
                fallback_tasks.append((ws, ds, ws_id, key))

        if fallback_tasks:
            with ThreadPoolExecutor(max_workers=10) as pool:
                tbl_futures = {}
                for ws, ds, ws_id, key in fallback_tasks:
                    ds_id = ds.get("id")
                    tbl_futures[pool.submit(self.get_dataset_tables, ws_id, ds_id)] = key

                for fut in as_completed(tbl_futures):
                    key = tbl_futures[fut]
                    try:
                        ds_table_results[key] = fut.result()
                    except Exception:
                        ds_table_results[key] = ([], [])

        # Phase 4: Assemble Table objects (CPU-only, no I/O)
        for ws, ds, ws_id in all_ds_tasks:
            ws_name = ws.get("name") or ws_id
            ds_id = ds.get("id")
            ds_name = ds.get("name") or ds_id
            key = f"{ws_id}:{ds_id}"

            # Build reports map for this workspace
            reports_by_dataset: Dict[str, List[Dict]] = {}
            for rpt in ws_reports.get(ws_id, []):
                rpt_ds_id = rpt.get("datasetId")
                if rpt_ds_id:
                    if rpt_ds_id not in reports_by_dataset:
                        reports_by_dataset[rpt_ds_id] = []
                    reports_by_dataset[rpt_ds_id].append({
                        "id": rpt.get("id"),
                        "name": rpt.get("name"),
                        "webUrl": rpt.get("webUrl"),
                    })

            ds_tables, ds_relationships = ds_table_results.get(key, ([], []))

            # Create one DASH Table per internal Power BI table
            for tbl in ds_tables:
                tbl_name = tbl.get("name") or ""
                if not tbl_name:
                    continue

                # Clean up display name for SharePoint URL tables
                tbl_display_name = _clean_table_display_name(tbl_name)

                # 2-level naming: Dataset/Table (like Snowflake's schema.table)
                full_name = f"{ds_name}/{tbl_display_name}"

                # Columns for this table only
                columns: List[TableColumn] = []
                for col in tbl.get("columns") or []:
                    col_name = col.get("name") or ""
                    col_type = col.get("dataType") or "unknown"
                    if col_name:
                        columns.append(TableColumn(
                            name=col_name,
                            dtype=col_type,
                            description=None,
                            metadata={"role": "column"},
                        ))

                # Measures for this table
                for measure in tbl.get("measures") or []:
                    measure_name = measure.get("name") or ""
                    expression = measure.get("expression") or ""
                    if measure_name:
                        columns.append(TableColumn(
                            name=measure_name,
                            dtype="measure",
                            description=expression[:200] if expression else None,
                            metadata={
                                "role": "measure",
                                "expression": expression,
                            },
                        ))

                # Build FKs for relationships FROM this table
                fks: List[ForeignKey] = []
                for rel in ds_relationships:
                    if rel.get("fromTable") == tbl_name:
                        to_table = rel.get("toTable") or ""
                        to_table_display = _clean_table_display_name(to_table)
                        fks.append(ForeignKey(
                            column=TableColumn(
                                name=rel.get("fromColumn") or "",
                                dtype="unknown",
                            ),
                            references_name=f"{ds_name}/{to_table_display}",
                            references_column=TableColumn(
                                name=rel.get("toColumn") or "",
                                dtype="unknown",
                            ),
                        ))

                # Metadata for query execution (workspace at connection level)
                metadata_json = {
                    "powerbi": {
                        "datasetId": ds_id,
                        "workspaceId": ws_id,
                        "workspaceName": ws_name,
                        "datasetName": ds_name,
                        "tableName": tbl_name,
                        "configuredBy": ds.get("configuredBy"),
                        "webUrl": ds.get("webUrl"),
                        "storageMode": ds.get("storageMode") or ds.get("targetStorageMode"),
                        "isOnPremGatewayRequired": ds.get("isOnPremGatewayRequired"),
                        "queryable": _is_dataset_queryable(ds),
                        "reports": reports_by_dataset.get(ds_id, []),
                    }
                }

                tables.append(Table(
                    name=full_name,
                    description=None,
                    columns=columns,
                    pks=[],
                    fks=fks if fks else [],
                    is_active=True,
                    metadata_json=metadata_json,
                ))

        return tables

    def get_schema(self, table_name: str) -> Table:
        """
        Get schema for a single table by name.

        Accepts:
          - "Dataset/Table" name path (exact match)
          - Internal table name only (first match)
          - Dataset ID (returns first table in that dataset)
        """
        all_tables = self.get_schemas()

        # Try exact name match (Dataset/Table)
        for tbl in all_tables:
            if tbl.name == table_name:
                return tbl

        # Try by internal table name only (first match)
        for tbl in all_tables:
            metadata = tbl.metadata_json or {}
            pbi = metadata.get("powerbi") or {}
            if pbi.get("tableName") == table_name:
                return tbl

        # Try by dataset ID (returns first table in that dataset)
        for tbl in all_tables:
            metadata = tbl.metadata_json or {}
            pbi = metadata.get("powerbi") or {}
            if pbi.get("datasetId") == table_name:
                return tbl

        raise RuntimeError(f"Table not found for '{table_name}'")

    def execute_query(
        self,
        query: str,
        table_name: Optional[str] = None,
        dataset_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        max_rows: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        Execute a DAX query against a dataset and return results as DataFrame.

        Args:
            query: DAX query string (must start with EVALUATE)
            table_name: Table name (e.g., "SalesModel/Customers") - will look up dataset_id/workspace_id
            dataset_id: Power BI dataset ID (alternative to table_name)
            workspace_id: Power BI workspace ID
            max_rows: Maximum rows to return

        Example:
            df = client.execute_query("EVALUATE Customers", "SalesModel/Customers")
            # or with explicit IDs:
            df = client.execute_query("EVALUATE Customers", dataset_id="abc", workspace_id="xyz")
        """
        if not query:
            raise ValueError("DAX query is required")

        # Mechanically strip any synthetic "Dataset/Table" qualifier the LLM may have
        # placed inside the DAX (DAX has no dataset qualifier -> "Cannot find table").
        query = self._sanitize_dax(query)

        # If table_name provided (but not dataset_id), look up the IDs.
        if table_name and not dataset_id:
            # P4: try the offline index FIRST (no live call, no 429). Falls back
            # to a live get_schema() only on a miss / empty index.
            off_ds, off_ws = self._lookup_ids_offline(table_name)
            if off_ds:
                dataset_id = off_ds
                workspace_id = workspace_id or off_ws
            else:
                try:
                    table = self.get_schema(table_name)
                    pbi = (table.metadata_json or {}).get("powerbi") or {}
                    dataset_id = pbi.get("datasetId")
                    workspace_id = workspace_id or pbi.get("workspaceId")
                except Exception:
                    pass

        # Last-resort: if still no dataset_id but the index has exactly one
        # dataset, use it — a single-model connection is unambiguous.
        if not dataset_id and self._table_index:
            ds_ids = {e.get("datasetId") for e in self._table_index.values() if e.get("datasetId")}
            if len(ds_ids) == 1:
                dataset_id = next(iter(ds_ids))
                if workspace_id is None:
                    for e in self._table_index.values():
                        if e.get("datasetId") == dataset_id:
                            workspace_id = e.get("workspaceId"); break

        if not dataset_id:
            raise ValueError("dataset_id is required (pass table_name or dataset_id)")

        # DAX result cache (flag CONNECTOR_ROBUSTNESS). Serve a fresh-enough
        # identical result without hitting Microsoft's slow engine. Fail-soft: any
        # cache error falls through to a normal live execution.
        try:
            from app.settings.hybrid_flags import flags as _hflags
            _robust = bool(_hflags.CONNECTOR_ROBUSTNESS)
        except Exception:
            _robust = False

        _key = None
        if _robust:
            try:
                import hashlib as _hl
                # Include the user id so a Row-Level-Security dataset (different users
                # see different rows of the SAME dataset) can never serve one user's
                # cached result to another. Empty for system/service contexts.
                _uid = getattr(self, "_bow_user_id", "") or ""
                _sig = f"{_uid}|{self.tenant_id or ''}|{workspace_id or ''}|{dataset_id}|{max_rows}|{query}"
                _key = _hl.sha256(_sig.encode("utf-8")).hexdigest()
                _cached = self._dax_cache_get(_key)
                if _cached is not None:
                    logger.info("powerbi.dax.cache_hit dataset=%s", dataset_id)
                    return _cached.copy()
            except Exception:
                _key = None

        df = self._execute_dax_internal(workspace_id, dataset_id, query, max_rows=max_rows)

        if _robust and _key is not None and df is not None:
            try:
                self._dax_cache_put(_key, df)
            except Exception:
                pass
        return df

    @classmethod
    def _dax_cache_get(cls, key: str):
        """Return a cached DataFrame if present and unexpired, else None (evicts
        expired entries lazily). Never raises."""
        entry = cls._dax_cache.get(key)
        if not entry:
            return None
        expiry, df = entry
        if time.time() >= expiry:
            cls._dax_cache.pop(key, None)
            return None
        return df

    @classmethod
    def _dax_cache_put(cls, key: str, df) -> None:
        """Store a DataFrame with a TTL. Enforces a hard size cap by dropping the
        oldest-expiring entries first. Stores a copy so callers can't mutate it."""
        if len(cls._dax_cache) >= cls._DAX_CACHE_MAX:
            # evict expired first, then the soonest-to-expire, to stay bounded
            now = time.time()
            for k in [k for k, (exp, _) in cls._dax_cache.items() if exp <= now]:
                cls._dax_cache.pop(k, None)
            while len(cls._dax_cache) >= cls._DAX_CACHE_MAX:
                oldest = min(cls._dax_cache.items(), key=lambda kv: kv[1][0])[0]
                cls._dax_cache.pop(oldest, None)
        cls._dax_cache[key] = (time.time() + cls._DAX_CACHE_TTL, df.copy())

    @staticmethod
    def _parse_retry_after(resp) -> Optional[float]:
        """Extract a wait time (seconds) from a 429/503 response.

        Power BI returns `Retry-After` in seconds (per Microsoft docs). Falls
        back to None when absent/malformed so the caller uses exp backoff.
        """
        for h in ("Retry-After", "retry-after"):
            v = resp.headers.get(h) if resp is not None and resp.headers else None
            if v:
                try:
                    return max(0.0, float(str(v).strip()))
                except (TypeError, ValueError):
                    return None
        return None

    def _post_dax_with_retry(self, url: str, body: dict, headers: dict):
        """POST executeQueries with rate-limit backoff (P2, flag
        CONNECTOR_ROBUSTNESS).

        On HTTP 429/503, honor `Retry-After` (else exp backoff 2/4/8s) and
        retry up to 3 times. On exhaustion raise :class:`PowerBIRateLimitError`
        with a clean message. When the flag is OFF this makes exactly one
        request (byte-identical to the prior behavior).
        """
        try:
            from app.settings.hybrid_flags import flags as _hflags
            robust = bool(_hflags.CONNECTOR_ROBUSTNESS)
        except Exception:
            robust = False

        if not robust:
            return self._http.post(url, json=body, headers=headers, timeout=120)

        max_retries = 3
        backoff = [2.0, 4.0, 8.0]
        last_resp = None
        for attempt in range(max_retries + 1):
            resp = self._http.post(url, json=body, headers=headers, timeout=120)
            last_resp = resp
            if resp.status_code not in (429, 503):
                return resp
            if attempt >= max_retries:
                break
            wait = self._parse_retry_after(resp)
            if wait is None:
                wait = backoff[min(attempt, len(backoff) - 1)]
            logger.warning(
                "powerbi.dax.rate_limited status=%s attempt=%d/%d wait=%.1fs",
                resp.status_code, attempt + 1, max_retries, wait,
            )
            time.sleep(wait)

        wait = self._parse_retry_after(last_resp) if last_resp is not None else None
        raise PowerBIRateLimitError(
            "Power BI is rate-limiting requests (HTTP 429). Please retry in a "
            f"{'few' if not wait else int(wait)} seconds.",
            retry_after=wait,
        )

    def _reauth(self) -> bool:
        """Force a fresh access token for 401 recovery (flag CONNECTOR_ROBUSTNESS).

        Clears the cached token + HTTP session and re-runs ``connect()`` — which
        re-mints via refresh_token (per-user client) or client_credentials (base).
        Returns True only if a new token was obtained. NEVER raises: a client that
        was constructed with a delegated access_token and no way to re-mint simply
        returns False and the caller keeps the original 401.
        """
        try:
            self._access_token = None
            self._http = None
            self.connect()
            return bool(self._access_token)
        except Exception:
            logger.warning("powerbi.reauth failed", exc_info=True)
            return False

    def _execute_dax_internal(
        self,
        workspace_id: Optional[str],
        dataset_id: str,
        dax: str,
        max_rows: Optional[int] = None,
    ) -> pd.DataFrame:
        """Internal DAX execution."""
        self.connect()
        # Use workspace-scoped endpoint if workspace_id provided
        if workspace_id:
            url = f"{self.BASE_URL}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries"
        else:
            url = f"{self.BASE_URL}/datasets/{dataset_id}/executeQueries"
        headers = self._build_headers()

        body = {
            "queries": [{"query": dax}],
            "serializerSettings": {"includeNulls": True},
        }

        resp = self._post_dax_with_retry(url, body, headers)
        # 401 auto-reauth (flag CONNECTOR_ROBUSTNESS): the access token can expire
        # mid-session -> remint once (refresh_token / client_credentials) and retry
        # the SAME query. Fail-soft: if reauth can't mint, fall through with the 401
        # so the error path is byte-identical to before.
        if resp.status_code == 401:
            try:
                from app.settings.hybrid_flags import flags as _hflags
                _robust = bool(_hflags.CONNECTOR_ROBUSTNESS)
            except Exception:
                _robust = False
            if _robust and self._reauth():
                headers = self._build_headers()
                resp = self._post_dax_with_retry(url, body, headers)
        if resp.status_code >= 300:
            technical, human, category = _humanize_pbi_error(resp.status_code, resp.text)
            # Log the raw envelope server-side only; never surface it to the user.
            logger.warning("powerbi.dax.error status=%s category=%s raw=%s",
                           resp.status_code, category, resp.text[:500])
            raise PowerBIQueryError(f"DAX query failed: {technical}", human, category)

        payload = resp.json() or {}
        results = payload.get("results") or []

        if not results:
            return pd.DataFrame()

        first_result = results[0]
        # "Success with error" (HTTP 200): row/table-limit errors arrive here, not as
        # a 4xx. Surface them through the same humanizer so they never leak raw.
        _perr = first_result.get("error")
        if _perr:
            _msg = (_perr.get("message") or str(_perr)) if isinstance(_perr, dict) else str(_perr)
            technical, human, category = _humanize_pbi_error(200, '{"error":{"message":%s}}' % __import__("json").dumps(_msg))
            logger.warning("powerbi.dax.error200 category=%s msg=%s", category, _msg[:300])
            raise PowerBIQueryError(f"DAX query failed: {technical}", human, category)
        tables = first_result.get("tables") or []

        if not tables:
            return pd.DataFrame()

        rows = tables[0].get("rows") or []

        if not rows:
            return pd.DataFrame()

        # Clean column names (remove brackets like [ColumnName])
        df = pd.DataFrame(rows)
        df.columns = [col.strip("[]") for col in df.columns]

        if max_rows is not None and max_rows > 0 and len(df) > max_rows:
            df = df.head(max_rows)

        return df

    def prompt_schema(self) -> str:
        """Format schemas for LLM prompt."""
        schemas = self.get_schemas()
        return ServiceFormatter(schemas).table_str

    @property
    def description(self) -> str:
        text = "Power BI Client: discover semantic models and execute DAX queries."
        text += self.system_prompt()
        return text

    def system_prompt(self) -> str:
        return self._system_prompt_base() + self._grounding_rules_prompt() + self._model_meta_prompt()

    def _real_table_names(self) -> List[str]:
        """The exact bare DAX table names that actually exist in this dataset, pulled
        from the already-cached offline table index (NO live network call). The index
        is keyed by both full ``Dataset/Table`` and bare ``Table`` names — we return the
        bare form (what DAX references). Empty list when the index isn't populated."""
        names: List[str] = []
        seen = set()
        try:
            for key in (self._table_index or {}).keys():
                bare = key.split("/")[-1] if "/" in key else key
                if bare and bare not in seen:
                    seen.add(bare)
                    names.append(bare)
        except Exception:  # noqa: BLE001 — grounding must never break the prompt
            return []
        return sorted(names)

    def _grounding_rules_prompt(self) -> str:
        """Hard grounding rules that force ANY model to use the REAL table/column names
        of this Power BI dataset instead of textbook placeholders (Table/Data/Measures/
        Dimension) or an assumed relational ``id`` primary key. Always emitted (fail-soft):
        the rule text stands even when the real-name list isn't available yet."""
        real = self._real_table_names()
        parts = ["\n### HARD GROUNDING RULES (Power BI — read before writing any DAX)\n"]
        parts.append(
            "This data source is Microsoft Power BI, queried with DAX (EVALUATE ...)."
        )
        if real:
            joined = ", ".join(f"'{n}'" for n in real)
            parts.append(f"Use ONLY these exact table names that exist in the dataset: [{joined}].")
        else:
            parts.append(
                "Use ONLY table names that appear in the schema/metadata below — never guess a name."
            )
        parts.append(
            "Reference columns as 'TableName'[ColumnName]. NEVER use generic placeholder "
            "names like Table, Data, Measures, Dimension, Fact, or Dim<X>."
        )
        parts.append(
            "There are NO `id` primary-key columns in this model — do NOT reference an `id` "
            "column unless it is explicitly listed in the schema for that table."
        )
        parts.append(
            "Each table belongs to a specific dataset — only query tables that exist above; "
            "if you cannot find a suitable real table/column, say so instead of inventing one.\n"
        )
        return "\n".join(parts)

    def _system_prompt_base(self) -> str:
        return """
## Power BI DAX Query Guide

Execute DAX queries against Power BI semantic models.

### Schema Structure

Each Power BI table is exposed as a separate schema table named `Dataset/Table`:
- `SalesModel/Customers` - Customers table in SalesModel dataset
- `SalesModel/Orders` - Orders table in SalesModel dataset

Tables in the same dataset share the same `metadata.powerbi.datasetId` and can be joined via relationships (see `fks` field).

### Table Name vs DAX Table Name

- **Schema table name** (e.g., `SalesModel/Customers`) - Pass as second argument to `execute_query()`
- **DAX table name** - The part after `/` (e.g., `Customers`) - Use inside DAX queries

The DAX table name is also available in `metadata.powerbi.tableName`.

### How to Execute Queries

**Signature**: `execute_query(dax_query, table_name)` - BOTH arguments are REQUIRED!

```python
# Schema table name as 2nd arg, DAX table name in query
# Use the EXACT db_clients key for your data source (see 'Available data clients' above). Do NOT use a connector type name like 'powerbi'.
df = db_clients[<your data source name>].execute_query(
    "EVALUATE Customers",           # DAX uses the table name (after /)
    "SalesModel/Customers"          # Schema table name (REQUIRED)
)
```

### DAX Query Pattern

```dax
EVALUATE <table_expression>
```

### Examples

```dax
-- Get all rows (quote table name if it has spaces)
EVALUATE Customers
EVALUATE 'Order Details'

-- Aggregate with grouping
EVALUATE
SUMMARIZECOLUMNS(
    Orders[Category],
    "Total", SUM(Orders[Amount])
)

-- Filter data
EVALUATE
FILTER(
    Customers,
    Customers[Status] = "Active"
)

-- Top N results
EVALUATE
TOPN(10,
    SUMMARIZECOLUMNS(Customers[Name], "Total", SUM(Orders[Value])),
    [Total], DESC
)
```

### Key DAX Syntax Rules
- Table names with spaces MUST use single quotes: 'Order Details'[Column]
- Column references: TableName[ColumnName] or 'Table Name'[ColumnName]
- Measure references: [MeasureName] (no table prefix)
- String literals use double quotes: "value"
- Relationships between tables are in `fks` - use RELATED() to traverse them
- INFO.TABLES() and INFO.COLUMNS() do NOT work via REST API - use the schema metadata instead

### CRITICAL — Aggregation / scalar-column rule (READ THIS)
DAX is NOT SQL. Every column reference in the OUTPUT must be EITHER:
  (a) a group-by key inside SUMMARIZECOLUMNS, OR
  (b) wrapped in an aggregation: SUM / MIN / MAX / COUNT / COUNTROWS / DISTINCTCOUNT / AVERAGE.
NEVER place a bare, many-valued column in a scalar / measure / ROW context. Power BI
will reject it with HTTP 400: "A single value for column '<col>' cannot be determined."
This is the #1 cause of failed DAX. When in doubt, aggregate.

### Canonical patterns — COPY THESE (do not invent SQL-style column selects)
Count all rows:
    EVALUATE ROW("count", COUNTROWS('projects'))
Count distinct values of a column:
    EVALUATE ROW("count", DISTINCTCOUNT('projects'[id]))
Latest / earliest date (scalar):
    EVALUATE ROW("latest", MAX('projects'[created_at]))
Sum / average of a measure column (scalar):
    EVALUATE ROW("total", SUM('SalesDetails_2024'[NetAmount]))
Group + aggregate (the workhorse — one row per group):
    EVALUATE
    SUMMARIZECOLUMNS(
        'projects'[project_status],
        "cnt", COUNTROWS('projects')
    )
Filter to a subset, then return rows (row-level detail is allowed here):
    EVALUATE FILTER('projects', 'projects'[project_status] = "Off Track")
Top N groups by an aggregate:
    EVALUATE
    TOPN(10, SUMMARIZECOLUMNS('projects'[project_sector], "cnt", COUNTROWS('projects')), [cnt], DESC)

### Always aggregate AT THE SOURCE
Push counting / summing / grouping / filtering INTO the DAX query. Do NOT pull every
row into pandas to count or sum — that is slow (Power BI's engine is 40-84s per query)
and wasteful. Return the smallest result that answers the question.

### If a query FAILS with "single value ... cannot be determined"
The named column is many-valued in a scalar context. FIX = wrap THAT column in an
aggregation (MAX/MIN/SUM/COUNT/DISTINCTCOUNT) or move it into SUMMARIZECOLUMNS as a
group key. DO NOT drop the column. DO NOT return an empty DataFrame. Re-run the fixed query.

### CRITICAL — table naming inside DAX (the #1 "Cannot find table" cause)
The schema lists each table as `Dataset/Table` (e.g. `Open Project Tracking/projects`).
That `Dataset/` prefix is a DISPLAY label — DAX has NO dataset qualifier. Inside the DAX
query you MUST use ONLY the bare table name, single-quoted:
  - RIGHT: `EVALUATE 'projects'`  /  `'projects'[On Risk]`
  - WRONG: `EVALUATE 'Open Project Tracking/projects'`  (400 "Cannot find table")
Pass the full `Dataset/Table` name as the 2nd argument to execute_query; use the BARE
name in the DAX text. Never put a `/` inside a DAX table reference.

### Prefer MEASURES over raw columns
If the model exposes a measure that answers the question (see the MEASURES list in the
schema), reference it directly — `EVALUATE ROW("v", [Measure Name])` — instead of
re-aggregating raw columns. Measures already contain the correct aggregation and are the
safest, fastest surface. Only aggregate raw columns when no measure fits.

### Joining across tables — use RELATIONSHIPS, never a blind cross join
Two tables can only be combined along a defined relationship (see the RELATIONSHIPS list
in the schema: from-table[col] -> to-table[col]). To answer across related tables use ONE
of: SUMMARIZECOLUMNS with a measure (cross-table filtering flows through the measure via
the relationship), or RELATED('OtherTable'[col]) to pull an attribute along an active
relationship. NEVER build a result from two tables that have NO relationship between them —
that produces a cartesian explosion (every row × every row) and a wrong answer. If the
tables you need are not related, say so rather than cross-joining.
"""

    # ----------------------------
    # Internal helpers
    # ----------------------------

    def _build_headers(self) -> Dict[str, str]:
        if not self._access_token:
            raise RuntimeError("Not authenticated")
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }


# Compatibility alias for dynamic resolver expecting 'PowerbiClient'
PowerbiClient = PowerBIClient
