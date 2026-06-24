from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Index

from app.models.base import BaseSchema


class SkillRun(BaseSchema):
    """Execution record for a skill's bundled script (per user).

    One row per run of a Skill's bundled script (e.g. ``scripts/cohort.py``).
    Captures who ran it (owner_user_id / organization_id), which script (path),
    lifecycle status (running|success|error|blocked), the result row count,
    captured stdout/error, and an optional pointer to a stored result. Timing is
    tracked via started_at/finished_at. Soft-deleted via deleted_at (BaseSchema
    convention).
    """

    __tablename__ = "skill_runs"

    skill_id = Column(String(36), ForeignKey("skills.id"), nullable=False, index=True)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=True, index=True)
    path = Column(String, nullable=False)                # which script ran, e.g. "scripts/cohort.py"
    status = Column(String(20), nullable=False, default="running")  # running|success|error|blocked
    rows = Column(Integer, nullable=True)                # result row count
    stdout = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    result_ref = Column(String, nullable=True)           # optional pointer to a stored result
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_skillrun_owner", "owner_user_id", "status"),
        Index("ix_skillrun_skill", "skill_id"),
    )

    def __repr__(self) -> str:
        return f"<SkillRun(id={self.id}, skill_id={self.skill_id}, path={self.path}, status={self.status})>"
