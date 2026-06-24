"""
ContextView - Read-only consumer-facing view over the current context snapshot.

Object-based grouping that separates static vs warm sections for planner/tools.
"""
from pydantic import BaseModel
from typing import Optional

from app.ai.context.sections.tables_schema_section import TablesSchemaContext
from app.ai.context.sections.files_schema_section import FilesSchemaContext
from app.ai.context.sections.instructions_section import InstructionsSection
from app.ai.context.sections.messages_section import MessagesSection
from app.ai.context.sections.widgets_section import WidgetsSection
from app.ai.context.sections.queries_section import QueriesSection
from app.ai.context.sections.observations_section import ObservationsSection
from app.ai.context.sections.resources_section import ResourcesSection
from app.ai.context.sections.code_section import CodeSection
from app.ai.context.sections.mentions_section import MentionsSection
from app.ai.context.sections.entities_section import EntitiesSection
from app.ai.context.sections.scheduled_tasks_section import ScheduledTasksSection
from app.ai.context.sections.brain import ProvenQueriesSection
from app.ai.context.sections.skills import SkillsSection
from app.ai.context.sections.semantic import SemanticTablesSection
from app.ai.context.sections.metrics import MetricsCatalogSection
from app.ai.context.sections.code_examples import CodeExamplesSection


class StaticSections(BaseModel):
    schemas: Optional[TablesSchemaContext] = None
    instructions: Optional[InstructionsSection] = None
    resources: Optional[ResourcesSection] = None
    code: Optional[CodeSection] = None
    files: Optional[FilesSchemaContext] = None
    # hybrid-brain Phase 4: proven reasoning-cache queries (BrainContextBuilder)
    brain: Optional[ProvenQueriesSection] = None
    # hybrid Phase 6: self-service skills L1 catalog (SkillContextBuilder)
    skills: Optional[SkillsSection] = None
    # Knowledge Layer Phase 4: approved semantic tables (SemanticContextBuilder)
    semantic: Optional[SemanticTablesSection] = None
    # Knowledge Layer Phase 4: approved metrics catalog (MetricsContextBuilder)
    metrics: Optional[MetricsCatalogSection] = None
    # Kepler Phase 2: proven generate_df code memory (CodeBankContextBuilder)
    code_bank: Optional[CodeExamplesSection] = None


class WarmSections(BaseModel):
    messages: Optional[MessagesSection] = None
    observations: Optional[ObservationsSection] = None
    widgets: Optional[WidgetsSection] = None
    queries: Optional[QueriesSection] = None
    mentions: Optional[MentionsSection] = None
    entities: Optional[EntitiesSection] = None
    scheduled_tasks: Optional[ScheduledTasksSection] = None


class ContextView(BaseModel):
    static: StaticSections
    warm: WarmSections
    meta: dict = {}

