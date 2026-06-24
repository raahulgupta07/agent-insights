"""Binder — map a pack's logical inputs to a studio's real columns.

The INVARIANT (method) is the same for every agent; the VARIABLE (which column
is "ebitda_actual", which is "sector") differs per agent. The binder produces
that mapping deterministically from the agent's profiled schema (the same
column dicts `column_intel` emits: {name, dtype, role, distinct, values, ...}).

A pack BINDS to a studio iff every NON-optional required_input matches some
column above a confidence floor. Bound -> the method is usable on this agent;
not bound -> the pack stays DORMANT (and the missing inputs are reported so the
UI can tell the user "add a Budget column").

Pure, deterministic, never-raises. No LLM here — matching is name/synonym/role
based, which is cheap and reviewable. (An LLM-assisted pass can be layered on
later in the Teach box; the binding is always review-gated before going live.)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# confidence floor for a single input match to count as "bound". Set above the
# weak single-shared-token score (0.55) so e.g. "ebitda_budget" does NOT falsely
# bind to "EBITDA_PY" just because both share the token "ebitda" — a missing
# budget column must leave the input UNMATCHED (-> pack dormant), not mis-bound.
_MIN_CONF = 0.6


def _norm(s: Any) -> str:
    """camel-split, lowercase, strip non-alphanumerics -> token string.

    Splits camelCase first ("BusinessUnit" -> "Business Unit") so warehouse-style
    column names tokenize the same as multi-word synonyms.
    """
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(s or ""))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _tokens(s: Any) -> List[str]:
    return [t for t in _norm(s).split(" ") if t]


def _name_score(target_terms: List[str], col_name: str) -> float:
    """0..1 similarity between a logical input's terms and a column name."""
    cn = _norm(col_name)
    cn_tokens = set(_tokens(col_name))
    if not target_terms:
        return 0.0
    best = 0.0
    for term in target_terms:
        nt = _norm(term)
        if not nt:
            continue
        if nt == cn:
            best = max(best, 1.0); continue
        # the input TERM appears inside a more-specific column name (one
        # direction only): "ebitda" in "ebitda actual" is a strong signal;
        # the reverse (generic column "revenue" inside specific term
        # "revenue ly") is NOT — that falls through to weak token overlap so a
        # generic column can't satisfy a more-specific input.
        if nt in cn:
            best = max(best, 0.85); continue
        # token overlap (Jaccard-ish over the term's tokens). Deliberately low
        # for a single shared token: a 2-token term sharing only 1 token scores
        # 0.55 (< _MIN_CONF) so a shared prefix like "ebitda" can't carry a
        # false match; both tokens shared scores 0.8.
        tt = set(_tokens(term))
        if tt:
            inter = len(tt & cn_tokens)
            if inter:
                best = max(best, 0.3 + 0.5 * (inter / len(tt)))
    return min(best, 1.0)


def _role_ok(want_role: Optional[str], col_role: Optional[str]) -> Optional[bool]:
    """True/False if a role constraint is given, None if no constraint."""
    if not want_role:
        return None
    return _norm(want_role) == _norm(col_role)


def _match_one(spec: dict, key: str, columns: List[dict]) -> Tuple[Optional[str], float]:
    """Best (column_name, confidence) for one required input, or (None, 0)."""
    synonyms = spec.get("synonyms") if isinstance(spec, dict) else None
    terms = [key] + (list(synonyms) if isinstance(synonyms, (list, tuple)) else [])
    # split snake/camel of the key itself into extra terms
    terms.append(key.replace("_", " "))
    want_role = spec.get("role") if isinstance(spec, dict) else None

    best_name: Optional[str] = None
    best_conf = 0.0
    for col in columns:
        cname = col.get("name") if isinstance(col, dict) else None
        if not cname:
            continue
        ns = _name_score(terms, cname)
        # ELIGIBILITY is on NAME similarity alone. Role must never manufacture a
        # match from a weak name (else two same-role measures sharing one token
        # — e.g. revenue_ly vs EBITDA_PY — would falsely bind). A non-matching
        # name is simply skipped.
        if ns < _MIN_CONF:
            continue
        rok = _role_ok(want_role, col.get("role") if isinstance(col, dict) else None)
        # role only RANKS among name-eligible columns (small nudge / penalty).
        conf = ns
        if rok is True:
            conf = min(1.0, conf + 0.1)
        elif rok is False:
            conf = conf * 0.7
        if conf > best_conf:
            best_conf, best_name = conf, cname
    return best_name, round(best_conf, 3)


def bind_pack(pack: dict, columns: List[dict]) -> dict:
    """Try to bind one pack to a flat list of column dicts.

    Returns:
      {
        bound:   bool,                       # all non-optional inputs matched
        binding: {input_key: column_name},   # the resolved map
        conf:    {input_key: 0..1},          # per-input confidence
        overall_conf: float,                 # min over required inputs
        missing: [input_key, ...],           # unmatched required inputs
      }
    Never raises.
    """
    out = {"bound": False, "binding": {}, "conf": {}, "overall_conf": 0.0, "missing": []}
    try:
        req = pack.get("required_inputs") or {}
        if not isinstance(req, dict):
            req = {}
        if not isinstance(columns, list):
            columns = []
        confs: List[float] = []
        for key, spec in req.items():
            spec = spec if isinstance(spec, dict) else {}
            optional = bool(spec.get("optional"))
            cname, conf = _match_one(spec, str(key), columns)
            if cname and conf >= _MIN_CONF:
                out["binding"][key] = cname
                out["conf"][key] = conf
                if not optional:
                    confs.append(conf)
            else:
                if not optional:
                    out["missing"].append(key)
        out["bound"] = len(out["missing"]) == 0 and len(req) > 0
        out["overall_conf"] = round(min(confs), 3) if confs else 0.0
    except Exception:
        return {"bound": False, "binding": {}, "conf": {}, "overall_conf": 0.0, "missing": []}
    return out


def columns_from_profile(profile: Any) -> List[dict]:
    """Normalise various column-source shapes into the binder's flat list.

    Accepts: a column_intel profile dict ({columns:[...]}), a bare list of
    column dicts, or a list of (name, dtype) tuples. Returns [{name, dtype,
    role, ...}]. Never raises.
    """
    try:
        if isinstance(profile, dict) and isinstance(profile.get("columns"), list):
            return [c for c in profile["columns"] if isinstance(c, dict) and c.get("name")]
        if isinstance(profile, list):
            out = []
            for c in profile:
                if isinstance(c, dict) and c.get("name"):
                    out.append(c)
                elif isinstance(c, (list, tuple)) and c:
                    out.append({"name": c[0], "dtype": c[1] if len(c) > 1 else "unknown",
                                "role": "dimension"})
            return out
    except Exception:
        pass
    return []
