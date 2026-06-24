"""Resolve a (question, answer) pair from a dash Completion row.

dash stores a chat turn as TWO sibling Completion rows in the same report:
  - the ``user`` row carries the question in ``prompt['content']`` (``completion`` empty)
  - the ``system`` row carries the answer in ``completion['content']`` (``prompt`` null)

The hybrid distiller / skill-authoring originally read BOTH fields off a single
row, so whichever row they got handed was missing half the pair and they bailed
out (returning None). This helper resolves the missing half from the paired
sibling via ``turn_index`` so callers get the full (question, answer) regardless
of which row they were handed.

Defensive throughout: malformed JSON, absent keys, or a failed sibling lookup
degrade to '' for the missing side — never raises.
"""

from __future__ import annotations

from typing import Any, Tuple


def _content(obj: Any) -> str:
    """Pull a 'content' string from a JSON column (dict | str | other)."""
    try:
        if isinstance(obj, dict):
            return str(obj.get("content") or "")
        if isinstance(obj, str):
            return obj
    except Exception:
        pass
    return ""


async def resolve_qa_pair(db: Any, completion: Any) -> Tuple[str, str]:
    """Return ``(question, answer)`` for the chat turn ``completion`` belongs to.

    Reads the row's own fields first; if the question (user side) or the answer
    (system side) is missing, fetches it from the nearest sibling row in the same
    report by ``turn_index``. Any failure leaves that side as ''.
    """
    question = _content(getattr(completion, "prompt", None))
    answer = _content(getattr(completion, "completion", None))

    if question and answer:
        return question, answer

    try:
        from sqlalchemy import select
        from app.models.completion import Completion

        report_id = getattr(completion, "report_id", None)
        turn_index = getattr(completion, "turn_index", None)

        if report_id is not None and turn_index is not None:
            if not question:
                # We were handed the answer (system) row -> question is the
                # nearest PRIOR user turn.
                stmt = (
                    select(Completion)
                    .where(Completion.report_id == report_id)
                    .where(Completion.turn_index < turn_index)
                    .where(Completion.role == "user")
                    .order_by(Completion.turn_index.desc())
                    .limit(1)
                )
                prior = (await db.execute(stmt)).scalars().first()
                if prior is not None:
                    question = _content(getattr(prior, "prompt", None)) or question

            if not answer:
                # We were handed the question (user) row -> answer is the nearest
                # NEXT non-user (system/assistant) turn.
                stmt = (
                    select(Completion)
                    .where(Completion.report_id == report_id)
                    .where(Completion.turn_index > turn_index)
                    .where(Completion.role != "user")
                    .order_by(Completion.turn_index.asc())
                    .limit(1)
                )
                nxt = (await db.execute(stmt)).scalars().first()
                if nxt is not None:
                    answer = _content(getattr(nxt, "completion", None)) or answer
    except Exception:
        # Never let the sibling lookup break the caller.
        pass

    return question, answer
