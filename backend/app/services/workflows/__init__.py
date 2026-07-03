"""Workflows v2 (HYBRID_WORKFLOWS_V2) — save & replay a finished analysis.

Two fail-soft coroutines, both additive and flag-gated at the route layer:
  * ``capture.save_workflow_from_report`` — turn a report's data-turn step plan
    into a saved, parameterized ``AnalysisWorkflow``.
  * ``replay.run_workflow`` — re-run the saved steps headless with concrete
    params and return the produced report/artifact ids.

Every public coroutine NEVER raises into the caller (logs + safe default).
"""
