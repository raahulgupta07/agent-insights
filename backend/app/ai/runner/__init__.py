# runner package

# Subagent fan-out (orchestrator-worker). Lightweight research workers take ONE
# focused sub-question, run their own read-only SELECT against a data-source
# client (clean context, own data access), and return a distilled finding. The
# orchestrator decomposes a hard/multi-source question, fans the sub-questions
# out concurrently (Semaphore-capped, bounded steps), and synthesizes one final
# answer. Genuine subagents — NOT full AgentV2 (no plan/execute/reflect, no
# nested tool use). Flag-gated via flags.SUBAGENTS at the tool boundary.
from .orchestrator import run_fanout, run_subtask, decompose

__all__ = ["run_fanout", "run_subtask", "decompose"]

