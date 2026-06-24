"""Phase C -- generative golden-minting for Domain Packs.

For each ACTIVE bound Domain Pack on a studio, use the pack's INVARIANT METHOD
plus its per-agent column BINDING to have a cheap LLM generate ONE (up to
``max_per_pack``) representative analytical question + a single-value
verification SELECT. We RUN that SELECT read-only against the studio's first
pinned data source, derive the headline expected value, and save it as a golden
``TestCase`` row. This GROUNDS the pack's method on the studio's REAL data --
library packs ship with ``eval_goldens: []``, so retrains otherwise have nothing
method-specific to regression-check.

Reuse, not reinvention (mirrors ``app.ai.knowledge.auto_evals`` exactly):
  * Suite       = ``eval_harness._find_or_create_suite`` (same per-studio suite
    name as auto_evals -> goldens co-locate).
  * TestCase    = same FieldRule shape (a FLAT matcher is silently push_skipped
    -> vacuous pass; MUST be a FieldRule via ``auto_evals._make_field_rule``).
  * Expected    = ``auto_evals._derive_expected`` (single-cell DataFrame).
  * Source      = ``auto_evals._resolve_first_pinned_source`` + its schema digest
    via ``knowledge_proposer._introspect_schema_text``.
  * Read-only   = ``routes.knowledge._is_read_only_sql``.
  * Active packs= ``pack_train._active_packs`` ({pack, binding, conf, ...}).
  * LLM         = the org's *small* default model, called through dash's one-shot
    ``LLM(...).inference`` wrapper (sync -> off the event loop via to_thread).

Design rules: self-gated on ``flags.DOMAIN_PACKS AND flags.AUTO_EVALS`` (reuses
AUTO_EVALS, no new flag) -> ``{"disabled": True}`` no-op. Creation ONLY. NEVER
raises into the caller. ASCII only.

LANDMINE: models are imported lazily INSIDE the function (a bare interpreter
hits a ``Completion`` mapper-init error when models are imported piecemeal;
runtime via the app is fine) -- mirrors auto_evals' lazy-import discipline.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# Bound the work so a train run stays cheap.
_MAX_PACKS = 6                  # process at most this many active packs
_MAX_PER_PACK_HARD = 4          # hard ceiling on items per pack
_NAME_LEN_CAP = 120             # TestCase.name max length


def _build_prompt(pack_name: str, method_text: str, binding: Dict[str, Any],
                  schema_digest: str, max_n: int) -> str:
    """Compose the per-pack one-shot generation prompt. Pure/deterministic."""
    bind_lines = "\n".join(
        f"  - {k} -> \"{v}\"" for k, v in list((binding or {}).items())[:24]
    ) or "  (no explicit binding)"
    method = (method_text or "").strip()
    if len(method) > 1600:
        method = method[:1600] + " ..."
    return (
        "You are designing grounded regression tests ('goldens') that verify an "
        "analytics agent correctly applies a named analytical METHOD (a 'skill') "
        "on this studio's REAL data.\n\n"
        f"SKILL: {pack_name}\n\n"
        f"METHOD (how this skill computes its deliverable):\n{method}\n\n"
        "COLUMN BINDING (the skill's logical input -> the REAL column it maps to "
        "in this warehouse):\n"
        f"{bind_lines}\n\n"
        "Below is the schema as `table(col1, col2, ...)` lines. Ground EVERYTHING "
        "ONLY in this schema and the bound columns above -- do NOT invent tables "
        "or columns.\n\n"
        f"Schema:\n{schema_digest}\n\n"
        f"Propose up to {max_n} item(s). For EACH, give:\n"
        "  - question: a natural-language business question THIS skill answers "
        "(phrase it the way a user would ask).\n"
        "  - sql: a single read-only SELECT (or WITH) that returns exactly ONE "
        "row and ONE column = the headline answer to the question (a COUNT, a "
        "SUM, a ratio, or the name of the top item via ORDER BY ... LIMIT 1).\n"
        "  - expect_kind: 'value' if the headline is a number, 'name' if a label.\n\n"
        "Use table/column names EXACTLY as written in the schema, verbatim. ALWAYS "
        'wrap every table and column in double quotes (e.g. SELECT COUNT(*) FROM '
        '"the_exact_table" WHERE "Some Col" = \'X\') -- names often contain '
        "spaces/colons and error unquoted. Prefer the BOUND columns. Keep each "
        "SQL trivial and deterministic: no parameters, no comments, no DDL, no "
        "writes, no semicolon-chaining (one statement only).\n\n"
        "Output STRICT JSON ONLY: a JSON array of objects with keys \"question\", "
        "\"sql\", \"expect_kind\". No prose, no code fences."
    )


def _parse_items(text: str) -> List[dict]:
    """Parse the LLM reply into a list of item dicts. Never raises -> []."""
    if not text:
        return []
    raw = text.strip()
    # Strip an accidental code fence.
    if raw.startswith("```"):
        raw = raw.strip("`")
        nl = raw.find("\n")
        if nl != -1:
            raw = raw[nl + 1:]
    # Slice to the outermost JSON array if there's surrounding prose.
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]
    try:
        data = json.loads(raw, strict=False)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: List[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        q = item.get("question")
        sql = item.get("sql")
        if isinstance(q, str) and q.strip() and isinstance(sql, str) and sql.strip():
            out.append({
                "question": q.strip(),
                "sql": sql.strip(),
                "expect_kind": str(item.get("expect_kind") or "value").strip().lower(),
            })
    return out


async def mint_pack_goldens(db, organization, studio_id: str,
                            *, max_per_pack: int = 2) -> dict:
    """Generatively mint grounded goldens from a studio's ACTIVE bound packs.

    Returns one of:
      * {"disabled": True, "created": 0}  when DOMAIN_PACKS+AUTO_EVALS not both on
      * {"ok": True, "created": N, "skipped": M, "by_pack": {...}, "suite_id": ...}
      * {"ok": True, "created": 0, "note": ...}  when there's nothing to do
      * {"ok": False, "error": <str>, "created": <N>}  on any failure

    Creation ONLY -- goldens are not executed here. NEVER raises into the caller.
    """
    created = 0
    skipped = 0
    by_pack: Dict[str, int] = {}
    suite_id: Optional[str] = None
    try:
        from app.settings.hybrid_flags import flags

        if not (getattr(flags, "DOMAIN_PACKS", False) and getattr(flags, "AUTO_EVALS", False)):
            return {"disabled": True, "created": 0}

        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return {"ok": False, "error": "no organization", "created": 0}

        try:
            per_pack = int(max_per_pack)
        except Exception:
            per_pack = 2
        if per_pack <= 0:
            per_pack = 2
        per_pack = min(per_pack, _MAX_PER_PACK_HARD)

        # 1. Load the studio (non-deleted, org-scoped).
        from sqlalchemy import select
        from app.models.studio import Studio

        studio = (
            await db.execute(
                select(Studio).where(
                    Studio.id == studio_id,
                    Studio.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if studio is None:
            return {"ok": False, "error": "studio not found", "created": 0}

        # 2. Resolve the FIRST pinned source + its schema digest.
        from app.ai.knowledge.auto_evals import (
            _resolve_first_pinned_source,
            _derive_expected,
            _make_field_rule,
        )
        from app.ai.brain.knowledge_proposer import _introspect_schema_text

        ds = await _resolve_first_pinned_source(db, studio, organization)
        if ds is None:
            return {"ok": True, "created": 0, "note": "no pinned data source"}
        source_id = str(getattr(ds, "id", "") or "")

        schema_digest, table_names = _introspect_schema_text(ds)
        if not schema_digest or not table_names:
            return {"ok": True, "created": 0, "note": "no introspectable schema"}

        # 3. Active bound packs for this studio.
        from app.ai.packs import pack_train

        packs = await pack_train._active_packs(db, studio_id)
        if not packs:
            return {"ok": True, "created": 0, "note": "no active packs"}
        packs = packs[:_MAX_PACKS]

        # 4. Small default model (reuse, no new infra).
        from app.services.llm_service import LLMService

        model = await LLMService().get_default_model(
            db, organization, current_user=None, is_small=True
        )
        if model is None:
            return {"ok": False, "error": "no model configured", "created": 0}

        # 5. Suite (same name auto_evals uses -> goldens co-locate).
        from app.services.eval_harness import _find_or_create_suite
        from app.routes.knowledge import _is_read_only_sql
        from app.models.eval import TestCase

        suite = await _find_or_create_suite(
            db, org_id=org_id, name=f"Studio {studio_id} goldens"
        )
        if suite is None:
            return {"ok": False, "error": "could not create suite", "created": 0}
        suite_id = str(suite.id)

        client = ds.get_client()

        for entry in packs:
            pack = entry.get("pack") or {}
            binding = entry.get("binding") or {}
            pack_name = str(pack.get("name") or pack.get("id") or "skill")
            method_text = str(pack.get("method_text") or "")
            by_pack.setdefault(pack_name, 0)

            # 5a. ONE LLM call per pack -> proposed items (sync -> worker thread).
            prompt = _build_prompt(pack_name, method_text, binding, schema_digest, per_pack)

            def _infer(_prompt: str = prompt) -> str:
                from app.ai.llm.llm import LLM
                from app.dependencies import async_session_maker

                return LLM(model, usage_session_maker=async_session_maker).inference(
                    _prompt, usage_scope="pack_goldens"
                )

            try:
                text = await asyncio.to_thread(_infer)
            except Exception as e:
                logger.warning("pack_goldens: LLM call failed for %s: %s", pack_name, e)
                continue

            items = _parse_items(text or "")[:per_pack]

            for item in items:
                try:
                    question = item["question"]
                    sql = item["sql"]

                    # Read-only guard.
                    if not _is_read_only_sql(sql):
                        skipped += 1
                        continue

                    # Dedupe by (suite, name): name = short, pack-prefixed.
                    name = f"[{pack_name}] {question}"[:_NAME_LEN_CAP]
                    exists = (
                        await db.execute(
                            select(TestCase.id)
                            .where(TestCase.suite_id == suite_id)
                            .where(TestCase.name == name)
                            .limit(1)
                        )
                    ).first()
                    if exists is not None:
                        skipped += 1
                        continue

                    # RUN the sql against the real source; derive the headline.
                    try:
                        df = await client.aexecute_query(sql)
                    except Exception as e:
                        logger.warning("pack_goldens: sql failed, skipping: %s", e)
                        skipped += 1
                        continue

                    expected = _derive_expected(df)
                    if not expected:
                        skipped += 1
                        continue

                    db.add(TestCase(
                        suite_id=suite_id,
                        name=name,
                        prompt_json={"content": question, "mode": "default"},
                        expectations_json={
                            "spec_version": 1,
                            "rules": [_make_field_rule(expected)],
                            "order_mode": "flexible",
                        },
                        data_source_ids_json=[source_id],
                        status="active",
                        auto_generated=True,
                    ))
                    created += 1
                    by_pack[pack_name] += 1
                except Exception as e:
                    logger.warning("pack_goldens: item failed, skipping: %s", e)
                    skipped += 1
                    continue

        if created:
            await db.commit()
        return {
            "ok": True,
            "created": created,
            "skipped": skipped,
            "by_pack": by_pack,
            "suite_id": suite_id,
        }
    except Exception as e:  # noqa: BLE001 -- never raise into the caller
        logger.warning("mint_pack_goldens failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e), "created": created}
