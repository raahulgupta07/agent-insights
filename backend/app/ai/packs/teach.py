"""Teach Box — turn a pasted analysis / SOP into trained agent behaviour.

The user pastes free text (a finished EBITDA deck, a methodology, a glossary,
a set of rules). ONE cheap LLM call classifies it into spans, each tagged with
the surface it belongs on:

  SKILL      -> a user-authored Domain Pack (method + required inputs + output)
               bound to the studio's real columns and stored inline in
               StudioBoundPack.pack_body (source='user'). This is the reusable
               "how to produce THIS analysis on all the data" recipe.
  INSTRUCTION-> a StudioInstruction (a standing behaviour rule).
  DATA_RULE  -> also a StudioInstruction, prefixed [DATA RULE] (a metric/filter
               convention, e.g. "FY starts in April", "exclude inactive SKUs").
  KNOWLEDGE  -> a KnowledgeDoc (reference text, PG-FTS retrieved when relevant).

Everything is born PENDING behind the existing review gate — nothing reaches
the agent until a human approves. `classify()` only reads + previews (incl. a
bind preview for SKILL spans so the UI can say "binds to 7 cols" / "needs a
Budget column"). `apply_spans()` persists the (possibly user-edited) spans.

Gated by flags.TEACH_BOX. Pure-ish + defensive: parsing/binding never raise;
the only hard dependency is the one LLM classify call and the DB writes.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 1. CLASSIFY — one LLM call, pasted text -> tagged spans
# ---------------------------------------------------------------------------

_SPAN_TYPES = {"SKILL", "INSTRUCTION", "DATA_RULE", "KNOWLEDGE",
               "METRIC", "QUERY", "EXAMPLE"}

_CLASSIFY_PROMPT = """You convert a pasted business analysis / SOP into structured \
"teach" spans for an analytics agent. Split the input into the smallest useful \
spans and tag each one. Respond with STRICT JSON only, no prose, no markdown \
fences.

Tags:
- "SKILL": a repeatable analytical METHOD that produces a deliverable (a report,
  a slide, a summary) by computing over data columns. Examples: "EBITDA
  good/bad/ugly exec summary", "monthly cohort retention deck". For a SKILL also
  emit a "skill" object describing how to reproduce it (see schema).
- "INSTRUCTION": a standing behaviour rule for the agent (tone, format,
  what to always include/avoid). Not tied to specific columns.
- "DATA_RULE": a data/metric convention or definition (fiscal calendar,
  inclusion/exclusion filters, how a metric is defined).
- "KNOWLEDGE": reference facts / glossary / context the agent should be able to
  look up. Not a method and not a rule.
- "METRIC": a named business metric with a definition and (if stated) a verified
  value (e.g. "Total leads = 1544, Logic: count rows where …"). For a METRIC also
  emit a "metric" object (see schema).
- "QUERY": a reusable / verified SQL query worth saving under a name. For a QUERY
  also emit a "query" object (see schema).
- "EXAMPLE": a verified question -> answer pair (a Q/A note), optionally with the
  SQL that proves it. For an EXAMPLE also emit an "example" object (see schema).

JSON schema:
{
  "spans": [
    {
      "type": "SKILL|INSTRUCTION|DATA_RULE|KNOWLEDGE|METRIC|QUERY|EXAMPLE",
      "title": "short label",
      "content": "the text of this span (for INSTRUCTION/DATA_RULE/KNOWLEDGE)",
      "skill": {                          // ONLY when type == SKILL
        "name": "human name of the skill",
        "method_text": "numbered, imperative steps to compute + categorise + present, generic over columns",
        "trigger_hints": ["phrases a user question would contain to want this"],
        "required_inputs": {
          "logical_key": {"role": "measure|dimension|date", "synonyms": ["likely column names"], "optional": false}
        },
        "output_spec": {"type": "slide|dashboard|report", "sections": ["..."]},
        "format": {"font": "...", "percentages": "..."}
      },
      "metric": {                         // ONLY when type == METRIC
        "name": "human name of the metric",
        "value": 1544,                    // the verified number, or null if none stated
        "definition": "the logic / filter text that defines the metric",
        "sql": "optional SQL that computes it"
      },
      "query": {                          // ONLY when type == QUERY
        "name": "human name of the query",
        "sql": "the SQL text"
      },
      "example": {                        // ONLY when type == EXAMPLE
        "question": "the asked question",
        "answer": "the verified answer",
        "sql": "optional SQL that proves the answer"
      }
    }
  ]
}

