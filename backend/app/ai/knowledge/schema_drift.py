"""Schema-drift detection (read-only, no persistence).

Compares the LIVE engine schema (``DataSource.get_client().get_schemas()`` →
Table objects with ``.name`` + ``.columns[].name``) against the STORED schema
(active ``DataSourceTable`` rows + their ``columns[]``). Reports tables/columns
that appeared live but aren't stored ("added") and stored ones that vanished
from the live engine ("removed").

Pure helper — does NOT touch the DB and never raises (fail-soft → {ok:False}).
Name comparison uses the same alnum-lower normalization the profiler uses so
hidden/cosmetic characters don't show up as false drift.
"""

from typing import Callable, List


def _live_schema_map(client, norm: Callable[[str], str]) -> dict:
    """{normalized_table_name: (display_name, {normalized_col: display_col})}."""
    out = {}
    try:
        schemas = client.get_schemas() or []
    except Exception:
        schemas = []
    for t in schemas:
        try:
            tname = str(getattr(t, "name", "") or "")
            if not tname:
                continue
            cols = {}
            for c in getattr(t, "columns", []) or []:
                cname = str(getattr(c, "name", "") or "")
                if cname:
                    cols[norm(cname)] = cname
            out[norm(tname)] = (tname, cols)
        except Exception:
            continue
    return out


def _stored_schema_map(stored_tables: List, norm: Callable[[str], str]) -> dict:
    """{normalized_table_name: (display_name, {normalized_col: display_col})}."""
    out = {}
    for t in stored_tables or []:
        try:
            tname = str(getattr(t, "name", "") or "")
            if not tname:
                continue
            cols = {}
            raw = getattr(t, "columns", None)
            if isinstance(raw, list):
                for entry in raw:
                    if not isinstance(entry, dict):
                        continue
                    cname = str(entry.get("name") or "")
                    if cname:
                        cols[norm(cname)] = cname
            out[norm(tname)] = (tname, cols)
        except Exception:
            continue
    return out


def compute_schema_drift(client, stored_tables: List, norm: Callable[[str], str]) -> dict:
    """Diff live vs stored schema. Never raises.

    Returns:
      {ok, drift:{tables_added, tables_removed, columns_added, columns_removed},
       has_drift}
    or {ok:False, error} on a fatal failure.
    """
    try:
        live = _live_schema_map(client, norm)
        stored = _stored_schema_map(stored_tables, norm)

        live_keys = set(live.keys())
        stored_keys = set(stored.keys())

        tables_added = sorted(live[k][0] for k in (live_keys - stored_keys))
        tables_removed = sorted(stored[k][0] for k in (stored_keys - live_keys))

        columns_added = []
        columns_removed = []
        # Only diff columns for tables present on BOTH sides — a whole added/
        # removed table is already reported at the table level.
        for k in (live_keys & stored_keys):
            live_name, live_cols = live[k]
            _stored_name, stored_cols = stored[k]
            lc = set(live_cols.keys())
            sc = set(stored_cols.keys())
            for ck in sorted(lc - sc):
                columns_added.append({"table": live_name, "column": live_cols[ck]})
            for ck in sorted(sc - lc):
                columns_removed.append({"table": live_name, "column": stored_cols[ck]})

        has_drift = bool(tables_added or tables_removed or columns_added or columns_removed)
        return {
            "ok": True,
            "drift": {
                "tables_added": tables_added,
                "tables_removed": tables_removed,
                "columns_added": columns_added,
                "columns_removed": columns_removed,
            },
            "has_drift": has_drift,
        }
    except Exception as e:  # noqa: BLE001 — fail-soft, never 500
        return {"ok": False, "error": f"schema-drift computation failed: {e}"}
