from sqlalchemy import Column, String, JSON, Integer, Boolean, Index
from app.models.base import BaseSchema


class UploadCache(BaseSchema):
    """File-hash -> extraction plan cache (cross-tenant).

    The robust Excel reader (5-layer) caches the resolved header/skip/unpivot
    plan keyed by file content sha256, so the same vendor template uploaded by
    any org reuses the plan with zero LLM calls.
    """

    __tablename__ = "upload_caches"
    __table_args__ = (
        Index("ix_upload_caches_hash", "file_hash", unique=True),
    )

    file_hash = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    file_ext = Column(String, nullable=True)
    plan = Column(JSON, nullable=True)
    rescue_used = Column(Boolean, nullable=False, default=False, server_default="0")
    hit_count = Column(Integer, nullable=False, default=0, server_default="0")
