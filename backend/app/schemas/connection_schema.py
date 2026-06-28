"""
Connection schemas for database connection management.
"""
from datetime import datetime
from typing import Any, Dict, Optional, List

from pydantic import BaseModel

from app.schemas.base import UTCDatetime


class ConnectionCreate(BaseModel):
    """Schema for creating a new database connection."""
    name: str
    type: str
    config: dict
    credentials: Optional[dict] = None
    auth_policy: str = "system_only"
    allowed_user_auth_modes: Optional[list] = None
    # "shared"  = org-wide connector (admin only; owner_user_id NULL, reusable).
    # "personal" = private connector owned by the creator (any user; owner forced
    #              to the session user server-side). Requires HYBRID_AGENT_CONNECTORS.
    scope: str = "shared"
    # 3-level connector VISIBILITY (management-plane sharing). When set, this WINS
    # over the legacy `scope` derive rule. One of:
    #   'private' = owner only.
    #   'shared'  = owner + specifically-granted users/groups.
    #   'org'     = all org members.
    # Any org member may self-service create at ANY level (non-private create
    # requires HYBRID_AGENT_CONNECTORS, same as personal). owner_user_id is always
    # the creator. Back-compat: when omitted, derived from `scope`
    # ('shared'->'org', else 'private').
    visibility: Optional[str] = None
    # Optional agent binding for a personal connector created from a studio's
    # Connectors page. When set (+ scope=personal), the connector is bound to that
    # studio (Connection.studio_id) so it lands in that agent's "My Connectors"
    # tab. Validated server-side (must be a studio in the caller's org). Ignored
    # for shared scope.
    studio_id: Optional[str] = None


class ConnectionUpdate(BaseModel):
    """Schema for updating an existing connection."""
    name: Optional[str] = None
    config: Optional[dict] = None
    credentials: Optional[dict] = None
    is_active: Optional[bool] = None
    auth_policy: Optional[str] = None  # system_only, user_required
    allowed_user_auth_modes: Optional[list] = None
    # Scheduled auto-reindex (enterprise `scheduled_reindex` feature).
    auto_reindex_enabled: Optional[bool] = None
    reindex_interval_hours: Optional[int] = None


class ConnectionSchema(BaseModel):
    """Schema for connection list view."""
    id: str
    name: str
    type: str
    is_active: bool
    auth_policy: str
    # User auth modes allowed for user_required connections (e.g. ["oauth"]).
    # The frontend uses this to skip the credentials modal and redirect
    # straight to the provider when OAuth is the only option.
    allowed_user_auth_modes: Optional[list] = None
    last_synced_at: Optional[str] = None
    organization_id: str
    table_count: int = 0
    tool_count: int = 0
    agent_count: int = 0
    agent_names: List[str] = []  # Names of linked agents (for delete confirmation)
    # Ownership tier: NULL = shared/org-wide connector; set = private to that user.
    # Lets the FE split "Shared" vs "My Connections". Never carries credentials.
    owner_user_id: Optional[str] = None
    # 3-level visibility for the management/list plane: 'private' | 'shared' |
    # 'org'. Lets the FE badge each connector. Never carries credentials.
    visibility: Optional[str] = None
    indexing: Optional[Dict[str, Any]] = None
    # Per-user auth status for the requesting user (user_required connections):
    # has_user_credentials / effective_auth / uses_fallback / connection.
    user_status: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ConnectionDetailSchema(BaseModel):
    """Extended schema for editing - includes config but not credentials (never sent back)."""
    id: str
    name: str
    type: str
    is_active: bool
    auth_policy: str
    allowed_user_auth_modes: Optional[list] = None
    config: dict  # Non-sensitive connection parameters
    last_synced_at: Optional[str] = None
    organization_id: str
    table_count: int = 0
    tool_count: int = 0
    agent_count: int = 0
    agent_names: List[str] = []  # Names of linked agents (for delete confirmation)
    has_credentials: bool = False  # Whether system credentials are set
    # Scheduled auto-reindex config (enterprise `scheduled_reindex` feature).
    auto_reindex_enabled: bool = True
    reindex_interval_hours: Optional[int] = None  # NULL -> default cadence
    next_retry_at: Optional[str] = None
    last_reindex_error: Optional[str] = None

    class Config:
        from_attributes = True


class ConnectionTableSchema(BaseModel):
    """Schema for connection table info."""
    id: str
    name: str
    column_count: int = 0
    
    class Config:
        from_attributes = True


class ConnectionTestOverride(BaseModel):
    """Optional overrides when testing a connection with new (unsaved) values."""
    config: Optional[dict] = None
    credentials: Optional[dict] = None


class ConnectionTestResult(BaseModel):
    """Schema for connection test results."""
    success: bool
    message: str
    connectivity: bool = False
    schema_access: bool = False
    table_count: int = 0
    # Optional richer info; older consumers ignore these.
    timings: Optional[Dict[str, float]] = None
    details: Optional[Dict[str, Any]] = None


class ConnectionIndexingProgress(BaseModel):
    """Lightweight payload inlined into the connection payload and returned
    from the indexing polling endpoint.
    """
    id: str
    status: str  # pending | running | completed | failed | cancelled
    phase: Optional[str] = None
    current_item: Optional[str] = None
    progress_done: int = 0
    progress_total: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    events: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True


class ConnectionIndexingSchema(ConnectionIndexingProgress):
    """Full indexing row (same shape today; kept separate for future expansion)."""
    connection_id: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

