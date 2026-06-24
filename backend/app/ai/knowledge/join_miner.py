"""JOIN MINER (Phase-6 join graph) — infer how tables connect.

We learn table join paths from the SQL the agent has actually run (the Query
Library + the chat-captured reasoning cache) plus, as a weak bonus signal, the
``pd.merge`` calls in generated python. The mined relationships are written to
``table_edges`` so the agent can later be told how tables join.

Design invariants (mirrors the rest of the hybrid knowledge layer):

* **Approval gate.** A mined edge lands ``status='pending'`` / ``source='inferred'``.
  ONLY ``status='approved'`` edges surface to the agent's join/lineage context, so
  a freshly mined edge is automatically invisible until a human approves it. The
  miner NEVER downgrades an already-``approved`` edge back to pending — re-running
  the miner refreshes ``join_count`` / ``confidence`` only.
* **No new dependencies.** Neither ``sqlglot`` nor ``sqlparse`` is installed and we
  must not add deps, so parsing is done with robust, case-insensitive regexes.
  This is intentionally best-effort: it recovers the common
  ``JOIN t ON a.c = b.d`` and ``WHERE a.c = b.d`` equi-join shapes and resolves
  table aliases back to real table names; anything it can't parse is simply
  skipped (a missing edge is harmless — it's an additive hint).
* **Fail-soft.** Every DB/parse operation is wrapped; on any error we return a safe
  default (``[]`` / ``0`` / ``None``) and NEVER raise into the caller. The whole
  subsystem is gated by ``flags.JOIN_MINE_ENABLED`` (default OFF, absent → OFF).

Public surface:
    parse_sql_joins(sql)        -> list[(lt, lc, rt, rc)]   (pure, unit-testable)
    parse_pandas_merges(code)   -> list[(lt, lc, rt, rc)]   (pure, unit-testable)
    mine_join_edges(db, ...)    -> int   (upserts edges for one org/ds)
    run_join_mining()           -> str | None   (self-contained daemon entry)
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

# A parsed equi-join pair: (left_table, left_col, right_table, right_col).
Edge = Tuple[str, str, str, str]

# Bound how many source SQL rows we scan per (org, ds) to keep work bounded.
_MAX_SQL_ROWS = 2000
# Cap orgs/data-sources touched per daemon pass (defensive bound).
_MAX_ORGS = 500
_MAX_DS_PER_ORG = 200


# ---------------------------------------------------------------------------
# Pure regex parsers
# ---------------------------------------------------------------------------

# An SQL identifier, optionally quoted/bracketed and optionally schema-qualified,
# e.g.  customers   "my schema"."My Table"   `db`.`tbl`   [dbo].[Orders]
_IDENT = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)'
_QUALIFIED = rf'{_IDENT}(?:\s*\.\s*{_IDENT})*'

# FROM/JOIN <table> [AS] <alias>  — used to build the alias -> real-table map.
# We only capture the *first* segment (table ref) and an optional alias token.
_FROM_JOIN_RE = re.compile(
    rf'\b(?:FROM|JOIN)\s+(?P<table>{_QUALIFIED})'
    rf'(?:\s+(?:AS\s+)?(?P<alias>{_IDENT}))?',
    re.IGNORECASE,
)

# Reserved words that can immediately follow a table ref and must NOT be eaten as
# an alias (e.g. ``FROM t ON ...``, ``JOIN t USING (...)``, ``FROM t WHERE ...``).
_ALIAS_STOPWORDS = {
    "on", "using", "where", "group", "order", "having", "limit", "join",
    "inner", "left", "right", "full", "outer", "cross", "natural", "union",
    "and", "or", "as", "set", "values", "select", "from", "lateral",
}

# An equi-join predicate:  a.col = b.col   (both sides qualified table.col).
# Captures the table token + column token on each side.
_EQUI_RE = re.compile(
    rf'(?P<lt>{_QUALIFIED})\s*\.\s*(?P<lc>{_IDENT})'
    rf'\s*=\s*'
    rf'(?P<rt>{_QUALIFIED})\s*\.\s*(?P<rc>{_IDENT})',
    re.IGNORECASE,
)

# pd.merge(...)  /  df.merge(...)  call body (best-effort, non-greedy).
_MERGE_RE = re.compile(
    r'(?:pd\s*\.\s*)?merge\s*\((?P<body>.*?)\)',
    re.IGNORECASE | re.DOTALL,
)
_ON_KW_RE = re.compile(r'\bon\s*=\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
_LEFT_ON_RE = re.compile(r'\bleft_on\s*=\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
_RIGHT_ON_RE = re.compile(r'\bright_on\s*=\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE)


def _strip_ident(tok: str) -> str:
    """Lowercase + strip quotes/backticks/brackets/whitespace from an identifier."""
    if not tok:
        return ""
    t = tok.strip()
    # Strip matched wrapping quote/bracket chars on each segment.
    t = t.replace("`", "").replace('"', "").replace("[", "").replace("]", "")
    return t.strip().lower()


def _last_segment(qualified: str) -> str:
    """Return the bare table name from a (possibly schema-qualified) ref.

    ``schema.table`` -> ``table``; an unqualified ``table`` -> ``table``. The
    bare table name is what we tally on (schema is dropped so the same physical
    table referenced with/without schema collapses together).
    """
    clean = _strip_ident(qualified)
    if not clean:
        return ""
    # Split on '.' (segments already de-quoted), keep the last non-empty part.
    parts = [p for p in clean.split(".") if p]
    return parts[-1] if parts else ""


def _build_alias_map(sql: str) -> dict[str, str]:
    """Derive {alias_or_tablename -> real_table_name} from FROM/JOIN clauses.

    Both the alias (``c``) and the table's own bare name (``customers``) map to
    the real table, so a predicate written either way resolves correctly.
    """
    amap: dict[str, str] = {}
    try:
        for m in _FROM_JOIN_RE.finditer(sql or ""):
            table_ref = m.group("table") or ""
            real = _last_segment(table_ref)
            if not real:
                continue
            # The table's own bare name always resolves to itself.
            amap.setdefault(real, real)
            alias_tok = m.group("alias")
            if alias_tok:
                alias = _strip_ident(alias_tok)
                # Don't treat a trailing keyword as an alias.
                if alias and alias not in _ALIAS_STOPWORDS:
                    amap[alias] = real
    except Exception:
        return amap
    return amap


def _resolve(token: str, amap: dict[str, str]) -> str:
    """Resolve a table/alias token to its real table name.

    Tries the bare last segment against the alias map; if unresolvable, keeps the
    bare token (per the spec — never drop just because we couldn't resolve).
    """
    bare = _last_segment(token)
    if not bare:
        return ""
    return amap.get(bare, bare)


def _canonical(lt: str, lc: str, rt: str, rc: str) -> Optional[Edge]:
    """Normalize a pair so (A.a,B.b) and (B.b,A.a) collapse to one orientation.

    Orientation is decided by table name, tie-broken by column. Drops self-joins
    on the identical (table,col) and any pair with an empty table.
    """
    lt, lc, rt, rc = lt.strip(), lc.strip(), rt.strip(), rc.strip()
    if not lt or not rt or not lc or not rc:
        return None
    if (lt, lc) == (rt, rc):
        return None  # degenerate
    # Canonical ordering: smaller (table, col) on the left.
    if (lt, lc) <= (rt, rc):
        return (lt, lc, rt, rc)
    return (rt, rc, lt, lc)


def parse_sql_joins(sql: str) -> List[Edge]:
    """Extract canonical equi-join edges from one SQL string. Pure, never raises.

    Handles ``JOIN t [AS alias] ON a.c = b.d`` and the weaker ``WHERE a.x = b.y``
    equi-join style (both flow through the same equi-predicate scan). Aliases are
    resolved back to real table names via the FROM/JOIN alias map; schema
    qualifiers are dropped to the bare table name; identifiers are lowercased and
    de-quoted. Each pair is canonically oriented and de-duplicated within this
    one SQL string.
    """
    out: List[Edge] = []
    if not sql or not isinstance(sql, str):
        return out
    try:
        amap = _build_alias_map(sql)
        seen: set[Edge] = set()
        for m in _EQUI_RE.finditer(sql):
            lt = _resolve(m.group("lt"), amap)
            lc = _strip_ident(m.group("lc"))
            rt = _resolve(m.group("rt"), amap)
            rc = _strip_ident(m.group("rc"))
            edge = _canonical(lt, lc, rt, rc)
            if edge is None or edge in seen:
                continue
            seen.add(edge)
            out.append(edge)
    except Exception as e:  # pure parser must never raise
        logger.debug("parse_sql_joins failed: %s", e)
        return []
    return out


def parse_pandas_merges(code: str) -> List[Edge]:
    """Best-effort extract join keys from ``pd.merge`` / ``df.merge`` calls.

    Table names are essentially unrecoverable from dataframe variable names, so
    the table slots are emitted EMPTY (``''``) — the caller drops empty-table
    pairs. This is purely a bonus signal; it must never raise. Forms handled:

        pd.merge(a, b, on='col')               -> ('', 'col', '', 'col')
        df.merge(other, left_on='x', right_on='y') -> ('', 'x', '', 'y')
    """
    out: List[Edge] = []
    if not code or not isinstance(code, str):
        return out
    try:
        seen: set[Edge] = set()
        for m in _MERGE_RE.finditer(code):
            body = m.group("body") or ""
            on = _ON_KW_RE.search(body)
            if on:
                col = _strip_ident(on.group(1))
                if col:
                    edge = ("", col, "", col)
                    if edge not in seen:
                        seen.add(edge)
                        out.append(edge)
                continue
            lo = _LEFT_ON_RE.search(body)
            ro = _RIGHT_ON_RE.search(body)
            if lo and ro:
                lc = _strip_ident(lo.group(1))
                rc = _strip_ident(ro.group(1))
                if lc and rc:
                    edge = ("", lc, "", rc)
                    if edge not in seen:
                        seen.add(edge)
                        out.append(edge)
    except Exception as e:
        logger.debug("parse_pandas_merges failed: %s", e)
        return []
    return out


def _confidence(count: int) -> float:
    """Monotonic freq -> confidence in (0, 1).

    ``count / (count + 2)`` — a simple bounded, monotonically increasing score:
    1 occurrence -> 0.33, 2 -> 0.50, 5 -> 0.71, 10 -> 0.83, asymptotes at 1.0.
    The +2 smoothing keeps a single observed join modest (it's only a hint until
    a human approves it).
    """
    try:
        c = max(0, int(count))
    except Exception:
        c = 0
    return min(1.0, c / (c + 2.0)) if c > 0 else 0.0


# ---------------------------------------------------------------------------
# DB mining
# ---------------------------------------------------------------------------

async def _collect_sql_texts(
    db: Any, *, org_id: str, data_source_id: Optional[str]
) -> List[str]:
    """Load candidate SQL strings for an org (+ optional ds, plus ds-null rows).

    Pulls from the Query Library (all rows) and the chat-captured Query Cache.
    Bounded by ``_MAX_SQL_ROWS`` each. Fail-soft -> [] on any error.
    """
    texts: List[str] = []
    try:
        from sqlalchemy import select, or_
        from app.models.query_library import QueryLibraryItem
        from app.models.query_cache import QueryCache

        # --- Query Library -------------------------------------------------
        try:
            ql_q = select(QueryLibraryItem.sql_text).where(
                QueryLibraryItem.organization_id == org_id,
                QueryLibraryItem.deleted_at.is_(None),
            )
            if data_source_id is not None:
                ql_q = ql_q.where(
                    or_(
                        QueryLibraryItem.data_source_id == data_source_id,
                        QueryLibraryItem.data_source_id.is_(None),
                    )
                )
            ql_q = ql_q.limit(_MAX_SQL_ROWS)
            res = await db.execute(ql_q)
            texts.extend(s for (s,) in res.all() if s)
        except Exception as e:
            logger.debug("join_miner: query_library load failed: %s", e)

        # --- Query Cache (chat-captured) -----------------------------------
        try:
            qc_q = select(QueryCache.sql_text).where(
                QueryCache.organization_id == org_id,
                QueryCache.deleted_at.is_(None),
            )
            if data_source_id is not None:
                qc_q = qc_q.where(
                    or_(
                        QueryCache.data_source_id == data_source_id,
                        QueryCache.data_source_id.is_(None),
                    )
                )
            qc_q = qc_q.limit(_MAX_SQL_ROWS)
            res = await db.execute(qc_q)
            texts.extend(s for (s,) in res.all() if s)
        except Exception as e:
            logger.debug("join_miner: query_cache load failed: %s", e)
    except Exception as e:
        logger.warning("join_miner: _collect_sql_texts failed: %s", e)
        return []
    return texts


async def _upsert_edge(
    db: Any,
    *,
    org_id: str,
    ds_id: Optional[str],
    edge: Edge,
    count: int,
) -> bool:
    """UPSERT one TableEdge. Approval-safe. Returns True if a row was written.

    - Existing row: update join_count + confidence; KEEP the existing status
      (never downgrade an 'approved' edge back to pending).
    - New row: insert status='pending', source='inferred'.
    NEVER raises.
    """
    lt, lc, rt, rc = edge
    if not lt or not rt:
        return False
    try:
        from sqlalchemy import select
        from app.models.table_edge import TableEdge

        conf = _confidence(count)
        res = await db.execute(
            select(TableEdge).where(
                TableEdge.organization_id == org_id,
                TableEdge.data_source_id == ds_id,
                TableEdge.left_table == lt,
                TableEdge.left_col == lc,
                TableEdge.right_table == rt,
                TableEdge.right_col == rc,
            )
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            existing.join_count = count
            existing.confidence = conf
            # Approval invariant: do NOT touch status (keeps 'approved' approved).
            await db.flush()
            return True

        row = TableEdge(
            organization_id=org_id,
            data_source_id=ds_id,
            left_table=lt,
            left_col=lc,
            right_table=rt,
            right_col=rc,
            join_count=count,
            confidence=conf,
            source="inferred",
            status="pending",
            structured_data={"origin": "join_miner"},
        )
        db.add(row)
        await db.flush()
        return True
    except Exception as e:
        logger.debug("join_miner: upsert edge %s failed: %s", edge, e)
        return False


async def mine_join_edges(
    db: Any,
    *,
    organization: Any,
    data_source_id: Optional[str] = None,
) -> int:
    """Mine join edges from proven SQL for one (org, ds) and UPSERT them.

    Tallies canonical equi-join pairs across the org's Query Library + Query
    Cache SQL, scores each by frequency, and upserts a pending/inferred TableEdge
    per distinct pair (skipping empty-table pairs). Commits once. Returns the
    number of edges upserted. NEVER raises -> 0 on any failure.
    """
    try:
        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return 0

        texts = await _collect_sql_texts(
            db, org_id=org_id, data_source_id=data_source_id
        )
        if not texts:
            return 0

        # Tally canonical edges across all SQL strings.
        tally: dict[Edge, int] = {}
        for sql in texts:
            for edge in parse_sql_joins(sql):
                if not edge[0] or not edge[2]:
                    continue  # skip empty tables (defensive)
                tally[edge] = tally.get(edge, 0) + 1

        if not tally:
            return 0

        upserted = 0
        for edge, count in tally.items():
            ok = await _upsert_edge(
                db, org_id=org_id, ds_id=data_source_id, edge=edge, count=count
            )
            if ok:
                upserted += 1

        if upserted:
            try:
                await db.commit()
            except Exception as e:
                logger.warning("join_miner: commit failed: %s", e)
                try:
                    await db.rollback()
                except Exception:
                    pass
                return 0
        return upserted
    except Exception as e:
        logger.warning("join_miner: mine_join_edges failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return 0


# ---------------------------------------------------------------------------
# VALUE-OVERLAP mining (no query history needed)
# ---------------------------------------------------------------------------

# Candidate key columns by name shape: anything ending in id, an *_id, or a
# *key* / *code* token. Case-insensitive, matches inside the column name.
_KEY_NAME_RE = re.compile(r'(?:id$|_id|key|code)', re.IGNORECASE)

# Defensive caps so one big connector can't run unbounded sampling work.
_VO_MAX_CANDIDATE_COLS = 60


def _is_value_overlap_candidate(col_name: str, role: Optional[str], dtype: Optional[str]) -> bool:
    """True if a column looks like a join key worth value-sampling.

    Two signals: (1) the NAME matches /id$|_id|key|code/i, or (2) the stored
    profiler ROLE is 'id'/'dimension'. Pure measures/dates/free-text are skipped:
    a name like an id always qualifies, otherwise we require an id/dimension role
    when role intel is present (a None role falls back to the name signal only).
    """
    name = (col_name or "").strip()
    if not name:
        return False
    if _KEY_NAME_RE.search(name):
        return True
    r = (role or "").strip().lower()
    if r in ("id", "dimension"):
        # Avoid obviously non-key dtypes when we have them.
        dt = (dtype or "").strip().lower()
        if any(tok in dt for tok in ("date", "time", "float", "double", "decimal", "numeric", "real")):
            return False
        return True
    return False


def _vo_confidence(overlap: float) -> float:
    """Confidence for a value-overlap edge: the overlap fraction itself, clamped."""
    try:
        o = float(overlap)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, o))


async def _sample_distinct_values(ds: Any, table: str, col: str, sample: int) -> Optional[set]:
    """Sample up to ``sample`` distinct non-null values of one column.

    Read-only guarded + double-quoted idents (names may contain spaces). Returns
    a set of stringified values, or None on any failure / empty. NEVER raises.
    """
    try:
        from app.routes.knowledge import _is_read_only_sql
        client = ds.get_client()
        qt = '"' + str(table).replace('"', '""') + '"'
        qc = '"' + str(col).replace('"', '""') + '"'
        sql = f'SELECT DISTINCT {qc} FROM {qt} WHERE {qc} IS NOT NULL LIMIT {int(sample)}'
        if not _is_read_only_sql(sql):
            return None
        df = await client.aexecute_query(sql)
        if df is None or len(df) == 0:
            return None
        vals = set()
        for v in df.iloc[:, 0].tolist():
            if v is None:
                continue
            s = str(v).strip()
            if s:
                vals.add(s)
        return vals or None
    except Exception as e:
        logger.debug("join_miner: sample %s.%s failed: %s", table, col, e)
        return None


async def mine_value_overlap_edges(
    db: Any,
    *,
    organization: Any,
    data_source: Any,
    max_pairs: int = 40,
    sample: int = 200,
    min_overlap: float = 0.5,
) -> dict:
    """Mine join edges from VALUE OVERLAP across a data source's tables.

    Unlike ``mine_join_edges`` (which needs proven SQL history), this samples
    distinct values of candidate key columns LIVE and proposes a join when two
    cross-table columns share a high fraction of values — so a brand-new
    connector with zero query history still gets join hints.

    Each proposal lands as a pending TableEdge (source='value_overlap'), mirroring
    the existing approval gate (never downgrades an approved edge). Confidence =
    the overlap fraction; join_count = round(overlap*3) (an overlap bucket).

    Gated by ``flags.JOIN_GRAPH``. NEVER raises -> {ok:False,error,mined:0}.
    """
    try:
        from app.settings.hybrid_flags import flags
        if not getattr(flags, "JOIN_GRAPH", False):
            return {"disabled": True, "mined": 0}

        org_id = str(getattr(organization, "id", None) or "")
        ds_id = str(getattr(data_source, "id", None) or "") or None
        if not org_id or ds_id is None:
            return {"ok": False, "error": "missing org/data_source id", "mined": 0}

        # --- Discover candidate key columns from the LIVE schema --------------
        try:
            client = data_source.get_client()
            tables = client.get_schemas()
        except Exception as e:
            return {"ok": False, "error": f"could not read schema: {e}", "mined": 0}

        # (table_name, col_name) -> set of sampled distinct string values.
        candidates: list[Tuple[str, str]] = []
        for t in (tables or []):
            tname = getattr(t, "name", None)
            if not tname:
                continue
            for c in (getattr(t, "columns", None) or []):
                cname = getattr(c, "name", None)
                dtype = getattr(c, "dtype", None)
                # get_schemas() Column carries no role; name+dtype only here.
                if cname and _is_value_overlap_candidate(cname, None, dtype):
                    candidates.append((str(tname), str(cname)))
                    if len(candidates) >= _VO_MAX_CANDIDATE_COLS:
                        break
            if len(candidates) >= _VO_MAX_CANDIDATE_COLS:
                break

        if len(candidates) < 2:
            return {"ok": True, "mined": 0, "candidates": len(candidates)}

        # --- Sample each candidate's distinct values (cache per column) ------
        value_sets: dict[Tuple[str, str], set] = {}
        for key in candidates:
            tbl, col = key
            vs = await _sample_distinct_values(data_source, tbl, col, sample)
            if vs and len(vs) >= 3:
                value_sets[key] = vs

        usable = list(value_sets.keys())
        if len(usable) < 2:
            return {"ok": True, "mined": 0, "candidates": len(candidates)}

        # --- Cross-table pairwise overlap -----------------------------------
        proposals: dict[Edge, float] = {}
        for i in range(len(usable)):
            for j in range(i + 1, len(usable)):
                a_key, b_key = usable[i], usable[j]
                if a_key[0] == b_key[0]:
                    continue  # same table — skip
                a, b = value_sets[a_key], value_sets[b_key]
                denom = min(len(a), len(b))
                if denom < 3:
                    continue
                overlap = len(a & b) / float(denom)
                if overlap < min_overlap:
                    continue
                # Canonical orientation so dedupe is stable regardless of order.
                edge = _canonical(a_key[0], a_key[1], b_key[0], b_key[1])
                if edge is None:
                    continue
                # Keep the strongest overlap if a pair canonicalizes the same.
                prev = proposals.get(edge)
                if prev is None or overlap > prev:
                    proposals[edge] = overlap

        if not proposals:
            return {"ok": True, "mined": 0, "candidates": len(candidates)}

        # Strongest first, capped.
        ranked = sorted(proposals.items(), key=lambda kv: kv[1], reverse=True)[:max_pairs]

        mined = 0
        for edge, overlap in ranked:
            ok = await _upsert_value_overlap_edge(
                db, org_id=org_id, ds_id=ds_id, edge=edge, overlap=overlap
            )
            if ok:
                mined += 1

        if mined:
            try:
                await db.commit()
            except Exception as e:
                logger.warning("join_miner: value-overlap commit failed: %s", e)
                try:
                    await db.rollback()
                except Exception:
                    pass
                return {"ok": False, "error": "commit failed", "mined": 0}

        return {"ok": True, "mined": mined, "candidates": len(candidates)}
    except Exception as e:
        logger.warning("join_miner: mine_value_overlap_edges failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e)[:200], "mined": 0}


async def _upsert_value_overlap_edge(
    db: Any,
    *,
    org_id: str,
    ds_id: Optional[str],
    edge: Edge,
    overlap: float,
) -> bool:
    """UPSERT one value-overlap TableEdge. Approval-safe. NEVER raises.

    Mirrors ``_upsert_edge`` (dedupe on org+ds+left+right+cols, never downgrades
    an approved edge) but stamps ``source='value_overlap'``, ``confidence=overlap``
    and ``join_count=round(overlap*3)`` (an overlap bucket so the freq-shaped
    consumers still get a sensible integer). Returns True if a row was written.
    """
    lt, lc, rt, rc = edge
    if not lt or not rt:
        return False
    try:
        from sqlalchemy import select
        from app.models.table_edge import TableEdge

        conf = _vo_confidence(overlap)
        bucket = max(1, int(round(conf * 3)))
        res = await db.execute(
            select(TableEdge).where(
                TableEdge.organization_id == org_id,
                TableEdge.data_source_id == ds_id,
                TableEdge.left_table == lt,
                TableEdge.left_col == lc,
                TableEdge.right_table == rt,
                TableEdge.right_col == rc,
            )
        )
        existing = res.scalar_one_or_none()
        if existing is not None:
            existing.join_count = bucket
            existing.confidence = conf
            # Approval invariant: do NOT touch status (keeps 'approved' approved).
            await db.flush()
            return True

        row = TableEdge(
            organization_id=org_id,
            data_source_id=ds_id,
            left_table=lt,
            left_col=lc,
            right_table=rt,
            right_col=rc,
            join_count=bucket,
            confidence=conf,
            source="value_overlap",
            status="pending",
            structured_data={"origin": "value_overlap", "overlap": round(conf, 4)},
        )
        db.add(row)
        await db.flush()
        return True
    except Exception as e:
        logger.debug("join_miner: value-overlap upsert %s failed: %s", edge, e)
        return False


async def run_join_mining() -> Optional[str]:
    """Self-contained daemon entry: mine join edges for every org / data source.

    Opens its own async session (like ``run_scheduled_evals``), re-checks the
    flag, iterates orgs and their data sources, and calls ``mine_join_edges`` per
    (org, ds). Returns a short summary string, or ``None`` when gated off / on any
    failure. NEVER raises.
    """
    try:
        from app.settings.hybrid_flags import flags

        # Flag may not yet exist on the registry; absent -> OFF (gated).
        if not getattr(flags, "JOIN_MINE_ENABLED", False):
            return None

        from app.settings.database import create_async_session_factory

        async_session = create_async_session_factory()

        orgs_processed = 0
        edges_total = 0

        async with async_session() as session:
            from sqlalchemy import select
            from app.models.organization import Organization
            from app.models.data_source import DataSource

            try:
                org_rows = (
                    await session.execute(
                        select(Organization)
                        .where(Organization.deleted_at.is_(None))
                        .limit(_MAX_ORGS)
                    )
                ).scalars().all()
            except Exception as e:
                logger.warning("join_miner: org discovery failed: %s", e)
                org_rows = []

            for organization in org_rows:
                try:
                    org_id = str(getattr(organization, "id", None) or "")
                    if not org_id:
                        continue

                    # Discover this org's data sources.
                    try:
                        ds_rows = (
                            await session.execute(
                                select(DataSource.id)
                                .where(
                                    DataSource.organization_id == org_id,
                                    DataSource.deleted_at.is_(None),
                                )
                                .limit(_MAX_DS_PER_ORG)
                            )
                        ).all()
                        ds_ids = [str(r[0]) for r in ds_rows if r and r[0]]
                    except Exception as e:
                        logger.debug("join_miner: ds discovery for %s failed: %s", org_id, e)
                        ds_ids = []

                    processed_this_org = False
                    # Per data source (scoped + ds-null rows fold in via _collect).
                    for ds_id in ds_ids:
                        n = await mine_join_edges(
                            session, organization=organization, data_source_id=ds_id
                        )
                        edges_total += n
                        processed_this_org = True

                    # Also mine org-wide (data_source_id=None) for ds-less SQL.
                    n = await mine_join_edges(
                        session, organization=organization, data_source_id=None
                    )
                    edges_total += n
                    processed_this_org = True

                    if processed_this_org:
                        orgs_processed += 1
                except Exception as inner:
                    logger.warning("join_miner: org failed: %s", inner)
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                    continue

        summary = (
            f"join_mining: upserted {edges_total} edge(s) across "
            f"{orgs_processed} org(s)"
        )
        logger.info(summary)
        return summary
    except Exception as e:
        logger.warning("run_join_mining failed: %s", e)
        return None
