"""Phase 5 — pack win-rate signal (adaptive demote).

A pack that keeps producing answers the user thumbs DOWN should stop winning the
router on that kind of question. This module is the feedback loop:

  fire   : at injection time the router picks a pack for a turn -> record_fire()
           writes ONE PackFireEvent linking the completion to (pack_id, cluster).
  signal : when the user thumbs that completion -> record_signal_for_completion()
           looks the fire up and increments passes/fails on PackWinrate.
  read   : the runtime resolver calls get_winrate() per candidate and feeds the
           score into router.score_candidate (low score => demoted; a proven
           loser is benched below the select floor entirely).

`question_cluster` keeps win-rate per question-pattern, not per pack globally, so
a pack that's great at "exec summary" but bad at "cohort retention" is demoted
only on the latter. The cluster is the pack trigger-hint the question matched
(cheap, reviewable); falls back to the pack domain, then "default".

Everything fail-soft + ASCII. Gated by flags.DOMAIN_PACKS at every entry.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# A loser is BENCHED (skipped as a candidate) only once we have enough signal.
_HARD_DEMOTE_SCORE = 0.15
_HARD_DEMOTE_MIN_SAMPLES = 5


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def cluster_for(question: str, pack: dict) -> str:
    """Pick the question-cluster key for a (question, pack): the trigger hint the
    question matched, else the pack domain, else 'default'. Pure, never raises."""
    try:
        q = _norm(question)
        hints = (pack or {}).get("trigger_hints") or []
        if q:
            qtokens = set(q.split(" "))
            for h in hints:
                ht = _norm(h)
                if not ht:
                    continue
                toks = ht.split(" ")
                if ht in q or all(t in qtokens for t in toks):
                    return ht[:160]
            # weaker: any distinctive single token
            for h in hints:
                ht = _norm(h)
                for t in ht.split(" "):
                    if len(t) >= 4 and t in qtokens:
                        return ht[:160]
        dom = _norm((pack or {}).get("domain"))
        return (dom or "default")[:160]
    except Exception:
        return "default"


async def record_fire(db, *, completion_id: str, studio_id: str,
                      organization_id: Optional[str], pack_id: str,
                      question_cluster: str) -> None:
    """Upsert the (one) PackFireEvent for a completion. Commits. Never raises."""
    try:
        if not completion_id or not pack_id:
            return
        from app.settings.hybrid_flags import flags
        if not getattr(flags, "DOMAIN_PACKS", False):
            return
        from sqlalchemy import select
        from app.models.studio import PackFireEvent

        existing = (
            await db.execute(
                select(PackFireEvent).where(
                    PackFireEvent.completion_id == str(completion_id),
                    PackFireEvent.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if existing is not None:
            existing.pack_id = str(pack_id)
            existing.question_cluster = (question_cluster or "default")[:160]
            existing.studio_id = str(studio_id)
            if organization_id:
                existing.organization_id = str(organization_id)
        else:
            db.add(PackFireEvent(
                completion_id=str(completion_id),
                studio_id=str(studio_id),
                organization_id=str(organization_id) if organization_id else None,
                pack_id=str(pack_id),
                question_cluster=(question_cluster or "default")[:160],
            ))
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("pack record_fire failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass


async def record_signal_for_completion(db, completion_id: str, passed: bool) -> dict:
    """Convert a thumbs vote on a completion into a pass/fail on PackWinrate.

    Looks up the completion's PackFireEvent; if a pack fired, increments
    passes/fails on the (studio, pack, cluster) row and recomputes score.
    Returns a small summary. Commits. Never raises."""
    try:
        from app.settings.hybrid_flags import flags
        if not getattr(flags, "DOMAIN_PACKS", False):
            return {"disabled": True}
        from sqlalchemy import select
        from app.models.studio import PackFireEvent, PackWinrate

        fire = (
            await db.execute(
                select(PackFireEvent).where(
                    PackFireEvent.completion_id == str(completion_id),
                    PackFireEvent.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if fire is None:
            return {"ok": True, "no_fire": True}

        cluster = fire.question_cluster or "default"
        row = (
            await db.execute(
                select(PackWinrate).where(
                    PackWinrate.studio_id == fire.studio_id,
                    PackWinrate.pack_id == fire.pack_id,
                    PackWinrate.question_cluster == cluster,
                    PackWinrate.deleted_at.is_(None),
                )
            )
        ).scalars().first()
        if row is None:
            row = PackWinrate(
                studio_id=fire.studio_id, pack_id=fire.pack_id,
                question_cluster=cluster, passes=0, fails=0,
            )
            db.add(row)
        if passed:
            row.passes = int(row.passes or 0) + 1
        else:
            row.fails = int(row.fails or 0) + 1
        total = int(row.passes or 0) + int(row.fails or 0)
        row.score = round(int(row.passes or 0) / total, 4) if total else None
        await db.commit()
        return {"ok": True, "pack_id": fire.pack_id, "cluster": cluster,
                "passes": row.passes, "fails": row.fails, "score": row.score}
    except Exception as e:  # noqa: BLE001
        logger.debug("pack record_signal failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}


async def get_winrate(db, studio_id: str, pack_id: str,
                      cluster: Optional[str] = None) -> Tuple[Optional[float], int]:
    """Return (score, samples) for a pack. Prefer the given cluster; else aggregate
    every cluster of the pack. (None, 0) when there is no signal. Never raises."""
    try:
        from sqlalchemy import select
        from app.models.studio import PackWinrate

        q = select(PackWinrate).where(
            PackWinrate.studio_id == str(studio_id),
            PackWinrate.pack_id == str(pack_id),
            PackWinrate.deleted_at.is_(None),
        )
        if cluster:
            q = q.where(PackWinrate.question_cluster == cluster)
        rows = (await db.execute(q)).scalars().all()
        if not rows and cluster:
            # fall back to the pack's aggregate across clusters
            return await get_winrate(db, studio_id, pack_id, cluster=None)
        passes = sum(int(r.passes or 0) for r in rows)
        fails = sum(int(r.fails or 0) for r in rows)
        total = passes + fails
        if total == 0:
            return None, 0
        return round(passes / total, 4), total
    except Exception as e:  # noqa: BLE001
        logger.debug("pack get_winrate failed: %s", e)
        return None, 0


def is_benched(score: Optional[float], samples: int) -> bool:
    """A proven loser: enough samples AND a low score -> skip as a candidate."""
    return (
        score is not None
        and samples >= _HARD_DEMOTE_MIN_SAMPLES
        and score < _HARD_DEMOTE_SCORE
    )
