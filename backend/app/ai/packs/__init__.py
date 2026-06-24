"""Domain Packs — a lightweight, data-gated "skills" engine.

This subsystem is the CityAgent alternative to the native heavy Skills engine
(`HYBRID_SKILLS`, sandbox-executed, prone to livelock). A *pack* is a pure
DECLARATIVE yaml file (method + required inputs + output spec + eval goldens).
Packs are never executed: they only STEER the default single-analyst loop
(`create_data` / `create_artifact`) by injecting a method + a per-agent data
binding into the planner context.

Three moving parts, all gated by `HYBRID_DOMAIN_PACKS` (default OFF):
  - registry.py : load + validate + cache the yaml pack library
  - binder.py   : match a pack's required_inputs to a studio's real columns
  - router.py   : candidate-gate (only BOUND packs) -> score -> top-1 -> inject

INVARIANT (method) is copied from the pack file; VARIABLE (the column binding)
is synthesised per-agent at train time. Copy the method, generate the binding.

Everything here is dependency-light and NEVER raises into the agent loop — on
any error the helpers fail open (return empty / None) so a malformed pack can
never break a real data question.
"""
