from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_async_db
from app.services.external_platform_manager import ExternalPlatformManager
from app.services.platform_adapters.adapter_factory import PlatformAdapterFactory
from app.models.external_platform import ExternalPlatform
import json
import os

router = APIRouter(tags=["teams-webhook"])

platform_manager = ExternalPlatformManager()

# In-memory fallback dedupe (single-worker/dev only when REDIS_URL is unset).
processed_events = set()

# Cross-worker dedupe: Redis SETNX+TTL shared by all `--workers N` processes so a
# Bot Connector retry can't fire a duplicate agent run on a different worker.
_DEDUPE_TTL = 3600  # seconds
_redis = None
_redis_init = False


async def _get_redis():
    """Lazily connect to Redis; return a client or None (→ in-memory fallback)."""
    global _redis, _redis_init
    if _redis_init:
        return _redis
    _redis_init = True
    url = os.environ.get("REDIS_URL")
    if not url:
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(url, encoding="utf-8", decode_responses=True)
        await client.ping()
        _redis = client
    except Exception as e:
        print(f"teams_webhook: Redis unavailable ({e}); using in-memory dedupe")
        _redis = None
    return _redis


async def _seen_before(activity_id: str) -> bool:
    """True if activity_id was already processed. Redis-backed (cross-worker) when
    REDIS_URL is set, else the in-memory set (single-worker fallback)."""
    if not activity_id:
        return False
    client = await _get_redis()
    if client is not None:
        try:
            first = await client.set(f"dedupe:teams:{activity_id}", "1", nx=True, ex=_DEDUPE_TTL)
            return not first
        except Exception as e:
            print(f"teams_webhook: Redis dedupe error ({e}); using in-memory fallback")
    if activity_id in processed_events:
        return True
    processed_events.add(activity_id)
    if len(processed_events) > 1000:
        processed_events.clear()
    return False


@router.post("/api/settings/integrations/teams/webhook")
async def teams_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
):
    """Handle Microsoft Teams webhook activities (Bot Connector v4)"""

    try:
        body = await request.body()
        activity = json.loads(body.decode("utf-8"))

        # Only process message activities; return 200 for everything else
        activity_type = activity.get("type")
        if activity_type != "message":
            print(f"TEAMS: Ignoring activity type: {activity_type}")
            return {"ok": True}

        # Extract tenant ID to find the right platform
        tenant_id = activity.get("channelData", {}).get("tenant", {}).get("id")

        # Find platform by tenant ID, or fall back to first active Teams platform
        # (Web Chat and Bot Framework Emulator don't send channelData.tenant.id)
        platform = None
        if tenant_id:
            platform = await find_platform_by_tenant_id(db, tenant_id)
        if not platform:
            platform = await find_any_teams_platform(db)
        if not platform:
            print(f"TEAMS: No platform found for tenant_id: {tenant_id}")
            return {"ok": True}

        # Verify JWT signature via adapter
        auth_header = request.headers.get("Authorization", "")
        adapter = PlatformAdapterFactory.create_adapter(platform)
        is_valid = await adapter.verify_webhook_signature(body, auth_header, "")
        if not is_valid:
            raise HTTPException(status_code=401, detail="Invalid token")

        # Skip bot's own messages
        from_id = activity.get("from", {}).get("id")
        app_id = platform.platform_config.get("app_id") or platform.decrypt_credentials().get("app_id")
        if from_id == app_id:
            print("TEAMS: Ignoring bot's own message")
            return {"ok": True}

        # Cross-worker deduplication by activity ID (Redis SETNX+TTL, in-mem fallback)
        activity_id = activity.get("id")
        if await _seen_before(activity_id):
            print(f"TEAMS: Activity {activity_id} already processed, skipping")
            return {"ok": True}

        # Skip empty messages
        text = activity.get("text", "").strip()
        if not text:
            print("TEAMS: Ignoring empty message")
            return {"ok": True}

        # Persist serviceUrl and bot identity on platform_config if changed
        service_url = activity.get("serviceUrl")
        bot_recipient = activity.get("recipient", {})
        updated_config = {**platform.platform_config}
        changed = False
        if service_url and updated_config.get("service_url") != service_url:
            updated_config["service_url"] = service_url
            changed = True
        if bot_recipient.get("id") and updated_config.get("bot_id") != bot_recipient["id"]:
            updated_config["bot_id"] = bot_recipient["id"]
            updated_config["bot_name"] = bot_recipient.get("name", "")
            changed = True
        if changed:
            platform.platform_config = updated_config
            await db.commit()

        # Route to manager
        result = await platform_manager.handle_incoming_message(
            db, "teams", platform.organization_id, activity, platform=platform
        )

        return {"ok": True, "result": result}

    except HTTPException:
        raise
    except Exception as e:
        print(f"TEAMS: Error in webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def find_platform_by_tenant_id(db: AsyncSession, tenant_id: str) -> ExternalPlatform:
    """Find platform by Teams tenant ID"""
    from sqlalchemy import select

    # Prefer per-agent (studio-bound) rows over org-wide (studio_id NOT NULL first).
    stmt = (
        select(ExternalPlatform)
        .where(
            ExternalPlatform.platform_type == "teams",
            ExternalPlatform.is_active.is_(True),
            ExternalPlatform.deleted_at.is_(None),
        )
        .order_by(ExternalPlatform.studio_id.is_(None).asc())
    )
    result = await db.execute(stmt)
    platforms = result.scalars().all()

    for platform in platforms:
        config = platform.platform_config or {}
        if config.get("tenant_id") == tenant_id:
            return platform

    return None


async def find_any_teams_platform(db: AsyncSession) -> ExternalPlatform:
    """Fallback: find any active Teams platform (for Web Chat / Emulator testing).
    Prefers a per-agent (studio-bound) row over the org-wide one."""
    from sqlalchemy import select

    stmt = (
        select(ExternalPlatform)
        .where(
            ExternalPlatform.platform_type == "teams",
            ExternalPlatform.is_active == True,
            ExternalPlatform.deleted_at.is_(None),
        )
        .order_by(ExternalPlatform.studio_id.is_(None).asc())
    )
    result = await db.execute(stmt)
    return result.scalars().first()
