"""SemanticContextBuilder — Knowledge Layer Phase 4 (read).

Injects APPROVED semantic-table + semantic-column meaning for the data sources
in scope. Self-gates on flags.SEMANTIC_LAYER (returns an empty section when the
flag is OFF, when there are no data sources in scope, or on any error). Mirrors
the BrainContextBuilder/SkillContextBuilder shape exactly.
"""
from __future__ import annotations
import os
from typing import Any, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.settings.hybrid_flags import flags
from app.models.semantic_table import SemanticTable, SemanticColumn
from app.ai.context.sections.semantic import (
    SemanticTablesSection,
    SemanticTableItem,
    SemanticColumnItem,
)


def _top_k() -> int:
    """Top-K cap for query-relevant semantic-table injection (env-overridable).

    Bounds the injected context so the planner prompt does not balloon as the
    Knowledge Layer grows (cf. arXiv:2605.22502 — in-context cost scales with
    procedure size). Only trims when there are MORE than K tables, so small
    knowledge bases are unaffected (byte-identical).
    """
    try:
        k = int(os.getenv("HYBRID_SEMANTIC_TOP_K", "12"))
        return k if k > 0 else 12
    except Exception:
        return 12


def _rank_tables(query: str, tables: List[Any], k: int) -> List[Any]:
    """Rank semantic tables by token-Jaccard of (name + description + use_cases)
    vs. the normalized query; return the top-K. Reuses the query-cache token
    idioms. Any failure -> return the original list (never hide on error)."""
    try:
        from app.ai.brain.query_cache_store import normalize_question, _tokens, _jaccard
        q_tokens = _tokens(normalize_question(query))
        if not q_tokens:
            return tables[:k]
        scored = []
        for t in tables:
            uc = t.use_cases if isinstance(t.use_cases, list) else []
            text = " ".join([t.table_name or "", t.description or "", " ".join(str(u) for u in uc)])
            scored.append((_jaccard(q_tokens, _tokens(normalize_question(text))), t))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:k]]
    except Exception:
        return tables[:k]


