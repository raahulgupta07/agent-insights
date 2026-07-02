from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func

from app.models.base import BaseSchema


class ConnectorSyncRun(BaseSchema):
    """Live per-clone sync run — a DB-backed, cross-worker-safe log of a per-user
    connector clone build (connect → sync tables → learn). One row per clone
    (data_source_id is UNIQUE, upserted) so the frontend can poll a CLI-style
    terminal of the sync regardless of which uvicorn worker served the request.

    See services/connector_sync.py (helpers) and
    services/per_user_connector.py::sync_clone_bg (the background writer).
    """
    __tablename__ = "connector_sync_run"
    __table_args__ = (
        UniqueConstraint("data_source_id", name="uq_connector_sync_run_data_source"),
    )

    # One live run row per clone (upsert key).
    data_source_id = Column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id = Column(
        String(36), ForeignKey("organizations.id"), nullable=False, index=True
    )
    # connecting | syncing | learning | done | error
    phase = Column(String, nullable=False, default="connecting")
    tables_total = Column(Integer, nullable=False, default=0)
    tables_done = Column(Integer, nullable=False, default=0)
    # Best-effort cumulative rows; may stay 0 if counts are unavailable.
    rows = Column(Integer, nullable=False, default=0)
    # List of {ts, level, table?, msg}; level ∈ step|ok|active|error
    log = Column(JSON, nullable=False, default=list)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
