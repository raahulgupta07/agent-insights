"""BRAIN_GRAPH — entity/correlation graph helpers (Phase 8).

HARD RULE: Apache AGE is dropped (not PG18-ready). The 2nd-brain graph is a
plain ``brain_graph_edges`` table + a recursive-CTE multi-hop traversal — NOT an
AGE graph. Each row is a directed, weighted edge between two named entities.

Two public surfaces:

  * ``propose_edges_from_entities`` — from APPROVED (published) catalog entities
    and/or a cross-source key-map, propose correlation edges. Everything lands as
    ``status='pending'`` (approval-gated; never overwrites a published edge;
    dedups identical pending). Reuses the approval-safe upsert discipline from
    ``knowledge_proposer.py``. Gated by ``flags.BRAIN_GRAPH`` — a no-op (empty
    result, nothing written) when OFF. NEVER raises.

  * ``neighbors`` — recursive-CTE multi-hop traversal returning ONLY
    ``status='published'`` edges reachable from a seed entity within ``max_hops``.
    Published-only is the approval invariant: a pending/draft edge is invisible.

LLM resolution (when an LLM is needed) follows the existing idiom:
``LLM(model, usage_session_maker=async_session_maker).inference(prompt)`` and the
small-model resolver in ``LLMService().get_default_model(..., is_small=True)``.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

# Provenance marker stamped on AI-proposed edges.
AI_SOURCE = "ai-graph"

# Reject degenerate entity names.
_MIN_ENTITY_LEN = 2
# Cap how many published entities we feed the proposer (prompt-size bound).
_MAX_ENTITIES = 40
# Cap proposed edges per call.
_MAX_PROPOSED = 24


def _clean(v: Any) -> str:
    return str(v or "").strip()


def _parse_edges(text: str) -> list[dict]:
    """Best-effort parse the model's JSON edge list. Tolerate junk -> []."""
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        parsed = json.loads(cleaned, strict=False)
    except Exception:
        return []
    if isinstance(parsed, dict):
        edges = parsed.get("edges")
        return edges if isinstance(edges, list) else []
    return []


def build_edge_prompt(entity_lines: str) -> str:
    """Compose the one-shot correlation-edge extraction prompt. Pure.

    Asks the model to propose directed correlation/relationship edges ONLY
    between the named entities below — never invent new entities.
    """
    return (
        "You are building a correlation graph between the named data entities "
        "below (each is a curated, published model or metric for one "
        "organization). Propose directed relationship edges that are clearly "
        "implied by the entity names/descriptions — e.g. one metric drives or "
        "correlates with another, or a model feeds a metric. Do NOT invent "
        "entities that are not in the list.\n\n"
        f"Entities:\n{entity_lines}\n\n"
        "Return ONLY a single-line JSON object, no prose, no markdown, with this "
        "exact shape:\n"
        '{"edges": [{"src": "<entity name from the list>", "dst": "<entity name '
        'from the list>", "relation": "<short verb phrase, e.g. correlates_with '
        '| drives | feeds>", "weight": <0.0-1.0 confidence>}]}\n\n'
        "Rules:\n"
        "- src and dst MUST both appear verbatim in the entity list.\n"
        "- Propose only high-confidence edges. Prefer fewer over guessing.\n"
        "- Output the JSON object ONLY."
    )


