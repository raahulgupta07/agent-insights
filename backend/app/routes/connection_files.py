"""Per-user FILE BROWSER for the existing file connectors (HYBRID_FILE_BROWSER).

Lets a user navigate a SharePoint / OneDrive / Google Drive connector's folders
and files with THEIR OWN identity, and ingest picked files as queryable Data
Agents. The client is built via ``connection_service.construct_client(db, conn,
current_user)``, which resolves the CALLING user's per-user credentials
(``auth_policy=user_required`` → the user's OAuth token). Because every Graph
call then runs as that user's Microsoft identity, the source's own ACLs isolate
each user's view — we add no app-side ACL of our own beyond the connection
read-access check.

Two endpoints (mounted under ``/api`` in main.py, paths declared bare):
  GET  /api/connections/{id}/files          — browse a folder / search
  POST /api/connections/{id}/files/ingest   — ingest picked files as Data Agents

Everything is flag-gated (404 / feature-locked when HYBRID_FILE_BROWSER is off,
mirroring routes/me_groups.py). When the user has no per-user credentials yet,
``construct_client`` raises a 403 from ``resolve_credentials`` — we translate
that to a clean 409 ``{"error": "connect_required"}`` so the FE shows the
Microsoft/Google sign-in button (which calls the existing connection_oauth flow).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import current_user
from app.dependencies import get_async_db, get_current_organization
from app.errors import AppError, ErrorCode
from app.models.connection import Connection
from app.models.organization import Organization
from app.models.user import User
from app.services.connection_service import ConnectionService
from app.settings.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/connections", tags=["connection-files"])

connection_service = ConnectionService()

# Cap a single ingested file at 100 MB — these become in-memory DuckDB tables,
# and Graph file reads are streamed whole into the upload lane.
_MAX_INGEST_BYTES = 100 * 1024 * 1024


def _ensure_enabled() -> None:
    """Raise 404 (feature locked) unless HYBRID_FILE_BROWSER is on.

    Mirrors routes/me_groups.py / private_connector_guard — a locked feature is a
    404, not a 403, so the endpoint's existence isn't leaked.
    """
    from app.settings.hybrid_flags import flags

    if not flags.FILE_BROWSER:
        raise AppError(
            ErrorCode.FEATURE_LOCKED,
            "The file browser is not enabled.",
            status_code=404,
        )


async def _load_connection(db: AsyncSession, connection_id: str, organization) -> Connection:
    """Load a connection org-scoped (404 if missing / not in this org), with the
    relations the access helpers need eagerly loaded."""
    row = (
        await db.execute(
            select(Connection)
            .options(
                selectinload(Connection.organization),
                selectinload(Connection.data_sources),
            )
            .where(
                Connection.id == connection_id,
                Connection.organization_id == str(organization.id),
            )
        )
    ).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


async def _check_access(db: AsyncSession, organization, user: User, connection: Connection) -> None:
    """Read-access check + private-connector owner guard (reuses connection.py)."""
    from app.routes.connection import _ensure_can_read_connection
    from app.services import private_connector_guard as _pcg

    # CREATOR-ONLY for private connectors (no admin bypass); no-op for org ones.
    _pcg.require_owner(connection, user)
    # General read access (admin / connection grant / accessible-DS).
    await _ensure_can_read_connection(db, organization, user, connection)


def _require_browsable(connection: Connection) -> None:
    """400 unless this connector's registry entry is a browsable file source
    (``is_document_based`` and ``data_shape == "files"``)."""
    from app.schemas.data_source_registry import get_entry

    try:
        entry = get_entry(connection.type)
    except ValueError:
        raise HTTPException(status_code=400, detail="This connector cannot be browsed.")
    if not (getattr(entry, "is_document_based", False) and getattr(entry, "data_shape", "") == "files"):
        raise HTTPException(
            status_code=400,
            detail="This connector is not a browsable file source (SharePoint / OneDrive / Drive only).",
        )


async def _build_user_client(db: AsyncSession, connection: Connection, user: User):
    """Build a client scoped to THIS user's credentials.

    Translates the 403 ``resolve_credentials`` raises when the user has no token
    yet into a 409 ``connect_required`` so the FE prompts sign-in. Any other
    client-construction failure becomes a 502 (never a raw 500 trace).
    """
    try:
        return await connection_service.construct_client(db, connection, user)
    except HTTPException as e:
        if e.status_code == 403:
            raise HTTPException(status_code=409, detail={"error": "connect_required"})
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("file-browser: client construction failed for connection %s: %s", connection.id, e)
        raise HTTPException(status_code=502, detail="Could not connect to the file source.")


def _normalize(item: dict) -> dict:
    """Normalize a client browse/search item to the FE-facing shape."""
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "is_folder": bool(item.get("is_folder", False)),
        "mime_type": item.get("mime_type"),
        "size": item.get("size"),
        "modified_at": item.get("modified_at"),
        "web_url": item.get("web_url"),
    }


@router.get("/{connection_id}/files")
async def browse_connection_files(
    connection_id: str,
    folder_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Browse one folder level (or search) of a file connector as THIS user.

    Returns ``{items: [...], folder_id}``. Each item is
    ``{id, name, is_folder, mime_type, size, modified_at, web_url}``. Subfolders
    are included (``is_folder=True``) so the FE can navigate.
    """
    _ensure_enabled()
    connection = await _load_connection(db, connection_id, organization)
    await _check_access(db, organization, current_user, connection)
    _require_browsable(connection)

    client = await _build_user_client(db, connection, current_user)

    try:
        if q:
            raw = client.search_files(q) or []
        elif hasattr(client, "list_children"):
            raw = client.list_children(folder_id) or []
        else:
            # Fallback: a client whose list_files already includes folders.
            raw = client.list_files(folder_id=folder_id) or []
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - fail-soft: never a 500 trace
        logger.warning("file-browser: browse failed for connection %s: %s", connection.id, e)
        raise HTTPException(status_code=502, detail="Could not list files from the source.")

    items = [_normalize(it) for it in raw if isinstance(it, dict)]
    return {"items": items, "folder_id": folder_id}


