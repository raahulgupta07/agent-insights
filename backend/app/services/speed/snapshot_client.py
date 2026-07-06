"""
SnapshotClient — query a Power BI / Fabric agent's LOCAL DuckDB snapshot with SQL
=================================================================================

A drop-in :class:`DataSourceClient` that the speed layer swaps in for a live BI
source. When active, the agent stops fanning slow live DAX over HTTP and instead
sees the source as a set of ordinary SQL tables living in a local DuckDB snapshot
(see ``app/services/speed/bi_snapshot.py``). It:

  * presents the snapshot as SQL tables (``get_schemas`` in the SAME shape the SQL
    clients return — a ``list[Table]`` from ``app.ai.prompt_formatters``), so the
    agent's schema renderer + executor accept it unchanged;
  * instructs the code-gen path to write standard **SQL** (DuckDB dialect), not
    DAX (``prompt_schema``);
  * runs that SQL against the local snapshot via ``bi_snapshot.query_snapshot``
    (``execute_query`` → pandas DataFrame). Read-only is enforced inside
    ``query_snapshot``.

Because it implements the same interface, ``db_clients[key].execute_query(...)``
"just works" — but hits DuckDB instead of Microsoft's live engine.
"""

from __future__ import annotations

from typing import Any, List, Optional

import pandas as pd

from app.data_sources.clients.base import Capability, DataSourceClient
from app.ai.prompt_formatters import Table, TableColumn, TableFormatter
from app.services.speed import bi_snapshot