async def _propose_edge(
    db: Any,
    *,
    org_id: str,
    ds_id: Optional[str],
    src: str,
    dst: str,
    relation: str,
    weight: float,
    structured_data: Optional[dict] = None,
) -> Optional[str]:
    """UPSERT a pending edge proposal. Returns its id, or None.

    Approval-safe (mirrors knowledge_proposer):
    - APPROVED/PUBLISHED edge for (org, ds, src, dst, relation): NEVER overwrite.
    - Identical pending edge already present: dedup, return it.
    - Other non-published row: update in place + flip to pending.
    - Otherwise: insert a new pending row.
    """
    from sqlalchemy import select
    from app.models.brain_graph_edge import BrainGraphEdge

    res = await db.execute(
        select(BrainGraphEdge).where(
            BrainGraphEdge.organization_id == org_id,
            BrainGraphEdge.data_source_id == ds_id,
            BrainGraphEdge.src_entity == src,
            BrainGraphEdge.dst_entity == dst,
            BrainGraphEdge.relation == relation,
        )
    )
    existing = res.scalar_one_or_none()
    if existing is not None:
        if (existing.status or "") == "published":
            return None  # never clobber a live edge
        if (existing.status or "") == "pending" and abs((existing.weight or 0.0) - weight) < 1e-9:
            return str(existing.id)  # identical pending dedup
        existing.weight = weight
        existing.source = AI_SOURCE
        existing.status = "pending"
        if structured_data is not None:
            existing.structured_data = structured_data
        await db.flush()
        return str(existing.id)

    row = BrainGraphEdge(
        organization_id=org_id,
        data_source_id=ds_id,
        src_entity=src,
        dst_entity=dst,
        relation=relation,
        weight=weight,
        source=AI_SOURCE,
        status="pending",
        structured_data=structured_data,
    )
    db.add(row)
    await db.flush()
    return str(row.id)


async def _published_entities(db: Any, *, org_id: str) -> list[dict]:
    """Load published catalog entities (models/metrics) for the org. Guarded."""
    try:
        from sqlalchemy import select
        from app.models.entity import Entity

        res = await db.execute(
            select(Entity).where(
                Entity.organization_id == org_id,
                Entity.status == "published",
                Entity.deleted_at.is_(None),
            ).limit(_MAX_ENTITIES)
        )
        rows = list(res.scalars().all())
    except Exception:
        return []
    out: list[dict] = []
    for e in rows:
        title = _clean(getattr(e, "title", None)) or _clean(getattr(e, "slug", None))
        if len(title) >= _MIN_ENTITY_LEN:
            out.append({"name": title, "type": _clean(getattr(e, "type", None)),
                        "description": _clean(getattr(e, "description", None))})
    return out


