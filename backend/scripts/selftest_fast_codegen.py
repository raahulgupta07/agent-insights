"""Self-test for Speed Phase 3 / Track C — Fast Codegen Model (HYBRID_FAST_CODEGEN).

Proves the codegen model-SELECTION logic (not execution):
  · flag OFF  → codegen step resolves to the NORMAL (reasoning) model.
  · flag ON   → codegen step resolves to the FAST/small Gemini model.

Pure + offline (no DB, no LLM). Mirrors the gate wired into create_data.py's
Coder site. Run:  PYTHONPATH=backend python backend/scripts/selftest_fast_codegen.py
"""
from __future__ import annotations

import os
import sys

# Make `app...` importable when run from the repo root or backend/.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.ai.knowledge.auto_model import codegen_model
import app.settings.hybrid_flags as HF
from app.settings.hybrid_flags import flags


class _FakeModel:
    def __init__(self, model_id, name, cost):
        self.model_id = model_id
        self.name = name
        self._cost = cost

    def get_output_cost_rate(self):
        return self._cost

    def __repr__(self):
        return f"{self.name}<{self.model_id}>"


# Org's models: a heavy reasoning default + a fast Gemini flash-lite small model.
NORMAL = _FakeModel("anthropic/claude-sonnet-4", "Claude Sonnet 4", 15.0)
FAST = _FakeModel("google/gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", 0.4)
ORG_MODELS = [NORMAL, FAST]


def resolve_codegen(normal_model, small_model, models):
    """Mirror the create_data.py Coder-site gate (flag + fail-soft), sans DB."""
    chosen = normal_model
    try:
        if flags.FAST_LANE and flags.FAST_CODEGEN:
            chosen = codegen_model(default_model=normal_model, small_model=small_model, models=models)
    except Exception:
        chosen = normal_model
    return chosen


def _set(fast_lane, fast_codegen):
    HF.set_override("HYBRID_FAST_LANE", fast_lane)
    HF.set_override("HYBRID_FAST_CODEGEN", fast_codegen)


def main() -> int:
    results = []

    # 1. Both flags OFF → normal model.
    _set(False, False)
    off = resolve_codegen(NORMAL, FAST, ORG_MODELS)
    results.append(("flags OFF → normal model", off.model_id == NORMAL.model_id, off.model_id))

    # 2. FAST_LANE ON but FAST_CODEGEN OFF → still normal (master alone insufficient).
    _set(True, False)
    half = resolve_codegen(NORMAL, FAST, ORG_MODELS)
    results.append(("FAST_LANE on / FAST_CODEGEN off → normal model", half.model_id == NORMAL.model_id, half.model_id))

    # 3. Both flags ON → fast Gemini model.
    _set(True, True)
    on = resolve_codegen(NORMAL, FAST, ORG_MODELS)
    results.append(("flags ON → fast Gemini model", on.model_id == FAST.model_id, on.model_id))

    # 4. Both ON but no small_model resolved → fail-soft picks fast from models list.
    _set(True, True)
    nolist = resolve_codegen(NORMAL, None, ORG_MODELS)
    results.append(("flags ON, no small_model → fast from list", nolist.model_id == FAST.model_id, nolist.model_id))

    # 5. Both ON, no small & no models → fail-soft to normal default.
    _set(True, True)
    bare = resolve_codegen(NORMAL, None, [])
    results.append(("flags ON, nothing to pick → default model", bare.model_id == NORMAL.model_id, bare.model_id))

    # cleanup overrides
    HF.set_override("HYBRID_FAST_LANE", None)
    HF.set_override("HYBRID_FAST_CODEGEN", None)

    ok = True
    for label, passed, resolved in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {label}  → resolved={resolved}")
        ok = ok and passed

    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