Choosing between the value-bearing types: prefer METRIC when the input gives a
metric NAME + a VALUE + its LOGIC (e.g. "Total leads = 1544, Logic: …"); prefer
EXAMPLE for a question/answer note; prefer QUERY for a named SQL snippet.

Rules: required_inputs keys are LOGICAL names (snake_case), not the user's exact
column names — list those as synonyms. Mark an input optional:true if the method
still works without it. Keep method_text data-agnostic (refer to the logical
inputs, never invent column names).

EXHAUSTIVE CAPTURE (critical): extract EVERY distinct rule, definition, metric
convention, filter, and Q&A fact in the input as its OWN span. Do NOT summarize,
merge, generalize, or drop any of them — one span per distinct rule/definition,
preserving the original wording in "content" verbatim. If the document defines a
term (e.g. "new user"), states how a metric is computed, or gives a
channel/contribution/segment rule, each is a SEPARATE DATA_RULE span. It is
better to emit too many spans than to omit one. There is no upper limit on the
number of spans. If the input is clearly a single method, emit ONE SKILL span.
{COLUMN_HINT}
INPUT:
<<<
{TEXT}
>>>
"""

_COLUMN_HINT_TMPL = """
IMPORTANT — this studio's REAL data columns are listed below. For every SKILL
required_input, set its "synonyms" to include the EXACT matching column name(s)
from this list so the input binds. If no column fits a required input, still
emit it (it will be flagged as missing for review).
AVAILABLE COLUMNS: {COLS}
"""


def _build_classify_prompt(text: str, column_names: Optional[List[str]] = None) -> str:
    snippet = (text or "")[:60000]
    if column_names:
        hint = _COLUMN_HINT_TMPL.replace("{COLS}", ", ".join(str(c) for c in column_names[:80]))
    else:
        hint = ""
    return _CLASSIFY_PROMPT.replace("{COLUMN_HINT}", hint).replace("{TEXT}", snippet)


def _extract_json(raw: str) -> Optional[dict]:
    """Tolerant JSON extraction — strip fences, grab the outermost object."""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # fall back: slice from first { to last }
    a, b = s.find("{"), s.rfind("}")
    if a >= 0 and b > a:
        try:
            return json.loads(s[a : b + 1])
        except Exception:
            return None
    return None


def _normalise_spans(parsed: Optional[dict]) -> List[dict]:
    """Coerce the LLM payload into a clean, typed span list. Never raises."""
    out: List[dict] = []
    if not isinstance(parsed, dict):
        return out
    spans = parsed.get("spans")
    if not isinstance(spans, list):
        return out
    for sp in spans:
        if not isinstance(sp, dict):
            continue
        t = str(sp.get("type") or "").strip().upper().replace("-", "_")
        if t not in _SPAN_TYPES:
            continue
        span: Dict[str, Any] = {
            "type": t,
            "title": str(sp.get("title") or "").strip()[:200],
            "content": str(sp.get("content") or "").strip(),
        }
        if t == "SKILL":
            skill = sp.get("skill") if isinstance(sp.get("skill"), dict) else {}
            span["skill"] = _clean_skill(skill, fallback_name=span["title"], fallback_method=span["content"])
        elif t == "METRIC":
            metric = sp.get("metric") if isinstance(sp.get("metric"), dict) else {}
            span["metric"] = _clean_metric(metric, fallback_name=span["title"], fallback_def=span["content"])
        elif t == "QUERY":
            query = sp.get("query") if isinstance(sp.get("query"), dict) else {}
            span["query"] = _clean_query(query, fallback_name=span["title"], fallback_sql=span["content"])
        elif t == "EXAMPLE":
            example = sp.get("example") if isinstance(sp.get("example"), dict) else {}
            span["example"] = _clean_example(example, fallback_question=span["title"], fallback_answer=span["content"])
        out.append(span)
    return out


def _coerce_float(v: Any) -> Optional[float]:
    """Coerce a metric value to float, tolerating strings like '1,544'. None on fail."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except Exception:
        return None


