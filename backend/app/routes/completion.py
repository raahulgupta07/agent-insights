from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import Optional
from app.dependencies import get_db
from app.services.completion_service import CompletionService
from app.schemas.completion_v2_schema import CompletionCreate, CompletionContextEstimateSchema
from app.schemas.sse_schema import SSEEvent, format_sse_event
from app.streaming.completion_stream import CompletionEventQueue
from app.websocket_manager import websocket_manager
from app.models.user import User
from app.core.auth import current_user
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_async_db
import json
import asyncio
from fastapi import Request
from fastapi.responses import StreamingResponse
import time
from app.core.permissions_decorator import requires_permission
from app.models.organization import Organization
from app.dependencies import get_current_organization, enforce_org_quota
from app.models.report import Report

router = APIRouter(tags=["completions"])

completion_service = CompletionService()

@router.post("/api/reports/{report_id}/completions/estimate", response_model=CompletionContextEstimateSchema)
@requires_permission('create_reports')
async def estimate_completion_tokens(
    report_id: str,
    completion: CompletionCreate,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db)
):
    return await completion_service.estimate_completion_tokens(
        db,
        report_id,
        completion,
        current_user,
        organization,
    )

@router.post("/api/reports/{report_id}/completions")
@requires_permission('create_reports')
async def create_completion(
    report_id: str,
    completion: CompletionCreate,
    request: Request,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db)
):
    """Unified completion endpoint.

    - Streams if: body `stream: true`, or `Accept: text/event-stream`, or `?stream=true`
    - Otherwise returns JSON response
    """
    # Hybrid Phase 9: gated per-org quota guard (no-op unless HYBRID_QUOTAS=on).
    await enforce_org_quota(organization, db, metric="data_queries")
    accept_header = request.headers.get("accept", "")
    body_stream_flag = getattr(completion, "stream", None)
    query_stream_flag = request.query_params.get("stream", "false").lower() == "true"
    wants_stream = (
        (body_stream_flag is True)
        or ("text/event-stream" in accept_header.lower())
        or query_stream_flag
    )
    if wants_stream:
        return await completion_service.create_completion_stream(
            db,
            report_id,
            completion,
            current_user,
            organization,
        )

    # Default to no background execution unless explicitly overridden via `?background=true`
    background = request.query_params.get("background", "false").lower() == "true"
    return await completion_service.create_completion(
        db,
        report_id,
        completion,
        current_user,
        organization,
        background=background,
    )

@router.get("/api/reports/{report_id}/completions.legacy")
@requires_permission('view_reports', model=Report)
async def get_completions(report_id: str, current_user: User = Depends(current_user), organization: Organization = Depends(get_current_organization), db: AsyncSession = Depends(get_async_db)):
    return await completion_service.get_completions(db, report_id, organization, current_user)

async def _authenticate_websocket(websocket: WebSocket, db: AsyncSession) -> Optional[User]:
    """Resolve the caller for a report websocket.

    Browsers can't set headers on a WebSocket, so the primary channel is the
    `?token=` query param (JWT or bow_ API key). Also accepts an
    `Authorization: Bearer <jwt|bow_...>` header and an `X-API-Key: bow_...`
    header for non-browser clients. Returns the User or None (never raises).
    """
    query_token = websocket.query_params.get("token")
    auth_header = websocket.headers.get("authorization", "")
    header_api_key = websocket.headers.get("x-api-key")

    # 1) bow_ API keys (X-API-Key, ?token=bow_..., or Authorization: Bearer bow_...)
    candidate_key = None
    if header_api_key and header_api_key.startswith("bow_"):
        candidate_key = header_api_key
    elif query_token and query_token.startswith("bow_"):
        candidate_key = query_token
    elif auth_header.startswith("Bearer bow_"):
        candidate_key = auth_header[len("Bearer "):]
    if candidate_key:
        try:
            from app.services.api_key_service import ApiKeyService
            user = await ApiKeyService().get_user_by_api_key(db, candidate_key)
            if user is not None:
                return user
        except Exception:
            pass

    # 2) JWT (?token=<jwt> or Authorization: Bearer <jwt>)
    jwt_token = None
    if query_token and not query_token.startswith("bow_"):
        jwt_token = query_token
    elif auth_header.startswith("Bearer ") and not auth_header.startswith("Bearer bow_"):
        jwt_token = auth_header[len("Bearer "):]
    if jwt_token:
        try:
            from app.core.auth import UserManager, get_jwt_strategy
            from fastapi_users.db import SQLAlchemyUserDatabase
            user_manager = UserManager(SQLAlchemyUserDatabase(db, User))
            user = await get_jwt_strategy().read_token(jwt_token, user_manager)
            if user is not None:
                return user
        except Exception:
            pass

    return None


