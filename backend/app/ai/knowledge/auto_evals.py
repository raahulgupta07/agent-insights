"""Auto-generate golden eval test cases for a Studio from its REAL data.

Goal: given a Studio's pinned data sources, have a cheap LLM propose a handful
of analytical questions, each paired with a SELECT that yields a single headline
value. We RUN each SELECT (read-only guarded) against the real source, derive the
actual aggregate, and save the (question, expected-substring) pair as a
``TestCase`` row (``auto_generated=True``). Future retrains then run these
goldens and can't silently regress the studio's grounded answers.

Reuse, not reinvention (CLAUDE.md HARD RULES 3/4/5):
  * Suite = ``eval_harness._find_or_create_suite`` (org-scoped TestSuite).
  * TestCase shape copies ``eval_harness.save_completion_as_golden`` exactly:
      prompt_json       = {"content": <question>, "mode": "default"}
      expectations_json = {"spec_version": 1, "rules": [rule], "order_mode": "flexible"}
    LANDMINE: the rule MUST be a FieldRule, NOT a flat matcher (a flat
    ``{"type":"text.contains",...}`` is silently push_skipped -> vacuous pass).
  * LLM   = the org's *small* default model via ``LLMService().get_default_model``
    (is_small=True), called through dash's one-shot ``LLM(...).inference`` wrapper
    (synchronous -> run off the event loop in a worker thread).
  * Schema = ``knowledge_proposer._introspect_schema_text`` (table(col, ...) text).
  * Read-only guard = ``routes.knowledge._is_read_only_sql``.
  * Pinned sources = same resolution as ``services.studio_artifacts``.

Design rules honored:
  * Self-gated on ``flags.AUTO_EVALS`` (default OFF) -> {"disabled": True} no-op.
  * NEVER raises into the caller. On any failure -> {"ok": False, "error": ...}.
  * Creation ONLY (running goldens is a separate, existing flow). ASCII only.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, List, Optional

from sqlalchemy import select

from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# Bound the number of pinned sources / cases / prompt size (cheap tier).
_MAX_CASES_HARD = 12
_EXPECT_LEN_CAP = 80  # max length of the derived expected substring


def _build_prompt(source_name: str, schema_digest: str, max_cases: int,
                  skill_context: str = "") -> str:
    """Compose the one-shot generation prompt. Pure/deterministic.

    ``skill_context`` (Phase 4) is the studio's active-skill block; when present
    it biases the goldens toward verifying those skills' computations."""
    skill_block = ""
    if skill_context:
        skill_block = (
            "\n" + skill_context.strip() +
            "\nPrefer questions that check the headline numbers these skills "
            "compute, where the schema supports it.\n\n"
        )
    return (
        "You are designing regression tests ('goldens') for an analytics agent "
        f"grounded on the data source '{source_name}'.\n\n"
        "Below is the schema as a list of `table(col1, col2, ...)` lines. Ground "
        "everything ONLY in this schema -- do NOT invent tables or columns.\n\n"
        f"Schema:\n{schema_digest}\n\n"
        f"{skill_block}"
        f"Propose up to {max_cases} simple analytical questions. For EACH, give:\n"
        "  - question: a short natural-language business question.\n"
        "  - sql: a single read-only SELECT (or WITH) that returns exactly ONE "
        "row and ONE column = the headline answer to the question (e.g. a COUNT, "
        "a SUM, or the name of the top category via ORDER BY ... LIMIT 1).\n"
        "  - expect_kind: 'value' if the headline is a number, 'name' if a label.\n\n"
        "Use table names EXACTLY as written above, verbatim (they may be long "
        "uuid-prefixed identifiers — never shorten or rename them). ALWAYS wrap "
        'every table and column in double quotes (e.g. SELECT COUNT(*) FROM '
        '"the_exact_table" WHERE "Call Outcome" = \'Successful\') — names often '
        "contain spaces/colons and error unquoted.\n"
        "Keep each SQL trivial and deterministic; no parameters, no semicolons "
        "beyond one optional trailing one, no comments. Prefer aggregates that "
        "won't change between identical runs.\n\n"
        "Output STRICT JSON ONLY: a JSON array of objects with keys "
        '"question", "sql", "expect_kind". No prose, no code fences.'
    )


