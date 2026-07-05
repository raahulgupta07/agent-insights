"""POST /api/data_sources/from-file — turn an uploaded Excel/CSV into a Data Agent.

Takes an existing File (uploaded via POST /api/files), creates a `spreadsheet`
Connection + DataSource backed by an in-memory DuckDB engine, runs schema
discovery so each sheet/CSV becomes a queryable table, and returns the created
DataSource (same shape as POST /api/data_sources) plus its discovered tables[].

Schema discovery is fail-soft: if the file can't be read the data source is
still returned (with empty tables[]) rather than crashing the request — except
when the file itself is missing/unreadable up front, which is a 400.
"""

import json
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import current_user
from app.core.permissions_decorator import requires_permission
from app.dependencies import get_async_db, get_current_organization
from app.models.connection import Connection
from app.models.data_source import DataSource
from app.models.domain_connection import domain_connection
from app.models.file import File as FileModel
from app.models.organization import Organization
from app.models.user import User
from app.services.data_source_service import DataSourceService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["data_sources"])
data_source_service = DataSourceService()


class DataSourceFromFileRequest(BaseModel):
    file_id: str
    data_source_name: Optional[str] = None
    sheet_names: Optional[List[str]] = None
    description: Optional[str] = None
    # P1 (HYBRID_MERGE_SAME_SCHEMA): when an upload is made in the context of a
    # Studio/agent, the same-schema merge PREFERS that agent's already-bound
    # spreadsheet source so a later-session upload of the same monthly template
    # always lands in the agent's ONE table (not a fresh source). Optional —
    # callers that don't set it get the org-wide column-signature match.
    studio_id: Optional[str] = None


def _dlt_table_name(ds) -> str:
    """Stable snake_case DuckDB table name for the dlt durable warehouse.

    Keyed by DataSource id (stable across appends) so every month of the same
    source merges into ONE table. Prefixed ``t_`` to guarantee a valid identifier.
    """
    import re as _re

    raw = str(getattr(ds, "id", "") or getattr(ds, "name", "") or "src")
    return "t_" + _re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")[:48]


async def _dedupe_ds_name(db: AsyncSession, org_id: str, base: str) -> str:
    """Return a DataSource name unique within the org: ``base`` if free, else
    ``base (2)``, ``base (3)`` … (org-scoped, case-insensitive). Fail-soft: on any
    query error just return ``base`` and let the insert's 409 guard handle it."""
    try:
        rows = (
            await db.execute(
                select(DataSource.name).where(
                    DataSource.organization_id == org_id,
                    func.lower(DataSource.name).like(func.lower(base) + "%"),
                )
            )
        ).scalars().all()
        taken = {str(n).strip().lower() for n in rows if n}
        if base.lower() not in taken:
            return base
        for i in range(2, 1000):
            cand = f"{base} ({i})"
            if cand.lower() not in taken:
                return cand
    except Exception:  # noqa: BLE001 - never block the upload on the dedupe probe
        pass
    return base


def _resolve_upload_path(stored_path: str) -> Optional[str]:
    """Resolve the on-disk absolute path for an uploaded file, traversal-safe.

    Uploaded files live flat under <cwd>/uploads/files/<basename> (see
    routes/file.py). Returns the path if it exists, else None.
    """
    if not stored_path:
        return None
    base = os.path.basename(stored_path)
    candidate = os.path.join(os.getcwd(), "uploads", "files", base)
    if os.path.exists(candidate):
        return candidate
    rel = os.path.join(os.getcwd(), stored_path)
    if os.path.exists(rel):
        return rel
    if os.path.isabs(stored_path) and os.path.exists(stored_path):
        return stored_path
    return None


async def _new_source_response(db, data_source_service, ds_id, organization, current_user, *, extra=None):
    """Build the standard from-file response body for an existing data source."""
    ds_schema = await data_source_service.get_data_source(db, str(ds_id), organization, current_user)
    try:
        tables = await data_source_service.get_data_source_schema(
            db, str(ds_id), include_inactive=True,
            organization=organization, current_user=current_user,
        )
    except Exception:  # noqa: BLE001
        tables = []
    body = json.loads(ds_schema.json()) if hasattr(ds_schema, "json") else dict(ds_schema)
    body["tables"] = [json.loads(t.json()) if hasattr(t, "json") else dict(t) for t in (tables or [])]
    if extra:
        body.update(extra)
    return body


