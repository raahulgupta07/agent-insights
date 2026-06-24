"""Router — pick the right pack for a question, then build the inject block.

This is the fix for the native-Skills "agent picks the wrong skill" problem.
Selection is THREE stacked filters, not one LLM name-guess:

  1. CANDIDATE GATE (hard) : only packs already BOUND + ACTIVE for this studio
                             are even visible. A pack whose inputs don't exist
                             in the agent's data can NEVER be picked.
  2. SCORE (rank)          : score = w_trigger*trigger + w_conf*bind_conf
                                     + w_winrate*winrate ; take the top one.
  3. WIN-RATE (adaptive)   : eval/feedback win-rate (Phase 5) demotes packs
                             that keep failing on a question pattern. Until
                             that table exists, win-rate defaults to neutral.

`select_pack` works on plain dicts so it is trivially unit-testable and has no
DB or LLM dependency. `build_injection_block` turns the winner into the
method+binding text that gets appended to the planner instructions.
Never raises — returns None / "" on any problem (fail open to the plain loop).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# score weights — trigger relevance, binding confidence, learned win-rate
_W_TRIGGER = 0.5
_W_CONF = 0.3
_W_WINRATE = 0.2

# a pack must clear this combined score to be injected at all
_SELECT_FLOOR = 0.20


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _trigger_score(question: str, hints: List[str]) -> float:
    """Fraction of trigger hints that appear in the question (0..1).

    A hint matches if all its tokens occur in the question (phrase-ish), or any
    single distinctive token (len>=4) appears. Cheap keyword overlap.
    """
    q = _norm(question)
    if not q or not hints:
        return 0.0
    qtokens = set(q.split(" "))
    hits = 0
    for h in hints:
        ht = _norm(h)
        if not ht:
            continue
        toks = ht.split(" ")
        if ht in q or all(t in qtokens for t in toks):
            hits += 1
        elif any(len(t) >= 4 and t in qtokens for t in toks):
            hits += 0.5
    return min(hits / max(len(hints), 1), 1.0)


def score_candidate(question: str, candidate: dict) -> float:
    """Combined selection score for one bound candidate.

    candidate = {pack: <pack dict>, overall_conf: float, winrate: float|None}
    """
    try:
        pack = candidate.get("pack") or {}
        trig = _trigger_score(question, pack.get("trigger_hints") or [])
        conf = float(candidate.get("overall_conf") or 0.0)
        wr = candidate.get("winrate")
        winrate = 0.5 if wr is None else float(wr)  # neutral until learned
        return round(_W_TRIGGER * trig + _W_CONF * conf + _W_WINRATE * winrate, 4)
    except Exception:
        return 0.0


def select_pack(question: str, candidates: List[dict]) -> Optional[dict]:
    """Return the winning candidate dict (with an added 'score'), or None.

    candidates: list of {pack, binding, overall_conf, winrate?}. Only pass
    BOUND + ACTIVE packs here — the hard candidate gate happens upstream (the
    caller queries studio_bound_pack WHERE status='active').
    """
    try:
        if not candidates:
            return None
        best = None
        best_score = -1.0
        for c in candidates:
            pack = c.get("pack") or {}
            # HARD relevance gate: a pack only fires when the QUESTION matches its
            # trigger domain — not merely because its data binds. Without this a
            # bound pack (high conf) would inject on every question (incl. off-
            # topic), recreating the native "wrong skill" problem. Binding is the
            # data gate; trigger is the intent gate; both must pass.
            if _trigger_score(question, pack.get("trigger_hints") or []) <= 0.0:
                continue
            s = score_candidate(question, c)
            if s > best_score:
                best_score, best = s, c
        if best is None or best_score < _SELECT_FLOOR:
            return None
        out = dict(best)
        out["score"] = best_score
        return out
    except Exception:
        return None


def build_injection_block(pack: dict, binding: Dict[str, str]) -> str:
    """Render the [METHOD]+[BINDING] text appended to planner instructions.

    This is the ENTIRE runtime effect of a pack: it steers the existing
    create_data / create_artifact loop. The pack never executes.
    """
    try:
        name = pack.get("name") or pack.get("id") or "skill"
        method = (pack.get("method_text") or "").strip()
        spec = pack.get("output_spec") or {}
        fmt = pack.get("format") or {}

        lines: List[str] = []
        lines.append(f"### Active skill: {name}")
        lines.append(
            "A domain skill matched this question. Follow its METHOD exactly, "
            "using the BINDING to map each step to this agent's real columns. "
            "Compute with `create_data`, then build the deliverable with "
            "`create_artifact` per the OUTPUT spec. Do not invent columns not in "
            "the binding; if a required input is missing, say so."
        )
        if method:
            lines.append("\n**METHOD**\n" + method)
        if binding:
            bmap = ", ".join(f"{k} = `{v}`" for k, v in binding.items())
            lines.append("\n**BINDING** (logical input → your column): " + bmap)
        if spec:
            lines.append("\n**OUTPUT**: " + _render_spec(spec))
        if fmt:
            fmt_txt = ", ".join(f"{k}: {v}" for k, v in fmt.items())
            lines.append("**FORMAT**: " + fmt_txt)
        return "\n".join(lines).strip()
    except Exception:
        return ""


def _render_spec(spec: dict) -> str:
    try:
        parts = []
        for k, v in spec.items():
            if isinstance(v, (list, tuple)):
                v = ", ".join(str(x) for x in v)
            elif isinstance(v, dict):
                v = ", ".join(f"{a}={b}" for a, b in v.items())
            parts.append(f"{k}: {v}")
        return "; ".join(parts)
    except Exception:
        return ""