def _parse_cases(text: str) -> List[dict]:
    """Parse the LLM reply into a list of case dicts. Never raises -> []."""
    if not text:
        return []
    raw = text.strip()
    # Strip an accidental code fence.
    if raw.startswith("```"):
        raw = raw.strip("`")
        nl = raw.find("\n")
        if nl != -1:
            raw = raw[nl + 1 :]
    # Slice to the outermost JSON array if there's surrounding prose.
    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
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
            out.append(
                {
                    "question": q.strip(),
                    "sql": sql.strip(),
                    "expect_kind": str(item.get("expect_kind") or "value").strip().lower(),
                }
            )
    return out


def _derive_expected(df: Any) -> Optional[str]:
    """Derive a stable expected substring from a single-cell DataFrame.

    Returns None when there's no usable headline value. Never raises.
    """
    try:
        if df is None or len(df) < 1 or len(df.columns) < 1:
            return None
        val = df.iloc[0, 0]
        if val is None:
            return None
        # Normalize floats that are really ints (5.0 -> "5") for clean matching.
        try:
            f = float(val)
            if f == int(f):
                s = str(int(f))
            else:
                s = repr(f)
        except (TypeError, ValueError):
            s = str(val)
        s = s.strip()
        if not s:
            return None
        return s[:_EXPECT_LEN_CAP]
    except Exception:
        return None


def _make_field_rule(expected: str) -> dict:
    """Build the FieldRule text.contains expectation (NOT a flat matcher)."""
    return {
        "type": "field",
        "target": {"category": "completion", "field": "text"},
        "matcher": {"type": "text.contains", "value": expected},
    }


async def _resolve_first_pinned_source(db: Any, studio: Any, organization: Any):
    """Return the first pinned DataSource for the studio (org-scoped) or None.

    Mirrors ``services.studio_artifacts._gather_pinned_schema`` resolution.
    """
    from app.models.data_source import DataSource
    from app.models.studio import StudioDataSource

    org_id = getattr(organization, "id", None) or getattr(studio, "organization_id", None)

    res = await db.execute(
        select(StudioDataSource)
        .where(
            StudioDataSource.studio_id == studio.id,
            StudioDataSource.deleted_at.is_(None),
        )
        .order_by(StudioDataSource.created_at.asc())
    )
    pins = list(res.scalars().all())
    if not pins:
        return None

    for pin in pins:
        agent_id = getattr(pin, "agent_id", None)
        if not agent_id:
            continue
        ds_res = await db.execute(
            select(DataSource).where(
                DataSource.id == agent_id,
                DataSource.organization_id == org_id,
            )
        )
        ds = ds_res.scalar_one_or_none()
        if ds is not None:
            return ds
    return None


