from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from app.models.prompt import Prompt
from app.models.data_source import DataSource
from app.schemas.prompt_schema import PromptCreate, PromptUpdate
from app.models.user import User
from app.models.organization import Organization
from app.settings.hybrid_flags import flags


class PromptService:

    # ── #555 prompt READ visibility (HYBRID_PROMPT_SCOPE) ────────────────────
    # Mirrors the /agents list: an 'agent'-scoped prompt is visible only to
    # explicit members of ALL its mentioned agents (public agents count),
    # 'private' → owner only, 'global' → everyone; the owner always sees their
    # own. Write/manage authority is unchanged (routes keep the admin bypass).
    @staticmethod
    def _prompt_ds_ids(prompt: Prompt) -> List[str]:
        """Data-source ids a prompt is scoped to (best-effort from `mentions`).
        Mirrors routes/prompt.py::_data_sources_from_mentions."""
        ids: List[str] = []
        for group in (prompt.mentions or []):
            if not isinstance(group, dict):
                continue
            is_ds_group = ("data" in str(group.get("name", "")).lower()) or group.get("type") == "data_source"
            for it in (group.get("items") or []):
                if isinstance(it, dict) and (is_ds_group or it.get("type") == "data_source"):
                    did = it.get("id") or it.get("value")
                    if did:
                        ids.append(str(did))
        return ids

    @staticmethod
    async def _member_ds_ids(db: AsyncSession, user_id: str, organization: Organization) -> set:
        """Explicit-membership data-source ids — does NOT short-circuit on
        full_admin (that is the point: admins see the same agents they joined)."""
        from app.core.permission_resolver import get_member_data_source_ids
        return {str(x) for x in await get_member_data_source_ids(db, str(user_id), str(organization.id))}

    @staticmethod
    async def _public_ds_ids(db: AsyncSession, organization: Organization, ds_ids: set) -> set:
        if not ds_ids:
            return set()
        rows = await db.execute(
            select(DataSource.id).filter(
                DataSource.organization_id == organization.id,
                DataSource.id.in_(list(ds_ids)),
                DataSource.is_public == True,  # noqa: E712
            )
        )
        return {str(r) for r in rows.scalars().all()}

    def _is_visible(self, prompt: Prompt, user_id: str, member_ds_ids: set, public_ds_ids: set) -> bool:
        scope = prompt.scope or "agent"
        if scope == "global":
            return True
        if str(prompt.user_id) == str(user_id):   # owner always sees their own
            return True
        if scope == "private":
            return False
        # agent: visible to members of ALL mentioned agents (public counts);
        # hidden if it mentions no resolvable agent.
        ds_ids = self._prompt_ds_ids(prompt)
        if not ds_ids:
            return False
        return all((d in member_ds_ids or d in public_ds_ids) for d in ds_ids)

    async def create_prompt(self, db: AsyncSession, prompt: PromptCreate, current_user: User, organization: Organization) -> Prompt:
        db_prompt = Prompt(**prompt.dict())
        db_prompt.user_id = current_user.id
        db_prompt.organization_id = organization.id
        db.add(db_prompt)
        await db.commit()
        await db.refresh(db_prompt)
        return db_prompt

    async def get_prompts(self, db: AsyncSession, current_user: User, organization: Organization, skip: int = 0, limit: int = 100) -> List[Prompt]:
        stmt = select(Prompt).filter(Prompt.organization_id == organization.id).offset(skip).limit(limit)
        result = await db.execute(stmt)
        prompts = result.scalars().all()
        # #555: scope READ visibility to agent membership. Flag OFF (or no user)
        # = legacy behavior (every member sees every prompt). Fail-soft.
        if not flags.PROMPT_SCOPE or current_user is None:
            return prompts
        try:
            member = await self._member_ds_ids(db, current_user.id, organization)
            all_ds: set = set()
            for p in prompts:
                all_ds.update(self._prompt_ds_ids(p))
            public = await self._public_ds_ids(db, organization, all_ds)
            return [p for p in prompts if self._is_visible(p, str(current_user.id), member, public)]
        except Exception:
            return prompts

    async def get_prompt(self, db: AsyncSession, prompt_id: str, current_user: User = None, organization: Organization = None) -> Optional[Prompt]:
        stmt = select(Prompt).filter(Prompt.id == prompt_id)
        if organization is not None:
            stmt = stmt.filter(Prompt.organization_id == organization.id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_prompt_visible(self, db: AsyncSession, prompt_id: str, current_user: User, organization: Organization) -> Optional[Prompt]:
        """READ-path fetch that enforces #555 visibility. Returns None when the
        prompt exists but the caller may not see it (route → 404/403). Used by
        the GET-one route ONLY — update/delete keep using get_prompt so the
        write path (which has its own authority) is unchanged."""
        p = await self.get_prompt(db, prompt_id, current_user, organization)
        if p is None:
            return None
        if not flags.PROMPT_SCOPE or current_user is None:
            return p
        try:
            member = await self._member_ds_ids(db, current_user.id, organization)
            public = await self._public_ds_ids(db, organization, set(self._prompt_ds_ids(p)))
            return p if self._is_visible(p, str(current_user.id), member, public) else None
        except Exception:
            return p

    async def update_prompt(self, db: AsyncSession, prompt_id: str, prompt: PromptUpdate, current_user: User = None, organization: Organization = None) -> Optional[Prompt]:
        db_prompt = await self.get_prompt(db, prompt_id, current_user, organization)
        if db_prompt:
            for key, value in prompt.dict(exclude_unset=True).items():
                setattr(db_prompt, key, value)
            await db.commit()
            await db.refresh(db_prompt)
        return db_prompt

    async def delete_prompt(self, db: AsyncSession, prompt_id: str, current_user: User = None, organization: Organization = None) -> Optional[dict]:
        db_prompt = await self.get_prompt(db, prompt_id, current_user, organization)
        if not db_prompt:
            return None
        # Snapshot the columns BEFORE deleting: after commit the ORM instance is
        # expired, and touching its attributes in the sync response serializer
        # would trigger a MissingGreenlet lazy-load. A plain dict is version- and
        # session-agnostic and validates cleanly against PromptResponse.
        data = {
            'id': db_prompt.id,
            'title': db_prompt.title,
            'text': db_prompt.text,
            'mode': db_prompt.mode,
            'model_id': db_prompt.model_id,
            'mentions': db_prompt.mentions,
            'parameters': db_prompt.parameters,
            'scope': db_prompt.scope,
            'is_starter': db_prompt.is_starter,
            'user_id': db_prompt.user_id,
            'created_at': db_prompt.created_at,
        }
        await db.delete(db_prompt)
        await db.commit()
        return data
