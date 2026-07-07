from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class CodeGenContext(BaseModel):
    user_prompt: str
    interpreted_prompt: Optional[str] = None

    # Curated/filtered strings (already rendered for prompt inclusion)
    schemas_excerpt: str
    # New: rendered descriptions of connected data sources/clients (LLM-ready text)
    data_sources_context: str = ""
    instructions_context: str = ""
    # Phase 3: compact grounding contract for the CODER (approved semantic meanings +
    # metric formulas + known join edges, scoped to the selected tables). Empty when
    # HYBRID_CODER_GROUNDING is off. Populated by build_codegen_context, rendered in
    # generate_code so the coder uses defined joins/metrics instead of guessing.
    grounding_context: str = ""
    mentions_context: str = "<mentions>No mentions for this turn</mentions>"
    entities_context: str = ""
    loadables_context: str = ""
    messages_context: str = ""
    resources_context: str = ""
    files_context: str = ""
    platform: Optional[str] = None
    history_summary: str = ""

    # Observations/history
    past_observations: List[Dict[str, Any]] = []
    last_observation: Optional[Dict[str, Any]] = None

    # Optional extras to guide generation (machine-usable)
    filtered_entities: List[Dict[str, Any]] = []
    successful_queries: List[str] = []
    # New: optional targeting info to drive snippet retrieval
    tables_by_source: Optional[List[Dict[str, Any]]] = None


class CodeGenRequest(BaseModel):
    context: CodeGenContext
    retries: int = 2

