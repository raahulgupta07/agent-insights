"""Autotrain writeback: persist proposals as PENDING knowledge.

Thin adapter over the existing approval-safe brain helpers so autotrain reuses
the SAME pending -> curator/human -> approved bus as use-time learning. Never
writes 'approved'. Never raises.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def write_semantic(db, *, org_id: str, ds_id: str, table_name: str, description: str) -> Optional[str]:
    try:
        from app.ai.brain.knowledge_proposer import _propose_semantic_table

        return await _propose_semantic_table(
            db, org_id=org_id, ds_id=ds_id, table_name=table_name, description=description
        )
    except Exception:
        logger.exception("write_semantic failed for %s", table_name)
        return None


async def write_metric(
    db, *, org_id: str, ds_id: str, name: str, definition: str, sql_calc: str, table_ref: str
) -> Optional[str]:
    try:
        from app.ai.brain.knowledge_proposer import _propose_metric

        return await _propose_metric(
            db,
            org_id=org_id,
            ds_id=ds_id,
            name=name,
            definition=definition,
            sql_calc=sql_calc,
            table_ref=table_ref,
        )
    except Exception:
        logger.exception("write_metric failed for %s", name)
        return None
