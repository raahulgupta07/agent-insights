"""
Planner collapse
================

Speed Phase 3, Track A. When a report's bound data sources ALREADY carry their
table schema (rendered into the planner context from cached ``DataSourceTable``
rows) and, further, when those rows carry per-column metadata
(``metadata_json`` / ``columns``), the planner does not need to spend LLM
plan/execute/reflect turns on the "research the tables first" steps —
``read_resources`` (list/inspect resources) and ``describe_tables`` (fetch
column schema). The schema is right there in the prompt.

This module is a PURE decision helper: given the two cached-schema signals plus
the flag state, it returns (a) a directive block to append to the planner
instructions and (b) how many planner turns that directive collapses. The agent
loop (``agent_v2.py``) computes the signals from the live context / DB and
appends the returned block. Keeping the decision here (no DB, no I/O, never
raises) makes it trivially unit-testable and keeps the hot loop thin.

Gating
------
The collapse only ever engages when BOTH the master ``HYBRID_FAST_LANE`` flag
AND ``HYBRID_PLANNER_COLLAPSE`` are on (see ``hybrid_flags.py`` — PLANNER_COLLAPSE
is documented as "Gated by FAST_LANE"). Either off => ``("", 0)`` => the planner
context is byte-identical to today. Fail-soft by construction.
"""

from __future__ import annotations

from typing import Tuple


def plan_collapse_directive(
    *,
    fast_lane: bool,
    planner_collapse: bool,
    has_schema: bool,
    has_column_metadata: bool,
) -> Tuple[str, int]:
    """Decide the planner-collapse directive from cached-schema signals.

    Parameters
    ----------
    fast_lane, planner_collapse:
        Flag state (``flags.FAST_LANE`` / ``flags.PLANNER_COLLAPSE``). Both must
        be True or nothing collapses.
    has_schema:
        True when the bound sources' table schema is already loaded into the
        planner context (i.e. the rendered schema excerpt is non-empty because
        ``DataSourceTable`` rows are present). Lets us skip ``read_resources``.
    has_column_metadata:
        True when the cached ``DataSourceTable`` rows carry per-column metadata
        (``metadata_json`` or a populated ``columns`` list). Lets us skip
        ``describe_tables``.

    Returns
    -------
    (directive_text, collapsed_steps)
        ``directive_text`` — block to append to the planner instructions (empty
        string when nothing collapses). ``collapsed_steps`` — number of planner
        turns the directive removes (0, 1, or 2). ``collapsed_steps`` is exactly
        the count of LLM-dispatched research steps the planner is told to skip.
    """
    # Master gate — either flag off => zero behaviour change.
    if not (fast_lane and planner_collapse):
        return "", 0

    collapsed_tools = []
    lines = []

    if has_schema:
        collapsed_tools.append("read_resources")
        lines.append(
            "- The full table schema for your bound data sources is ALREADY "
            "included in your context above. Do NOT call read_resources / "
            "list-resources to fetch it — reuse the schema you already have."
        )

    if has_column_metadata:
        collapsed_tools.append("describe_tables")
        lines.append(
            "- Per-column metadata (names, types, and profiled details) for "
            "those tables is ALSO already in your context. Do NOT call "
            "describe_tables / get-schema for them — the columns are known."
        )

    if not lines:
        # Flags on but no cached schema present => run the full loop as normal.
        return "", 0

    directive = (
        "SCHEMA ALREADY KNOWN (fast path): The tables you would normally have "
        "to research are already described in the context above.\n"
        + "\n".join(lines)
        + "\nProceed directly to the next real step (clarify / create_data / "
        "answer) instead of spending a turn re-reading the schema."
    )
    return directive, len(collapsed_tools)


# ---------------------------------------------------------------------------
# Self-test (A4): flag ON + cached schema => FEWER LLM-dispatched planner steps
# than flag OFF. Run: `python -m app.services.speed.planner_collapse`
# (from backend/, PYTHONPATH=backend). No DB / LLM required — pure logic.
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    def _steps_dispatched(*, fast_lane, planner_collapse, has_schema, has_col_meta):
        """A tiny model of the planner's research phase.

        Baseline: the planner dispatches one LLM turn to read_resources and one
        to describe_tables (2 research turns) before it can answer. Collapse
        removes whichever of those the cached schema makes redundant.
        """
        BASELINE_RESEARCH_STEPS = 2
        _directive, collapsed = plan_collapse_directive(
            fast_lane=fast_lane,
            planner_collapse=planner_collapse,
            has_schema=has_schema,
            has_column_metadata=has_col_meta,
        )
        return BASELINE_RESEARCH_STEPS - collapsed, collapsed, _directive

    print("=== Planner Collapse self-test (Speed Phase 3, Track A) ===")

    # Cached schema is present in all three scenarios; only the flags differ.
    off_steps, off_collapsed, off_dir = _steps_dispatched(
        fast_lane=False, planner_collapse=False, has_schema=True, has_col_meta=True
    )
    # Half-on (only PLANNER_COLLAPSE, no FAST_LANE master) must NOT collapse.
    half_steps, half_collapsed, half_dir = _steps_dispatched(
        fast_lane=False, planner_collapse=True, has_schema=True, has_col_meta=True
    )
    on_steps, on_collapsed, on_dir = _steps_dispatched(
        fast_lane=True, planner_collapse=True, has_schema=True, has_col_meta=True
    )

    print(f"flag OFF          : LLM research steps = {off_steps}  (collapsed {off_collapsed})")
    print(f"FAST_LANE off only: LLM research steps = {half_steps}  (collapsed {half_collapsed})")
    print(f"flag ON  + cached : LLM research steps = {on_steps}  (collapsed {on_collapsed})")
    print(f"directive injected when ON:\n---\n{on_dir}\n---")

    checks = [
        ("flag OFF collapses nothing", off_collapsed == 0 and off_dir == ""),
        ("half-on (no master) collapses nothing", half_collapsed == 0 and half_dir == ""),
        ("flag ON collapses 2 research steps", on_collapsed == 2),
        ("flag ON dispatches FEWER steps than OFF", on_steps < off_steps),
        ("flag ON injects a non-empty directive", bool(on_dir)),
    ]
    ok = all(passed for _, passed in checks)
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print("RESULT:", "PASS" if ok else "FAIL")
    import sys as _sys
    _sys.exit(0 if ok else 1)
