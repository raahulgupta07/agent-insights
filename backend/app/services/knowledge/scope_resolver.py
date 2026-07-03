"""scope_resolver — map any agent / data source to the SCOPE KEYS that gate
sharing of learned knowledge.

The scope key is the crux of leak-safe reuse: two agents share a learning ONLY
if they resolve to the same (scope_kind, scope_key). Because a Power BI
semantic-model GUID is identical only for users with the same access, sharing
by that key is safe by construction — no separate ACL table needed. Retrieval
always intersects with the *viewer's own* resolved scopes (see P3), so a user
never receives knowledge for a scope they don't hold.

Scope kinds:
  model   — Power BI / Fabric semantic model (ConnectionTable.metadata_json.powerbi.datasetId)
  schema  — a relational schema signature (source type + sorted table names)
  file    — an uploaded file's shape signature (table + sorted column names)
  user    — PRIVATE tier (scope_key = user_id); never shared across users

All functions are pure + fail-soft: bad/missing metadata degrades to fewer
scopes, never raises. Nothing here reads the DB — pass already-loaded ORM rows
(or plain dicts with the same attributes).
"""
from __future__ import annotations

import hashlib
from typing import Any, Iterable


def stable_hash(*parts: Any) -> str:
    """Deterministic short sha256 over the given parts (order-sensitive).

    Shared by the singularize key (P2) and the sanitizer (P1). None/empty parts
    are coerced to '' so a hash is always produced.
    """
    joined = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8", "replace")).hexdigest()


def _meta(table: Any) -> dict:
    m = getattr(table, "metadata_json", None)
    if m is None and isinstance(table, dict):
        m = table.get("metadata_json")
    return m if isinstance(m, dict) else {}


def _table_name(table: Any) -> str:
    n = getattr(table, "name", None)
    if n is None and isinstance(table, dict):
        n = table.get("name")
    return str(n or "")


def model_scope_keys(connection_tables: Iterable[Any]) -> list[str]:
    """Distinct Power BI/Fabric semantic-model GUIDs across the given tables."""
    keys: set[str] = set()
    for t in connection_tables or []:
        pbi = _meta(t).get("powerbi") if isinstance(_meta(t).get("powerbi"), dict) else None
        if pbi:
            ds_id = pbi.get("datasetId") or pbi.get("dataset_id")
            if ds_id:
                keys.add(str(ds_id))
    return sorted(keys)


def schema_signature(source_type: str | None, table_names: Iterable[str]) -> str:
    """Stable signature for a relational schema = type + sorted table names.

    Same set of tables under the same connector type -> same signature, so two
    users pointed at the same warehouse schema share learnings; a different
    table set (different access) does not.
    """
    names = sorted({str(n).strip().lower() for n in table_names if str(n).strip()})
    return "schema:" + stable_hash(str(source_type or "").lower(), *names)


def file_signature(table_name: str, column_names: Iterable[str]) -> str:
    """Stable signature for one uploaded file's shape = table + sorted columns."""
    cols = sorted({str(c).strip().lower() for c in column_names if str(c).strip()})
    return "file:" + stable_hash(str(table_name or "").strip().lower(), *cols)


def _columns(table: Any) -> list[str]:
    cols = getattr(table, "columns", None)
    if cols is None and isinstance(table, dict):
        cols = table.get("columns")
    out: list[str] = []
    for c in cols or []:
        if isinstance(c, dict):
            out.append(str(c.get("name") or ""))
        else:
            out.append(str(getattr(c, "name", "") or c))
    return [c for c in out if c]


def private_scope(user_id: str) -> dict:
    """The PRIVATE tier for a personal agent / own scratchpad-grade learning."""
    return {"scope_kind": "user", "scope_key": str(user_id)}


def is_private(scope: dict) -> bool:
    return (scope or {}).get("scope_kind") == "user"


def resolve_agent_scopes(
    data_source: Any,
    connection_tables: Iterable[Any] | None = None,
) -> list[dict]:
    """Resolve the SHARED scopes an agent (data source) contributes to / reads.

    Priority:
      1. Any Power BI/Fabric semantic models present -> one 'model' scope each
         (the most precise, access-identical key).
      2. Otherwise a single 'schema' scope over the source's table names.
      3. File/upload sources with no model metadata also fall to per-file 'file'
         scopes (each upload shape is its own scope).

    Returns a de-duplicated list of {scope_kind, scope_key}. Never raises.
    """
    tables = list(connection_tables or [])
    scopes: list[dict] = []
    seen: set[tuple] = set()

    def add(kind: str, key: str) -> None:
        if not key:
            return
        sig = (kind, key)
        if sig not in seen:
            seen.add(sig)
            scopes.append({"scope_kind": kind, "scope_key": key})

    # 1. semantic models (Power BI / Fabric)
    for key in model_scope_keys(tables):
        add("model", key)
    if scopes:
        return scopes

    src_type = getattr(data_source, "type", None)
    if src_type is None and isinstance(data_source, dict):
        src_type = data_source.get("type")

    # 3. file-shaped sources -> per-file signature
    is_file_like = str(src_type or "").lower() in {"file", "upload", "duckdb", "excel", "csv"}
    if is_file_like and tables:
        for t in tables:
            add("file", file_signature(_table_name(t), _columns(t)))
        if scopes:
            return scopes

    # 2. relational schema signature (fallback for any DB/connector)
    names = [_table_name(t) for t in tables]
    if names:
        add("schema", schema_signature(src_type, names))

    return scopes
