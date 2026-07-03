"""access — the retrieval gate.

A learning is visible to a viewer ONLY if:
  - SHARED tier: its (scope_kind, scope_key) is one the viewer's own agent
    resolves to (intersection). The viewer cannot receive knowledge for a
    model/schema/file they don't themselves hold.
  - PRIVATE tier (scope_kind='user'): its scope_key equals the viewer's own
    user_id. One user's private memory never reaches another user.

These are pure predicates/filters; the DB query in P3 uses ``visible_scope_pairs``
to build its WHERE clause, and ``can_view`` is the belt-and-suspenders row check.
"""
from __future__ import annotations

from typing import Any, Iterable


def _pair(scope: dict) -> tuple[str, str]:
    return (str(scope.get("scope_kind") or ""), str(scope.get("scope_key") or ""))


def visible_scope_pairs(
    viewer_user_id: str | None,
    viewer_scopes: Iterable[dict],
    organization_id: str | None = None,
) -> list[tuple[str, str]]:
    """The exact (scope_kind, scope_key) pairs a viewer may read.

    = the viewer agent's own SHARED scopes (tier 1, model/schema/file)
      + the viewer's OWN private scope (tier 2, user)
      + the org-wide GLOBAL scope (tier 3, org) — every agent reads this.
    Feed this straight into a tuple-IN filter.
    """
    pairs: set[tuple[str, str]] = set()
    for s in viewer_scopes or []:
        k = _pair(s)
        if k[1]:
            pairs.add(k)
    if viewer_user_id:
        pairs.add(("user", str(viewer_user_id)))
    if organization_id:
        pairs.add(("org", str(organization_id)))  # GLOBAL tier — all agents
    return sorted(pairs)


def can_view(
    row: Any,
    viewer_user_id: str | None,
    viewer_scopes: Iterable[dict],
    organization_id: str | None = None,
) -> bool:
    """True iff `row` (an AgentKnowledge-like obj/dict) is visible to the viewer."""
    rk = str(getattr(row, "scope_kind", None) or (row.get("scope_kind") if isinstance(row, dict) else "") or "")
    rkey = str(getattr(row, "scope_key", None) or (row.get("scope_key") if isinstance(row, dict) else "") or "")

    if rk == "user":
        # private tier: only its own owner
        return bool(viewer_user_id) and rkey == str(viewer_user_id)

    if rk == "org":
        # global tier: every agent in the org (the DB query is already
        # org-filtered; accept when it matches or when no org context given)
        return (not organization_id) or rkey == str(organization_id)

    allowed = {
        p for p in visible_scope_pairs(viewer_user_id, viewer_scopes, organization_id)
        if p[0] not in ("user", "org")
    }
    return (rk, rkey) in allowed


def intersect_scopes(a: Iterable[dict], b: Iterable[dict]) -> list[dict]:
    """Scopes present in BOTH sets (used to answer 'who shares this model')."""
    sb = {_pair(s) for s in b or []}
    out, seen = [], set()
    for s in a or []:
        p = _pair(s)
        if p in sb and p not in seen and p[1]:
            seen.add(p)
            out.append({"scope_kind": p[0], "scope_key": p[1]})
    return out
