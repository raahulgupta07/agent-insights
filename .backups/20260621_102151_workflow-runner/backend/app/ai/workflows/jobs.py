"""Concrete deterministic workflows built on the pure `runner` engine.

Each job resolves a work-list, picks a worker `stage_fn`, picks a verifier
`judge_fn`, and hands them to `run_pipeline`. Jobs NEVER raise -> they return
the engine summary dict (or a tiny error-shaped summary).

`WORKFLOWS` = name -> coroutine registry used by the HTTP surface.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.ai.workflows.runner import (
    run_pipeline,
    llm_judge,
    produced_knowledge_judge,
)

logger = logging.getLogger(__name__)


def _empty_summary(label: str, reason: str) -> dict:
    return {
        "label": label,
        "processed": 0,
        "passed": 0,
        "skipped": 0,
        "failed": 0,
        "log": [],
        "results": [],
        "note": reason,
    }


async def train_connector_tables(
    *,
    db,
    organization,
    user=None,
    data_source,
    model=None,
    max_tables: int = 25,
    use_llm_judge: bool = False,
) -> dict:
    """Autotrain a whole data source, reliably, with a per-table verifier gate.

    Resolves the data source's ACTIVE live connector tables exactly like
    `app/services/autotrain/connector.py::autotrain_data_source` (selectinload
    DataSourceTable -> connection_table -> connection; skip 'City Agent Staging';
    columns via `_columns_for_dst_row`), caps at `max_tables`, then runs each
    table through `autotrain_connector` gated by a knowledge verifier.

    Never raises.
    """
    label = "train_connector_tables"

    # Reuse the connector service's table-resolution helpers (module-level).
    try:
        from app.services.autotrain.connector import (
            autotrain_connector,
            _columns_for_dst_row,
            _dst_row_is_staging,
            _safe_ident,
        )
    except Exception:
        logger.exception("%s: could not import connector service", label)
        return _empty_summary(label, "connector service import failed")

    org_id = getattr(organization, "id", None)
    ds_id = getattr(data_source, "id", None)
    if not org_id or not ds_id:
        return _empty_summary(label, "missing org/ds")

    # --- default model (best-effort) ----------------------------------------
    if model is None:
        try:
            from sqlalchemy import select as _select
            from app.models.llm_model import LLMModel

            model = (
                await db.execute(
                    _select(LLMModel).where(LLMModel.is_default == True)  # noqa: E712
                )
            ).scalars().first()
        except Exception:
            logger.info("%s: default model lookup failed", label, exc_info=True)
            model = None

    # --- resolve active DataSourceTable rows --------------------------------
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.connection_table import ConnectionTable
        from app.models.datasource_table import DataSourceTable

        rows = (
            await db.execute(
                select(DataSourceTable)
                .where(
                    DataSourceTable.datasource_id == ds_id,
                    DataSourceTable.is_active == True,  # noqa: E712
                    DataSourceTable.deleted_at.is_(None),
                )
                .options(
                    selectinload(DataSourceTable.connection_table).selectinload(
                        ConnectionTable.connection
                    )
                )
            )
        ).scalars().all()
    except Exception:
        logger.exception("%s: failed to load tables", label)
        return _empty_summary(label, "load tables failed")

    # Build the (name, columns) work-list: skip staging + unsafe idents, cap.
    try:
        cap = max(1, int(max_tables or 1))
    except Exception:
        cap = 1
    worklist: list = []
    for r in rows:
        if len(worklist) >= cap:
            break
        name = getattr(r, "name", None)
        if not name or not _safe_ident(name):
            continue
        if _dst_row_is_staging(r):
            continue
        worklist.append((name, _columns_for_dst_row(r)))

    if not worklist:
        return _empty_summary(label, "no trainable connector tables")

    # --- stage worker: autotrain ONE table ----------------------------------
    async def _stage(table_tuple):
        table, cols = table_tuple
        return await autotrain_connector(
            db,
            organization=organization,
            data_source=data_source,
            table=table,
            columns=cols,
            model=model,
        )

    # --- verifier gate -------------------------------------------------------
    if use_llm_judge:
        judge = llm_judge(
            model,
            criteria=(
                "the table got a useful semantic description + at least one "
                "metric or verified Q&A"
            ),
        )
    else:
        judge = produced_knowledge_judge()

    return await run_pipeline(
        items=worklist,
        stage_fn=_stage,
        judge_fn=judge,
        label=label,
        # MUST be 1: autotrain_connector's writeback commits on the SHARED async
        # session — concurrent items collide ("Session is already flushing").
        # Sequential is correct here; the engine still supports concurrency for
        # jobs whose stage_fn uses its own session.
        max_concurrency=1,
    )


WORKFLOWS = {"train_connector_tables": train_connector_tables}
