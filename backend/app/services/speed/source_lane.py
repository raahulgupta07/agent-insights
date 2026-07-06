"""Speed-lane classifier for data sources — the foundation of the adaptive speed layer.

Every data source is tagged into exactly ONE of three SPEED LANES that describe how
fast we can get bytes back and therefore how a later routing/caching layer should treat it.
This module is PURE: no DB calls, no I/O, stdlib + typing only. It never raises.

The three lanes (why they exist):

  LANE_LOCAL ("local")
    Data already lives in OUR OWN Postgres warehouse (or an uploaded/materialized file).
    Fastest possible path — a plain local SQL read, no external hop. Covers uploaded
    spreadsheets/CSV/Excel and file connectors whose bytes we download+materialize
    (SharePoint / OneDrive / Google Drive files → DuckDB/pandas tables).

  LANE_WAREHOUSE ("warehouse")
    A live SQL database/engine we query over the network but WITH pushdown — filters,
    joins and aggregation run on the remote engine, so it's live but efficient. Covers
    every real SQL warehouse/OLAP store (Postgres, Snowflake, BigQuery, MSSQL, MySQL,
    Redshift, Databricks, Trino/Presto, Druid, Vertica, Oracle, ClickHouse, Sisense, …).
    This is the SAFE DEFAULT for anything unknown: assume live pushdown, never wrongly
    assume the data is sitting local.

  LANE_BI ("bi")
    A semantic / BI model queried live over HTTP with a heavy, slow dialect (DAX / MDX /
    logical SQL) — Power BI and Microsoft Fabric especially. These are the slowest and the
    prime candidates for the speed layer to SNAPSHOT rather than hit live every time.

Precedence when a source has multiple connections: BI > WAREHOUSE > LOCAL
(if ANY connection is BI the whole source is BI; else if ANY is WAREHOUSE it's WAREHOUSE;
else LOCAL). Rationale: the slowest/most-fragile lane dominates the routing decision.

The type→lane mapping is DATA-DRIVEN off substring groups so a brand-new connector
self-classifies (e.g. a future 'powerbi_embedded' → BI via the 'powerbi' group; a future
'yellowbrick_sql' → WAREHOUSE via the 'sql' group) instead of relying on a brittle,
exhaustive literal list. Known literals from this repo's connector registry are still
listed explicitly for correctness.
"""

from __future__ import annotations

from typing import Any, Optional

# ── Lane constants ──────────────────────────────────────────────────────────
LANE_LOCAL = "local"
LANE_WAREHOUSE = "warehouse"
LANE_BI = "bi"


# ── Explicit known literals (from app/schemas/data_source_registry.py) ──────
# These are the exact `connection.type` strings used in the repo, normalized to
# lower-case. They pin the correct lane even where a substring rule might be
# ambiguous.
_LOCAL_LITERALS = {
    # Uploaded / file-backed — bytes materialized into our own warehouse/DuckDB.
    "spreadsheet", "csv", "excel", "file", "upload",
    # Document/file connectors: we DOWNLOAD the files and read them via pandas
    # (graph_drive_client / google_drive_client surface files as local tables).
    # They are NOT queried live with pushdown → treat as LOCAL. If a future
    # variant becomes a live-queried semantic model, move it to _BI_LITERALS.
    "sharepoint", "onedrive", "google_drive",
    # Local single-file engines.
    "sqlite", "duckdb", "qvd",
}

_BI_LITERALS = {
    # Semantic/BI models queried live over HTTP with DAX/MDX/logical-SQL.
    "powerbi", "powerbi_user", "powerbi_report_server",
    "ms_fabric", "ms_fabric_user",
    "qlik_sense", "oracle_bi", "tableau",
}

_WAREHOUSE_LITERALS = {
    # Live SQL databases / OLAP engines with pushdown.
    "postgresql", "mysql", "mariadb", "mssql", "oracledb", "sybase", "teradata",
    "snowflake", "bigquery", "aws_redshift", "aws_athena", "databricks_sql",
    "spark_connect", "trino", "presto", "clickhouse", "pinot", "druid",
    "vertica", "azure_data_explorer", "sisense", "timbr", "timbr_a2a",
    "salesforce", "netsuite", "mongodb", "posthog", "aws_cost",
}

# ── Substring groups (so NEW connectors self-classify) ──────────────────────
# Checked in precedence order BI → LOCAL → WAREHOUSE. Order matters: a token like
# "fabric" must resolve to BI before any generic fallback.
_BI_SUBSTRINGS = (
    "powerbi", "power_bi", "fabric", "qlik", "tableau", "cognos", "oracle_bi",
    "obiee", "looker", "mdx", "dax", "semantic_model",
)
_LOCAL_SUBSTRINGS = (
    "spreadsheet", "excel", "csv", "upload", "file", "sqlite", "duckdb",
    "sharepoint", "onedrive", "google_drive", "gdrive", "qvd", "parquet",
)
_WAREHOUSE_SUBSTRINGS = (
    "sql", "postgres", "mysql", "maria", "oracle", "snowflake", "bigquery",
    "redshift", "athena", "databricks", "spark", "trino", "presto",
    "clickhouse", "pinot", "druid", "vertica", "teradata", "sybase",
    "kusto", "warehouse", "db", "mongo",
)


