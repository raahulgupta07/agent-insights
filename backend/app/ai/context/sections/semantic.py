"""SemanticTablesSection — Knowledge Layer Phase 4 (read).

Surfaces approved per-table / per-column semantic meaning so the planner knows
what each table and column represents in business terms. Same shape as
brain/skills sections: a Pydantic ContextSection with a self-contained
``render()`` that produces concise plain text (empty string when no items).
"""
from __future__ import annotations
from typing import ClassVar, List
from pydantic import BaseModel
from app.ai.context.sections.base import ContextSection


class SemanticColumnItem(BaseModel):
    name: str
    meaning: str


class SemanticTableItem(BaseModel):
    table_name: str
    description: str = ""
    use_cases: List[str] = []
    columns: List[SemanticColumnItem] = []
    # --- Governance (Kepler Phase 1; only populated when HYBRID_GOVERNANCE) ---
    owner: str = ""
    pii: bool = False
    freshness: str = ""          # precomputed label e.g. "fresh", "stale 5d"
    pii_columns: List[str] = []   # column names flagged PII


class SemanticTablesSection(ContextSection):
    tag_name: ClassVar[str] = "semantic_tables"
    items: List[SemanticTableItem] = []
    data_as_of: str = ""          # latest source sync (ISO date), governance only

    def render(self) -> str:
        if not self.items:
            return ""
        lines: List[str] = ["<semantic_tables>"]
        # PII policy line — emitted only when some table/column carries PII.
        if any(t.pii or t.pii_columns for t in self.items):
            lines.append(
                "  policy: items marked PII hold personal data — never output PII "
                "columns unless explicitly asked AND authorized; state the data-as-of date."
            )
        if self.data_as_of:
            lines.append(f"  data as of: {self.data_as_of}")
        for t in self.items:
            head = f"- {t.table_name}"
            if t.description and t.description.strip():
                head += f": {t.description.strip()}"
            lines.append(head)
            if t.use_cases:
                uc = ", ".join(u for u in t.use_cases if u)
                if uc:
                    lines.append(f"    use cases: {uc}")
            # governance footer (only when any governance field present)
            gparts: List[str] = []
            if t.owner:
                gparts.append(f"owner={t.owner}")
            if t.freshness:
                gparts.append(t.freshness)
            if t.pii_columns:
                gparts.append("PII: " + ", ".join(t.pii_columns))
            elif t.pii:
                gparts.append("PII table")
            if gparts:
                lines.append("    governance: " + " · ".join(gparts))
            for c in t.columns:
                if c.meaning and c.meaning.strip():
                    lines.append(f"    {c.name} -> {c.meaning.strip()}")
        lines.append("</semantic_tables>")
        return "\n".join(lines)
