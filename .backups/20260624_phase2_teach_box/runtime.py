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


async def resolve_injection(db, studio_id: Optional[str], question: str) -> str:
    """Pick the best ACTIVE bound pack for this studio+question and render it."""
    try:
        if not db or not studio_id:
            return ""
        from sqlalchemy import select
        from app.models.studio import StudioBoundPack
        from app.ai.packs import registry, router

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
            return ""

        candidates: List[dict] = []
        for r in rows:
            pack = registry.get_pack(r.pack_id)
            if not pack:
                continue  # row points at a pack no longer in the library
            candidates.append({
                "pack": pack,
                "binding": dict(r.binding_map or {}),
                "overall_conf": float(r.conf or 0.0),
                "winrate": None,  # Phase 5 pack_winrate feeds this
            })
        if not candidates:
            return ""

        winner = router.select_pack(question or "", candidates)
        if not winner:
            return ""
        return router.build_injection_block(winner["pack"], winner.get("binding") or {})
    except Exception:
        return ""