async def propose_edges_from_entities(
    db: Any,
    *,
    organization: Any,
    model: Any,
    data_source_id: Optional[str] = None,
    key_map: Optional[List[dict]] = None,
    llm_inference: Optional[Callable[[str], str]] = None,
) -> dict:
    """Propose PENDING correlation edges from approved entities (+ optional
    cross-source key-map). Returns ``{'edges': [...ids]}`` (empty when nothing
    written). Returns ``{}`` when gated off / no entities. NEVER raises.

    ``key_map`` (optional): a list of ``{"src": ..., "dst": ..., "relation": ...,
    "weight": ...}`` join/correlation hints (e.g. from the federation key-map);
    these are written directly as pending edges (no LLM), provenance
    ``source='entity-keymap'``.
    """
    out: dict = {"edges": []}
    try:
        from app.settings.hybrid_flags import flags

        if not flags.BRAIN_GRAPH:
            return {}

        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return {}

        # 1. Direct key-map hints -> pending edges (deterministic, no LLM).
        for km in (key_map or []):
            if not isinstance(km, dict):
                continue
            src = _clean(km.get("src"))
            dst = _clean(km.get("dst"))
            if len(src) < _MIN_ENTITY_LEN or len(dst) < _MIN_ENTITY_LEN:
                continue
            relation = _clean(km.get("relation")) or "related_to"
            try:
                weight = float(km.get("weight", 0.0))
            except Exception:
                weight = 0.0
            new_id = await _propose_edge(
                db, org_id=org_id, ds_id=data_source_id,
                src=src, dst=dst, relation=relation, weight=weight,
                structured_data={"origin": "key-map"},
            )
            if new_id:
                out["edges"].append(new_id)

        # 2. LLM-proposed correlation edges between published entities.
        entities = await _published_entities(db, org_id=org_id)
        if len(entities) >= 2:
            entity_lines = "\n".join(
                f"- {e['name']}" + (f" ({e['type']})" if e['type'] else "")
                + (f": {e['description']}" if e['description'] else "")
                for e in entities
            )
            valid_names = {e["name"] for e in entities}

            infer = llm_inference
            if infer is None:
                def infer(p: str) -> str:  # noqa: E306 - tiny lazy default
                    from app.ai.llm.llm import LLM
                    from app.dependencies import async_session_maker

                    return LLM(model, usage_session_maker=async_session_maker).inference(p)

            prompt = build_edge_prompt(entity_lines)
            raw = (infer(prompt) or "").strip()
            for ed in _parse_edges(raw)[:_MAX_PROPOSED]:
                if not isinstance(ed, dict):
                    continue
                src = _clean(ed.get("src"))
                dst = _clean(ed.get("dst"))
                if src not in valid_names or dst not in valid_names or src == dst:
                    continue
                relation = _clean(ed.get("relation")) or "correlates_with"
                try:
                    weight = float(ed.get("weight", 0.0))
                except Exception:
                    weight = 0.0
                weight = max(0.0, min(1.0, weight))
                new_id = await _propose_edge(
                    db, org_id=org_id, ds_id=data_source_id,
                    src=src, dst=dst, relation=relation, weight=weight,
                    structured_data={"origin": "llm-correlation"},
                )
                if new_id:
                    out["edges"].append(new_id)

        if out["edges"]:
            await db.commit()
        return out
    except Exception as e:  # never break the caller
        logger.warning("brain_graph propose_edges_from_entities failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"edges": []}


async def neighbors(
    db: Any,
    *,
    org_id: str,
    entity: str,
    max_hops: int = 2,
) -> List[dict]:
    """Recursive-CTE multi-hop traversal. Returns PUBLISHED edges only.

    Walks the directed ``brain_graph_edges`` graph from ``entity`` up to
    ``max_hops`` hops, following only ``status='published'`` edges (the approval
    invariant — pending/draft edges are invisible). Cycle-safe via a path-visited
    guard. Returns a list of ``{src, dst, relation, weight, hop}`` dicts ordered
    by hop then descending weight. NEVER raises — degrades to ``[]``.
    """
    seed = _clean(entity)
    if not org_id or not seed:
        return []
    try:
        hops = max(1, min(int(max_hops or 1), 6))
    except Exception:
        hops = 2

    try:
        from sqlalchemy import text

        # Recursive CTE: BFS over published edges, bounded by hop count, with a
        # path string to kill cycles. Parameterized + read-only.
        sql = text(
            """
            WITH RECURSIVE walk(src_entity, dst_entity, relation, weight, hop, path) AS (
                SELECT e.src_entity, e.dst_entity, e.relation, e.weight, 1 AS hop,
                       (e.src_entity || '>' || e.dst_entity) AS path
                FROM brain_graph_edges e
                WHERE e.organization_id = :org_id
                  AND e.status = 'published'
                  AND e.deleted_at IS NULL
                  AND e.src_entity = :seed
                UNION ALL
                SELECT e.src_entity, e.dst_entity, e.relation, e.weight, w.hop + 1,
                       (w.path || '>' || e.dst_entity) AS path
                FROM brain_graph_edges e
                JOIN walk w ON e.src_entity = w.dst_entity
                WHERE e.organization_id = :org_id
                  AND e.status = 'published'
                  AND e.deleted_at IS NULL
                  AND w.hop < :hops
                  AND w.path NOT LIKE ('%' || e.dst_entity || '%')
            )
            SELECT src_entity, dst_entity, relation, weight, hop
            FROM walk
            ORDER BY hop ASC, weight DESC
            LIMIT 200
            """
        )
        res = await db.execute(sql, {"org_id": org_id, "seed": seed, "hops": hops})
        rows = res.fetchall()
    except Exception as e:
        logger.warning("brain_graph neighbors traversal failed: %s", e)
        return []

    out: List[dict] = []
    seen: set = set()
    for r in rows:
        src, dst, rel, weight, hop = r[0], r[1], r[2], r[3], r[4]
        key = (src, dst, rel)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "src": src,
            "dst": dst,
            "relation": rel,
            "weight": float(weight or 0.0),
            "hop": int(hop or 0),
        })
    return out