async def generate_evals_for_studio(
    db: Any,
    *,
    organization: Any,
    current_user: Any,
    studio_id: str,
    model: Any = None,
    max_cases: int = 6,
    skill_context: str = "",
) -> dict:
    """Auto-generate golden TestCases for a studio from its real data.

    Returns one of:
      * {"disabled": True, "created": 0}           when flags.AUTO_EVALS is OFF
      * {"ok": True, "created": N, "suite_id": ..., "skipped": M}
      * {"ok": False, "error": <str>, "created": N}   on any failure

    Creation ONLY -- the goldens are not executed here. NEVER raises.
    """
    created = 0
    skipped = 0
    suite_id: Optional[str] = None
    try:
        from app.settings.hybrid_flags import flags

        if not getattr(flags, "AUTO_EVALS", False):
            return {"disabled": True, "created": 0}

        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return {"ok": False, "error": "no organization", "created": 0}

        try:
            cap = int(max_cases)
        except Exception:
            cap = 6
        if cap <= 0:
            cap = 6
        cap = min(cap, _MAX_CASES_HARD)

        # 1. Load the studio (non-deleted, org-scoped).
        from app.models.studio import Studio

        studio_res = await db.execute(
            select(Studio).where(
                Studio.id == studio_id,
                Studio.deleted_at.is_(None),
            )
        )
        studio = studio_res.scalar_one_or_none()
        if studio is None:
            return {"ok": False, "error": "studio not found", "created": 0}

        # 2. Resolve the FIRST pinned source (keep it cheap) + its schema digest.
        ds = await _resolve_first_pinned_source(db, studio, organization)
        if ds is None:
            return {"ok": False, "error": "no pinned data source", "created": 0}
        source_id = str(getattr(ds, "id", "") or "")
        source_name = getattr(ds, "name", None) or source_id

        from app.ai.brain.knowledge_proposer import _introspect_schema_text

        schema_digest, table_names = _introspect_schema_text(ds)
        if not schema_digest or not table_names:
            return {"ok": False, "error": "no introspectable schema", "created": 0}

        # 3. Resolve the small default model (reuse, no new infra).
        if model is None:
            from app.services.llm_service import LLMService

            model = await LLMService().get_default_model(
                db, organization, current_user, is_small=True
            )
        if model is None:
            return {"ok": False, "error": "no model configured", "created": 0}

        # 4. ONE LLM call -> proposed cases (sync wrapper -> worker thread).
        prompt = _build_prompt(source_name, schema_digest, cap, skill_context)

        def _infer() -> str:
            from app.ai.llm.llm import LLM
            from app.dependencies import async_session_maker

            return LLM(model, usage_session_maker=async_session_maker).inference(
                prompt, usage_scope="auto_evals"
            )

        try:
            text = await asyncio.to_thread(_infer)
        except Exception as e:
            logger.warning("auto_evals LLM call failed: %s", e)
            return {"ok": False, "error": "model call failed", "created": 0}

        cases = _parse_cases(text or "")[:cap]
        if not cases:
            return {"ok": True, "created": 0, "suite_id": None, "skipped": 0}

        # 5. Find-or-create the per-studio goldens suite.
        from app.services.eval_harness import _find_or_create_suite
        from app.routes.knowledge import _is_read_only_sql
        from app.models.eval import TestCase

        suite_name = f"Studio {studio_id} goldens"
        suite = await _find_or_create_suite(db, org_id=org_id, name=suite_name)
        if suite is None:
            return {"ok": False, "error": "could not create suite", "created": 0}
        suite_id = str(suite.id)

        client = ds.get_client()

        for case in cases:
            try:
                question = case["question"]
                sql = case["sql"]

                # 5a. Read-only guard.
                if not _is_read_only_sql(sql):
                    skipped += 1
                    continue

                # 5b. Dedupe by (suite, name) -- skip if a same-named case exists.
                name = question[:120]
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

                # 5c. RUN the sql against the real source; derive expected value.
                try:
                    df = await client.aexecute_query(sql)
                except Exception as e:
                    logger.warning("auto_evals: sql failed, skipping: %s", e)
                    skipped += 1
                    continue

                expected = _derive_expected(df)
                if not expected:
                    skipped += 1
                    continue

                rule = _make_field_rule(expected)

                test_case = TestCase(
                    suite_id=suite_id,
                    name=name,
                    prompt_json={"content": question, "mode": "default"},
                    expectations_json={
                        "spec_version": 1,
                        "rules": [rule],
                        "order_mode": "flexible",
                    },
                    data_source_ids_json=[source_id],
                    status="active",
                    auto_generated=True,
                )
                db.add(test_case)
                created += 1
            except Exception as e:
                logger.warning("auto_evals: case failed, skipping: %s", e)
                skipped += 1
                continue

        await db.commit()
        return {"ok": True, "created": created, "suite_id": suite_id, "skipped": skipped}
    except Exception as e:  # noqa: BLE001 -- never raise into the caller
        logger.warning("generate_evals_for_studio failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e), "created": created}
