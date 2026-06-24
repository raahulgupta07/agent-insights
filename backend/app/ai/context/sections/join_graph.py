from __future__ import annotations
from typing import ClassVar, List
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection, xml_escape


class JoinEdgeItem(BaseModel):
    left_table: str
    left_col: str
    right_table: str
    right_col: str
    join_count: int = 0
    confidence: float = 0.0


class JoinGraphSection(ContextSection):
    """Top approved table-join edges (join adjacency) for the run's data source.

    Rendered only when flags.JOIN_GRAPH is ON and approved edges exist;
    otherwise the builder hands back an empty section -> render() == "".
    """
    tag_name: ClassVar[str] = "join_graph"
    items: List[JoinEdgeItem] = []

    # Cap rendered lines defensively (tokens matter — injected into planner prompt).
    _MAX_LINES: ClassVar[int] = 30

    def render(self) -> str:
        if not self.items:
            return ""
        lines = [
            "### How tables join",
            "Observed join paths in this org's data, most-used first. Use as "
            "hints for joining tables; verify with a live query before relying "
            "on a relationship.",
        ]
        for it in self.items[: self._MAX_LINES]:
            lt = xml_escape(it.left_table)
            lc = xml_escape(it.left_col)
            rt = xml_escape(it.right_table)
            rc = xml_escape(it.right_col)
            seen = f"  (seen {it.join_count}x)" if it.join_count else ""
            lines.append(f"- {lt}.{lc} = {rt}.{rc}{seen}")
        return "\n".join(lines)
