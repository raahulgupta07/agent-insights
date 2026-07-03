"""Daily offline context pipeline (Part B).

Merges every context layer for a table into ONE normalized per-table document
(via the P3 Unified Table Card) and embeds it once, so retrieval reads a
pre-built ``metadata_json['context_doc']`` instead of reassembling the card on
every request (the OpenAI daily-offline-pipeline pattern, Diagram 5).

Public entry points (imported by main.py lifespan + core/scheduler):
  * ``build_offline_context``          — build+persist+embed for ONE org.
  * ``run_scheduled_offline_context``  — self-contained nightly daemon entry.

All flag-gated on ``flags.OFFLINE_CONTEXT`` (default OFF → no-op) and fail-soft.
"""
from app.services.context_offline.pipeline import (
    build_offline_context,
    run_scheduled_offline_context,
)

__all__ = ["build_offline_context", "run_scheduled_offline_context"]
