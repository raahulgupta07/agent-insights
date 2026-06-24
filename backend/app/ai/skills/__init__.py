"""
Self-service Skills subsystem (Phase 6)
=======================================

Claude-style SKILL.md capabilities with progressive disclosure: an L1 catalog
(name + description) is surfaced to the planner, and the full SKILL.md body (L2)
is loaded on demand via a load_skill(name) tool. Skills are scoped
personal / org / global and visible only when status='active'.

Everything here is gated by flags.SKILLS and degrades to a safe no-op when the
flag is off — a fresh deploy behaves exactly like upstream dash.
"""
