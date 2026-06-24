from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index

from app.models.base import BaseSchema


class SkillFile(BaseSchema):
    """Bundled skill resource (Phase S3.1, L3 progressive disclosure).

    A file shipped alongside a Skill's SKILL.md body: executable scripts,
    reference docs loaded on demand, or assets. Content is stored inline as
    text OR as an "s3:<key>" pointer for larger/binary payloads. Soft-deleted
    via deleted_at (BaseSchema convention).
    """

    __tablename__ = "skill_files"

    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=False, index=True)
    path = Column(String, nullable=False)            # relative path e.g. "scripts/queries.sql"
    kind = Column(String(20), nullable=False, default="reference")  # 'script'|'reference'|'asset'
    content = Column(Text, nullable=True)            # inline text, OR an "s3:<key>" pointer
    deleted_at = Column(DateTime, nullable=True)     # soft delete (match skill.py convention)

    __table_args__ = (
        Index("ix_skillfile_skill", "skill_id", "kind"),
    )

    def __repr__(self) -> str:
        return f"<SkillFile(id={self.id}, skill_id={self.skill_id}, path={self.path}, kind={self.kind})>"
