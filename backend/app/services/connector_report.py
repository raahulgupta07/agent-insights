"""Connector Reports — per-connector-template usage rollup for the admin
Connectors settings page. Read-only, org-scoped, fail-soft.

In this fork a "per-user connector" is a CLONED DataSource: `template_source_id`
points at the admin's template DataSource and `is_user_template=False`. We roll
usage up per connector TEMPLATE, listing every user who registered a clone with
their usage metrics (questions, tokens, cost, sync state).

Query idioms mirror app/services/console_service.py (LLMUsageRecord group-by +
User/DataSource joins). Question COUNT joins Completion → the
report_data_source_association assoc table filtered to the clone's data_source_id
(clones are per-user so this is a clean per-connector attribution).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.data_source import DataSource
from app.models.user import User
from app.models.completion import Completion
from app.models.datasource_table import DataSourceTable
from app.models.llm_usage_record import LLMUsageRecord
from app.models.connector_sync_run import ConnectorSyncRun
from app.models.user_data_source_credentials import UserDataSourceCredentials
from app.models.report_data_source_association import report_data_source_association

logger = logging.getLogger(__name__)

# Known connector catalog — mirrors frontend/pages/settings/connectors.vue.
# (key, connection_type, label). Order is the desired display order.
_CATALOG = [
    ("powerbi", "powerbi_user", "Power BI"),
    ("fabric", "ms_fabric", "Microsoft Fabric"),
    ("onedrive", "onedrive", "OneDrive"),
    ("sharepoint", "sharepoint", "SharePoint"),
]
_TYPE_TO_META = {typ: (key, label) for key, typ, label in _CATALOG}
_ORDER = {key: i for i, (key, _typ, _label) in enumerate(_CATALOG)}


def _connector_kind(ds: DataSource) -> str | None:
    """The backing connection type for a template/clone DataSource, or None."""
    try:
        conns = ds.connections or []
        if conns:
            return conns[0].type
    except Exception:
        pass
    return None


def _conn_account_email(ds: DataSource) -> str | None:
    """Real connector sign-in email for a per-user clone (e.g. the Microsoft /
    Power BI account, distinct from the app-login email). Read from the clone's
    connection `config` JSON, falling back to the clone name suffix
    "<Template> · <email>". Returns None if not present."""
    try:
        for conn in (ds.connections or []):
            cfg = getattr(conn, "config", None) or {}
            if isinstance(cfg, dict):
                for k in ("email", "ms_account_email", "upn", "userPrincipalName",
                          "account_email", "account", "username"):
                    v = cfg.get(k)
                    if isinstance(v, str) and "@" in v:
                        return v.strip()
    except Exception:
        pass
    try:
        nm = ds.name or ""
        if "·" in nm:
            tail = nm.rsplit("·", 1)[-1].strip()
            if "@" in tail:
                return tail
    except Exception:
        pass
    return None


def _prompt_text(p) -> str:
    """Best-effort plain text out of a Completion.prompt JSON value."""
    if p is None:
        return ""
    if isinstance(p, str):
        return p.strip()
    if isinstance(p, dict):
        return str(p.get("content") or p.get("text") or p.get("prompt") or "").strip()
    return str(p).strip()


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


async def connector_report(db, organization_id, days: int = 30) -> list[dict]:
    """Per connector-template rollup with a per-user usage row list.

    Includes ALL known catalog connectors even with zero configured template /
    zero users (so OneDrive/SharePoint render as empty groups). Usage aggregates
    (questions/tokens/cost) are windowed to the last `days`; connected_at and
    table counts are lifetime.
    """
    org_id = str(organization_id)
    days = max(1, int(days or 30))
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)
    seven = now - timedelta(days=7)

    # 1. Templates in this org (each is a connector the admin configured once).
    templates = (await db.execute(
        select(DataSource)
        .where(
            DataSource.organization_id == org_id,
            DataSource.is_user_template == True,  # noqa: E712
            DataSource.deleted_at.is_(None),
        )
        .options(selectinload(DataSource.connections))
    )).scalars().all()

    template_ids = [str(t.id) for t in templates]

    # 2. User clones registered against those templates.
    clones: list[DataSource] = []
    if template_ids:
        clones = (await db.execute(
            select(DataSource)
            .where(
                DataSource.template_source_id.in_(template_ids),
                DataSource.is_user_template == False,  # noqa: E712
                DataSource.deleted_at.is_(None),
            )
            .options(selectinload(DataSource.connections))
        )).scalars().all()

    clone_ids = [str(c.id) for c in clones]

    # 3. Owner users (email/name).
    user_ids = list({str(c.owner_user_id) for c in clones if c.owner_user_id})
    users: dict[str, User] = {}
    if user_ids:
        urows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        users = {str(u.id): u for u in urows}

    # 4. Token/cost aggregates by clone data_source_id (windowed).
    usage: dict[str, dict] = {}
    if clone_ids:
        rows = (await db.execute(
            select(
                LLMUsageRecord.data_source_id.label("ds"),
                func.coalesce(
                    func.sum(LLMUsageRecord.prompt_tokens + LLMUsageRecord.completion_tokens), 0
                ).label("tokens"),
                func.coalesce(func.sum(LLMUsageRecord.total_cost_usd), 0).label("cost"),
                func.max(LLMUsageRecord.created_at).label("last_used"),
            )
            .where(
                LLMUsageRecord.organization_id == org_id,
                LLMUsageRecord.data_source_id.in_(clone_ids),
                LLMUsageRecord.created_at >= cutoff,
            )
            .group_by(LLMUsageRecord.data_source_id)
        )).all()
        for r in rows:
            usage[str(r.ds)] = {
                "tokens": int(r.tokens or 0),
                "cost": float(r.cost or 0),
                "last_used": r.last_used,
            }

    # 5. Question counts by clone data_source_id (Completion role='user',
    #    joined via the report↔data_source assoc, windowed).
    questions: dict[str, int] = {}
    if clone_ids:
        rows = (await db.execute(
            select(
                report_data_source_association.c.data_source_id.label("ds"),
                func.count(Completion.id).label("q"),
            )
            .select_from(Completion)
            .join(
                report_data_source_association,
                report_data_source_association.c.report_id == Completion.report_id,
            )
            .where(
                report_data_source_association.c.data_source_id.in_(clone_ids),
                Completion.role == "user",
                Completion.deleted_at.is_(None),
                Completion.created_at >= cutoff,
            )
            .group_by(report_data_source_association.c.data_source_id)
        )).all()
        for r in rows:
            questions[str(r.ds)] = int(r.q or 0)

    # 6. Sync run per clone (status/tables/error).
    sync: dict[str, ConnectorSyncRun] = {}
    if clone_ids:
        srows = (await db.execute(
            select(ConnectorSyncRun).where(ConnectorSyncRun.data_source_id.in_(clone_ids))
        )).scalars().all()
        for s in srows:
            sync[str(s.data_source_id)] = s

    # 7. Credential last_used_at per clone (fallback / signal for status).
    cred_last: dict[str, datetime] = {}
    if clone_ids:
        rows = (await db.execute(
            select(
                UserDataSourceCredentials.data_source_id.label("ds"),
                func.max(UserDataSourceCredentials.last_used_at).label("lu"),
            )
            .where(UserDataSourceCredentials.data_source_id.in_(clone_ids))
            .group_by(UserDataSourceCredentials.data_source_id)
        )).all()
        for r in rows:
            if r.lu:
                cred_last[str(r.ds)] = r.lu

    # 8. Table counts per clone (fallback when the sync run has no tables_total).
    tbl_count: dict[str, int] = {}
    if clone_ids:
        rows = (await db.execute(
            select(
                DataSourceTable.datasource_id.label("ds"),
                func.count(DataSourceTable.id).label("n"),
            )
            .where(DataSourceTable.datasource_id.in_(clone_ids))
            .group_by(DataSourceTable.datasource_id)
        )).all()
        for r in rows:
            tbl_count[str(r.ds)] = int(r.n or 0)

    # --- Assemble groups keyed by connector KEY -----------------------------
    # Start from the full catalog so empty connectors still show.
    groups: dict[str, dict] = {}
    for key, typ, label in _CATALOG:
        groups[key] = {
            "connector_key": key,
            "connector_label": label,
            "connector_type": typ,
            "template_data_source_id": None,
            "connected_count": 0,
            "active_7d": 0,
            "questions": 0,
            "tokens": 0,
            "cost_usd": 0.0,
            "last_used_at": None,
            "users": [],
        }

    # Map each template to a group key (falls back to a synthetic key for
    # connector types not in the known catalog).
    tpl_key: dict[str, str] = {}
    for t in templates:
        typ = _connector_kind(t)
        key, label = _TYPE_TO_META.get(typ or "", (None, None))
        if key is None:
            # Unknown connector type — surface it under its own key at the end.
            key = ("other:" + (typ or (t.name or "connector"))).lower()
            if key not in groups:
                groups[key] = {
                    "connector_key": key,
                    "connector_label": t.name or (typ or "Connector"),
                    "connector_type": typ,
                    "template_data_source_id": None,
                    "connected_count": 0,
                    "active_7d": 0,
                    "questions": 0,
                    "tokens": 0,
                    "cost_usd": 0.0,
                    "last_used_at": None,
                    "users": [],
                }
        tpl_key[str(t.id)] = key
        # First configured template of this kind owns the template id.
        if groups[key]["template_data_source_id"] is None:
            groups[key]["template_data_source_id"] = str(t.id)

    # Attach each clone as a user row under its template's group.
    for c in clones:
        cid = str(c.id)
        key = tpl_key.get(str(c.template_source_id))
        if key is None or key not in groups:
            continue
        g = groups[key]

        u = users.get(str(c.owner_user_id)) if c.owner_user_id else None
        us = usage.get(cid, {})
        toks = int(us.get("tokens", 0) or 0)
        cost = float(us.get("cost", 0) or 0)
        q = int(questions.get(cid, 0) or 0)

        run = sync.get(cid)
        last_used = us.get("last_used") or cred_last.get(cid) or c.last_synced_at

        # Status: error if the sync errored; live if used within 7d; else idle.
        if run is not None and (run.error or run.phase == "error"):
            status = "error"
        elif last_used and last_used >= seven:
            status = "live"
        else:
            status = "idle"

        tables = 0
        if run is not None and run.tables_total:
            tables = int(run.tables_total or 0)
        else:
            tables = int(tbl_count.get(cid, 0) or 0)

        g["users"].append({
            "data_source_id": cid,
            "user_id": str(c.owner_user_id) if c.owner_user_id else None,
            "email": (u.email if u else None),
            "connector_email": _conn_account_email(c),
            "name": (u.name if u else None),
            "status": status,
            "connected_at": _iso(c.created_at),
            "last_used_at": _iso(last_used),
            "tables": tables,
            "questions": q,
            "tokens": toks,
            "cost_usd": round(cost, 4),
        })

        # Roll up group totals.
        g["connected_count"] += 1
        if status == "live":
            g["active_7d"] += 1
        g["questions"] += q
        g["tokens"] += toks
        g["cost_usd"] = round(g["cost_usd"] + cost, 4)
        if last_used and (g["last_used_at"] is None or _iso(last_used) > g["last_used_at"]):
            g["last_used_at"] = _iso(last_used)

    # Sort user rows within each group by last_used desc (nulls last).
    for g in groups.values():
        g["users"].sort(key=lambda r: (r["last_used_at"] or ""), reverse=True)

    # Order: catalog order first, then unknown "other:" groups by label.
    ordered = sorted(
        groups.values(),
        key=lambda g: (_ORDER.get(g["connector_key"], 100 + len(_ORDER)), g["connector_label"] or ""),
    )
    return ordered


async def connector_user_detail(db, organization_id, data_source_id, days: int = 30) -> dict:
    """Per-user connector detail (one clone). Usage windowed to `days`;
    daily_questions is the last 14 days regardless of window."""
    org_id = str(organization_id)
    ds_id = str(data_source_id)
    days = max(1, int(days or 30))
    now = datetime.utcnow()
    cutoff = now - timedelta(days=days)
    seven = now - timedelta(days=7)

    clone = (await db.execute(
        select(DataSource)
        .where(
            DataSource.id == ds_id,
            DataSource.organization_id == org_id,
            DataSource.deleted_at.is_(None),
        )
        .options(selectinload(DataSource.connections))
    )).scalars().first()
    if clone is None:
        return {"error": "not_found"}

    # Connector label from the template's kind (fall back to the clone's own).
    label = None
    typ = None
    if clone.template_source_id:
        tpl = (await db.execute(
            select(DataSource)
            .where(DataSource.id == str(clone.template_source_id))
            .options(selectinload(DataSource.connections))
        )).scalars().first()
        if tpl is not None:
            typ = _connector_kind(tpl)
    if typ is None:
        typ = _connector_kind(clone)
    label = _TYPE_TO_META.get(typ or "", (None, typ or "Connector"))[1]

    owner = None
    if clone.owner_user_id:
        owner = (await db.execute(
            select(User).where(User.id == str(clone.owner_user_id))
        )).scalars().first()

    # Token in/out + cost (windowed).
    tok = (await db.execute(
        select(
            func.coalesce(func.sum(LLMUsageRecord.prompt_tokens), 0),
            func.coalesce(func.sum(LLMUsageRecord.completion_tokens), 0),
            func.coalesce(func.sum(LLMUsageRecord.total_cost_usd), 0),
            func.max(LLMUsageRecord.created_at),
        )
        .where(
            LLMUsageRecord.organization_id == org_id,
            LLMUsageRecord.data_source_id == ds_id,
            LLMUsageRecord.created_at >= cutoff,
        )
    )).first()
    tokens_in = int(tok[0] or 0) if tok else 0
    tokens_out = int(tok[1] or 0) if tok else 0
    cost_usd = float(tok[2] or 0) if tok else 0.0
    usage_last = tok[3] if tok else None

    # Credential last-used fallback.
    cred_lu = (await db.execute(
        select(func.max(UserDataSourceCredentials.last_used_at))
        .where(UserDataSourceCredentials.data_source_id == ds_id)
    )).scalar()
    last_used = usage_last or cred_lu or clone.last_synced_at

    # User completions on reports bound to this clone (windowed) — questions,
    # top questions, daily sparkline.
    ucomps = (await db.execute(
        select(Completion.prompt, Completion.created_at)
        .select_from(Completion)
        .join(
            report_data_source_association,
            report_data_source_association.c.report_id == Completion.report_id,
        )
        .where(
            report_data_source_association.c.data_source_id == ds_id,
            Completion.role == "user",
            Completion.deleted_at.is_(None),
            Completion.created_at >= cutoff,
        )
    )).all()

    questions = len(ucomps)

    # Top questions (top 5 by frequency).
    from collections import Counter
    counter: Counter = Counter()
    for prompt, _created in ucomps:
        txt = _prompt_text(prompt)
        if txt:
            counter[txt[:280]] += 1
    top_questions = [{"text": t, "count": n} for t, n in counter.most_common(5)]

    # Daily questions — last 14 days (dialect-safe: bucket in Python).
    day_cut = now - timedelta(days=14)
    buckets: dict[str, int] = {}
    for i in range(14):
        d = (day_cut + timedelta(days=i + 1)).date().isoformat()
        buckets[d] = 0
    for _prompt, created in ucomps:
        if created and created >= day_cut:
            key = created.date().isoformat()
            if key in buckets:
                buckets[key] += 1
    daily_questions = [{"date": d, "count": n} for d, n in sorted(buckets.items())]

    # Avg latency (system completions with elapsed_ms, windowed).
    avg_latency = (await db.execute(
        select(func.avg(Completion.elapsed_ms))
        .select_from(Completion)
        .join(
            report_data_source_association,
            report_data_source_association.c.report_id == Completion.report_id,
        )
        .where(
            report_data_source_association.c.data_source_id == ds_id,
            Completion.elapsed_ms.isnot(None),
            Completion.deleted_at.is_(None),
            Completion.created_at >= cutoff,
        )
    )).scalar()
    avg_latency_ms = int(avg_latency) if avg_latency else None

    # Errors in the last 7 days (failed completions on this clone's reports).
    errors_7d = (await db.execute(
        select(func.count(Completion.id))
        .select_from(Completion)
        .join(
            report_data_source_association,
            report_data_source_association.c.report_id == Completion.report_id,
        )
        .where(
            report_data_source_association.c.data_source_id == ds_id,
            Completion.status.in_(["error", "failed"]),
            Completion.deleted_at.is_(None),
            Completion.created_at >= seven,
        )
    )).scalar()
    errors_7d = int(errors_7d or 0)

    # Sync run — tables/rows + history from the log.
    run = (await db.execute(
        select(ConnectorSyncRun).where(ConnectorSyncRun.data_source_id == ds_id)
    )).scalars().first()

    if run is not None and run.tables_total:
        tables = int(run.tables_total or 0)
    else:
        tables = int((await db.execute(
            select(func.count(DataSourceTable.id))
            .where(DataSourceTable.datasource_id == ds_id)
        )).scalar() or 0)
    rows_total = int(run.rows or 0) if run is not None else 0

    sync_history = []
    if run is not None and isinstance(run.log, list):
        for e in run.log:
            if not isinstance(e, dict):
                continue
            lvl = e.get("level")
            ok = (lvl == "ok") or (e.get("status") == "done")
            sync_history.append({
                "ts": e.get("ts"),
                "phase": e.get("msg") or e.get("table") or lvl or "",
                "table": e.get("table"),
                "tables": None,          # not per-entry in the log
                "rows": e.get("rows"),
                "ms": None,              # per-step latency not recorded in the log
                "ok": bool(ok),
                "level": lvl,
            })

    status = "idle"
    if run is not None and (run.error or run.phase == "error"):
        status = "error"
    elif last_used and last_used >= seven:
        status = "live"

    return {
        "data_source_id": ds_id,
        "email": (owner.email if owner else None),
        "connector_email": _conn_account_email(clone),
        "name": (owner.name if owner else None),
        "connector_label": label,
        "connector_type": typ,
        "status": status,
        "connected_at": _iso(clone.created_at),
        "last_used_at": _iso(last_used),
        "tables": tables,
        "rows": rows_total,
        "questions": questions,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost_usd, 4),
        "avg_latency_ms": avg_latency_ms,
        "errors_7d": errors_7d,
        "top_questions": top_questions,
        "daily_questions": daily_questions,
        "sync_history": sync_history,
    }
