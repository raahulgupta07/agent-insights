from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ServiceAccountCreate(BaseModel):
    name: str
    description: Optional[str] = None


class ServiceAccountUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # Set False to disable the account (its keys are rejected at auth time),
    # True to re-enable.
    is_active: Optional[bool] = None


class ServiceAccountKeyInfo(BaseModel):
    """A key as shown in list/get responses — NEVER includes the plaintext
    token, only the display prefix + lifecycle timestamps."""
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceAccountResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    created_by_user_id: Optional[str] = None
    key_count: int = 0
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ServiceAccountDetail(ServiceAccountResponse):
    keys: List[ServiceAccountKeyInfo] = []


class ServiceAccountKeyCreate(BaseModel):
    name: str = "Default"
    expires_at: Optional[datetime] = None


class ServiceAccountKeyCreated(ServiceAccountKeyInfo):
    """Issue-key RESPONSE — includes the plaintext token EXACTLY ONCE.

    This is the ONLY response shape that carries ``token``. List/get responses
    use ``ServiceAccountKeyInfo`` (no plaintext). The caller must store it now;
    only the SHA-256 hash is persisted server-side, so it can never be shown
    again.
    """
    token: str
