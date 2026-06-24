"""Deterministic WORKFLOW RUNNER (#5).

A code-driven (NOT LLM-driven) batch pipeline: fan a work-list through a single
stage worker, gate EACH item with a verifier (pass / retry / skip), and keep a
full per-item log. The SEQUENCE and the gates are deterministic — only the
worker (`stage_fn`) and the optional `llm_judge` call the LLM.

Reuses existing workers (e.g. `autotrain_connector`). Flag-gated via
`flags.WORKFLOWS` (checked at the HTTP surface). Default OFF.

- `runner.run_pipeline` : the pure engine (never raises).
- `runner.llm_judge` / `runner.produced_knowledge_judge` : verifier factories.
- `jobs.WORKFLOWS` : name -> concrete-workflow registry.
"""

from __future__ import annotations

from app.ai.workflows import runner  # noqa: F401
from app.ai.workflows import jobs  # noqa: F401

__all__ = ["runner", "jobs"]
