from __future__ import annotations
from typing import ClassVar, List, Optional
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection, xml_escape


class ReferencedFileItem(BaseModel):
    filename: str
    content_type: Optional[str] = None
    text: str = ""


class FileReferencesSection(ContextSection):
    """Files the user explicitly pinned into this report's prompt context (#497).

    Rendered only when flags.FILE_REFERENCES is ON and at least one referenced
    file resolved; otherwise the builder hands back an empty section ->
    render() == "" (agent context byte-identical to flag-off).
    """
    tag_name: ClassVar[str] = "referenced_files"
    items: List[ReferencedFileItem] = []

    def render(self) -> str:
        if not self.items:
            return ""
        lines = [
            "## REFERENCED FILES",
            "The user pinned these uploaded files to this conversation. Treat their "
            "content as directly relevant context for the request.",
        ]
        for it in self.items:
            ct = f" ({xml_escape(it.content_type)})" if it.content_type else ""
            lines.append(f"\n### {xml_escape(it.filename)}{ct}")
            body = (it.text or "").strip()
            if body:
                lines.append(xml_escape(body))
        return "\n".join(lines)