@router.websocket("/ws/api/reports/{report_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    report_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    # Authenticate BEFORE accepting: an unauthenticated caller must not be able
    # to subscribe to a report's live event stream. Close with 1008 (policy
    # violation) on failure.
    user = await _authenticate_websocket(websocket, db)
    if user is None:
        await websocket.accept()
        await websocket.close(code=1008)
        return

    print(f"=== websocket_endpoint for report {report_id} (user {user.id}) ===")
    try:
        await websocket_manager.connect(websocket, report_id)
        
        # Start keep-alive task
        keep_alive_task = asyncio.create_task(websocket_manager.keep_alive(websocket))
        
        while True:
            try:
                data = await websocket.receive_text()
                if data == "pong":  # Handle ping-pong
                    continue
                print(f"Received data: {data}")
                # Handle incoming data if necessary
            except WebSocketDisconnect:
                break
    except Exception as e:
        print(f"Error in WebSocket connection: {e}")
    finally:
        websocket_manager.disconnect(websocket, report_id)
        if 'keep_alive_task' in locals():
            keep_alive_task.cancel()

@requires_permission('manage_settings')
@router.get("/api/completions/{completion_id}/plans")
async def get_completion_plans(completion_id: str, current_user: User = Depends(current_user), organization: Organization = Depends(get_current_organization), db: AsyncSession = Depends(get_async_db)):
    return await completion_service.get_completion_plans(db, current_user, organization, completion_id)


@router.get("/api/reports/{report_id}/completions")
@requires_permission('view_reports', model=Report)
async def get_completions_v2(
    report_id: str,
    limit: int = 10,
    before: str | None = None,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db)
):
    """New UI-focused completions response with ordered blocks and artifacts.

    - limit: last N completions (user+system), default 10
    - before: ISO datetime cursor to fetch items strictly before it
    """
    return await completion_service.get_completions_v2(db, report_id, organization, current_user, limit=limit, before=before)

@requires_permission('create_reports')
@router.post("/api/completions/{completion_id}/sigkill")
async def update_completion_sigkill(completion_id: str, current_user: User = Depends(current_user), organization: Organization = Depends(get_current_organization), db: AsyncSession = Depends(get_async_db)):
    return await completion_service.update_completion_sigkill(db, completion_id, current_user, organization)


@requires_permission('create_reports')
@router.post("/api/completions/{completion_id}/tool-results/{tool_call_id}")
async def submit_tool_result(
    completion_id: str,
    tool_call_id: str,
    body: dict,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db),
):
    """Accept an Office.js execution result from the Excel taskpane and resolve
    the waiting tool future. Used by the write_officejs_code tool."""
    return await completion_service.submit_tool_result(db, completion_id, tool_call_id, body, current_user, organization)


@requires_permission('create_reports')
@router.post("/api/completions/{completion_id}/tool_executions/{tool_execution_id}/clarify_response")
async def submit_clarify_response(
    completion_id: str,
    tool_execution_id: str,
    body: dict,
    current_user: User = Depends(current_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_async_db),
):
    """Persist the user's selections from the clarify tool form so the UI can
    rehydrate them on reload (and across devices)."""
    return await completion_service.submit_clarify_response(
        db, completion_id, tool_execution_id, body, current_user, organization
    )