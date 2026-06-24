from __future__ import annotations
from typing import ClassVar, List
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection, xml_escape


class DocChunkItem(BaseModel):
    title: str = ""
    text: str = ""


class DocsSection(ContextSection):
    """Relevant business/term definitions from approved company docs (Phase 5 docs RAG).

    Rendered only when flags.DOC_KNOWLEDGE is ON and query-driven retrieval
    returned chunks; otherwise the builder hands back an empty section ->
    render() == "".
    """
    tag_name: ClassVar[str] = "docs"
    items: List[DocChunkItem] = []

    # Cap rendered items + per-chunk chars defensively (tokens matter — injected
    # into planner prompt).
    _MAX_ITEMS: ClassVar[int] = 4
    _MAX_CHARS: ClassVar[int] = 600

    def render(self) -> str:
        if not self.items:
            return ""
        lines = [
            "### Company definitions",
            "Relevant business/term definitions from approved company docs. Use "
            "to resolve ambiguous terms; cite the doc title if you rely on one.",
        ]
        for it in self.items[: self._MAX_ITEMS]:
            title = xml_escape(it.title)
            text = it.text or ""
            if len(text) > self._MAX_CHARS:
                text = text[: self._MAX_CHARS] + "…"
            text = xml_escape(text)
            lines.append(f"- **{title}**: {text}")
        return "\n".join(lines)
