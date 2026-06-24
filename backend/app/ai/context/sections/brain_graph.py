from __future__ import annotations
from typing import ClassVar, List
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection, xml_escape


class CorrelationEdgeItem(BaseModel):
    src: str
    dst: str
    relation: str
    weight: float = 0.0


class CorrelationGraphSection(ContextSection):
    """Top published correlation/entity edges for the run's data source.

    Rendered only when flags.BRAIN_GRAPH is ON and published edges exist;
    otherwise the builder hands back an empty section -> render() == "".
    """
    tag_name: ClassVar[str] = "correlation_graph"
    items: List[CorrelationEdgeItem] = []

    def render(self) -> str:
        if not self.items:
            return ""
        lines = [
            "## CORRELATION GRAPH (approved)",
            "Known entity correlations/relationships in this org's data. Use as "
            "hints for cross-metric analysis; verify with a live query before "
            "asserting a relationship.",
        ]
        for it in self.items:
            w = f" (weight {it.weight:.2f})" if it.weight else ""
            lines.append(
                f"- {xml_escape(it.src)} --{xml_escape(it.relation)}--> "
                f"{xml_escape(it.dst)}{w}"
            )
        return "\n".join(lines)
