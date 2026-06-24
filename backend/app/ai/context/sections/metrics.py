"""MetricsCatalogSection — Knowledge Layer Phase 4 (read).

Surfaces approved named business metrics (name -> definition, table_ref,
sql_calc) so the planner reuses the canonical definition instead of inventing
one. Same shape as brain/skills sections; ``render()`` is self-contained and
returns an empty string when there are no items.
"""
from __future__ import annotations
from typing import ClassVar, List, Optional
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection


class MetricItem(BaseModel):
    name: str
    definition: str = ""
    table_ref: str = ""
    sql_calc: str = ""
    owner: Optional[str] = None


class MetricsCatalogSection(ContextSection):
    tag_name: ClassVar[str] = "metrics_catalog"
    items: List[MetricItem] = []

    def render(self) -> str:
        if not self.items:
            return ""
        lines: List[str] = [
            "<metrics_catalog>",
            "Approved business metrics. Prefer these definitions; use "
            "resolve_metric to fetch a metric's full SQL.",
        ]
        for m in self.items:
            parts = [f"- {m.name}"]
            if m.definition and m.definition.strip():
                parts.append(f": {m.definition.strip()}")
            if m.table_ref and m.table_ref.strip():
                parts.append(f" ({m.table_ref.strip()})")
            if m.sql_calc and m.sql_calc.strip():
                calc = " ".join(m.sql_calc.split())
                if len(calc) > 200:
                    calc = calc[:200] + "…"
                parts.append(f" [{calc}]")
            lines.append("".join(parts))
        lines.append("</metrics_catalog>")
        return "\n".join(lines)
