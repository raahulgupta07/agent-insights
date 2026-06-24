from __future__ import annotations
from typing import ClassVar, List
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection, xml_escape


class MemoryItem(BaseModel):
    mem_key: str = ""
    text: str = ""


class AgentMemorySection(ContextSection):
    """Relevant remembered notes the agent saved in earlier sessions.

    Rendered only when flags.AGENT_MEMORY is ON and query-driven recall
    returned visible memories (own personal + approved shared); otherwise the
    builder hands back an empty section -> render() == "".
    """
    tag_name: ClassVar[str] = "memory"
    items: List[MemoryItem] = []

    # Cap rendered items + per-note chars defensively (tokens matter — injected
    # into the planner prompt).
    _MAX_ITEMS: ClassVar[int] = 5
    _MAX_CHARS: ClassVar[int] = 400

    def render(self) -> str:
        if not self.items:
            return ""
        lines = [
            "### Remembered notes",
            "Notes you saved earlier about this project/data. Use them; "
            "don't re-derive what's already known here.",
        ]
        for it in self.items[: self._MAX_ITEMS]:
            key = xml_escape(it.mem_key or "note")
            text = it.text or ""
            if len(text) > self._MAX_CHARS:
                text = text[: self._MAX_CHARS] + "…"
            text = xml_escape(text)
            lines.append(f"- **{key}**: {text}")
        return "\n".join(lines)
