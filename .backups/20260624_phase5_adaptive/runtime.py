"""Runtime glue — resolve the pack injection block for a live agent turn.

Bridges the pure engine (registry / binder / router) to the DB at query time.
Called from the AgentV2 planner once per turn, behind flags.DOMAIN_PACKS +
flags.PACK_ROUTER. Hard candidate gate = only ACTIVE studio_bound_packs rows
for THIS studio are considered, so a pack the data can't support is invisible.

Returns the method+binding text to append to the planner instructions, or ""
(fail open) on anything: flag off, no studio, no bound packs, no match, error.
Never raises into the agent loop.
"""

from __future__ import annotations

from typing import List, Optional


async def resolve_pack(db, studio_id: Optional[str], question: str) -> Optional[dict]:
    """Pick the best ACTIVE bound pack for this studio+question.

    Returns ``{block, pack_id, cluster, binding}`` for the winner, or None. The
    Phase 5 win-rate loop feeds each candidate's learned score in and BENCHES a
    proven loser (enough 👎 on this question-cluster) before scoring. Never raises.
    """
    try:
        if not db or not studio_id:
            return None
        from sqlalchemy import select
        from app.models.studio import StudioBoundPack
        from app.ai.packs import registry, router
        from app.ai.packs import winrate as _wr

        rows = (
            await db.execute(
                select(StudioBoundPack).where(
                    StudioBoundPack.studio_id == str(studio_id),
                    StudioBoundPack.status == "active",
                    StudioBoundPack.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        if not rows:
            return None

        q = question or ""
        candidates: List[dict] = []
        for r in rows:
            # Library packs come from the yaml registry; user-authored packs
            # (Teach Box, source='user') have no file — their full dict lives
            # inline in pack_body. Prefer the registry, fall back to pack_body.
            pack = registry.get_pack(r.pack_id)
            if not pack and isinstance(getattr(r, "pack_body", None), dict) and r.pack_body:
                pack = r.pack_body
            if not pack:
                continue  # row points at a pack with neither a file nor a body
            # Phase 5: learned win-rate for THIS question-cluster.
            cluster = _wr.cluster_for(q, pack)
            score, samples = await _wr.get_winrate(db, str(studio_id), r.pack_id, cluster)
            if _wr.is_benched(score, samples):
                continue  # proven loser on this pattern — not even a candidate
            candidates.append({
                "pack": pack,
                "binding": dict(r.binding_map or {}),
                "overall_conf": float(r.conf or 0.0),
                "winrate": score,  # None until enough signal -> router treats as neutral
                "_cluster": cluster,
            })
        if not candidates:
            return None

        winner = router.select_pack(q, candidates)
        if not winner:
            return None
        block = router.build_injection_block(winner["pack"], winner.get("binding") or {})
        if not block:
            return None
        return {
            "block": block,
            "pack_id": str(winner["pack"].get("id") or ""),
            "cluster": winner.get("_cluster") or "default",
            "binding": winner.get("binding") or {},
        }
    except Exception:
        return None


async def resolve_injection(db, studio_id: Optional[str], question: str) -> str:
    """Back-compat string form: the winner's injection block, or "" (fail open)."""
    try:
        res = await resolve_pack(db, studio_id, question)
        return (res or {}).get("block", "") if res else ""
    except Exception:
        return ""