class IngestRequest(BaseModel):
    file_ids: List[str]
    studio_id: Optional[str] = None
    data_source_name: Optional[str] = None


async def _bind_studio(db: AsyncSession, *, org_id: str, studio_id: str, data_source_id: str) -> Optional[str]:
    """Pin a created DataSource to a Studio via StudioDataSource (fail-soft).

    Mirrors routes/sync.py ``_ensure_studio_link``: org-scoped Studio check,
    StudioDataSource has only ``studio_id`` + ``agent_id`` (agent_id == the
    DataSource id). Returns the studio_id on success, else None.
    """
    from app.models.studio import Studio, StudioDataSource

    try:
        studio = (
            await db.execute(
                select(Studio).where(
                    Studio.id == studio_id,
                    Studio.organization_id == org_id,
                    Studio.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if studio is None:
            return None
        existing = (
            await db.execute(
                select(StudioDataSource).where(
                    StudioDataSource.studio_id == studio_id,
                    StudioDataSource.agent_id == data_source_id,
                    StudioDataSource.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(StudioDataSource(studio_id=studio_id, agent_id=data_source_id))
            await db.commit()
        return studio_id
    except Exception:  # noqa: BLE001 - binding is best-effort
        logger.warning("file-browser: studio bind failed for studio %s", studio_id, exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


@router.post("/{connection_id}/files/ingest")
async def ingest_connection_files(
    connection_id: str,
    payload: IngestRequest,
    current_user: User = Depends(current_user),
    db: AsyncSession = Depends(get_async_db),
    organization: Organization = Depends(get_current_organization),
):
    """Ingest one or more picked files into queryable Data Agents (per-user).

    For each file_id: fetch the raw bytes from the source as THIS user, hand them
    to ``file_service.upload_file`` (as an UploadFile-like), then
    ``create_data_source_from_file`` — the exact lane POST /data_sources/from-file
    uses. Optionally pins each created DataSource to ``studio_id``.

    Partial-success friendly: returns ``{ingested: [...], errors: [...]}``.
    """
    _ensure_enabled()
    connection = await _load_connection(db, connection_id, organization)
    await _check_access(db, organization, current_user, connection)
    _require_browsable(connection)

    client = await _build_user_client(db, connection, current_user)

    file_ids = [f for f in (payload.file_ids or []) if f]
    if not file_ids:
        raise HTTPException(status_code=400, detail="Provide at least one file_id to ingest.")

    # Capture scalars up-front: create_data_source_from_file commits internally,
    # which expires every ORM object in this session (greenlet landmine).
    org_id = str(organization.id)

    from io import BytesIO
    from starlette.datastructures import Headers, UploadFile as StarletteUploadFile

    from app.services.file_service import FileService
    from app.routes.data_source_from_file import (
        DataSourceFromFileRequest,
        create_data_source_from_file,
    )

    file_service = FileService()
    ingested: List[dict] = []
    errors: List[dict] = []

    for file_id in file_ids:
        try:
            # 1. Fetch raw bytes + original filename as THIS user.
            if hasattr(client, "read_file_bytes"):
                name, content = client.read_file_bytes(file_id, max_bytes=_MAX_INGEST_BYTES)
            else:
                # Last-resort: read_file may already return bytes for unknown types.
                raw = client.read_file(file_id, max_bytes=_MAX_INGEST_BYTES)
                content = raw if isinstance(raw, (bytes, bytearray)) else None
                name = file_id
                if content is None:
                    raise ValueError("Client cannot return raw bytes for this file")

            if not content:
                raise ValueError("File is empty or unreadable")

            # 2. Persist the bytes as a File row via the standard upload lane.
            upload = StarletteUploadFile(
                file=BytesIO(bytes(content)),
                filename=name,
                headers=Headers({"content-type": "application/octet-stream"}),
            )
            file_schema = await file_service.upload_file(
                db=db,
                file=upload,
                current_user=current_user,
                organization=organization,
            )

            # 3. Turn the File into a Data Agent (reuses dedup / same-schema merge).
            #    NOTE: commits internally → org/user ORM objects are now expired;
            #    only touch captured strings / the returned dict afterwards.
            req = DataSourceFromFileRequest(
                file_id=str(file_schema.id),
                data_source_name=(payload.data_source_name or None),
            )
            result = await create_data_source_from_file(
                req,
                current_user=current_user,
                db=db,
                organization=organization,
            )
            data_source_id = (result or {}).get("id")
            data_source_id = str(data_source_id) if data_source_id else None
            ds_name = (result or {}).get("name") or name

            entry = {"file_id": file_id, "data_source_id": data_source_id, "name": ds_name}

            # 4. Optional Studio pin (fail-soft).
            if payload.studio_id and data_source_id:
                bound = await _bind_studio(
                    db, org_id=org_id, studio_id=payload.studio_id, data_source_id=data_source_id
                )
                if bound:
                    entry["studio_id"] = bound

            ingested.append(entry)
        except HTTPException as e:
            errors.append({"file_id": file_id, "error": str(e.detail)})
        except Exception as e:  # noqa: BLE001 - one bad file must not sink the batch
            logger.warning("file-browser: ingest failed for file %s: %s", file_id, e)
            errors.append({"file_id": file_id, "error": str(e)})
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass

    return {"ingested": ingested, "errors": errors}