def _clean_metric(metric: dict, *, fallback_name: str, fallback_def: str) -> dict:
    metric = metric if isinstance(metric, dict) else {}
    name = str(metric.get("name") or fallback_name or "Untitled metric").strip()[:200]
    definition = str(metric.get("definition") or fallback_def or "").strip()
    sql = str(metric.get("sql") or "").strip()
    return {
        "name": name,
        "value": _coerce_float(metric.get("value")),
        "definition": definition,
        "sql": sql,
    }


def _clean_query(query: dict, *, fallback_name: str, fallback_sql: str) -> dict:
    query = query if isinstance(query, dict) else {}
    name = str(query.get("name") or fallback_name or "Untitled query").strip()[:200]
    sql = str(query.get("sql") or fallback_sql or "").strip()
    return {"name": name, "sql": sql}


def _clean_example(example: dict, *, fallback_question: str, fallback_answer: str) -> dict:
    example = example if isinstance(example, dict) else {}
    question = str(example.get("question") or fallback_question or "").strip()
    answer = str(example.get("answer") or fallback_answer or "").strip()
    sql = str(example.get("sql") or "").strip()
    return {"question": question, "answer": answer, "sql": sql}


def _clean_skill(skill: dict, *, fallback_name: str, fallback_method: str) -> dict:
    name = str(skill.get("name") or fallback_name or "Untitled skill").strip()[:200]
    method = str(skill.get("method_text") or fallback_method or "").strip()
    hints = skill.get("trigger_hints")
    hints = [str(h).strip() for h in hints if str(h).strip()] if isinstance(hints, list) else []
    req = skill.get("required_inputs")
    clean_req: Dict[str, dict] = {}
    if isinstance(req, dict):
        for k, v in req.items():
            key = re.sub(r"[^a-z0-9_]+", "_", str(k).lower()).strip("_")
            if not key:
                continue
            v = v if isinstance(v, dict) else {}
            syns = v.get("synonyms")
            clean_req[key] = {
                "role": str(v.get("role") or "").strip() or None,
                "synonyms": [str(s).strip() for s in syns if str(s).strip()] if isinstance(syns, list) else [],
                "optional": bool(v.get("optional")),
            }
    return {
        "name": name,
        "method_text": method,
        "trigger_hints": hints,
        "required_inputs": clean_req,
        "output_spec": skill.get("output_spec") if isinstance(skill.get("output_spec"), dict) else {},
        "format": skill.get("format") if isinstance(skill.get("format"), dict) else {},
    }


async def classify(db, organization, text: str,
                   column_names: Optional[List[str]] = None) -> List[dict]:
    """One LLM call -> normalised spans. Empty list on any failure (fail open).

    column_names (the studio's real columns) make SKILL inputs bind reliably:
    the model is told to set each input's synonyms to the matching real column.
    """
    try:
        from app.services.llm_service import LLMService
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        model = await LLMService().get_default_model(db, organization, None, is_small=True)
        if model is None:
            return []
        prompt = _build_classify_prompt(text, column_names)
        raw = (
            LLM(model, usage_session_maker=async_session_maker).inference(
                prompt, usage_scope="teach_box"
            )
            or ""
        )
        return _normalise_spans(_extract_json(raw))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 2. SKILL span -> Domain Pack dict (the user-authored pack body)
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return (s or "user-skill")[:100]


def build_skill_pack(skill: dict, *, studio_id: str) -> dict:
    """Render a SKILL span into a registry-shaped pack dict (registry/binder/router
    all consume this exact shape). pack_id is namespaced per-studio so user skills
    never collide with library packs or each other."""
    skill = skill if isinstance(skill, dict) else {}
    name = str(skill.get("name") or "User skill").strip()
    pack_id = f"user-{studio_id[:8]}-{_slugify(name)}"
    return {
        "id": pack_id,
        "name": name,
        "domain": "user.teach",
        "method_text": str(skill.get("method_text") or "").strip(),
        "trigger_hints": list(skill.get("trigger_hints") or []),
        "required_inputs": dict(skill.get("required_inputs") or {}),
        "output_spec": dict(skill.get("output_spec") or {}),
        "format": dict(skill.get("format") or {}),
        "eval_goldens": [],
        "_source": "user",
    }


# ---------------------------------------------------------------------------
# 3. Studio columns (for binding a SKILL span at teach/approve time)
# ---------------------------------------------------------------------------

