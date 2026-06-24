"""StudioSection — per-Studio engineered context (hybrid Studios ST7).

When the active report belongs to a Studio (Report.studio_id set) AND
flags.STUDIOS is ON, the StudioContextBuilder folds the Studio's
engineered context into a single section:

  - voice       : Studio.persona (the tone / reply-language line)
  - instructions: ACTIVE StudioInstruction rows (approved-only; pending
                  never reaches the model)
  - examples    : ACTIVE StudioExample rows rendered as Q -> answer(/sql)
                  few-shot pairs (approved-only)

This section ONLY adds voice + instructions + examples. The Studio's
pinned skills are injected by SkillContextBuilder and its grounded
schemas by SchemaContextBuilder — this builder must NOT duplicate those.

Render is pure and never raises; an empty section renders to "" so the
flag-OFF / non-studio path is byte-identical to upstream.
"""
from __future__ import annotations
from typing import ClassVar, List, Optional
from pydantic import BaseModel

from app.ai.context.sections.base import ContextSection


class StudioInstructionItem(BaseModel):
    content: str


class StudioExampleItem(BaseModel):
    question: str
    answer: str
    sql: Optional[str] = None


class StudioSection(ContextSection):
    tag_name: ClassVar[str] = "studio_context"

    # The Studio's "voice" (Studio.persona) — tone + reply-language line.
    voice: Optional[str] = None
    # ACTIVE (approved) instructions for this Studio.
    instructions: List[StudioInstructionItem] = []
    # ACTIVE (approved) golden few-shot examples for this Studio.
    examples: List[StudioExampleItem] = []

    def render(self) -> str:
        # Nothing to inject unless at least one of voice/instructions/examples
        # is present. Empty -> "" so the non-studio path is unchanged.
        if not (self.voice or self.instructions or self.examples):
            return ""

        parts: List[str] = []

        if self.voice and self.voice.strip():
            parts.append("## Studio voice\n" + self.voice.strip())

        if self.instructions:
            lines = ["## Studio instructions"]
            for it in self.instructions:
                content = (it.content or "").strip()
                if content:
                    lines.append(f"- {content}")
            # Only emit the block if it carries at least one non-empty rule.
            if len(lines) > 1:
                parts.append("\n".join(lines))

        if self.examples:
            lines = ["## Studio golden examples"]
            for ex in self.examples:
                q = (ex.question or "").strip()
                a = (ex.answer or "").strip()
                if not (q and a):
                    continue
                lines.append(f"Q: {q}")
                lines.append(f"A: {a}")
                sql = (ex.sql or "").strip()
                if sql:
                    lines.append(f"SQL:\n{sql}")
                lines.append("")  # blank line between examples
            if len(lines) > 1:
                parts.append("\n".join(lines).rstrip())

        inner = "\n\n".join(p for p in parts if p)
        if not inner:
            return ""
        # Wrap in a tagged block (mirrors the section convention; escape only
        # the wrapper inner is unnecessary — content is model instructions, not
        # attribute values — so we keep the body verbatim inside the tag).
        return f"<{self.tag_name}>\n{inner}\n</{self.tag_name}>"
