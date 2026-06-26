"""User-owned groups service (HYBRID_USER_GROUPS).

CRUD for personal contact groups: a ``Group`` row with ``owner_user_id`` set.
Org/admin/LDAP groups (``owner_user_id`` NULL) are NEVER returned or mutated
here — every query is scoped to ``owner_user_id == current_user.id`` AND the
current org, so this surface cannot touch the RBAC/admin group set.

Mirrors rbac_service style: async, AsyncSession, ``select()``, HTTPException for
errors. Membership reuses the existing ``GroupMembership`` table (user_id rows).
``shared_count`` counts ResourceGrant rows where the group is the principal.
"""
import logging
from typing import List, Optional
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.models.group import Group
from app.models.group_membership import GroupMembership
from app.models.resource_grant import ResourceGrant
from app.models.user import User
from app.models.membership import Membership
from app.schemas.me_groups_schema import (
    MyGroupSchema, MyGroupMemberSchema, ContactSchema,
    MyGroupCreate, MyGroupUpdate,
)

logger = logging.getLogger(__name__)


class MeGroupsService:

    # ── helpers ────────────────────────────────────────────────────────────

    async def _get_owned_group(
        self, db: AsyncSession, org_id: str, user_id: str, group_id: str
    ) -> Group:
        """Load a group the caller OWNS in this org, or raise 404 / 403.

        404 when the group doesn't exist in this org. 403 when it exists but is
        owned by someone else / is an org group (owner_user_id NULL).
        """
        result = await db.execute(
            select(Group).where(
                Group.id == group_id,
                Group.organization_id == org_id,
                Group.deleted_at.is_(None),
            )
        )
        group = result.scalar_one_or_none()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        if group.owner_user_id != user_id:
            raise HTTPException(status_code=403, detail="You do not own this group")
        return group

    async def _members_for_groups(
        self, db: AsyncSession, group_ids: List[str]
    ) -> dict:
        """Return {group_id: [MyGroupMemberSchema, ...]} for registered users."""
        if not group_ids:
            return {}
        result = await db.execute(
            select(GroupMembership)
            .options(selectinload(GroupMembership.user))
            .where(
                GroupMembership.group_id.in_(group_ids),
                GroupMembership.user_id.isnot(None),
                GroupMembership.deleted_at.is_(None),
            )
        )
        out: dict = {gid: [] for gid in group_ids}
        for m in result.scalars().all():
            out.setdefault(m.group_id, []).append(MyGroupMemberSchema(
                user_id=m.user_id,
                name=m.user.name if m.user else None,
                email=m.user.email if m.user else None,
            ))
        return out

    async def _shared_counts(self, db: AsyncSession, org_id: str, group_ids: List[str]) -> dict:
        """Return {group_id: shared_count} = # resource grants where the group
        is the principal (i.e. how many resources are shared with the group)."""
        if not group_ids:
            return {}
        result = await db.execute(
            select(ResourceGrant.principal_id, func.count(ResourceGrant.id))
            .where(
                ResourceGrant.organization_id == org_id,
                ResourceGrant.principal_type == "group",
                ResourceGrant.principal_id.in_(group_ids),
                ResourceGrant.deleted_at.is_(None),
            )
            .group_by(ResourceGrant.principal_id)
        )
        return {pid: cnt for pid, cnt in result.all()}

    def _to_schema(
        self, group: Group, members: List[MyGroupMemberSchema], shared_count: int
    ) -> MyGroupSchema:
        return MyGroupSchema(
            id=str(group.id),
            name=group.name,
            description=group.description,
            member_count=len(members),
            members=members,
            shared_count=shared_count,
        )

    # ── list ───────────────────────────────────────────────────────────────

    async def list_my_groups(
        self, db: AsyncSession, org_id: str, user_id: str
    ) -> List[MyGroupSchema]:
        result = await db.execute(
            select(Group)
            .where(
                Group.organization_id == org_id,
                Group.owner_user_id == user_id,
                Group.deleted_at.is_(None),
            )
            .order_by(Group.name)
        )
        groups = list(result.scalars().all())
        if not groups:
            return []
        gids = [str(g.id) for g in groups]
        members_by_group = await self._members_for_groups(db, gids)
        shared_by_group = await self._shared_counts(db, org_id, gids)
        return [
            self._to_schema(
                g,
                members_by_group.get(str(g.id), []),
                shared_by_group.get(str(g.id), 0),
            )
            for g in groups
        ]

    async def get_my_group(
        self, db: AsyncSession, org_id: str, user_id: str, group_id: str
    ) -> MyGroupSchema:
        group = await self._get_owned_group(db, org_id, user_id, group_id)
        gid = str(group.id)
        members = (await self._members_for_groups(db, [gid])).get(gid, [])
        shared = (await self._shared_counts(db, org_id, [gid])).get(gid, 0)
        return self._to_schema(group, members, shared)

    # ── create ─────────────────────────────────────────────────────────────

    async def create_my_group(
        self, db: AsyncSession, org_id: str, user_id: str, data: MyGroupCreate
    ) -> MyGroupSchema:
        group = Group(
            organization_id=org_id,
            name=data.name,
            description=data.description,
            owner_user_id=user_id,
        )
        db.add(group)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            # (organization_id, name) unique constraint
            raise HTTPException(
                status_code=409,
                detail="A group with this name already exists in this organization",
            )

        # Members: requested ids (validated as org members) + the creator.
        wanted = list(data.member_user_ids or [])
        wanted.append(user_id)
        await self._add_members(db, org_id, str(group.id), wanted, commit=False)

        await db.commit()
        await db.refresh(group)
        return await self.get_my_group(db, org_id, user_id, str(group.id))

    # ── update ─────────────────────────────────────────────────────────────

    async def update_my_group(
        self, db: AsyncSession, org_id: str, user_id: str, group_id: str, data: MyGroupUpdate
    ) -> MyGroupSchema:
        group = await self._get_owned_group(db, org_id, user_id, group_id)
        if data.name is not None:
            group.name = data.name
        if data.description is not None:
            group.description = data.description
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="A group with this name already exists in this organization",
            )
        return await self.get_my_group(db, org_id, user_id, group_id)

    # ── delete ─────────────────────────────────────────────────────────────

    async def delete_my_group(
        self, db: AsyncSession, org_id: str, user_id: str, group_id: str
    ) -> None:
        group = await self._get_owned_group(db, org_id, user_id, group_id)
        await db.delete(group)  # memberships cascade (Group.memberships cascade)
        await db.commit()

    # ── members ────────────────────────────────────────────────────────────

    async def _org_member_user_ids(self, db: AsyncSession, org_id: str) -> set:
        """Set of user_ids that are registered members of this org."""
        result = await db.execute(
            select(Membership.user_id).where(
                Membership.organization_id == org_id,
                Membership.user_id.isnot(None),
            )
        )
        return {row[0] for row in result.all()}

    async def _add_members(
        self, db: AsyncSession, org_id: str, group_id: str,
        user_ids: List[str], commit: bool = True,
    ) -> None:
        """Add registered org members to a group (idempotent). Non-members are
        rejected with 400. Existing memberships are skipped silently."""
        if not user_ids:
            return
        # de-dup, preserve order
        seen: set = set()
        wanted = [u for u in user_ids if u and not (u in seen or seen.add(u))]

        org_members = await self._org_member_user_ids(db, org_id)
        invalid = [u for u in wanted if u not in org_members]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Not organization members: {', '.join(invalid)}",
            )

        existing_result = await db.execute(
            select(GroupMembership.user_id).where(
                GroupMembership.group_id == group_id,
                GroupMembership.user_id.in_(wanted),
            )
        )
        already = {row[0] for row in existing_result.all()}
        for uid in wanted:
            if uid in already:
                continue
            db.add(GroupMembership(group_id=group_id, user_id=uid))

        if commit:
            await db.commit()

    async def add_members(
        self, db: AsyncSession, org_id: str, user_id: str, group_id: str,
        user_ids: List[str],
    ) -> MyGroupSchema:
        await self._get_owned_group(db, org_id, user_id, group_id)
        if not user_ids:
            raise HTTPException(status_code=400, detail="Provide at least one user_id")
        await self._add_members(db, org_id, group_id, user_ids, commit=True)
        return await self.get_my_group(db, org_id, user_id, group_id)

    async def remove_member(
        self, db: AsyncSession, org_id: str, user_id: str, group_id: str, member_user_id: str
    ) -> None:
        await self._get_owned_group(db, org_id, user_id, group_id)
        result = await db.execute(
            select(GroupMembership).where(
                GroupMembership.group_id == group_id,
                GroupMembership.user_id == member_user_id,
            )
        )
        gm = result.scalar_one_or_none()
        if not gm:
            raise HTTPException(status_code=404, detail="Group membership not found")
        await db.delete(gm)
        await db.commit()

    # ── contacts (org members for the picker) ───────────────────────────────

    async def list_contacts(
        self, db: AsyncSession, org_id: str, q: Optional[str] = None, limit: int = 200
    ) -> List[ContactSchema]:
        """Org members offered to the share/group picker as {user_id,name,email}.

        Reuses the org-members query (Membership -> User). Only registered users
        (user_id set) are returned. Optional case-insensitive ``q`` filter on
        name/email. Capped at ``limit`` (default 200)."""
        stmt = (
            select(Membership)
            .options(selectinload(Membership.user))
            .where(
                Membership.organization_id == org_id,
                Membership.user_id.isnot(None),
            )
        )
        result = await db.execute(stmt)
        memberships = result.scalars().all()

        ql = q.strip().lower() if q else None
        out: List[ContactSchema] = []
        for m in memberships:
            user = m.user
            if not user:
                continue
            name = user.name or ""
            email = user.email or ""
            if ql and ql not in name.lower() and ql not in email.lower():
                continue
            out.append(ContactSchema(
                user_id=str(user.id),
                name=user.name,
                email=user.email,
            ))
            if len(out) >= limit:
                break
        return out


me_groups_service = MeGroupsService()