async def _studio_primary_ds(db, studio_id: str) -> Optional[str]:
    """The first data source bound to a studio (metrics/queries need a
    data_source_id). None if the studio has no pinned source. Never raises."""
    try:
        from sqlalchemy import select
        from app.models.studio import StudioDataSource

        ds_id = (
            await db.execute(
                select(StudioDataSource.agent_id).where(
                    StudioDataSource.studio_id == str(studio_id),
                    StudioDataSource.deleted_at.is_(None),
                ).limit(1)
            )
        ).scalars().first()
        return str(ds_id) if ds_id else None
    except Exception:
        return None


async def studio_columns(db, studio_id: str) -> List[dict]:
    """Flatten the profiled columns of every active table of a studio's pinned
    sources into the binder's flat shape [{name, dtype, role, values}]. The
    stored shape is {name, dtype, metadata:{role,...}}; we hoist metadata up."""
    try:
        from sqlalchemy import select
        from app.models.studio import StudioDataSource
        from app.models.datasource_table import DataSourceTable

        ds_ids = (
            await db.execute(
                select(StudioDataSource.agent_id).where(
                    StudioDataSource.studio_id == str(studio_id),
                    StudioDataSource.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        if not ds_ids:
            return []
        tables = (
            await db.execute(
                select(DataSourceTable).where(
                    DataSourceTable.datasource_id.in_(list(ds_ids)),
                    DataSourceTable.is_active.is_(True),
                )
            )
        ).scalars().all()

        flat: List[dict] = []
        seen = set()
        for t in tables:
            for c in (t.columns or []):
                if not isinstance(c, dict):
                    continue
                nm = c.get("name")
                if not nm or nm in seen:
                    continue
                seen.add(nm)
                meta = c.get("metadata") if isinstance(c.get("metadata"), dict) else {}
                flat.append({
                    "name": nm,
                    "dtype": c.get("dtype"),
                    "role": meta.get("role") or "dimension",
                    "values": meta.get("values") or [],
                })
        return flat
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 4. PREVIEW + APPLY
# ---------------------------------------------------------------------------

async def preview_spans(db, studio_id: str, spans: List[dict]) -> List[dict]:
    """Annotate each span with what it WILL become (no writes). SKILL spans get
    a bind preview computed against the studio's real columns."""
    from app.ai.packs import binder

    cols = await studio_columns(db, studio_id)
    out: List[dict] = []
    for sp in spans:
        t = sp.get("type")
        item = {"type": t, "title": sp.get("title"), "content": sp.get("content")}
        if t == "SKILL":
            pack = build_skill_pack(sp.get("skill") or {}, studio_id=studio_id)
            res = binder.bind_pack(pack, binder.columns_from_profile(cols))
            item["skill"] = sp.get("skill")
            item["target"] = "domain_pack"
            item["bind"] = {
                "bound": res.get("bound"),
                "overall_conf": res.get("overall_conf"),
                "binding": res.get("binding"),
                "missing": res.get("missing"),
            }
            item["will_be"] = "active skill" if res.get("bound") else "dormant (needs columns)"
        elif t == "KNOWLEDGE":
            item["target"] = "knowledge_doc"
            item["will_be"] = "pending knowledge doc"
        elif t == "METRIC":
            item["metric"] = sp.get("metric") or {}
            item["target"] = "metric_definition"
            _v = item["metric"].get("value")
            item["will_be"] = "verified metric" if _v is not None else "draft metric"
        elif t == "QUERY":
            item["query"] = sp.get("query") or {}
            item["target"] = "query_library"
            item["will_be"] = "golden query"
        elif t == "EXAMPLE":
            item["example"] = sp.get("example") or {}
            item["target"] = "studio_example"
            item["will_be"] = "pending example (Q→A)"
        else:  # INSTRUCTION | DATA_RULE
            item["target"] = "studio_instruction"
            item["will_be"] = "pending instruction"
        out.append(item)
    return out


async def apply_spans(db, organization, studio_id: str, spans: List[dict],
                      *, default_status: str = "pending") -> dict:
    """Persist spans to their surfaces. Everything born pending (review gate).
    Returns a per-surface summary. Commits once at the end."""
    from app.models.studio import StudioInstruction, StudioBoundPack, StudioExample
    from app.models.metric_definition import MetricDefinition
    from app.models.query_library import QueryLibraryItem
    from app.ai.packs import binder
    from app.ai.knowledge.docs_index import ingest_doc

    created = {"instructions": 0, "data_rules": 0, "knowledge": 0,
               "skills_active": 0, "skills_dormant": 0,
               "metrics": 0, "queries": 0, "examples": 0, "errors": []}
    cols = None
    org_id = str(organization.id)
    primary_ds = await _studio_primary_ds(db, studio_id)

    for sp in spans:
        t = sp.get("type")
        try:
            if t in ("INSTRUCTION", "DATA_RULE"):
                content = (sp.get("content") or sp.get("title") or "").strip()
                if not content:
                    continue
                if t == "DATA_RULE":
                    content = f"[DATA RULE] {content}"
                    created["data_rules"] += 1
                else:
                    created["instructions"] += 1
                db.add(StudioInstruction(
                    studio_id=str(studio_id), content=content,
                    source="auto", status=default_status,
                ))
            elif t == "KNOWLEDGE":
                title = (sp.get("title") or "Pasted knowledge").strip()
                body = (sp.get("content") or "").strip()
                if not body:
                    continue
                # ingest_doc commits internally (chunks + dedup); born pending.
                await ingest_doc(db, organization=organization, title=title,
                                 body=body, source="paste")
                created["knowledge"] += 1
            elif t == "SKILL":
                if cols is None:
                    cols = await studio_columns(db, studio_id)
                pack = build_skill_pack(sp.get("skill") or {}, studio_id=str(studio_id))
                res = binder.bind_pack(pack, binder.columns_from_profile(cols))
                bound = bool(res.get("bound"))
                db.add(StudioBoundPack(
                    studio_id=str(studio_id),
                    pack_id=pack["id"],
                    binding_map=res.get("binding") or {},
                    output_spec=pack.get("output_spec") or {},
                    eval_goldens=[],
                    status=(default_status if bound else "dormant"),
                    source="user",
                    conf=res.get("overall_conf") or 0.0,
                    missing=res.get("missing") or [],
                    pack_body=pack,
                ))
                created["skills_active" if bound else "skills_dormant"] += 1
            elif t == "METRIC":
                metric = sp.get("metric") or {}
                name = (metric.get("name") or sp.get("title") or "").strip()
                if not name:
                    continue
                if not primary_ds:
                    created["errors"].append("METRIC: no data source bound to studio")
                    continue
                try:
                    value = metric.get("value")
                    row = MetricDefinition(
                        organization_id=org_id,
                        data_source_id=primary_ds,
                        name=name,
                        definition=(metric.get("definition") or "").strip(),
                        table_ref="",
                        sql_calc=(metric.get("sql") or "").strip(),
                        status=("approved" if value is not None else "draft"),
                    )
                    if value is not None:
                        row.is_locked = True
                        row.last_value = value
                    db.add(row)
                    created["metrics"] += 1
                except Exception as e:
                    created["errors"].append(f"METRIC: {e}")
            elif t == "QUERY":
                query = sp.get("query") or {}
                name = (query.get("name") or sp.get("title") or "").strip()
                sql_text = (query.get("sql") or "").strip()
                if not name or not sql_text:
                    continue
                if not primary_ds:
                    created["errors"].append("QUERY: no data source bound to studio")
                    continue
                try:
                    db.add(QueryLibraryItem(
                        organization_id=org_id,
                        data_source_id=primary_ds,
                        name=name,
                        sql_text=sql_text,
                        source="teach",
                        status="active",
                        is_golden=True,
                    ))
                    created["queries"] += 1
                except Exception as e:
                    created["errors"].append(f"QUERY: {e}")
            elif t == "EXAMPLE":
                example = sp.get("example") or {}
                question = (example.get("question") or sp.get("title") or "").strip()
                answer = (example.get("answer") or sp.get("content") or "").strip()
                if not question or not answer:
                    continue
                try:
                    db.add(StudioExample(
                        studio_id=str(studio_id),
                        question=question,
                        answer=answer,
                        sql=((example.get("sql") or "").strip() or None),
                        source="auto",
                        status="pending",
                    ))
                    created["examples"] += 1
                except Exception as e:
                    created["errors"].append(f"EXAMPLE: {e}")
        except Exception as e:  # one bad span never sinks the batch
            created["errors"].append(f"{t}: {e}")

    await db.commit()
    return created
