from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.dependencies import get_async_db
from app.services.external_platform_manager import ExternalPlatformManager
from app.services.external_platform_service import ExternalPlatformService
from app.services.platform_adapters.adapter_factory import PlatformAdapterFactory
from app.models.external_platform import ExternalPlatform
import json
import hmac
import hashlib
import time
import os

router = APIRouter(tags=["slack-webhook"])

platform_manager = ExternalPlatformManager()
platform_service = ExternalPlatformService()

# Reject inbound requests whose signed timestamp is older than this (replay guard).
SLACK_MAX_SKEW_SECONDS = 60 * 5

# In-memory fallback dedupe (single-worker/dev only when REDIS_URL is unset).
processed_events = set()

# Cross-worker dedupe: Redis SETNX+TTL shared by all `--workers N` processes so a
# provider retry can't fire a duplicate agent run on a different worker.
_DEDUPE_TTL = 3600  # seconds — covers Slack's retry window
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
        print(f"slack_webhook: Redis unavailable ({e}); using in-memory dedupe")
        _redis = None
    return _redis


async def _seen_before(event_id: str) -> bool:
    """True if event_id was already processed. Redis-backed (cross-worker) when
    REDIS_URL is set, else the in-memory set (single-worker fallback)."""
    if not event_id:
        return False
    client = await _get_redis()
    if client is not None:
        try:
            # SET key 1 NX EX ttl → truthy on first sight, None if it already exists.
            first = await client.set(f"dedupe:slack:{event_id}", "1", nx=True, ex=_DEDUPE_TTL)
            return not first
        except Exception as e:
            print(f"slack_webhook: Redis dedupe error ({e}); using in-memory fallback")
    if event_id in processed_events:
        return True
    processed_events.add(event_id)
    if len(processed_events) > 1000:
        processed_events.clear()
    return False

@router.post("/api/settings/integrations/slack/webhook")
async def slack_webhook(
    request: Request,
    db: AsyncSession = Depends(get_async_db)
):
    """Handle Slack webhook events"""
    
    try:
        # Get request body
        body = await request.body()
        body_text = body.decode('utf-8')
        
        # Get headers
        slack_signature = request.headers.get('x-slack-signature', '')
        slack_timestamp = request.headers.get('x-slack-request-timestamp', '')
        
        # Parse JSON
        event_data = json.loads(body_text)
        
        # Handle URL verification challenge
        if event_data.get('type') == 'url_verification':
            return {"challenge": event_data.get('challenge')}
        
        # Get team ID to find the right platform
        team_id = event_data.get('team_id')
        if not team_id:
            raise HTTPException(status_code=400, detail="No team_id in event")

        # Find platform by team ID
        platform = await find_platform_by_team_id(db, team_id)
        if not platform:
            print(f"No platform found for team_id: {team_id}")
            return {"ok": True}  # Don't fail, just ignore

        # --- Signature verification (fail-closed) --------------------------------
        # Reject stale timestamps first (replay guard), then HMAC-verify the body
        # against the platform's Fernet-decrypted signing secret via the adapter.
        try:
            ts = int(slack_timestamp)
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Missing or invalid timestamp")
        if abs(time.time() - ts) > SLACK_MAX_SKEW_SECONDS:
            raise HTTPException(status_code=401, detail="Stale request timestamp")

        adapter = PlatformAdapterFactory.create_adapter(platform)
        is_valid = await adapter.verify_webhook_signature(body, slack_signature, slack_timestamp)
        if not is_valid:
            # Missing signing secret → adapter returns False → we reject (fail-closed).
            raise HTTPException(status_code=401, detail="Invalid signature")

        # Check if this is a bot message (ignore bot messages to prevent loops)
        event = event_data.get("event", {})
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            print("Ignoring bot message to prevent loops")
            return {"ok": True}

        # Check if this is an event_callback
        if event_data.get("type") != "event_callback":
            print(f"Ignoring non-event_callback: {event_data.get('type')}")
            return {"ok": True}

        # Accept both 'message' (DMs) and 'app_mention' (channel mentions) events
        event_type = event.get("type")
        if event_type not in ("message", "app_mention"):
            print(f"Ignoring unsupported event type: {event_type}")
            return {"ok": True}

        # Cross-worker deduplication using event_id (Redis SETNX+TTL, in-mem fallback)
        event_id = event_data.get('event_id')
        if await _seen_before(event_id):
            print(f"Event {event_id} already processed, skipping")
            return {"ok": True}

        # For DMs (message events), only process if channel_type is 'im'
        # For app_mention events, process regardless of channel type (they come from channels)
        if event_type == "message" and event.get('channel_type') != 'im':
            print(f"Ignoring non-DM message: {event.get('channel_type')}")
            return {"ok": True}

        # Skip if message is empty
        if not event.get('text', '').strip():
            print("Ignoring empty message")
            return {"ok": True}
        
        # Handle the event
        result = await platform_manager.handle_incoming_message(
            db, "slack", platform.organization_id, event_data, platform=platform
        )
        
        return {"ok": True, "result": result}

    except HTTPException:
        # Preserve verification/validation status codes (401/400) — don't mask as 500.
        raise
    except Exception as e:
        print(f"Error in Slack webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def find_platform_by_team_id(db: AsyncSession, team_id: str) -> ExternalPlatform:
    """Find platform by Slack team ID"""
    
    from sqlalchemy import select
    
    # Prefer per-agent (studio-bound) rows over the org-wide row when both match
    # the same workspace — so a Slack app wired to a specific agent answers from
    # that agent's data scope. studio_id NOT NULL sorts first.
    stmt = (
        select(ExternalPlatform)
        .where(
            ExternalPlatform.platform_type == "slack",
            ExternalPlatform.is_active.is_(True),
            ExternalPlatform.deleted_at.is_(None),
        )
        .order_by(ExternalPlatform.studio_id.is_(None).asc())
    )
    result = await db.execute(stmt)
    platforms = result.scalars().all()

    for platform in platforms:
        config = platform.platform_config or {}
        if config.get("team_id") == team_id:
            return platform

    return None
