"""Per-agent connector auto-train (train a Data Agent once its sync completes).

Two entry points, both additive + fail-soft + gated on ``flags.AUTOTRAIN``:

  * ON-SYNC — ``run_autotrain_and_log`` is called at the END of
    ``per_user_connector.sync_clone_bg`` (after seed + learn) when the agent's
    auto-train config is enabled with cadence ``on_sync``. It streams table-by-table
    progress into the SAME live sync-log run (``services/connector_sync``) the
    AgentSyncLog terminal polls.
  * MANUAL "Train now" — ``train_bg`` opens its OWN fresh connector_sync run so the
    same terminal shows a live training pass on demand.

Per-agent config lives in
``organization_settings.config['connector_auto_train'][ds_id]``::

    {"enabled": bool, "cadence": "on_sync"|"daily"|"weekly", "auto_approve": bool}

DEFAULT = enabled + on_sync + auto_approve (a freshly-connected agent trains itself
and its proposals go live). The `data_sources` table has NO `config` column (moved to
Connection), so per-agent connector settings use the org-settings bucket — the SAME
pattern as ``services/scheduled_connector_sync`` (connector_auto_sync). No migration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_KEY = "connector_auto_train"
_VALID_CADENCE = ("on_sync", "daily", "weekly")
_DEFAULT = {"enabled": True, "cadence": "on_sync", "auto_approve": True}

_STAGING_CONN_NAME = "City Agent Staging"


# --- per-agent config (org-settings bucket) ---------------------------------

def _defaults() -> dict:
    return dict(_DEFAULT)


async def get_config(db, org_id: str, ds_id: str) -> dict:
    """Read the per-agent auto-train config, defaults applied when unset."""
    try:
        from sqlalchemy import select
        from app.models.organization_settings import OrganizationSettings
        row = (await db.execute(
            select(OrganizationSettings).where(
                OrganizationSettings.organization_id == str(org_id)
            )
        )).scalars().first()
        bucket = ((row.config or {}) if row else {}).get(_KEY) or {}
        entry = bucket.get(str(ds_id))
        if not isinstance(entry, dict):
            return _defaults()
        out = _defaults()
        out.update({k: entry[k] for k in ("enabled", "cadence", "auto_approve") if k in entry})
        if out.get("cadence") not in _VALID_CADENCE:
            out["cadence"] = _DEFAULT["cadence"]
        out["enabled"] = bool(out.get("enabled"))
        out["auto_approve"] = bool(out.get("auto_approve"))
        return out
    except Exception:  # noqa: BLE001 — fail-soft to the enabled default
        logger.debug("connector_auto_train.get_config failed", exc_info=True)
        return _defaults()


async def set_config(
    db, org_id: str, ds_id: str, *,
    enabled=None, cadence=None, auto_approve=None,
) -> dict:
    """Upsert the per-agent auto-train config (partial — only given fields change)."""
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.models.organization_settings import OrganizationSettings

    row = (await db.execute(
        select(OrganizationSettings).where(
            OrganizationSettings.organization_id == str(org_id)
        )
    )).scalars().first()
    if row is None:
        row = OrganizationSettings(organization_id=str(org_id), config={})
        db.add(row)
    cfg = dict(row.config or {})
    bucket = dict(cfg.get(_KEY) or {})
    entry = _defaults()
    prior = bucket.get(str(ds_id))
    if isinstance(prior, dict):
        entry.update({k: prior[k] for k in ("enabled", "cadence", "auto_approve") if k in prior})
    if enabled is not None:
        entry["enabled"] = bool(enabled)
    if cadence is not None and str(cadence) in _VALID_CADENCE:
        entry["cadence"] = str(cadence)
    if auto_approve is not None:
        entry["auto_approve"] = bool(auto_approve)
    if entry.get("cadence") not in _VALID_CADENCE:
        entry["cadence"] = _DEFAULT["cadence"]
    bucket[str(ds_id)] = entry
    cfg[_KEY] = bucket
    row.config = cfg
    flag_modified(row, "config")
    await db.commit()
    return entry


# --- model resolution (data-agent training model) ---------------------------

async def resolve_data_train_model(db, organization, user):
    """Resolve the DATA-AGENT training model, mirroring
    ``routes/autotrain_connector.autotrain_from_connector``:
    org ``default_data_train_model_id`` -> ``default_train_model_id`` ->
    ``LLMModel.is_default``. Fail-soft -> None (autotrain then falls back itself)."""
    from sqlalchemy import select
    from app.models.llm_model import LLMModel
    model = None
    try:
        from app.services.organization_settings_service import OrganizationSettingsService
        _settings = await OrganizationSettingsService().get_settings(db, organization, user)
        _cfg = _settings.config if isinstance(_settings.config, dict) else {}
        _want = _cfg.get("default_data_train_model_id") or _cfg.get("default_train_model_id")
        if _want:
            model = (
                await db.execute(select(LLMModel).where(LLMModel.model_id == _want))
            ).scalars().first()
    except Exception:  # noqa: BLE001
        model = None
    if model is None:
        try:
            model = (
                await db.execute(select(LLMModel).where(LLMModel.is_default == True))  # noqa: E712
            ).scalars().first()
        except Exception:  # noqa: BLE001
            model = None
    return model


# --- auto-approve the just-proposed knowledge -------------------------------

async def _approve_proposed(db, *, org_id: str, ds_id: str, semantic_ids: list, metric_ids: list) -> int:
    """Flip the specific auto-trained proposals (+ this DS's pending Q&A queries)
    from 'pending' to 'approved' so a freshly-connected agent's knowledge is live.
    Scoped to the ids autotrain just created; fail-soft -> returns count flipped."""
    n = 0
    from sqlalchemy import update
    try:
        from app.models.semantic_table import SemanticTable
        from app.models.metric_definition import MetricDefinition
        from app.models.query_library import QueryLibraryItem
    except Exception:  # noqa: BLE001
        return 0
    try:
        if semantic_ids:
            res = await db.execute(
                update(SemanticTable)
                .where(
                    SemanticTable.id.in_([str(x) for x in semantic_ids]),
                    SemanticTable.status == "pending",
                )
                .values(status="approved")
            )
            n += int(res.rowcount or 0)
        if metric_ids:
            res = await db.execute(
                update(MetricDefinition)
                .where(
                    MetricDefinition.id.in_([str(x) for x in metric_ids]),
                    MetricDefinition.status == "pending",
                )
                .values(status="approved")
            )
            n += int(res.rowcount or 0)
        # Q&A rows only carry a count in the summary; approve this DS's pending
        # query-library rows (freshly proposed by this training pass).
        res = await db.execute(
            update(QueryLibraryItem)
            .where(
                QueryLibraryItem.organization_id == str(org_id),
                QueryLibraryItem.data_source_id == str(ds_id),
                QueryLibraryItem.status == "pending",
            )
            .values(status="approved")
        )
        n += int(res.rowcount or 0)
        await db.commit()
    except Exception:  # noqa: BLE001
        logger.warning("connector_auto_train._approve_proposed failed for %s", ds_id, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0
    return n


# --- the shared per-table training loop (writes the live sync log) ----------

async def run_autotrain_and_log(
    db, *, organization, data_source, user, model=None,
    auto_approve: bool = True, phase: str = "training", use_counters: bool = False,
) -> dict:
    """Train every ACTIVE non-staging table of ``data_source`` -> PENDING knowledge
    (optionally auto-approved), streaming table-by-table progress into the live
    connector_sync run keyed by the data source id. Never raises.

    ``phase`` = the connector_sync phase to tag lines with ('learning' for the
    on-sync append so the FE stage strip stays coherent, 'training' for a dedicated
    Train-now run). ``use_counters`` drives the run's tables_total / tables_done bar
    (only for a dedicated run that started clean — NOT for the on-sync append, which
    would overshoot the sync's own count). Returns a small summary dict.
    """
    from app.services import connector_sync
    from app.services.autotrain import connector as connector_svc
    from app.routes.autotrain_connector import _columns_for_table, _connection_is_staging

    out = {"tables": 0, "semantics": 0, "metrics": 0, "qa": 0, "approved": 0, "errors": []}
    try:
        from app.settings.hybrid_flags import flags
        if not flags.AUTOTRAIN:
            out["errors"].append("AUTOTRAIN flag OFF")
            return out
    except Exception:  # noqa: BLE001
        out["errors"].append("flags import failed")
        return out

    ds_id = str(getattr(data_source, "id", "") or "")
    org_id = str(getattr(organization, "id", "") or "")
    if not ds_id or not org_id:
        out["errors"].append("missing org/ds")
        return out

    if model is None:
        model = await resolve_data_train_model(db, organization, user)

    # Build the (table, columns) worklist — active, non-deleted, non-staging.
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
    except Exception:  # noqa: BLE001
        logger.exception("connector_auto_train: load tables failed for %s", ds_id)
        out["errors"].append("load tables failed")
        return out

    worklist = [r for r in rows if r.name and not _connection_is_staging(r)]
    total = len(worklist)
    if total == 0:
        await connector_sync.log_step(
            db, ds_id, level="ok", phase=phase,
            msg="auto-train: no live tables to train",
        )
        return out

    if use_counters:
        await connector_sync.set_totals(db, ds_id, tables_total=total)
    await connector_sync.log_step(
        db, ds_id, level="step", phase=phase, stage="profile",
        msg=f"Auto-training on {total} table{'s' if total != 1 else ''}…",
    )

    sem_ids: list = []
    met_ids: list = []
    for r in worklist:
        name = r.name
        # Each per-table autotrain_connector call generates a table description +
        # column meanings (→ 'meanings'), heuristic metrics (→ 'metrics') and Q&A
        # (→ 'queries'). The dominant, always-present output is the table/column
        # meaning, so the per-table line carries the 'meanings' stage; metrics /
        # queries are summarised after the loop (only when actually produced).
        await connector_sync.log_step(
            db, ds_id, level="active", phase=phase, stage="meanings",
            msg=f"Training {name}…",
        )
        cols = _columns_for_table(r)
        try:
            summary = await connector_svc.autotrain_connector(
                db, organization=organization, data_source=data_source,
                table=name, columns=cols, model=model,
            )
        except Exception as e:  # autotrain_connector never raises, belt+suspenders
            logger.exception("connector_auto_train: table %s failed", name)
            out["errors"].append(f"{name}: {str(e)[:160]}")
            await connector_sync.log_step(
                db, ds_id, level="error", phase=phase, msg=f"{name} — training error",
            )
            continue
        sem_ids.extend(summary.get("semantics") or [])
        met_ids.extend(summary.get("metrics") or [])
        out["semantics"] += len(summary.get("semantics") or [])
        out["metrics"] += len(summary.get("metrics") or [])
        out["qa"] += int(summary.get("qa") or 0)
        out["tables"] += 1
        await connector_sync.log_step(
            db, ds_id, level="ok", phase=phase, stage="meanings",
            table=(name if use_counters else None),
            msg=f"Trained {name}", status=("done" if use_counters else None),
            inc_tables=bool(use_counters),
        )

    # Summarise the metrics / queries stages once (only when the run actually
    # produced them — a PBI connector with no SQL Q&A leaves 'queries' unseen →
    # the FE shows it 'skipped', which is honest).
    if out["metrics"]:
        await connector_sync.log_step(
            db, ds_id, level="ok", phase=phase, stage="metrics",
            msg=f"saved {out['metrics']} metric{'s' if out['metrics'] != 1 else ''}",
        )
    if out["qa"]:
        await connector_sync.log_step(
            db, ds_id, level="ok", phase=phase, stage="queries",
            msg=f"captured {out['qa']} example quer{'ies' if out['qa'] != 1 else 'y'}",
        )

    if auto_approve and (sem_ids or met_ids or out["qa"]):
        try:
            approved = await _approve_proposed(
                db, org_id=org_id, ds_id=ds_id, semantic_ids=sem_ids, metric_ids=met_ids,
            )
            out["approved"] = approved
            if approved:
                await connector_sync.log_step(
                    db, ds_id, level="ok", phase=phase, stage="rules",
                    msg=f"approved {approved} auto-trained knowledge item{'s' if approved != 1 else ''}",
                )
        except Exception:  # noqa: BLE001
            logger.warning("connector_auto_train: approve step failed for %s", ds_id, exc_info=True)
    elif not auto_approve and out["tables"]:
        await connector_sync.log_step(
            db, ds_id, level="ok", phase=phase, stage="rules",
            msg="left auto-trained knowledge PENDING (approve in Knowledge > Review)",
        )

    await connector_sync.log_step(
        db, ds_id, level="ok", phase=phase,
        msg=f"Auto-train complete: {out['tables']} table{'s' if out['tables'] != 1 else ''}",
    )
    return out


# --- background worker for the manual "Train now" endpoint -------------------

async def train_bg(ds_id: str, org_id: str, user_id: str, auto_approve=None) -> None:
    """Background worker for POST /data_sources/{id}/train — opens its OWN fresh
    connector_sync run so the AgentSyncLog terminal shows a live training pass on
    demand. Own DB session (the request session is closed by now); fully fail-soft.
    ``auto_approve`` None -> fall back to the agent's saved auto-train config."""
    from app.dependencies import async_session_maker
    from app.services import connector_sync
    from sqlalchemy import select
    from app.models.data_source import DataSource
    from app.models.organization import Organization
    from app.models.user import User
    from sqlalchemy.orm import selectinload

    ds_id = str(ds_id)
    org_id = str(org_id)
    user_id = str(user_id)
    try:
        async with async_session_maker() as db:
            await connector_sync.start_run(db, data_source_id=ds_id, organization_id=org_id)
            await connector_sync.log_step(
                db, ds_id, level="step", phase="training", stage="discover",
                msg="starting training",
            )
            ds = (
                await db.execute(
                    select(DataSource)
                    .options(selectinload(DataSource.connections))
                    .where(DataSource.id == ds_id)
                )
            ).scalars().first()
            org = (
                await db.execute(select(Organization).where(Organization.id == org_id))
            ).scalars().first()
            user = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalars().first()
            if ds is None or org is None:
                await connector_sync.finish_run(db, ds_id, phase="error", error="agent not found")
                await connector_sync.log_step(
                    db, ds_id, level="error", phase="error", msg="agent not found",
                )
                return
            if auto_approve is None:
                cfg = await get_config(db, org_id, ds_id)
                auto_approve = bool(cfg.get("auto_approve", True))
            await run_autotrain_and_log(
                db, organization=org, data_source=ds, user=user,
                auto_approve=bool(auto_approve), phase="training", use_counters=True,
            )
            await connector_sync.finish_run(db, ds_id, phase="done")
            await connector_sync.log_step(
                db, ds_id, level="ok", phase="done", stage="ready",
                msg="training complete",
            )
            # Bust the cached agent Overview so the next open reflects new knowledge.
            try:
                from app.routes.data_source import invalidate_overview_cache
                invalidate_overview_cache(ds_id)
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001
        logger.warning("connector_auto_train.train_bg failed for %s: %s", ds_id, e)
        try:
            async with async_session_maker() as db2:
                await connector_sync.finish_run(db2, ds_id, phase="error", error=str(e))
                await connector_sync.log_step(
                    db2, ds_id, level="error", phase="error", msg=str(e),
                )
        except Exception:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
