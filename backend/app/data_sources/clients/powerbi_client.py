from app.data_sources.clients.base import DataSourceClient
from app.ai.prompt_formatters import Table, TableColumn, ForeignKey, ServiceFormatter
from typing import List, Dict, Optional, Tuple
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

        # Phase 4: Try DAX query on the first dataset to verify query access
        first_ds = ds_list[0]
        first_ds_id = first_ds["id"]
        first_ds_name = first_ds.get("name") or first_ds_id
        try:
            url = f"{self.BASE_URL}/groups/{first_ws_id}/datasets/{first_ds_id}/executeQueries"
            body = {
                "queries": [{"query": "EVALUATE ROW(\"test\", 1)"}],
                "serializerSettings": {"includeNulls": True},
            }
            resp = self._http.post(url, json=body, headers=headers, timeout=30)
            if resp.status_code >= 300:
                # Extract the detail message from Power BI's error response
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

                if not detail_msg:
                    detail_msg = f"HTTP {resp.status_code} on dataset '{first_ds_name}'. Ensure the service principal is added as a Member or Contributor in your Power BI workspaces, and that the workspace is on Premium/PPU/Embedded capacity."

                return {
                    "success": False,
                    "message": f"Connected but cannot query datasets: {detail_msg}",
                    "connectivity": True,
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connected but cannot query dataset '{first_ds_name}': {e}",
                "connectivity": True,
            }

        return {
            "success": True,
            "message": f"Connected to Power BI. Found {len(workspaces)}+ workspace(s), {len(ds_list)} dataset(s) in first workspace.",
            "workspaces": len(workspaces),
            "datasets": len(ds_list),
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
                _sig = f"{self.tenant_id or ''}|{workspace_id or ''}|{dataset_id}|{max_rows}|{query}"
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
            raise RuntimeError(f"DAX query failed: HTTP {resp.status_code} {resp.text}")

        payload = resp.json() or {}
        results = payload.get("results") or []

        if not results:
            return pd.DataFrame()

        first_result = results[0]
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
df = db_clients['powerbi'].execute_query(
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