async def _spreadsheet_connections(db, org_id):
    """All non-deleted spreadsheet Connections for the org, eagerly mapped to
    their (single) DataSource. Returns list[(Connection, DataSource)]."""
    rows = (
        await db.execute(
            select(Connection)
            .options(selectinload(Connection.data_sources))
            .where(
                Connection.organization_id == org_id,
                Connection.type == "spreadsheet",
                Connection.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    out = []
    for c in rows:
        ds = (c.data_sources[0] if getattr(c, "data_sources", None) else None)
        if ds is not None and ds.deleted_at is None:
            out.append((c, ds))
    return out


async def _studio_bound_ds_ids(db, studio_id) -> set:
    """DataSource ids currently bound to a Studio/agent (live links only).

    Used by the same-schema merge to PREFER an agent's own spreadsheet source so
    a later-session upload of the same template lands in its ONE table. Fail-soft:
    any error -> empty set (falls back to org-wide match ordering)."""
    if not studio_id:
        return set()
    try:
        from app.models.studio import StudioDataSource

        rows = (
            await db.execute(
                select(StudioDataSource.agent_id).where(
                    StudioDataSource.studio_id == str(studio_id),
                    StudioDataSource.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        return {str(r) for r in rows if r}
    except Exception:  # noqa: BLE001
        return set()


def _same_template(a, b) -> bool:
    """True when two normalized column-sets are the SAME upload template.

    Exact set equality is too brittle across separate sessions (a reordered
    header, a case change, one added/renamed column). Order/case/whitespace and
    lineage columns are already folded out by ``normalize_columns``; on top of
    that this tolerates a small, bounded number of differing columns on EACH side
    (a stray note column, one rename) while still rejecting a genuinely different
    schema or a small table that is merely a subset of a much wider one.
    """
    try:
        if not a or not b:
            return False
        if a == b:
            return True
        inter = len(a & b)
        if inter == 0:
            return False
        only_a = len(a - b)
        only_b = len(b - a)
        # allow ~10% drift, at least one column, on each side independently
        max_diff = max(1, round(0.10 * max(len(a), len(b))))
        return only_a <= max_diff and only_b <= max_diff
    except Exception:  # noqa: BLE001
        return False


async def _try_merge_same_schema(
    db, *, organization, current_user, file, abs_path, content_hash, studio_id=None
):
    """Task 5: return a response body when this upload should reuse an existing
    source (byte-identical dedup OR same-schema append), else None to fall back.

    Matching is by COLUMN SIGNATURE (order-insensitive, lineage-column-excluded,
    trivial-drift tolerant), never by filename/stem. When ``studio_id`` is in
    scope, that agent's already-bound spreadsheet source is tried FIRST so an
    agent's later-session uploads always converge into its one table. Soft-deleted
    sources are excluded up front and can never block a live match.

    Defensive throughout — any failure returns None so the caller creates a new
    source as today.
    """
    from app.services.ingest import smart_upload
    from app.data_sources.clients.spreadsheet_client import SpreadsheetClient
    from sqlalchemy.orm.attributes import flag_modified

    candidates = await _spreadsheet_connections(db, str(organization.id))
    if not candidates:
        return None

    # P1: prefer the studio/agent's own bound spreadsheet source(s) — put them at
    # the front so a schema match there wins over any other org source.
    bound_ids = await _studio_bound_ds_ids(db, studio_id)
    if bound_ids:
        candidates.sort(key=lambda cd: 0 if str(cd[1].id) in bound_ids else 1)

    # ── (a) content-hash dedup: byte-identical re-upload -> point to existing ──
    for conn, ds in candidates:
        try:
            cfg = json.loads(conn.config) if isinstance(conn.config, str) else (conn.config or {})
        except Exception:  # noqa: BLE001
            cfg = {}
        if cfg.get("content_hash") and cfg.get("content_hash") == content_hash:
            logger.info("from-file: dedup hit -> reuse data_source %s (hash %s)", ds.id, content_hash[:12])
            return await _new_source_response(
                db, data_source_service, ds.id, organization, current_user,
                extra={"reused": True, "merged": False, "reason": "content_hash_dedup"},
            )

    # ── (b) same-schema append: match normalized column-set of sheet(s) ────────
    try:
        new_frames = SpreadsheetClient(path=file.path, file_id=str(file.id))._load_frames()
    except Exception:  # noqa: BLE001
        return None
    if not new_frames:
        return None
    new_colsets = {name: smart_upload.normalize_columns(df.columns) for name, df in new_frames.items()}

    for conn, ds in candidates:
        try:
            cfg = json.loads(conn.config) if isinstance(conn.config, str) else (conn.config or {})
            existing = SpreadsheetClient(
                path=cfg.get("path"),
                sheet_names=cfg.get("sheet_names"),
                file_id=cfg.get("file_id"),
                merged_paths=cfg.get("merged_paths"),
            )._load_frames()
        except Exception:  # noqa: BLE001
            continue
        existing_colsets = {name: smart_upload.normalize_columns(df.columns) for name, df in existing.items()}

        # Every NEW sheet must match SOME existing sheet by column signature
        # (trivial-drift tolerant — the same monthly template across sessions).
        all_match = bool(new_colsets) and all(
            any(_same_template(ncs, ecs) for ecs in existing_colsets.values())
            for ncs in new_colsets.values()
        )
        if not all_match:
            continue

        # Append: add this file to the target source's merged_paths + re-sync.
        label = smart_upload.label_from_filename(file.filename or file.path)
        mp = list(cfg.get("merged_paths") or [])
        # IDEMPOTENCY GUARD: never re-append a file already merged (by file_id OR
        # byte-identical content hash). Without this, re-ingesting the same file
        # stacks its rows again -> duplicate inflation (the 4.5x dup we hit).
        _already = any(
            str(m.get("file_id")) == str(file.id)
            or (content_hash and m.get("content_hash") == content_hash)
            for m in mp
        )
        if _already:
            return await _new_source_response(
                db, data_source_service, ds.id, organization, current_user,
                extra={"reused": True, "merged": True, "reason": "already_merged_skip_dupe"},
            )
        mp.append({"path": file.path, "label": label, "file_id": str(file.id), "content_hash": content_hash})
        cfg["merged_paths"] = mp
        conn.config = json.dumps(cfg) if isinstance(conn.config, str) else cfg
        flag_modified(conn, "config")
        await db.commit()

        # Re-run schema discovery so row counts/profiling reflect the merged data.
        try:
            from app.services.connection_service import ConnectionService

            ds_q = await db.execute(
                select(DataSource).options(selectinload(DataSource.connections)).filter(DataSource.id == ds.id)
            )
            ds_full = ds_q.scalar_one()
            conn_full = ds_full.connections[0]
            await ConnectionService().refresh_schema(db=db, connection=conn_full, current_user=current_user)
            await data_source_service.sync_domain_tables_from_connection(
                db=db, data_source=ds_full, connection=conn_full, max_auto_select=9999,
            )
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("from-file: re-sync after same-schema append failed", exc_info=True)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

        logger.info("from-file: same-schema append -> data_source %s (+%s)", ds.id, label)

        # DURABILITY (persist-on-append): write the merged frames to staging_<org>
        # (Postgres volume) so the data survives container restart/rebuild. The
        # main new-source path persists, but this append branch returns BEFORE
        # reaching that block — so without this, appended months live only in
        # in-memory DuckDB and vanish on restart. Fail-soft.
        _append_persisted = False
        try:
            from app.settings.hybrid_flags import flags as _pw_flags

            if _pw_flags.PERSIST_WAREHOUSE:
                from app.services.ingest import upload_persist

                ds_pq = await db.execute(
                    select(DataSource).options(selectinload(DataSource.connections)).filter(DataSource.id == ds.id)
                )
                ds_persist = ds_pq.scalar_one()
                _append_wh = await upload_persist.persist_upload_to_warehouse(
                    db, organization=organization, data_source=ds_persist, file=file,
                )
                _append_persisted = bool(_append_wh and _append_wh.get("tables"))
        except Exception:  # noqa: BLE001
            logger.warning("from-file: warehouse persist on same-schema append failed", exc_info=True)

        # NEWPIPE P2/P3 (HYBRID_DLT_INGEST): durable, idempotent dlt merge into the
        # per-org DuckDB file warehouse (by _source_period + content-hash). Additive
        # to the legacy path; never raises. OFF -> skipped entirely.
        # REDUNDANT once the direct loader persisted (see new-source branch note):
        # skip it to avoid the DuckDB single-writer lock error + the stale
        # quality_gate "table does not exist". Reconcile below is the real check.
        try:
            from app.settings.hybrid_flags import flags as _dlt_flags

            if (_dlt_flags.DLT_INGEST or _dlt_flags.FULL_PIPELINE) and not _append_persisted:
                from app.services.ingest import dlt_ingest as _dlt
                _tbl = _dlt_table_name(ds)
                _res = _dlt.ingest_file(
                    org_id=str(organization.id), table=_tbl,
                    file_path=_resolve_upload_path(file.path or ""),
                    file_name=file.filename or file.path,
                )
                logger.info("from-file: dlt_ingest append %s", _res)
                # NEWPIPE P6 quality gate on the durable warehouse
                from app.services.ingest import quality_gate as _qg
                _gate = _qg.run_quality_gate(str(organization.id), _tbl)
                logger.info("from-file: quality_gate append passed=%s hard_fail=%s",
                            _gate.get("passed"), _gate.get("hard_fail"))
        except Exception:  # noqa: BLE001
            logger.warning("from-file: dlt_ingest append failed", exc_info=True)

        # Phase 2/5 (HYBRID_INGEST_RECONCILE): THIS is the real multi-file merge
        # path (each appended month grows merged_paths). Reconcile here so a
        # dropped month flips the source DEGRADED + surfaces coverage — the
        # new-source branch above always has merged_paths=[] so it can't.
        extra = {"reused": True, "merged": True, "reason": "same_schema_append", "appended_label": label}
        try:
            from app.settings.hybrid_flags import flags as _rec_flags

            if _rec_flags.INGEST_RECONCILE:
                from app.services.ingest import reconcile as _reconcile

                ds_q2 = await db.execute(
                    select(DataSource).options(selectinload(DataSource.connections)).filter(DataSource.id == ds.id)
                )
                ds_r = ds_q2.scalar_one()
                cov = await _reconcile.run_ingest_reconcile(
                    db, organization=organization, data_source=ds_r, connection=ds_r.connections[0],
                )
                if cov:
                    extra["ingest_coverage"] = cov
        except Exception:  # noqa: BLE001
            logger.warning("from-file: reconcile on same-schema append failed", exc_info=True)

        return await _new_source_response(
            db, data_source_service, ds.id, organization, current_user,
            extra=extra,
        )

    return None


async def _route_glossary_sheets(db, *, organization, data_source, file, abs_path):
    """Task 6: detect glossary/data-dictionary sheets in the file, ingest each
    into the Knowledge layer (KnowledgeDoc, pending), and deactivate the
    corresponding junk queryable table. Returns the list of routed sheet names.

    Conservative + fail-soft: only confident glossary sheets are routed; a sheet
    that also reads as a real table stays queryable unless it's confidently a
    glossary. Never raises into the caller.
    """
    from app.services.ingest import smart_upload
    from app.data_sources.clients.spreadsheet_client import SpreadsheetClient
    from app.ai.knowledge.docs_index import ingest_doc
    from app.models.datasource_table import DataSourceTable

    routed: list[str] = []
    try:
        frames = SpreadsheetClient(path=file.path, file_id=str(file.id))._load_frames()
    except Exception:  # noqa: BLE001
        return routed
    if not frames:
        return routed

    for table_name, df in frames.items():
        try:
            if not smart_upload.looks_like_glossary(df, sheet_name=table_name, filename=file.filename or ""):
                continue
            body = smart_upload.glossary_to_markdown(df, sheet_name=table_name)
            if not body or not body.strip():
                continue
            title = f"{(file.filename or 'glossary')} — {table_name}"
            await ingest_doc(
                db, organization=organization, title=title, body=body,
                source="upload", data_source_id=str(data_source.id),
            )
            # Deactivate the junk queryable table (the slugged sheet name).
            try:
                tbl = (
                    await db.execute(
                        select(DataSourceTable).where(
                            DataSourceTable.datasource_id == data_source.id,
                            func.lower(DataSourceTable.name) == table_name.lower(),
                        )
                    )
                ).scalars().first()
                if tbl is not None:
                    tbl.is_active = False
                    await db.commit()
            except Exception:  # noqa: BLE001
                try:
                    await db.rollback()
                except Exception:  # noqa: BLE001
                    pass
            routed.append(table_name)
            logger.info("from-file: routed glossary sheet '%s' -> KnowledgeDoc (pending)", table_name)
        except Exception:  # noqa: BLE001
            logger.warning("from-file: glossary route for sheet '%s' failed", table_name, exc_info=True)
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
            continue
    return routed


@router.post("/data_sources/from-file")
@requires_permission('create_data_source')
async def create_data_source_from_file(
    payload: DataSourceFromFileRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    # ── 1. Fetch the File, org-scoped (404 if not owned by the org) ──────
    file_result = await db.execute(
        select(FileModel).filter(
            FileModel.id == payload.file_id,
            FileModel.organization_id == organization.id,
        )
    )
    file = file_result.scalar_one_or_none()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    abs_path = _resolve_upload_path(file.path or "")
    if not abs_path:
        raise HTTPException(status_code=400, detail="File content is missing or unreadable")

    # Basic extension sanity (the client also validates on read).
    ext = os.path.splitext(abs_path)[1].lower()
    if ext not in {".xlsx", ".xlsm", ".xls", ".csv", ".tsv", ".txt"}:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Upload an Excel (.xlsx/.xls) or CSV file.",
        )

    # ── 1b. Task 5 (HYBRID_MERGE_SAME_SCHEMA): content-hash dedup + same-schema
    # append. Fail-soft — any error here falls through to today's behavior
    # (new source + new table per file).
    content_hash = ""
    try:
        from app.settings.hybrid_flags import flags as _flags
        from app.services.ingest import smart_upload

        content_hash = smart_upload.file_content_hash(abs_path)
        if _flags.MERGE_SAME_SCHEMA and content_hash:
            merged = await _try_merge_same_schema(
                db,
                organization=organization,
                current_user=current_user,
                file=file,
                abs_path=abs_path,
                content_hash=content_hash,
                studio_id=payload.studio_id,
            )
            if merged is not None:
                return merged
    except Exception:  # noqa: BLE001 - merge is best-effort, never blocks upload
        logger.warning("from-file: merge/dedup probe failed; proceeding with new source", exc_info=True)

    # ── 2. Create the Connection (type='spreadsheet') ───────────────────
    config = {
        "file_id": str(file.id),
        "sheet_names": payload.sheet_names,
        # Resolved server-side path so the client reads without a DB lookup.
        "path": file.path,
        # Task 5: stored on the connection config (queryable JSON; least-invasive
        # spot — no new column/migration) so a byte-identical re-upload and a
        # same-schema append can find this source later. Harmless when the flag
        # is off (just metadata the client ignores).
        "content_hash": content_hash,
        # Task 5: extra same-schema files merged into this source (populated by
        # _try_merge_same_schema on a later matching upload). Empty here.
        "merged_paths": [],
    }

    # Auto-generate connection name as spreadsheet-N (mirrors create_data_source).
    count_result = await db.execute(
        select(func.count(Connection.id)).filter(
            Connection.organization_id == organization.id,
            Connection.type == "spreadsheet",
        )
    )
    existing_count = count_result.scalar() or 0
    connection = Connection(
        name=f"spreadsheet-{existing_count + 1}",
        type="spreadsheet",
        config=json.dumps(config),
        organization_id=str(organization.id),
        is_active=True,
        auth_policy="system_only",
    )
    db.add(connection)
    await db.flush()

    # ── 3. Create the DataSource + link via domain_connection ───────────
    # DataSource names are unique per organization (uq_data_sources_org_name).
    # Rather than hard-blocking a same-named upload, auto-suffix " (2)", " (3)"…
    # so the user can keep multiple snapshots of the same report. They can rename
    # later. A genuine race still surfaces the 409 below.
    base_name = (payload.data_source_name or "").strip() or (file.filename or "Spreadsheet")
    ds_name = await _dedupe_ds_name(db, str(organization.id), base_name)
    data_source = DataSource(
        name=ds_name,
        organization_id=organization.id,
        is_public=False,
        is_active=True,
        use_llm_sync=False,
        owner_user_id=current_user.id,
        description=payload.description,
    )
    data_source.connections.append(connection)
    db.add(data_source)

    try:
        await db.commit()
        await db.refresh(data_source)
    except Exception as e:
        await db.rollback()
        # Duplicate name per org is the common case (uq_data_sources_org_name).
        raise HTTPException(
            status_code=409,
            detail=(
                f"A data source named '{ds_name}' already exists in this organization. "
                "Please choose a different name."
            ),
        )

    # Creator becomes a member with manage rights (mirrors create_data_source).
    await data_source_service._create_memberships(
        db, data_source, [current_user.id], permissions=["manage"]
    )

    # ── 4. Schema discovery (fail-soft) ─────────────────────────────────
    # Reuse the SAME canonical path the demo/normal flow uses:
    #   ConnectionService.refresh_schema -> ConnectionTable
    #   DataSourceService.sync_domain_tables_from_connection -> DataSourceTable
    try:
        from app.services.connection_service import ConnectionService

        # Reload data source with its connection eagerly loaded for the sync.
        ds_q = await db.execute(
            select(DataSource)
            .options(selectinload(DataSource.connections))
            .filter(DataSource.id == data_source.id)
        )
        data_source = ds_q.scalar_one()
        conn = data_source.connections[0]

        await ConnectionService().refresh_schema(
            db=db, connection=conn, current_user=current_user
        )
        await data_source_service.sync_domain_tables_from_connection(
            db=db,
            data_source=data_source,
            connection=conn,
            max_auto_select=9999,  # activate all sheets — small files
        )
        await db.commit()
    except Exception as e:
        logger.warning(
            "from-file: schema discovery failed for data_source %s (file %s): %s",
            data_source.id, payload.file_id, e,
        )
        try:
            await db.rollback()
        except Exception:
            pass

    # ── 4b. Task 6 (HYBRID_SMART_HEADER): glossary routing ──────────────
    # If a sheet looks like a field-definition glossary, route its content into
    # the Knowledge layer (KnowledgeDoc, pending) so its terms can map onto OTHER
    # sources' columns — and deactivate the junk queryable table. Fail-soft.
    glossary_routed: list[str] = []
    try:
        from app.settings.hybrid_flags import flags as _sh_flags

        if _sh_flags.SMART_HEADER:
            glossary_routed = await _route_glossary_sheets(
                db, organization=organization, data_source=data_source, file=file, abs_path=abs_path,
            )
    except Exception:  # noqa: BLE001
        logger.warning("from-file: glossary routing failed", exc_info=True)

    # ── 4c. Task T2 (HYBRID_TOTAL_ROW): pre-aggregated total-row detection ──
    # Scan the just-ingested frames for likely roll-up/subtotal rows (e.g. a
    # `site='ALL Total'` row already summed across sites) and record markers in
    # each DataSourceTable.metadata_json + emit a guardrail Instruction so the
    # agent excludes them and stops double-counting SUM(). Fail-soft, flag-gated.
    try:
        from app.settings.hybrid_flags import flags as _tr_flags

        if _tr_flags.TOTAL_ROW:
            from app.ai.knowledge.total_rows import apply_total_row_detection

            await apply_total_row_detection(
                db,
                organization=organization,
                data_source=data_source,
                abs_path=abs_path,
                sheet_names=payload.sheet_names,
                merged_paths=config.get("merged_paths") or [],
            )
    except Exception:  # noqa: BLE001
        logger.warning("from-file: total-row detection failed", exc_info=True)

    # ── 4c2. Import v2 P4 (HYBRID_PERSIST_WAREHOUSE): persist to staging ──
    # Write the frames into the per-org Postgres staging schema (durable, deep
    # stats) and stamp physical refs so the unified VIEW below can materialize.
    # Runs BEFORE T4 so cross_source_unify sees the physical tables. Fail-soft.
    warehouse: Optional[dict] = None
    try:
        from app.settings.hybrid_flags import flags as _pw_flags

        if _pw_flags.PERSIST_WAREHOUSE:
            from app.services.ingest import upload_persist

            warehouse = await upload_persist.persist_upload_to_warehouse(
                db, organization=organization, data_source=data_source, file=file,
            )
    except Exception:  # noqa: BLE001
        logger.warning("from-file: warehouse persist failed", exc_info=True)

    # ── 4c2b. NEWPIPE P2/P3 (HYBRID_DLT_INGEST): durable dlt merge ───────
    # The direct loader (4c2 above) already wrote + registered the table to
    # Postgres staging, so the dlt DuckDB re-ingest is REDUNDANT — it only
    # re-opens the per-org DuckDB file with a different config (→ "same database
    # file with a different config" lock error + delay) and then quality_gate
    # reads a DuckDB table that isn't there (→ "table t_<id> does not exist").
    # Skip it whenever the loader already persisted rows; reconcile (4c3) is the
    # real validation. dlt still runs as a fallback when persist didn't write.
    _loader_persisted = bool(warehouse and warehouse.get("tables"))
    try:
        from app.settings.hybrid_flags import flags as _dlt_flags

        if (_dlt_flags.DLT_INGEST or _dlt_flags.FULL_PIPELINE) and not _loader_persisted:
            from app.services.ingest import dlt_ingest as _dlt
            _tbl = _dlt_table_name(data_source)
            _res = _dlt.ingest_file(
                org_id=str(organization.id), table=_tbl,
                file_path=_resolve_upload_path(file.path or ""),
                file_name=file.filename or file.path,
            )
            logger.info("from-file: dlt_ingest new-source %s", _res)
            from app.services.ingest import quality_gate as _qg
            _gate = _qg.run_quality_gate(str(organization.id), _tbl)
            logger.info("from-file: quality_gate new-source passed=%s hard_fail=%s",
                        _gate.get("passed"), _gate.get("hard_fail"))
    except Exception:  # noqa: BLE001
        logger.warning("from-file: dlt_ingest new-source failed", exc_info=True)

    # ── 4c3. Phase 2 (HYBRID_INGEST_RECONCILE): reconcile gate ──────────
    # Compare what actually materialized against what the merge tried to load.
    # Any failed file or row shortfall -> stamp ingest_coverage + mark the source
    # DEGRADED, so the gap is visible (agent context P3 + UI P5) instead of a
    # silent partial ingest. Fail-soft, flag-gated, no data mutation.
    ingest_coverage: Optional[dict] = None
    try:
        from app.settings.hybrid_flags import flags as _rec_flags

        if _rec_flags.INGEST_RECONCILE:
            from app.services.ingest import reconcile as _reconcile

            # Reload the source with its connection eagerly loaded.
            ds_q = await db.execute(
                select(DataSource)
                .options(selectinload(DataSource.connections))
                .filter(DataSource.id == data_source.id)
            )
            ds_full = ds_q.scalar_one()
            conn_full = ds_full.connections[0]
            ingest_coverage = await _reconcile.run_ingest_reconcile(
                db, organization=organization, data_source=ds_full, connection=conn_full,
            )
    except Exception:  # noqa: BLE001
        logger.warning("from-file: ingest reconcile failed", exc_info=True)

    # ── 4c4. E3 column profiling + E4 data-quality validation ───────────
    # Master Plan stages 3-4. Additive, fail-soft, flag-gated. E3 writes a
    # per-column profile (dtype/null_pct/distinct/min/max/top_values) into each
    # DataSourceTable.columns[].metadata — the SAME store column_intel uses, so
    # the agent's schema context surfaces distinct/nulls/values automatically
    # (tables_schema_section reads col metadata). E4 runs the null/dup +
    # near-duplicate-category checks and stamps a <data_quality> block onto each
    # active table's metadata_json (rendered like the coverage note) so the agent
    # is warned about typo-split categories / dead columns before it answers.
    try:
        from app.settings.hybrid_flags import flags as _pv_flags

        if _pv_flags.COLUMN_PROFILE or _pv_flags.DATA_VALIDATION:
            from app.services.ingest import column_profile as _cp
            from app.services.ingest import data_validator as _dv
            from app.data_sources.clients.spreadsheet_client import SpreadsheetClient
            from app.models.datasource_table import DataSourceTable

            frames = SpreadsheetClient(path=file.path, file_id=str(file.id))._load_frames()

            trows = (
                await db.execute(
                    select(DataSourceTable).where(
                        DataSourceTable.datasource_id == str(data_source.id),
                        DataSourceTable.is_active.is_(True),
                    )
                )
            ).scalars().all()

            merged_profile: dict = {}
            all_warnings: list = []
            for _name, _df in (frames or {}).items():
                prof = _cp.profile_frame(_df)
                merged_profile.update(prof)
                if _pv_flags.DATA_VALIDATION:
                    all_warnings.extend(_dv.null_and_dup_checks(_df, prof))

            if _pv_flags.COLUMN_PROFILE and merged_profile:
                _cp.persist_profile(trows, merged_profile)

            # Only stamp a block when there are real findings — a "clean" marker
            # would add context noise on every upload for no benefit.
            if _pv_flags.DATA_VALIDATION and all_warnings:
                from sqlalchemy.orm.attributes import flag_modified
                block = _dv.build_data_quality_block(all_warnings)
                for _t in trows:
                    md = dict(getattr(_t, "metadata_json", None) or {})
                    md["data_quality"] = block
                    _t.metadata_json = md
                    flag_modified(_t, "metadata_json")

            await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("from-file: column profile / data validation failed", exc_info=True)

    # ── 4d. Post-ingest enrichment (T4 / T6 / T7) ───────────────────────
    # All additive + fail-soft; each in its own try/except so one failing can
    # never affect the others or the upload. T4/T6 are flag-gated; T7 (cosmetic
    # default-name improvement) is always-on but only acts on auto-derived names.
    unified_groups: list = []
    quality_summary: list = []
    renamed_to: Optional[str] = None
    try:
        from app.settings.hybrid_flags import flags as _pi_flags
        from app.services.ingest import post_ingest

        # T4 — cross-source unify (same-shape monthly siblings).
        try:
            if _pi_flags.CROSS_SOURCE_UNIFY:
                unified_groups = await post_ingest.run_cross_source_unify(
                    db, organization=organization, data_source=data_source,
                )
        except Exception:  # noqa: BLE001
            logger.warning("from-file: cross-source unify failed", exc_info=True)

        # T6 — data quality scan.
        try:
            if _pi_flags.DATA_QUALITY:
                quality_summary = await post_ingest.run_data_quality_scan(
                    db, organization=organization, data_source=data_source, file=file,
                )
        except Exception:  # noqa: BLE001
            logger.warning("from-file: data quality scan failed", exc_info=True)

        # T7 — better multi-file naming (only when the name was auto-derived).
        try:
            if not (payload.data_source_name or "").strip():
                renamed_to = await post_ingest.run_better_naming(
                    db, organization=organization, data_source=data_source,
                    file=file, dedupe_fn=_dedupe_ds_name,
                )
        except Exception:  # noqa: BLE001
            logger.warning("from-file: better-naming failed", exc_info=True)
    except Exception:  # noqa: BLE001 - import/setup guard
        logger.warning("from-file: post-ingest enrichment unavailable", exc_info=True)

    # ── 4e. Import v2 P2 (HYBRID_AUTO_MAP_GLOSSARY): standalone glossary file ──
    # If the WHOLE uploaded file is a glossary/definitions file, parse it and
    # auto-map its terms onto the columns of the org's EXISTING data sources
    # (pending SemanticColumn meanings) + ingest it as a KnowledgeDoc. Fail-soft.
    glossary_mapped: Optional[dict] = None
    try:
        from app.settings.hybrid_flags import flags as _gm_flags

        if _gm_flags.AUTO_MAP_GLOSSARY:
            from app.services.ingest import glossary_map
            from app.data_sources.clients.spreadsheet_client import SpreadsheetClient

            frames = SpreadsheetClient(path=file.path, file_id=str(file.id))._load_frames()
            if glossary_map.is_glossary_file(frames):
                terms = glossary_map.extract_glossary_terms(frames)
                if terms:
                    glossary_mapped = await glossary_map.map_glossary_to_org(
                        db, organization=organization, terms=terms,
                        source_filename=file.filename or "Glossary",
                    )
    except Exception:  # noqa: BLE001
        logger.warning("from-file: glossary auto-map failed", exc_info=True)

    # ── 5. Build the response: DataSourceSchema (+ tables[]) ─────────────
    ds_schema = await data_source_service.get_data_source(
        db, str(data_source.id), organization, current_user
    )

    try:
        tables = await data_source_service.get_data_source_schema(
            db,
            str(data_source.id),
            include_inactive=True,
            organization=organization,
            current_user=current_user,
        )
    except Exception as e:
        logger.warning("from-file: could not load tables for response: %s", e)
        tables = []

    # Return the exact DataSourceSchema shape plus the discovered tables[].
    body = json.loads(ds_schema.json()) if hasattr(ds_schema, "json") else dict(ds_schema)
    body["tables"] = [
        json.loads(t.json()) if hasattr(t, "json") else dict(t) for t in (tables or [])
    ]
    if glossary_routed:
        body["glossary_routed"] = glossary_routed
    if unified_groups:
        body["unified_groups"] = unified_groups
    if quality_summary:
        body["quality_findings"] = quality_summary
    if renamed_to:
        body["renamed_to"] = renamed_to
    if glossary_mapped and glossary_mapped.get("columns_mapped"):
        body["glossary_mapped"] = glossary_mapped
    if warehouse and warehouse.get("tables"):
        body["warehouse"] = warehouse
    if ingest_coverage:
        body["ingest_coverage"] = ingest_coverage
    return body
