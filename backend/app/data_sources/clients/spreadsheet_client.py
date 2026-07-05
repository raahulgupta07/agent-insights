from __future__ import annotations

"""Spreadsheet data-source client.

Loads a single uploaded local file (.xlsx / .xls / .csv) into an in-memory
DuckDB connection so the agent can query it with SQL exactly like any other
warehouse connector. Each Excel sheet (or the single CSV) becomes a DuckDB
table whose name is a sanitized version of the sheet name / file stem.

The client is credential-less: everything it needs lives in the connection
`config` (`path`, optional `sheet_names`). It reuses the DuckDB base machinery
for `get_tables` / `get_schema` / `prompt_schema` by loading the spreadsheet
into real tables inside a fresh in-memory connection on each `connect()`.
"""

import logging
import os
import re
from contextlib import contextmanager
from typing import Generator, List, Optional

import duckdb
import pandas as pd

from app.ai.prompt_formatters import Table, TableColumn, TableFormatter
from app.data_sources.clients.base import DataSourceClient

logger = logging.getLogger(__name__)


_CSV_EXTS = {".csv", ".tsv", ".txt"}
_XLSX_EXTS = {".xlsx", ".xlsm"}
_XLS_EXTS = {".xls"}


class SpreadsheetClient(DataSourceClient):
    """Query an uploaded Excel/CSV file via an in-memory DuckDB engine."""

    def __init__(
        self,
        path: str | None = None,
        sheet_names: Optional[List[str]] = None,
        file_id: str | None = None,
        # Task 5 (HYBRID_MERGE_SAME_SCHEMA): extra same-schema files merged into
        # this one source. Each entry: {"path": str, "label": str}. The primary
        # `path` is loaded first; merged paths are UNION-appended with a
        # `_source_label` provenance column. Forwarded from connection config.
        merged_paths: Optional[List[dict]] = None,
        # Tolerate any extra config/cred keys the registry/constructor merge
        # may forward (this client is credential-less).
        **_kwargs,
    ):
        self.path = path
        # Normalize sheet_names to a clean list[str] | None.
        if isinstance(sheet_names, str):
            sheet_names = [s.strip() for s in sheet_names.split(",") if s.strip()]
        self.sheet_names: Optional[List[str]] = (
            [str(s) for s in sheet_names] if sheet_names else None
        )
        self.file_id = file_id
        self.merged_paths: List[dict] = list(merged_paths or [])
        # Phase 1 (HYBRID_INGEST_RECONCILE): populated by _load_frames with the
        # per-file ingest outcome when the flag is on; None otherwise. Read by
        # the from-file route's reconcile gate (Phase 2+).
        self.last_ingest_report: Optional[dict] = None

    # ── helpers ──────────────────────────────────────────────────────────

    def _resolve_path(self, raw_path: str | None = None) -> str:
        """Resolve the on-disk path of an uploaded file.

        Uploaded files are stored flat under <cwd>/uploads/files/<basename>.
        We rebuild the path from that trusted root + the sanitized basename so
        a tampered DB value can never escape the uploads directory (matches the
        guard in routes/file.py:get_file_content).
        """
        raw_path = raw_path if raw_path is not None else self.path
        if not raw_path:
            raise RuntimeError("Spreadsheet client has no file path configured")
        # If the stored path already points at an existing absolute file, trust it.
        if os.path.isabs(raw_path) and os.path.exists(raw_path):
            return raw_path
        base = os.path.basename(raw_path)
        candidate = os.path.join(os.getcwd(), "uploads", "files", base)
        if os.path.exists(candidate):
            return candidate
        # Fall back to cwd-relative (path is e.g. "uploads/files/<name>").
        rel = os.path.join(os.getcwd(), raw_path)
        if os.path.exists(rel):
            return rel
        raise RuntimeError(f"Spreadsheet file not found: {raw_path}")

    @staticmethod
    def _safe_table_name(base: str, used: set[str]) -> str:
        name = re.sub(r"[^a-zA-Z0-9_]+", "_", str(base)).strip("_").lower() or "sheet"
        # DuckDB identifiers must not start with a digit when unquoted.
        if name[0].isdigit():
            name = f"t_{name}"
        original = name
        i = 1
        while name in used:
            i += 1
            name = f"{original}_{i}"
        used.add(name)
        return name

    @staticmethod
    def _maybe_fix_header(df: "pd.DataFrame", path: str, sheet, engine: str | None) -> "pd.DataFrame":
        """Task 6 (HYBRID_SMART_HEADER): if the default read produced too many
        ``Unnamed: N`` columns, re-read raw + detect the real header row.

        Fail-soft: returns ``df`` unchanged on any error or when the flag is off.
        """
        try:
            from app.settings.hybrid_flags import flags

            if not flags.SMART_HEADER:
                return df
            from app.services.ingest import smart_upload

            if smart_upload.unnamed_fraction(df.columns) <= 0.40:
                return df
            if sheet is None:  # CSV
                raw = pd.read_csv(path, header=None, sep=None, engine="python")
            else:
                raw = pd.read_excel(path, sheet_name=sheet, header=None, engine=engine)
            return smart_upload.reread_with_detected_header(
                df, raw, sheet_label=str(sheet if sheet is not None else os.path.basename(path))
            )
        except Exception:  # noqa: BLE001 - never break ingest on header heuristics
            return df

    def _read_one_file_robust(self, path: str, ext: str) -> "Optional[dict[str, pd.DataFrame]]":
        """Import v2 (P3, HYBRID_ROBUST_INGEST): read via the robust ingest readers
        (encoding/delimiter sniff, real-header detection, banner skip, id-safe
        numeric, bad-row skip) instead of the naive pandas read.

        Returns the {name -> DataFrame} mapping, or ``None`` to signal the caller
        should fall back to the naive reader (flag off, empty result, or error).

        Phase 4 (HYBRID_INGEST_RECONCILE): the reconcile guard's purpose is "load
        everything; never silently drop a file", and banner-header / odd-format
        files are the #1 cause of a silent drop. So the reconcile flag ALSO
        enables the robust readers here — turning the guard on makes the failing
        months actually parse instead of throwing into the merge-loop swallow.
        """
        try:
            from app.settings.hybrid_flags import flags

            if not (flags.ROBUST_INGEST or flags.INGEST_RECONCILE):
                return None
            out: dict[str, pd.DataFrame] = {}
            if ext in _CSV_EXTS:
                from app.services.ingest.csv_reader import read_csv

                df = read_csv(path)
                if df is None or df.empty:
                    return None
                out[os.path.splitext(os.path.basename(path))[0]] = df
                return out
            if ext in _XLSX_EXTS or ext in _XLS_EXTS:
                from app.services.ingest.excel_reader import read_excel

                tables = read_excel(path)
                if not tables:
                    return None
                wanted = self.sheet_names
                for t in tables:
                    sheet = str(t.get("sheet"))
                    if wanted is not None and sheet not in wanted:
                        continue
                    df = t.get("df")
                    if df is not None and not df.empty:
                        out[sheet] = df
                return out or None
        except Exception:  # noqa: BLE001 - any robust-read failure -> naive fallback
            return None
        return None

    def _read_one_file(self, raw_path: str) -> "dict[str, pd.DataFrame]":
        """Read ONE file into {sheet/stem -> DataFrame}, applying smart-header.

        Keyed by the ORIGINAL sheet/stem name (not yet table-slugged) so the
        merge step can align same-named sheets across files. Raises on an
        unreadable / unsupported file so the caller can surface a 400.
        """
        path = self._resolve_path(raw_path)
        ext = os.path.splitext(path)[1].lower()
        out: dict[str, pd.DataFrame] = {}

        # Import v2 (P3): prefer the robust readers when enabled; fall back to the
        # naive path below on None (flag off / empty / error) so behavior is
        # unchanged when the flag is off.
        robust = self._read_one_file_robust(path, ext)
        if robust:
            return robust

        if ext in _CSV_EXTS:
            sep = "\t" if ext == ".tsv" else None  # None → pandas sniffs ',' default
            df = pd.read_csv(path, sep=sep, engine="python")
            df = self._maybe_fix_header(df, path, None, None)
            stem = os.path.splitext(os.path.basename(path))[0]
            out[stem] = df
            return out

        if ext in _XLSX_EXTS or ext in _XLS_EXTS:
            engine = "openpyxl" if (ext in _XLSX_EXTS) else "xlrd"
            # sheet_name=None → all sheets as an ordered dict.
            all_sheets = pd.read_excel(path, sheet_name=None, engine=engine)
            wanted = self.sheet_names
            for sheet, df in all_sheets.items():
                if wanted is not None and str(sheet) not in wanted:
                    continue
                out[str(sheet)] = self._maybe_fix_header(df, path, sheet, engine)
            if not out and wanted is not None:
                raise RuntimeError(
                    f"None of the requested sheets {wanted} were found in the file. "
                    f"Available: {list(all_sheets.keys())}"
                )
            return out

        raise RuntimeError(f"Unsupported spreadsheet file type: {ext or '(none)'}")

    def _load_frames(self) -> "dict[str, pd.DataFrame]":
        """Read the file(s) into a mapping of {table_name: DataFrame}.

        With Task-5 merged_paths set, same-named sheets across all files are
        concatenated into one frame and stamped with a `_source_label`
        provenance column. Raises on an unreadable/unsupported primary file.
        """
        used: set[str] = set()
        primary = self._read_one_file(self.path)

        # HYBRID_ONE_TABLE_MERGE: same-schema monthly files must land in ONE
        # timeless table. Compute the flag up-front so the naming is period-free
        # even at CREATION (the first single file, when merged_paths is still
        # empty) — not only on later merges. Without this the very first month's
        # slug (`…_jan_25`) freezes as the table name forever and a later August
        # upload can't correct it.
        try:
            from app.settings.hybrid_flags import flags as _otm_flags
            one_table = bool(_otm_flags.ONE_TABLE_MERGE)
        except Exception:  # noqa: BLE001
            one_table = False

        def _timeless_name(raw: str) -> str:
            """Slug the sheet/stem, then (when one_table) drop any month/year
            token so `…_jan_25`, `…_aug_25`, `…_2025_08` all resolve to the same
            period-free table name. Falls back to the plain slug on any issue."""
            base = self._safe_table_name(raw, used)
            if not one_table:
                return base
            try:
                from app.services.ingest.post_ingest import derive_period_and_stem
                stem, _p = derive_period_and_stem(base)
                return (stem or base).strip("_") or base
            except Exception:  # noqa: BLE001
                return base

        # Fast path: no merge -> slug (period-stripped when one_table) + return.
        if not self.merged_paths:
            return {_timeless_name(name): df for name, df in primary.items()}

        from app.services.ingest.smart_upload import (
            SOURCE_LABEL_COL,
            SOURCE_PERIOD_COL,
            label_from_filename,
            period_label_from_filename,
            normalize_columns,
        )

        # Pipeline v1 (P1, HYBRID_ONE_TABLE_MERGE): same-schema files (e.g. 6
        # monthly CSVs whose filename stems differ) should stack into ONE table
        # keyed by their COLUMN SIGNATURE, not the per-file stem — so the agent
        # queries `FROM crm` instead of UNION-ALL across N stem-named tables.
        # Flag OFF -> group by stem name (exact prior behavior).

        # Tolerant signature grouping: files that are the SAME monthly template
        # apart from a stray/renamed column must stack into ONE table — matching
        # the from-file route's same-schema merge tolerance (`_same_template`).
        # Exact-hash grouping would split a trivially-drifted file into its own
        # table and re-break "one agent = one table". `pd.concat(sort=False)`
        # unions the differing columns (NaN-filling the gaps) so the extra column
        # is harmless. The primary file is processed first, so it seeds the
        # representative signature for its group.
        _sig_groups: list[tuple[str, frozenset]] = []

        def _same_template(a: frozenset, b: frozenset) -> bool:
            # identical after normalization, or differing by a small bounded
            # number of columns on each side (one added / one renamed). Rejects a
            # genuinely different schema or a narrow subset of a much wider table.
            if not a or not b:
                return False
            if a == b:
                return True
            if not (a & b):
                return False
            max_diff = max(1, round(0.10 * max(len(a), len(b))))
            return len(a - b) <= max_diff and len(b - a) <= max_diff

        def _group_key(name: str, df) -> str:
            if not one_table:
                return name
            try:
                # signature = order-independent set of data column names (ignore
                # the provenance/lineage columns we add).
                cols = [c for c in df.columns
                        if str(c) not in (SOURCE_LABEL_COL, SOURCE_PERIOD_COL)]
                sig = normalize_columns(cols)
                if not sig:
                    return name
                for gk, gsig in _sig_groups:
                    if _same_template(sig, gsig):
                        return gk
                gk = "sig:%d" % len(_sig_groups)
                _sig_groups.append((gk, sig))
                return gk
            except Exception:  # noqa: BLE001
                return name

        # canonical display name per group (period token stripped from the stem)
        group_name: dict[str, str] = {}

        def _canon(name: str) -> str:
            # Slug FIRST (raw stems carry spaces/parens like "…(Jan'25)" that the
            # period regex can't see), THEN strip the period token — so the merge
            # path derives the same timeless name as the creation fast path above.
            try:
                from app.services.ingest.post_ingest import derive_period_and_stem
                base = self._safe_table_name(str(name), set())
                stem, _p = derive_period_and_stem(base)
                return (stem or base).strip("_") or "dataset"
            except Exception:  # noqa: BLE001
                return str(name)

        # Phase 1 (HYBRID_INGEST_RECONCILE): make the merge fail-LOUD like the
        # chat-upload path. We record each file's outcome (loaded|failed + rows
        # + error) so a later reconcile gate can flip the source DEGRADED and
        # tell the agent which periods are missing — instead of a bad file being
        # silently swallowed by `except: continue`. The actual swallow still
        # happens (queries never block on one bad file); we just stop hiding it.
        try:
            from app.settings.hybrid_flags import flags as _rec_flags
            reconcile = bool(_rec_flags.INGEST_RECONCILE)
        except Exception:  # noqa: BLE001
            reconcile = False
        file_reports: list[dict] = []

        # Stamp the primary file's rows with its own provenance label (+ period
        # when one is derivable from the filename — Import v2 P1).
        primary_label = label_from_filename(self.path or "primary")
        primary_period = period_label_from_filename(self.path or "")
        merged: dict[str, list[pd.DataFrame]] = {}
        primary_rows = 0
        for name, df in primary.items():
            d = df.copy()
            d[SOURCE_LABEL_COL] = primary_label
            if primary_period:
                d[SOURCE_PERIOD_COL] = primary_period
            k = _group_key(name, df)
            group_name.setdefault(k, _canon(name) if one_table else name)
            merged.setdefault(k, []).append(d)
            primary_rows += len(df)
        if reconcile:
            file_reports.append({
                "path": self.path,
                "label": primary_label,
                "period": primary_period or None,
                "status": "loaded",
                "rows": int(primary_rows),
                "primary": True,
                "error": None,
            })

        # Append each merged file (fail-soft per file). With one_table on, same-
        # signature frames from differently-named files join the same group.
        for spec in self.merged_paths:
            mpath = spec.get("path") if isinstance(spec, dict) else spec
            mlabel = (spec.get("label") if isinstance(spec, dict) else None) or label_from_filename(mpath)
            mperiod = period_label_from_filename(mpath or "")
            try:
                appended_rows = 0
                for name, df in self._read_one_file(mpath).items():
                    d = df.copy()
                    d[SOURCE_LABEL_COL] = mlabel
                    if mperiod:
                        d[SOURCE_PERIOD_COL] = mperiod
                    k = _group_key(name, df)
                    group_name.setdefault(k, _canon(name) if one_table else name)
                    merged.setdefault(k, []).append(d)
                    appended_rows += len(df)
                if reconcile:
                    file_reports.append({
                        "path": mpath,
                        "label": mlabel,
                        "period": mperiod or None,
                        "status": "loaded",
                        "rows": int(appended_rows),
                        "primary": False,
                        "error": None,
                    })
            except Exception as e:  # noqa: BLE001
                # A bad merged file never blocks the primary upload's queries —
                # but with reconcile on we RECORD it (was: silent `continue`)
                # and log it, so the gap is visible instead of invisible.
                if reconcile:
                    file_reports.append({
                        "path": mpath,
                        "label": mlabel,
                        "period": mperiod or None,
                        "status": "failed",
                        "rows": 0,
                        "primary": False,
                        "error": str(e)[:500],
                    })
                    logger.warning(
                        "spreadsheet merge: file failed to load, recorded as gap: %s (%s)",
                        mpath, e,
                    )
                continue

        frames: dict[str, pd.DataFrame] = {}
        for key, parts in merged.items():
            try:
                combined = pd.concat(parts, ignore_index=True, sort=False) if len(parts) > 1 else parts[0]
            except Exception:
                combined = parts[0]
            frames[self._safe_table_name(group_name.get(key, key), used)] = combined

        # Stash the per-file ingest report on the instance so the from-file route
        # (Phase 2+) can reconcile materialized rows vs source rows and surface
        # coverage. None when the flag is off -> downstream treats it as "no
        # reconcile data" and behaves exactly as today.
        if reconcile:
            expected = 1 + len(self.merged_paths)
            loaded = [r for r in file_reports if r["status"] == "loaded"]
            failed = [r for r in file_reports if r["status"] == "failed"]
            self.last_ingest_report = {
                "expected_files": int(expected),
                "loaded_files": len(loaded),
                "failed_files": len(failed),
                "source_rows": int(sum(r["rows"] for r in loaded)),
                "files": file_reports,
            }
        return frames

    @contextmanager
    def connect(self) -> Generator[duckdb.DuckDBPyConnection, None, None]:
        con: duckdb.DuckDBPyConnection | None = None
        try:
            frames = self._load_frames()
            # E5 (HYBRID_DATA_TYPING): cast number/date-shaped columns to real
            # types so DuckDB does true SUM/AVG + date math instead of string ops.
            # Fail-soft + flag-gated; category/text/provenance columns untouched
            # (protects the verified-golden COUNT filters). OFF -> raw frames.
            try:
                from app.settings.hybrid_flags import flags as _ty_flags
                if _ty_flags.DATA_TYPING:
                    from app.services.ingest.typing import apply_typing
                    frames = {name: apply_typing(df) for name, df in frames.items()}
            except Exception:  # noqa: BLE001 — typing never blocks a query
                pass
            con = duckdb.connect(database=":memory:")
            for table_name, df in frames.items():
                # Register the DataFrame then materialize a real table so the
                # view survives after the local `df` ref leaves scope.
                con.register(f"_src_{table_name}", df)
                con.execute(
                    f'CREATE TABLE "{table_name}" AS SELECT * FROM _src_{table_name}'
                )
                con.unregister(f"_src_{table_name}")
            yield con
        except Exception as e:
            raise RuntimeError(f"Error while loading spreadsheet: {e}")
        finally:
            try:
                if con is not None:
                    con.close()
            except Exception:
                pass

    # ── base interface ───────────────────────────────────────────────────

    def execute_query(self, sql: str) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(sql).df()

    def get_tables(self) -> List[Table]:
        tables: List[Table] = []
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
                ORDER BY table_name
                """
            ).fetchall()
            for (name,) in rows:
                cols: List[TableColumn] = []
                try:
                    desc = con.execute(f'DESCRIBE "{name}"').fetchall()
                    for d in desc:
                        cols.append(TableColumn(name=d[0], dtype=str(d[1])))
                except Exception:
                    try:
                        df = con.execute(f'SELECT * FROM "{name}" LIMIT 0').df()
                        for c in df.columns:
                            cols.append(TableColumn(name=str(c), dtype="unknown"))
                    except Exception:
                        pass
                tables.append(
                    Table(
                        name=name,
                        columns=cols,
                        pks=[],
                        fks=[],
                        metadata_json={"source": "spreadsheet", "file_id": self.file_id},
                    )
                )
        return tables

    def get_schema(self, table_name: str) -> Table:
        cols: List[TableColumn] = []
        with self.connect() as con:
            try:
                desc = con.execute(f'DESCRIBE "{table_name}"').fetchall()
                for d in desc:
                    cols.append(TableColumn(name=d[0], dtype=str(d[1])))
            except Exception:
                pass
        return Table(name=table_name, columns=cols, pks=[], fks=[])

    def get_schemas(self) -> List[Table]:
        return self.get_tables()

    def prompt_schema(self) -> str:
        return TableFormatter(self.get_schemas()).table_str

    def test_connection(self):
        try:
            with self.connect() as con:
                rows = con.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='main' AND table_type='BASE TABLE' ORDER BY table_name"
                ).fetchall()
                table_count = len(rows)
            return {
                "success": True,
                "message": f"Spreadsheet loaded: {table_count} table(s) ready",
                "details": {"table_count": table_count, "file_id": self.file_id},
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    @property
    def description(self):
        system_prompt = """
        You can call the execute_query method to run SQL queries (DuckDB syntax)
        over the spreadsheet's sheets. Each sheet/CSV is a table.

        ```python
        df = client.execute_query("SELECT * FROM sheet1 LIMIT 10")
        ```
        """
        try:
            names = ", ".join(t.name for t in self.get_schemas())
        except Exception:
            names = ""
        head = f"Spreadsheet data source. Tables: {names}\n\n" if names else "Spreadsheet data source.\n\n"
        return head + system_prompt


# Compatibility alias for dynamic resolver expecting 'SpreadsheetClient'.
SpreadsheetClient = SpreadsheetClient
