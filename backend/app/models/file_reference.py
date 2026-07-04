"""FileReference — pin an uploaded org file into a report's prompt context (#497).

A durable, org-scoped link {report} -> {existing uploaded File}. At context-build
time the referenced file's text (its LLM-facing ``description``) is injected into
the planner instructions, so the agent treats the file as directly relevant to
the conversation.

Kept deliberately minimal for the fork: this references the fork's own uploaded
``files`` rows (path/preview already stored) — NOT the upstream connector
file-source substrate (``filesrc01``), which the fork does not have. Everything is
gated behind ``flags.FILE_REFERENCES`` at read time.
"""
from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.orm import relationship

from .base import BaseSchema


class FileReference(BaseSchema):
    __tablename__ = "file_references"

    report_id = Column(String(36), ForeignKey("reports.id"), nullable=False, index=True)
    # The referenced uploaded file (fork's own ``files`` table).
    file_id = Column(String(36), ForeignKey("files.id"), nullable=False, index=True)

    organization_id = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    file = relationship("File")