class SnapshotClient(DataSourceClient):
    """Data-source client backed by a local DuckDB snapshot of a BI model."""

    capabilities: set = {Capability.QUERY}

    def __init__(
        self,
        data_source_id: str,
        source_name: str,
        schema: Optional[list] = None,
        **kwargs,
    ) -> None:
        # Accept/ignore any extra kwargs so a caller passing connector-specific
        # params can't fail on construction.
        super().__init__()
        self.data_source_id = str(data_source_id)
        self.source_name = source_name or "snapshot"
        # Optional pre-supplied schema (list of table dicts or Table objects in
        # the same shape get_schemas returns). Kept raw; normalized lazily.
        self.schema = schema
        # The caller sets this post-construction on the base contract.
        self._bow_user_id = kwargs.get("_bow_user_id")

    # --- SQL execution ------------------------------------------------------

    def execute_query(self, *args, **kwargs) -> pd.DataFrame:
        """Run standard SQL against the local DuckDB snapshot → DataFrame.

        Pulls the SQL string from kwargs (``code`` → ``query`` → ``sql`` →
        ``dax``, first non-empty wins), or the first non-empty positional arg.
        A DAX / non-read-only statement is surfaced as a clear ValueError (with
        the available table names) so the agent can self-correct to SQL. The
        read-only guard + actual execution live inside ``query_snapshot``.
        """
        sql = None
        for key in ("code", "query", "sql", "dax"):
            val = kwargs.get(key)
            if val is not None and str(val).strip():
                sql = str(val)
                break
        if sql is None:
            for arg in args:
                if arg is not None and str(arg).strip():
                    sql = str(arg)
                    break

        if sql is None or not sql.strip():
            raise ValueError(
                "No SQL provided. This data source is a local DuckDB snapshot — "
                "call execute_query with a SELECT statement. "
                + self._available_tables_hint()
            )

        # Reject DAX / write statements up-front with a clear, self-correctable
        # message rather than silently returning an empty frame.
        if not self._looks_read_only(sql):
            raise ValueError(
                "This data source is a LOCAL DuckDB SNAPSHOT and only accepts "
                "read-only SQL (SELECT / WITH). It does NOT understand DAX / "
                "EVALUATE. Rewrite your query as standard SQL. "
                + self._available_tables_hint()
            )

        return bi_snapshot.query_snapshot(self.data_source_id, sql)

    # --- schema -------------------------------------------------------------

    def get_schemas(self) -> List[Table]:
        """Return the snapshot's tables as a ``list[Table]`` (SQL-client shape).

        Uses the caller-supplied schema when present (normalized), else
        introspects the DuckDB snapshot store. Table names are the DuckDB
        snapshot keys (what the agent must actually query).
        """
        if self.schema:
            return self._normalize_supplied_schema(self.schema)
        return self._introspect_schema()

    def get_schema(self, table_name: str) -> Optional[Table]:
        """Return the single Table matching ``table_name`` (by snapshot key,
        display name, or source name), or None."""
        target_key = bi_snapshot.snapshot_key(self.data_source_id, table_name)
        for tbl in self.get_schemas():
            meta = tbl.metadata_json or {}
            if tbl.name == table_name:
                return tbl
            if meta.get("snapshot_table") == target_key or tbl.name == target_key:
                return tbl
            if meta.get("source_table") == table_name:
                return tbl
        return None

    def prompt_schema(self) -> str:
        """Code-gen instructions that make the agent write SQL, not DAX."""
        tables = self.get_schemas()
        names = [t.name for t in tables]
        example_table = names[0] if names else "<table>"
        header = (
            f"This data source is a LOCAL SNAPSHOT of a Power BI / Fabric model, "
            f"stored in DuckDB. Query it with standard **SQL** (DuckDB dialect), "
            f"e.g. db_clients[<your data source name>].execute_query("
            f'"SELECT * FROM {example_table} LIMIT 100"). '
            f"Do NOT use DAX / EVALUATE — that will fail. "
            f"Available tables: {', '.join(names) if names else '(none snapshotted yet)'}. "
            f"Use the exact table names shown below.\n\n"
        )
        # Reuse the SQL client's table/column formatting for the body.
        return header + TableFormatter(tables).table_str

    # --- connection / meta --------------------------------------------------

    @property
    def description(self) -> str:
        return "Local DuckDB snapshot of a Power BI/Fabric model (queried with SQL)."

    def test_connection(self) -> bool:
        """True when a non-empty snapshot store exists for this source. Never raises."""
        try:
            meta = bi_snapshot.snapshot_meta(self.data_source_id)
            return bool(meta.get("count"))
        except Exception:
            return False

    # --- internals ----------------------------------------------------------

    def _looks_read_only(self, sql: str) -> bool:
        """Delegate to bi_snapshot's read-only guard; permissive fallback."""
        guard = getattr(bi_snapshot, "_is_read_only_sql", None)
        if callable(guard):
            try:
                return bool(guard(sql))
            except Exception:
                pass
        first = (sql or "").strip().lstrip("(").split(None, 1)
        return bool(first) and first[0].lower() in ("select", "with", "table", "from")

    def _available_tables_hint(self) -> str:
        try:
            names = [t.name for t in self.get_schemas()]
        except Exception:
            names = []
        if not names:
            return "No tables are snapshotted for this source yet."
        return "Available tables: " + ", ".join(names) + "."

    def _normalize_supplied_schema(self, schema: list) -> List[Table]:
        """Coerce a caller-supplied schema (dicts or Table objects) into
        ``list[Table]``, remapping each table name to its DuckDB snapshot key
        (the actually-queryable identifier)."""
        out: List[Table] = []
        for item in schema or []:
            try:
                if isinstance(item, Table):
                    src_name = item.name
                    cols = item.columns or []
                    columns = [
                        TableColumn(
                            name=c.name,
                            dtype=getattr(c, "dtype", None),
                            description=getattr(c, "description", None),
                            metadata=getattr(c, "metadata", None),
                        )
                        for c in cols
                    ]
                    desc = item.description
                else:
                    src_name = item.get("name") or item.get("table") or item.get("table_name")
                    if not src_name:
                        continue
                    columns = []
                    for c in item.get("columns") or []:
                        if isinstance(c, dict):
                            cname = c.get("name") or c.get("column_name")
                            if not cname:
                                continue
                            columns.append(
                                TableColumn(
                                    name=cname,
                                    dtype=c.get("dtype") or c.get("type") or c.get("data_type"),
                                    description=c.get("description"),
                                    metadata=c.get("metadata"),
                                )
                            )
                        else:
                            cname = getattr(c, "name", None)
                            if cname:
                                columns.append(
                                    TableColumn(name=cname, dtype=getattr(c, "dtype", None))
                                )
                    desc = item.get("description")

                snap_key = bi_snapshot.snapshot_key(self.data_source_id, src_name)
                out.append(
                    Table(
                        name=snap_key,
                        description=desc,
                        columns=columns,
                        pks=[],
                        fks=[],
                        metadata_json={"snapshot_table": snap_key, "source_table": src_name},
                    )
                )
            except Exception:
                continue
        return out

    def _introspect_schema(self) -> List[Table]:
        """Build the table list by reading the DuckDB snapshot store: table keys
        + row counts from ``snapshot_meta``, columns from ``information_schema``.
        Fail-soft → empty list."""
        try:
            meta = bi_snapshot.snapshot_meta(self.data_source_id)
        except Exception:
            return []
        tables_meta = meta.get("tables") or {}
        if not tables_meta:
            return []

        # Map DuckDB table key -> original BI table name.
        key_to_name = {}
        for src_name, info in tables_meta.items():
            key = (info or {}).get("table_key") or bi_snapshot.snapshot_key(
                self.data_source_id, src_name
            )
            key_to_name[key] = src_name

        out: List[Table] = []
        for key, src_name in key_to_name.items():
            columns: List[TableColumn] = []
            try:
                safe_key = key.replace("'", "''")
                col_df = bi_snapshot.query_snapshot(
                    self.data_source_id,
                    "SELECT column_name, data_type FROM information_schema.columns "
                    f"WHERE table_name = '{safe_key}' ORDER BY ordinal_position",
                )
                if col_df is not None and len(col_df) > 0:
                    for _, row in col_df.iterrows():
                        columns.append(
                            TableColumn(
                                name=str(row.get("column_name")),
                                dtype=(str(row.get("data_type")) if row.get("data_type") is not None else None),
                            )
                        )
            except Exception:
                columns = []
            out.append(
                Table(
                    name=key,
                    description=None,
                    columns=columns,
                    pks=[],
                    fks=[],
                    metadata_json={"snapshot_table": key, "source_table": src_name},
                )
            )
        return out
