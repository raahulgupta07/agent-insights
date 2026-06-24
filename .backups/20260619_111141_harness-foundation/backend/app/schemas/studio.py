from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from app.schemas.base import OptionalUTCDatetime


class StudioRole(str, Enum):
    """Effective role a user holds on a Studio."""
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class StudioShareScope(str, Enum):
    """Sharing scope for a Studio."""
    private = "private"   # members only
    org = "org"           # every org member is a viewer
    link = "link"         # public read-only token (deferred behind ST6)


class StudioCreate(BaseModel):
    name: str
    description: Optional[str] = None
    persona: Optional[str] = None
    avatar: Optional[str] = None
    share_scope: StudioShareScope = StudioShareScope.private
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class StudioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    persona: Optional[str] = None
    avatar: Optional[str] = None
    share_scope: Optional[StudioShareScope] = None
    config: Optional[Dict[str, Any]] = None


class StudioResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    persona: Optional[str] = None
    avatar: Optional[str] = None
    owner_user_id: str
    organization_id: str
    share_scope: str
    share_token: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None

    class Config:
        from_attributes = True


class StudioMemberResponse(BaseModel):
    id: str
    studio_id: str
    user_id: str
    role: str
    user_name: Optional[str] = None   # resolved display name (echo-only)
    user_email: Optional[str] = None  # resolved email (echo-only)
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None

    class Config:
        from_attributes = True
