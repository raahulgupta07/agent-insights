from __future__ import annotations
from typing import ClassVar, List
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection, xml_escape


class HybridHitItem(BaseModel):
    kind: str
    title: str
    body: str = ""


class HybridSearchSection(ContextSection):
    """Top knowledge hits for the user's question (FTS + vector + Jaccard, RRF).

    Rendered only when flags.SEMANTIC_SEARCH is ON and the index returns hits;
    otherwise the builder hands back an empty section -> render() == "".
    """
    tag_name: ClassVar[str] = "relevant_knowledge"
    items: List[HybridHitItem] = []

    def render(self) -> str:
        if not self.items:
            return ""
        lines = [
            "## RELEVANT KNOWLEDGE (semantic search)",
            "Top matches from this org's approved knowledge for the question. "
            "Use as grounding hints; verify with a live query before asserting.",
        ]
        for it in self.items:
            snippet = (it.body or "").strip().replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240] + "…"
            label = xml_escape(it.title or "(untitled)")
            kind = xml_escape(it.kind or "")
            if snippet:
                lines.append(f"- [{kind}] {label} — {xml_escape(snippet)}")
            else:
                lines.append(f"- [{kind}] {label}")
        return "\n".join(lines)
