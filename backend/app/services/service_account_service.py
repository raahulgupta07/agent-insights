import logging
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_account import ServiceAccount
from app.models.api_key import ApiKey
from app.models.user import User
from app.models.organization import Organization
from app.services.api_key_service import ApiKeyService
from app.schemas.service_account_schema import (
    ServiceAccountCreate, ServiceAccountUpdate, ServiceAccountResponse,
    ServiceAccountDetail, ServiceAccountKeyInfo, ServiceAccountKeyCreate,
    ServiceAccountKeyCreated,
)

logger = logging.getLogger(__name__)


class ServiceAccountService:
    """CRUD for service accounts + their API keys.

    Every method is org-scoped: a service account (and its keys) is only
    reachable through ``_get_sa_or_404``, which filters on
    ``organization_id`` — a caller from another org gets a 404 (no existence
    leak). Keys reuse the fork's ``api_keys`` table + ``ApiKeyService``
    generator (``bow_`` prefix, SHA-256 hash); only the hash + a 12-char
    display prefix are stored, and the plaintext is returned exactly once at
    issue time.
    """

    def __init__(self):
        self._api_key_service = ApiKeyService()

    # ── helpers ──────────────────────────────────────────────────────────

    async def _get_sa_or_404(self, db: AsyncSession, org_id: str, sa_id: str) -> ServiceAccount:
        result = await db.execute(
            select(ServiceAccount).where(
                ServiceAccount.id == sa_id,
                ServiceAccount.organization_id == org_id,
                ServiceAccount.deleted_at.is_(None),
            )
        )
        sa = result.scalar_one_or_none()
        if not sa:
            raise HTTPException(status_code=404, detail="Service account not found")
        return sa

    async def _key_stats(self, db: AsyncSession, sa_id: str) -> Tuple[int, Optional[datetime]]:
        result = await db.execute(
            select(func.count(ApiKey.id), func.max(ApiKey.last_used_at)).where(
                ApiKey.service_account_id == sa_id,
                ApiKey.deleted_at.is_(None),
            )
        )
        count, last_used = result.one()
        return int(count or 0), last_used

    async def _to_response(self, db: AsyncSession, sa: ServiceAccount) -> ServiceAccountResponse:
        count, last_used = await self._key_stats(db, sa.id)
        return ServiceAccountResponse(
            id=sa.id,
            name=sa.name,
            description=sa.description,
            is_active=bool(sa.is_active),
            created_at=sa.created_at,
            created_by_user_id=sa.created_by_user_id,
            key_count=count,
            last_used_at=last_used,
        )

    # ── accounts ─────────────────────────────────────────────────────────

    async def list_service_accounts(self, db: AsyncSession, org: Organization) -> List[ServiceAccountResponse]:
        result = await db.execute(
            select(ServiceAccount)
            .where(
                ServiceAccount.organization_id == org.id,
                ServiceAccount.deleted_at.is_(None),
            )
            .order_by(ServiceAccount.created_at.desc())
        )
        return [await self._to_response(db, sa) for sa in result.scalars().all()]

    async def create_service_account(
        self, db: AsyncSession, data: ServiceAccountCreate, creator: User, org: Organization,
    ) -> ServiceAccountResponse:
        sa = ServiceAccount(
            organization_id=org.id,
            name=data.name,
            description=data.description,
            created_by_user_id=str(creator.id),
            is_active=True,
        )
        db.add(sa)
        await db.commit()
        await db.refresh(sa)
        return await self._to_response(db, sa)

    async def get_service_account(self, db: AsyncSession, org: Organization, sa_id: str) -> ServiceAccountDetail:
        sa = await self._get_sa_or_404(db, org.id, sa_id)
        base = await self._to_response(db, sa)
        keys_result = await db.execute(
            select(ApiKey)
            .where(ApiKey.service_account_id == sa.id, ApiKey.deleted_at.is_(None))
            .order_by(ApiKey.created_at.desc())
        )
        keys = [ServiceAccountKeyInfo.model_validate(k) for k in keys_result.scalars().all()]
        return ServiceAccountDetail(**base.model_dump(), keys=keys)

    async def update_service_account(
        self, db: AsyncSession, org: Organization, sa_id: str, data: ServiceAccountUpdate,
    ) -> ServiceAccountResponse:
        sa = await self._get_sa_or_404(db, org.id, sa_id)
        if data.name is not None:
            sa.name = data.name
        if data.description is not None:
            sa.description = data.description
        if data.is_active is not None:
            sa.is_active = data.is_active
        await db.commit()
        await db.refresh(sa)
        return await self._to_response(db, sa)

    async def delete_service_account(self, db: AsyncSession, org: Organization, sa_id: str) -> None:
        sa = await self._get_sa_or_404(db, org.id, sa_id)
        now = datetime.utcnow()
        sa.deleted_at = now
        sa.is_active = False
        # Revoke + soft-delete all its keys so none can authenticate afterwards.
        keys = await db.execute(
            select(ApiKey).where(ApiKey.service_account_id == sa.id, ApiKey.deleted_at.is_(None))
        )
        for k in keys.scalars().all():
            if k.revoked_at is None:
                k.revoked_at = now
            k.deleted_at = now
        await db.commit()

    # ── keys ─────────────────────────────────────────────────────────────

    async def issue_key(
        self, db: AsyncSession, org: Organization, sa_id: str, data: ServiceAccountKeyCreate,
    ) -> ServiceAccountKeyCreated:
        sa = await self._get_sa_or_404(db, org.id, sa_id)
        # Reuse the fork's generator: bow_<token_urlsafe(32)>, SHA-256 hash,
        # 12-char display prefix. Store hash + prefix only; return plaintext once.
        full_key, key_hash, key_prefix = self._api_key_service._generate_api_key()
        key = ApiKey(
            user_id=None,  # service-account key — no backing human user
            organization_id=org.id,
            service_account_id=sa.id,
            name=data.name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            expires_at=data.expires_at,
        )
        db.add(key)
        await db.commit()
        await db.refresh(key)
        return ServiceAccountKeyCreated(
            id=key.id,
            name=key.name,
            key_prefix=key.key_prefix,
            created_at=key.created_at,
            last_used_at=key.last_used_at,
            revoked_at=key.revoked_at,
            expires_at=key.expires_at,
            token=full_key,
        )

    async def revoke_key(self, db: AsyncSession, org: Organization, sa_id: str, key_id: str) -> None:
        # Org-scope via the account, then verify the key belongs to it.
        sa = await self._get_sa_or_404(db, org.id, sa_id)
        result = await db.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.service_account_id == sa.id,
                ApiKey.deleted_at.is_(None),
            )
        )
        key = result.scalar_one_or_none()
        if not key:
            raise HTTPException(status_code=404, detail="API key not found")
        if key.revoked_at is None:
            key.revoked_at = datetime.utcnow()
        await db.commit()