class SemanticContextBuilder:
    def __init__(self, db: AsyncSession, organization, data_source_ids: Optional[List[str]] = None):
        self.db = db
        self.organization = organization
        self.data_source_ids = data_source_ids

    async def build(self, query: Optional[str] = None) -> SemanticTablesSection:
        # Flag OFF / no scope -> empty section (fresh deploy = upstream behaviour).
        if not flags.SEMANTIC_LAYER:
            return SemanticTablesSection(items=[])
        if not self.data_source_ids:
            return SemanticTablesSection(items=[])
        try:
            stmt = (
                select(SemanticTable)
                .where(SemanticTable.organization_id == str(self.organization.id))
                .where(SemanticTable.data_source_id.in_([str(d) for d in self.data_source_ids]))
                .where(SemanticTable.status == "approved")
                .order_by(SemanticTable.table_name.asc())
            )
            # Bi-temporal (HYBRID_BITEMPORAL): only currently-valid versions reach
            # the agent. No-op (None) when the flag is OFF.
            from app.ai.brain import bitemporal
            cond = bitemporal.current_condition(SemanticTable)
            if cond is not None:
                stmt = stmt.where(cond)
            tables = list((await self.db.execute(stmt)).scalars().all())
            if not tables:
                return SemanticTablesSection(items=[])

            # Bound the injected set: when a run query is present and there are
            # more tables than the cap, keep only the top-K most query-relevant
            # (prevents the prompt ballooning as the catalog grows). No query or
            # under the cap -> unchanged.
            k = _top_k()
            if query and query.strip() and len(tables) > k:
                tables = _rank_tables(query, tables, k)

            # Pull approved column meanings for those tables (one query).
            table_ids = [str(t.id) for t in tables]
            col_stmt = (
                select(SemanticColumn)
                .where(SemanticColumn.semantic_table_id.in_(table_ids))
                .where(SemanticColumn.status == "approved")
                .order_by(SemanticColumn.name.asc())
            )
            cols = list((await self.db.execute(col_stmt)).scalars().all())
            cols_by_table: dict[str, List[SemanticColumnItem]] = {}
            pii_cols_by_table: dict[str, List[str]] = {}
            for c in cols:
                # PII column names are collected regardless of whether they have
                # a meaning, so the governance footer can warn on them.
                if getattr(c, "pii", False):
                    pii_cols_by_table.setdefault(str(c.semantic_table_id), []).append(c.name)
                if not (c.meaning and str(c.meaning).strip()):
                    continue
                cols_by_table.setdefault(str(c.semantic_table_id), []).append(
                    SemanticColumnItem(name=c.name, meaning=c.meaning)
                )

            # Governance (Kepler Phase 1) — only compute when the flag is on.
            gov = flags.GOVERNANCE
            data_as_of = ""
            synced_by_ds: dict[str, Any] = {}
            if gov:
                try:
                    from app.models.data_source import DataSource
                    ds_rows = list((await self.db.execute(
                        select(DataSource).where(
                            DataSource.id.in_([str(d) for d in self.data_source_ids])
                        )
                    )).scalars().all())
                    latest = None
                    for d in ds_rows:
                        s = getattr(d, "last_synced_at", None)
                        if s:
                            synced_by_ds[str(d.id)] = s
                            if latest is None or s > latest:
                                latest = s
                    if latest:
                        data_as_of = latest.date().isoformat()
                except Exception:
                    pass

            def _freshness(t) -> str:
                if not gov:
                    return ""
                from datetime import datetime, timezone, timedelta
                refreshed = t.last_refreshed_at or synced_by_ds.get(str(t.data_source_id))
                sla = t.freshness_sla_hours
                if not refreshed:
                    return ""
                ref = refreshed if refreshed.tzinfo else refreshed.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - ref
                days = max(0, int(age.total_seconds() // 86400))
                if sla and age > timedelta(hours=int(sla)):
                    return f"stale {days}d"
                return "fresh" if days == 0 else f"{days}d old"

            items: List[SemanticTableItem] = []
            for t in tables:
                use_cases = t.use_cases if isinstance(t.use_cases, list) else []
                items.append(
                    SemanticTableItem(
                        table_name=t.table_name,
                        description=t.description or "",
                        use_cases=[str(u) for u in use_cases],
                        columns=cols_by_table.get(str(t.id), []),
                        owner=(getattr(t, "owner", None) or "") if gov else "",
                        pii=bool(getattr(t, "pii", False)) if gov else False,
                        freshness=_freshness(t),
                        pii_columns=pii_cols_by_table.get(str(t.id), []) if gov else [],
                    )
                )
            # HYBRID_TABLE_CARD (P3): merge every layer for each table into ONE
            # card and overlay approved Shared-Memory corrections (corrected
            # baseline). Self-contained + fail-soft; OFF -> no extra_cards ->
            # byte-identical section. Coupled to SEMANTIC_LAYER (this builder).
            extra_cards: List[str] = []
            try:
                from app.settings.hybrid_flags import flags as _tc_flags
                if _tc_flags.TABLE_CARD:
                    from app.services.knowledge.table_card import (
                        build_table_card, overlay_memory, render_card,
                    )
                    from app.services.knowledge.retrieve import recall_items
                    from app.models.data_source import DataSource as _DS
                    _ds_rows = list((await self.db.execute(
                        select(_DS).where(_DS.id.in_([str(d) for d in self.data_source_ids]))
                    )).scalars().all())
                    _ds_by_id = {str(d.id): d for d in _ds_rows}
                    _recall = await recall_items(
                        self.db,
                        organization_id=str(self.organization.id),
                        current_user_id=None,
                        data_source_ids=[str(d) for d in self.data_source_ids],
                    )
                    # HYBRID_OFFLINE_CONTEXT (Part B read-side): prefer the nightly
                    # pre-built per-table context_doc (the fuller card, built from the
                    # real DataSourceTable) over rebuilding live. Map table name ->
                    # stored text. OFF or no doc -> live build_table_card below.
                    _prebuilt: dict = {}
                    if _tc_flags.OFFLINE_CONTEXT:
                        try:
                            from app.models.data_source import DataSourceTable as _DST
                            _dst_rows = list((await self.db.execute(
                                select(_DST).where(_DST.datasource_id.in_([str(d) for d in self.data_source_ids]))
                            )).scalars().all())
                            for _dst in _dst_rows:
                                _m = _dst.metadata_json if isinstance(_dst.metadata_json, dict) else {}
                                _cd = _m.get("context_doc") if isinstance(_m.get("context_doc"), dict) else {}
                                _ctext = str(_cd.get("text") or "").strip()
                                if _ctext:
                                    _prebuilt[str(_dst.name)] = _ctext
                        except Exception:
                            _prebuilt = {}
                    for t in tables:
                        _ds = _ds_by_id.get(str(t.data_source_id))
                        if _ds is None:
                            continue
                        _pre = _prebuilt.get(str(t.table_name))
                        if _pre:
                            # serve pre-built card, still overlay live corrections
                            _txt = render_card(overlay_memory({"table": t.table_name, "_prebuilt_text": _pre}, _recall))
                            if not _txt:
                                _txt = _pre
                            extra_cards.append(_txt)
                            continue
                        _card = await build_table_card(
                            self.db,
                            organization_id=str(self.organization.id),
                            data_source=_ds,
                            table=t.table_name,
                        )
                        _card = overlay_memory(_card, _recall)
                        _txt = render_card(_card)
                        if _txt:
                            extra_cards.append(_txt)
            except Exception:
                extra_cards = []
            return SemanticTablesSection(items=items, data_as_of=data_as_of, extra_cards=extra_cards)
        except Exception:
            return SemanticTablesSection(items=[])
