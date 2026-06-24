from enum import Enum
from typing import Any, Dict, List, Optional

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


class StudioContentStatus(str, Enum):
    """Review state of an auto-born or hand-written studio rule/example."""
    pending = "pending"   # never reaches the model
    active = "active"     # approved -> injected by the context assembler


class StudioContentSource(str, Enum):
    """Origin of a studio rule/example."""
    auto = "auto"       # machine-generated (bootstrap / learning loop)
    manual = "manual"   # hand-written by a human


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


class StudioSourcePreview(BaseModel):
    """A trimmed pinned-source entry for the studio-card logo stack."""
    name: str
    type: Optional[str] = None


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
    bootstrap_state: Optional[Dict[str, Any]] = None
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None

    # --- Studio-card stats (ST card enrichment) -------------------------- #
    # All OPTIONAL with safe defaults so old/empty rows never break
    # serialization. Populated by the list + detail endpoints; absent fields
    # fall back to these defaults.
    source_count: int = 0                              # pinned sources
    member_count: int = 0                              # members (owner counts as 1)
    sources_preview: List[StudioSourcePreview] = Field(default_factory=list)  # first 3
    chat_count: int = 0                                # reports bound (Report.studio_id)
    last_active_at: OptionalUTCDatetime = None         # max bound-report timestamp
    eval_pass_rate: Optional[float] = None             # 0..1 across sources' evals; null if none
    activity_7d: List[int] = Field(default_factory=lambda: [0] * 7)  # chats/day, oldest->newest

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


class StudioInstructionCreate(BaseModel):
    content: str
    source: StudioContentSource = StudioContentSource.manual
    status: StudioContentStatus = StudioContentStatus.pending
    score: Optional[float] = None
    instruction_id: Optional[str] = None


class StudioInstructionResponse(BaseModel):
    id: str
    studio_id: str
    content: str
    source: str
    status: str
    score: Optional[float] = None
    instruction_id: Optional[str] = None
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None

    class Config:
        from_attributes = True


class StudioExampleCreate(BaseModel):
    question: str
    answer: str
    sql: Optional[str] = None
    source: StudioContentSource = StudioContentSource.manual
    status: StudioContentStatus = StudioContentStatus.pending
    score: Optional[float] = None


class StudioExampleResponse(BaseModel):
    id: str
    studio_id: str
    question: str
    answer: str
    sql: Optional[str] = None
    source: str
    status: str
    uses: int = 0
    score: Optional[float] = None
    created_at: OptionalUTCDatetime = None
    updated_at: OptionalUTCDatetime = None

    class Config:
        from_attributes = True