def classify_connection_type(conn_type: Optional[str]) -> str:
    """Classify a single connection.type string into a speed lane.

    Returns one of LANE_LOCAL / LANE_WAREHOUSE / LANE_BI.

    Order of resolution:
      1. exact known literal (most precise)
      2. substring groups BI → LOCAL → WAREHOUSE (lets new connectors self-classify)
      3. unknown → LANE_WAREHOUSE (safest: assume live pushdown, never assume local)
    """
    if not conn_type:
        # No type info → safest default is live pushdown, not local.
        return LANE_WAREHOUSE

    t = conn_type.strip().lower()
    if not t:
        return LANE_WAREHOUSE

    # 1. Exact known literals.
    if t in _BI_LITERALS:
        return LANE_BI
    if t in _LOCAL_LITERALS:
        return LANE_LOCAL
    if t in _WAREHOUSE_LITERALS:
        return LANE_WAREHOUSE

    # 2. Substring groups (BI first — 'fabric'/'powerbi' must win before generics).
    if any(s in t for s in _BI_SUBSTRINGS):
        return LANE_BI
    if any(s in t for s in _LOCAL_SUBSTRINGS):
        return LANE_LOCAL
    if any(s in t for s in _WAREHOUSE_SUBSTRINGS):
        return LANE_WAREHOUSE

    # 3. Unknown type → default WAREHOUSE (treat as live pushdown, never wrongly local).
    return LANE_WAREHOUSE


def _connection_types(data_source: Any) -> list:
    """Best-effort pull of connection.type strings off a data_source. Never raises."""
    types: list = []
    connections = getattr(data_source, "connections", None) or []
    for conn in connections:
        try:
            types.append(getattr(conn, "type", None))
        except Exception:
            continue
    return types


def classify_data_source(data_source: Any) -> str:
    """Classify a data source into a speed lane from its connections.

    Precedence: BI > WAREHOUSE > LOCAL. If ANY connection is BI the source is BI;
    else if ANY is WAREHOUSE it's WAREHOUSE; else LOCAL.

    Fail-soft: no connections / any error → LANE_LOCAL (uploaded default). Never raises.
    """
    try:
        lanes = [classify_connection_type(ct) for ct in _connection_types(data_source)]
        if not lanes:
            return LANE_LOCAL
        if LANE_BI in lanes:
            return LANE_BI
        if LANE_WAREHOUSE in lanes:
            return LANE_WAREHOUSE
        return LANE_LOCAL
    except Exception:
        # Never let classification break a caller.
        return LANE_LOCAL


if __name__ == "__main__":
    # Self-test — pure, deterministic, no deps.
    checks = [
        ("powerbi_user", LANE_BI),
        ("ms_fabric", LANE_BI),
        ("powerbi", LANE_BI),
        ("ms_fabric_user", LANE_BI),
        ("postgresql", LANE_WAREHOUSE),
        ("snowflake", LANE_WAREHOUSE),
        ("MSSQL", LANE_WAREHOUSE),          # mixed-case literal → normalized
        ("spreadsheet", LANE_LOCAL),
        ("csv", LANE_LOCAL),
        ("sharepoint", LANE_LOCAL),
        ("onedrive", LANE_LOCAL),
        ("totally_unknown", LANE_WAREHOUSE),
        (None, LANE_WAREHOUSE),
        ("", LANE_WAREHOUSE),
        ("powerbi_embedded_v2", LANE_BI),   # future connector via substring group
        ("yellowbrick_sql", LANE_WAREHOUSE),
    ]

    ok = True
    for conn_type, expected in checks:
        got = classify_connection_type(conn_type)
        status = "PASS" if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"{status}: classify_connection_type({conn_type!r}) = {got!r} (expected {expected!r})")

    # Fake data_source precedence checks.
    class _C:
        def __init__(self, t):
            self.type = t

    class _DS:
        def __init__(self, conns):
            self.connections = conns

    ds_checks = [
        (_DS([_C("postgresql"), _C("powerbi")]), LANE_BI),        # BI dominates
        (_DS([_C("postgresql"), _C("spreadsheet")]), LANE_WAREHOUSE),  # WH over LOCAL
        (_DS([_C("spreadsheet"), _C("csv")]), LANE_LOCAL),
        (_DS([]), LANE_LOCAL),                                     # no connections
        (_DS(None), LANE_LOCAL),                                   # fail-soft
    ]
    for ds, expected in ds_checks:
        got = classify_data_source(ds)
        status = "PASS" if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"{status}: classify_data_source({[getattr(c,'type',None) for c in (ds.connections or [])]}) = {got!r} (expected {expected!r})")

    print("\nALL PASS" if ok else "\nSOME FAILED")
