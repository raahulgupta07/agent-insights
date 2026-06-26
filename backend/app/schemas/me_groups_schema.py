"""Pydantic schemas for user-owned groups (HYBRID_USER_GROUPS).

Request/response shapes for the /api/me/groups* + /api/me/contacts router.
Kept separate from rbac_schema (admin/org groups) so the user-facing surface
can evolve without touching the RBAC contract.
"""
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional


class ContactSchema(BaseModel):
    """An org member offered to the share/group picker."""
    user_id: str
    name: Optional[str] = None
    email: Optional[str] = None


class MyGroupMemberSchema(BaseModel):
    """A registered member of a user-owned group."""
    user_id: str
    name: Optional[str] = None
    email: Optional[str] = None


class MyGroupSchema(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    member_count: int = 0
    members: List[MyGroupMemberSchema] = []
    shared_count: int = 0


class MyGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    member_user_ids: List[str] = []

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Group name cannot be empty")
        return v


class MyGroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Group name cannot be empty")
        return v


class MyGroupMemberAdd(BaseModel):
    """Add one or many members. Prefer ``user_ids`` (batch); ``user_id`` is a
    single-add convenience. At least one must be provided."""
    user_id: Optional[str] = None
    user_ids: Optional[List[str]] = None

    def resolved_ids(self) -> List[str]:
        ids: List[str] = []
        if self.user_ids:
            ids.extend(self.user_ids)
        if self.user_id:
            ids.append(self.user_id)
        # de-dup, preserve order
        seen: set = set()
        out: List[str] = []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                out.append(i)
        return out
