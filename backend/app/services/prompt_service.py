from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from app.models.prompt import Prompt
from app.schemas.prompt_schema import PromptCreate, PromptUpdate
from app.models.user import User
from app.models.organization import Organization


class PromptService:

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
        return result.scalars().all()

    async def get_prompt(self, db: AsyncSession, prompt_id: str, current_user: User = None, organization: Organization = None) -> Optional[Prompt]:
        stmt = select(Prompt).filter(Prompt.id == prompt_id)
        if organization is not None:
            stmt = stmt.filter(Prompt.organization_id == organization.id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

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
