"""
Skill Optimizer (SkillOpt closed loop)
======================================

Native, OpenRouter-only, GPU-free, approval-gated closed-loop optimization of a
single Skill's ``SKILL.md`` body, validated against a held-out GOLDEN eval suite.

Pattern credit: microsoft/SkillOpt — treat the skill document as a *trainable
artifact* and improve it with a measured feedback loop instead of fine-tuning
weights. The loop here is:

    rollout  -> drive the golden eval suite with the candidate SKILL.md PINNED,
                read the deterministic PASS/FAIL matcher per case.
    reflect  -> gather the FAILING cases (+ optional Judge critiques) from the
                last rollout.
    aggregate-> ask the LLM (OpenRouter, mirroring skill_authoring) for AT MOST
                ``max_edits_per_epoch`` bounded textual edits, returning the FULL
                revised SKILL.md.
    select   -> rollout the candidate; accept ONLY on a STRICT improvement of the
                held-out pass-rate (the SkillOpt SELECT gate).
    update   -> persist the winning body as a NEW ``status='draft'`` Skill row
                (coexists with the live ``active`` row). Supersede-on-activate is
                a human-approval step wired elsewhere — we NEVER touch the live
                active row here.

Design rules honored (CLAUDE.md HARD RULES 3/4/5):
- Flag-gated by ``flags.SKILL_OPTIMIZE`` (env ``HYBRID_SKILL_OPTIMIZE``), default
  OFF -> a no-op summary, no rollouts, no writes.
- Approval-gated: the optimized version lands as a DRAFT; it only goes live after
  a human activates it.
- Side-effect-light: ``optimize_skill`` NEVER raises into the caller; every step
  is guarded and degrades to a safe summary. Rolls back on a failed write.
- OpenRouter-only LLM via dash's ``LLM`` wrapper (mirrors ``skill_authoring`` and
  ``knowledge_proposer``); no new client path, no GPU.
- Bi-temporal timestamps are NAIVE UTC (the cols are TIMESTAMP WITHOUT TIME ZONE;
  asyncpg rejects aware datetimes against them).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# How long to wait for a single rollout's TestResult rows to reach a terminal
# state before reading the pass-rate. The headless executor runs the analyst per
# case in the background, so we poll.
_ROLLOUT_TIMEOUT_S = 900.0
_ROLLOUT_POLL_S = 2.0

# Reject a candidate body that came back empty or implausibly short.
_MIN_BODY_LEN = 20


def _naive_utc_now() -> datetime:
    """Naive UTC now — bi-temporal cols are TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _json_list(val: Any) -> List[Any]:
    """Decode a JSON list column (or passthrough a list) -> list; [] on failure."""
    if not val:
        return []
    if isinstance(val, (list, tuple)):
        return list(val)
    try:
        parsed = json.loads(val)
        return list(parsed) if isinstance(parsed, (list, tuple)) else []
    except Exception:
        return []


def _as_pin(name: str, md: str, skill: Any) -> Dict[str, Any]:
    """Build the pinned-skill contract dict for a rollout.

    Shape (force-loaded candidate during a rollout):
        {"name": str, "skill_md": str, "allowed_tools": list, "disallowed_tools": list}

    ``allowed_tools`` / ``disallowed_tools`` are pulled off the live skill row and
    JSON-decoded when stored as JSON text.
    """
    return {
        "name": str(name or getattr(skill, "name", "") or ""),
        "skill_md": str(md or ""),
        "allowed_tools": _json_list(getattr(skill, "allowed_tools", None)),
        "disallowed_tools": _json_list(getattr(skill, "disallowed_tools", None)),
    }


def _pass_rate(results: List[Any]) -> float:
    """Pass-rate over a rollout's TestResult rows.

    PASS = ``status == 'pass'``; the denominator is every row that reached a
    decided state (pass/fail/error). Returns 0.0 when there is nothing decided.
    """
    decided = 0
    passed = 0
    for r in results or []:
        st = getattr(r, "status", None)
        if st in ("pass", "fail", "error"):
            decided += 1
            if st == "pass":
                passed += 1
    if decided <= 0:
        return 0.0
    return float(passed) / float(decided)


def build_optimize_prompt(
    current_md: str,
    failing: List[Dict[str, Any]],
    *,
    max_edits: int,
) -> str:
    """Compose the SkillOpt AGGREGATE prompt. Pure, deterministic.

    Asks the model to make AT MOST ``max_edits`` bounded textual edits to the
    SKILL.md to fix the failing cases, and to return the FULL revised SKILL.md
    (frontmatter included), nothing else.
    """
    lines: List[str] = []
    for i, f in enumerate(failing[:12], start=1):
        q = str(f.get("question") or "").strip()
        exp = str(f.get("expectation") or "").strip()
        crit = str(f.get("critique") or "").strip()
        seg = f"{i}. Question: {q}"
        if exp:
            seg += f"\n   Expected: {exp}"
        if crit:
            seg += f"\n   Critique: {crit}"
        lines.append(seg)
    failing_block = "\n".join(lines) if lines else "(no specific failing cases captured)"

    return (
        "You are improving a reusable analytics SKILL document so a future "
        "analyst follows it more reliably. The SKILL is a generalizable, "
        "repeatable procedure — keep it GENERALIZED (no question-specific data "
        "values).\n\n"
        "Current SKILL.md (full, frontmatter included):\n"
        "-----8<----- BEGIN SKILL.md -----8<-----\n"
        f"{current_md}\n"
        "-----8<----- END SKILL.md -----8<-----\n\n"
        "These held-out eval cases FAILED with the current SKILL.md:\n"
        f"{failing_block}\n\n"
        f"Make AT MOST {max_edits} small, bounded textual edits to the SKILL.md "
        "that would most plausibly fix those failures (clarify steps, tighten "
        "the procedure, correct a misleading instruction). Do NOT bloat it, do "
        "NOT hard-code any case's specific values, and KEEP the YAML frontmatter "
        "(name/description) intact.\n\n"
        "Output EXACTLY the FULL revised SKILL.md (frontmatter + body), nothing "
        "else — no preamble, no commentary, no code fences around the whole file."
    )


def _strip_fence(text: str) -> str:
    """Strip a wrapping ```markdown / ``` code fence the model may add."""
    s = (text or "").strip()
    if s.startswith("```"):
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


async def _resolve_model(db: Any, organization: Any, user: Any, model: Any) -> Any:
    """Resolve an LLM model to drive the AGGREGATE call. Mirrors skill_authoring /
    knowledge_proposer: prefer the given model, else the org default (small).
    None on failure (caller aborts the LLM step)."""
    if model is not None:
        return model
    try:
        from app.services.llm_service import LLMService

        return await LLMService().get_default_model(db, organization, user, is_small=True)
    except Exception as e:
        logger.warning("skill optimizer model resolve failed: %s", e)
        return None


def _make_infer(model: Any):
    """Lazy one-shot LLM infer closure — the exact OpenRouter idiom used by
    skill_authoring.distill_skill_from_completion / knowledge_proposer."""

    def infer(p: str) -> str:  # noqa: E306 - tiny lazy default
        from app.ai.llm.llm import LLM
        from app.dependencies import async_session_maker

        return LLM(model, usage_session_maker=async_session_maker).inference(p)

    return infer


async def _await_completions_terminal(
    db: Any,
    run_id: str,
    *,
    timeout_s: float = _ROLLOUT_TIMEOUT_S,
    poll_s: float = _ROLLOUT_POLL_S,
) -> bool:
    """Poll the system COMPLETIONS behind a run's TestResults until each result's
    latest system completion is terminal (success/error/stopped), or timeout.

    Path 1 (``create_and_execute_background``) runs the analyst but NEVER flips
    ``TestResult.status`` to terminal — finalization is explicit. So we wait on the
    COMPLETIONS (the analyst's real signal), then let ``finalize_run_results`` score.
    Returns True if every result's system completion is terminal; False on timeout
    (caller still proceeds to finalize partial). Guarded -> False on exception."""
    from sqlalchemy import select
    from app.models.eval import TestResult
    from app.models.completion import Completion

    deadline = time.monotonic() + float(timeout_s)
    while True:
        try:
            # Analyst flips completion status in a SEPARATE session. Use
            # populate_existing=True so each SELECT overwrites the cached attrs
            # IN the awaited execute (NOT expire_all, which would leave attrs
            # expired -> implicit IO on later sync access -> greenlet_spawn err).
            res = await db.execute(
                select(TestResult)
                .where(TestResult.run_id == str(run_id))
                .execution_options(populate_existing=True)
            )
            rows = list(res.scalars().all())
            all_done = bool(rows)
            for r in rows:
                head_id = getattr(r, "head_completion_id", None)
                if not head_id:
                    all_done = False
                    break
                head = (
                    await db.execute(
                        select(Completion)
                        .where(Completion.id == str(head_id))
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one_or_none()
                if head is None:
                    all_done = False
                    break
                existing_system = (
                    await db.execute(
                        select(Completion)
                        .where(
                            Completion.report_id == str(head.report_id),
                            Completion.parent_id == str(head.id),
                            Completion.role == "system",
                        )
                        .order_by(Completion.created_at.desc())
                        .limit(1)
                        .execution_options(populate_existing=True)
                    )
                ).scalar_one_or_none()
                if existing_system is None or getattr(
                    existing_system, "status", ""
                ) not in ("success", "error", "stopped"):
                    all_done = False
                    break
            if all_done:
                return True
        except Exception as e:
            logger.warning("skill optimizer completions poll failed: %s", e)
            return False

        if time.monotonic() >= deadline:
            logger.warning(
                "skill optimizer rollout timed out (run=%s); finalizing partial",
                run_id,
            )
            return False
        await asyncio.sleep(poll_s)


async def _rollout(
    db: Any,
    *,
    organization: Any,
    user: Any,
    pinned_skill: Dict[str, Any],
    case_ids: Optional[List[str]],
    eval_suite_id: Optional[str],
) -> tuple[float, List[Any]]:
    """Run the golden eval suite with ``pinned_skill`` forced, wait for it to
    finish, and return ``(pass_rate, result_rows)``.

    Drives ``TestRunService.create_and_execute_background`` (the rollout entry
    point gaining a ``pinned_skill`` kwarg) and reads each case's deterministic
    PASS/FAIL from the persisted ``TestResult.status``. Guarded -> (0.0, []).
    """
    try:
        from app.services.test_run_service import TestRunService

        svc = TestRunService()
        run, _results = await svc.create_and_execute_background(
            db,
            organization,
            user,
            case_ids=[str(c) for c in case_ids] if case_ids else None,
            suite_id=str(eval_suite_id) if eval_suite_id else None,
            trigger_reason="skill_optimize",
            pinned_skill=pinned_skill,
        )
        if run is None:
            return 0.0, []
        # Path 1 runs the analyst but never finalizes TestResults -> wait for the
        # COMPLETIONS to finish, then explicitly finalize+score the run.
        await _await_completions_terminal(db, str(run.id))
        rows = await TestRunService().finalize_run_results(
            db, organization, user, str(run.id)
        )
        return _pass_rate(rows), rows
    except TypeError as te:
        # The pinned_skill kwarg is added by another WAVE-1 agent. If it is not
        # yet present, surface a clear, non-fatal signal instead of crashing.
        logger.warning(
            "skill optimizer rollout TypeError (pinned_skill kwarg?): %s", te
        )
        return 0.0, []
    except Exception as e:
        logger.warning("skill optimizer rollout failed: %s", e)
        return 0.0, []


async def _gather_failing(
    db: Any,
    *,
    rows: List[Any],
    organization: Any,
    user: Any,
    model: Any,
) -> List[Dict[str, Any]]:
    """REFLECT: from the last rollout's rows, collect the failing cases as
    {question, expectation, critique}. Judge critique is an OPTIONAL signal
    (best-effort; absent on any failure). Guarded -> []."""
    from sqlalchemy import select
    from app.models.eval import TestResult, TestCase

    failing: List[Dict[str, Any]] = []
    judge = None  # built lazily on first need; optional

    for r in rows or []:
        if getattr(r, "status", "") not in ("fail", "error"):
            continue
        question = ""
        expectation = ""
        critique = ""
        try:
            case = await db.get(TestCase, str(getattr(r, "case_id", "") or ""))
            if case is not None:
                pj = getattr(case, "prompt_json", None) or {}
                if isinstance(pj, dict):
                    question = str(pj.get("content") or "").strip()
                spec = getattr(case, "expectations_json", None) or {}
                if isinstance(spec, dict):
                    rules = spec.get("rules") or []
                    if isinstance(rules, list) and rules:
                        try:
                            expectation = json.dumps(rules[0])[:400]
                        except Exception:
                            expectation = str(rules[0])[:400]
        except Exception:
            pass

        # Optional Judge critique — feeds the edit prompt as a soft signal only.
        try:
            failure_reason = getattr(r, "failure_reason", None)
            if failure_reason:
                critique = str(failure_reason)[:400]
        except Exception:
            pass

        failing.append(
            {
                "question": question,
                "expectation": expectation,
                "critique": critique,
            }
        )
    return failing


async def _persist_draft_version(
    db: Any,
    *,
    skill: Any,
    best_md: str,
) -> Optional[str]:
    """UPDATE/persist: INSERT a NEW draft Skill = a copy of the original (same
    name/scope/org/owner/frontmatter) with ``skill_md=best_md`` and a fresh
    bi-temporal stamp. Does NOT modify or supersede the live active row.

    Returns the new row id, or None on failure (rolled back). NEVER raises.
    """
    try:
        from app.models.skill import Skill

        now = _naive_utc_now()
        new_skill = Skill(
            name=getattr(skill, "name", None),
            description=getattr(skill, "description", None),
            scope=getattr(skill, "scope", None) or "personal",
            owner_user_id=getattr(skill, "owner_user_id", None),
            organization_id=getattr(skill, "organization_id", None),
            skill_md=best_md,
            category=getattr(skill, "category", None),
            status="draft",
            hit_count=0,
            # Carry frontmatter fields verbatim from the source row.
            allowed_tools=getattr(skill, "allowed_tools", None),
            disallowed_tools=getattr(skill, "disallowed_tools", None),
            disable_model_invocation=bool(
                getattr(skill, "disable_model_invocation", False)
            ),
            user_invocable=bool(getattr(skill, "user_invocable", True)),
            skill_metadata=getattr(skill, "skill_metadata", None),
            license=getattr(skill, "license", None),
            # Bi-temporal: a fresh, currently-valid draft version.
            valid_at=now,
            invalid_at=None,
            superseded_by=None,
        )
        db.add(new_skill)
        await db.flush()
        new_id = str(new_skill.id)
        await db.commit()
        return new_id
    except Exception as e:
        logger.warning("skill optimizer draft persist failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return None


async def _load_visible_skill(
    db: Any, *, organization: Any, user: Any, skill_id: str
) -> Optional[Any]:
    """Load the Skill by id, requiring it to be visible/active (live row:
    status='active' AND invalid_at IS NULL). None when missing / not live."""
    try:
        from app.models.skill import Skill

        skill = await db.get(Skill, str(skill_id))
        if skill is None:
            return None
        if getattr(skill, "deleted_at", None) is not None:
            return None
        if (getattr(skill, "status", None) or "") != "active":
            return None
        if getattr(skill, "invalid_at", None) is not None:
            return None
        return skill
    except Exception as e:
        logger.warning("skill optimizer load skill failed: %s", e)
        return None


async def optimize_skill(
    db: Any,
    *,
    organization: Any,
    user: Any,
    skill_id: str,
    eval_suite_id: Optional[str] = None,
    case_ids: Optional[List[str]] = None,
    epochs: int = 3,
    max_edits_per_epoch: int = 3,
    model: Any = None,
) -> Dict[str, Any]:
    """SkillOpt-style closed-loop optimization of ONE skill's SKILL.md, gated by
    a held-out golden eval suite. Returns a summary dict; NEVER raises; no-op
    summary when ``flags.SKILL_OPTIMIZE`` is off or inputs are missing.

    Summary shape:
        {"skill_id", "epochs_run", "baseline_score", "best_score",
         "improved": bool, "accepted_edits": [...], "new_version_id": id_or_None}
    or, on a short-circuit, {"skipped": True, "reason": str}.
    """
    try:
        # 1. Flag gate.
        from app.settings.hybrid_flags import flags

        if not flags.SKILL_OPTIMIZE:
            return {"skipped": True, "reason": "flag off"}

        if db is None or not skill_id:
            return {"skipped": True, "reason": "missing inputs"}

        # 2. Load the live skill.
        skill = await _load_visible_skill(
            db, organization=organization, user=user, skill_id=str(skill_id)
        )
        if skill is None:
            return {"skipped": True, "reason": "skill not found or not active"}

        skill_name = getattr(skill, "name", "") or ""
        best_md = getattr(skill, "skill_md", "") or ""
        if not best_md:
            return {"skipped": True, "reason": "skill has no body"}

        # Resolve the held-out eval suite/cases. We do NOT fabricate cases.
        if not eval_suite_id and not case_ids:
            return {
                "skipped": True,
                "reason": "no eval_suite_id or case_ids provided",
                "skill_id": str(skill_id),
            }

        # Resolve a model for the AGGREGATE step up-front (rollouts don't need it).
        agg_model = await _resolve_model(db, organization, user, model)

        # 3. BASELINE rollout.
        baseline_score, last_rows = await _rollout(
            db,
            organization=organization,
            user=user,
            pinned_skill=_as_pin(skill_name, best_md, skill),
            case_ids=case_ids,
            eval_suite_id=eval_suite_id,
        )
        best_score = baseline_score

        accepted_edits: List[Dict[str, Any]] = []
        epochs_run = 0
        no_improve_streak = 0

        # 4. Epoch loop: reflect -> aggregate -> select.
        for epoch in range(max(0, int(epochs))):
            epochs_run = epoch + 1

            # a. REFLECT — failing cases (+ optional critiques) from the last run.
            failing = await _gather_failing(
                db,
                rows=last_rows,
                organization=organization,
                user=user,
                model=agg_model,
            )
            if not failing:
                # Nothing failing to learn from — stop early.
                break

            # b. AGGREGATE — ask the LLM for a bounded revision. Fail-soft.
            if agg_model is None:
                break
            try:
                prompt = build_optimize_prompt(
                    best_md, failing, max_edits=int(max_edits_per_epoch)
                )
                infer = _make_infer(agg_model)
                raw = infer(prompt)
                if hasattr(raw, "__await__"):
                    raw = await raw  # tolerate an async infer override
                candidate_md = _strip_fence(str(raw or ""))
            except Exception as e:
                logger.warning("skill optimizer aggregate LLM failed: %s", e)
                break

            if not candidate_md or len(candidate_md) < _MIN_BODY_LEN:
                # Unusable revision — don't waste a rollout.
                no_improve_streak += 1
                if no_improve_streak >= 2:
                    break
                continue
            if candidate_md.strip() == best_md.strip():
                # Model returned the same doc — no progress possible.
                break

            # c. SELECT rollout — evaluate the candidate.
            cand_score, cand_rows = await _rollout(
                db,
                organization=organization,
                user=user,
                pinned_skill=_as_pin(skill_name, candidate_md, skill),
                case_ids=case_ids,
                eval_suite_id=eval_suite_id,
            )

            # d. STRICT accept gate.
            if cand_score > best_score:
                best_md = candidate_md
                best_score = cand_score
                last_rows = cand_rows
                accepted_edits.append(
                    {
                        "epoch": epochs_run,
                        "score": cand_score,
                        "prev_score": baseline_score
                        if not accepted_edits
                        else accepted_edits[-1]["score"],
                        "n_failing_addressed": len(failing),
                    }
                )
                no_improve_streak = 0
            else:
                no_improve_streak += 1
                if no_improve_streak >= 2:
                    # No improvement two epochs running — stop.
                    break

        # 5. UPDATE/persist — only when the best body actually improved.
        improved = bool(best_md != (getattr(skill, "skill_md", "") or ""))
        new_version_id: Optional[str] = None
        if improved and best_score > baseline_score:
            new_version_id = await _persist_draft_version(
                db, skill=skill, best_md=best_md
            )
        else:
            # No strict improvement -> nothing to persist.
            improved = False

        # 6. Summary.
        return {
            "skill_id": str(skill_id),
            "epochs_run": epochs_run,
            "baseline_score": baseline_score,
            "best_score": best_score,
            "improved": improved,
            "accepted_edits": accepted_edits,
            "new_version_id": new_version_id,
        }
    except Exception as e:  # never raise into the caller
        logger.warning("optimize_skill failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"skipped": True, "reason": f"error: {e}", "skill_id": str(skill_id)}


# --- Nightly leader-gated auto-optimize daemon (#7) -------------------------

# Hard caps so a nightly run can NEVER explode token cost. The optimizer runs a
# full eval rollout per candidate (N LLM completions each), so we bound both the
# per-org fan-out and the global total.
_DAEMON_MAX_PER_ORG = 3
_DAEMON_MAX_TOTAL = 10


async def run_scheduled_skill_optimize() -> dict:
    """Nightly leader-gated auto-optimize of stale/low-scoring skills (#7 daemon).

    Self-contained: own session, re-checks flags, never raises. Picks a SMALL,
    bounded set of candidate skills that ALREADY have an eval suite tied to their
    data source(s); for each, runs optimize_skill(epochs=1). No suite -> skip
    (we never fabricate evals). Returns a summary dict.

    Candidate-selection note (linkage):
    A ``Skill`` row carries NO data_source_id and NO direct eval-suite FK — it is
    scoped only by organization / owner / scope (see app/models/skill.py). A
    ``TestSuite`` is scoped by ``organization_id`` (app/models/eval.py). The ONLY
    safe, non-fabricated linkage available today is the SHARED ORGANIZATION: an
    active skill and an org eval suite that already owns >=1 runnable (active,
    non-draft) case live under the same org. We pair them at that granularity and
    NEVER invent cases. This is coarse but correct (the optimizer's own held-out
    SELECT gate can only ever ACCEPT a strict eval improvement, so a loosely
    matched suite degrades to a no-op, it cannot regress a skill).

    TODO(daemon-candidate-selection): a precise skill->suite link needs a real
    skill<->data_source association (e.g. a skill_data_sources join table or a
    data_source_ids column on ``skills``) so we can pick the suite whose
    ``TestCase.data_source_ids_json`` overlaps the skill's data source(s). Until
    that exists, org-level pairing is the safe MVP.
    """
    try:
        from app.settings.hybrid_flags import flags

        # Re-check BOTH the outer feature flag and the daemon flag — either off
        # short-circuits to a clean no-op (no session, no rollouts, no writes).
        if not (flags.SKILL_OPTIMIZE and flags.SKILL_OPTIMIZE_DAEMON):
            return {"skipped": True}

        from app.settings.database import create_async_session_factory

        async_session = create_async_session_factory()

        from sqlalchemy import select
        from app.models.skill import Skill
        from app.models.eval import TestSuite, TestCase
        from app.models.organization import Organization as _Org

        results: List[Dict[str, Any]] = []
        ran = 0
        capped = False

        async with async_session() as session:
            # Orgs that own at least one active skill AND at least one eval suite
            # with a runnable case. Process per org so the per-org cap applies.
            org_rows = (
                await session.execute(
                    select(Skill.organization_id)
                    .where(Skill.status == "active")
                    .where(Skill.invalid_at.is_(None))
                    .where(Skill.organization_id.isnot(None))
                    .where(Skill.deleted_at.is_(None))
                    .distinct()
                )
            ).all()
            org_ids = [str(r[0]) for r in org_rows if r and r[0]]

            for org_id in org_ids:
                if ran >= _DAEMON_MAX_TOTAL:
                    capped = True
                    logger.info(
                        "skill-optimize daemon: hit global cap %s — skipping remaining orgs",
                        _DAEMON_MAX_TOTAL,
                    )
                    break

                try:
                    organization = await session.get(_Org, org_id)
                    if organization is None:
                        continue

                    # The rollout path (create_and_execute_background -> stub report)
                    # needs a real current_user (it stamps the report owner +
                    # requested_by). The nightly scheduler has no request user, so
                    # resolve any org member (mirrors run_scheduled_evals). No member
                    # -> skip this org (can't run rollouts without an owner) — else
                    # create_and_execute_background derefs current_user.id and every
                    # rollout fails, making the daemon a silent no-op.
                    from app.services.eval_harness import _resolve_org_member_user
                    member_user = await _resolve_org_member_user(session, org_id)
                    if member_user is None:
                        logger.info(
                            "skill-optimize daemon: org %s has no member user — skipping",
                            org_id,
                        )
                        continue

                    # An org eval suite that already owns a runnable case. No
                    # suite -> skip this org (we never fabricate evals).
                    suite_id = (
                        await session.execute(
                            select(TestSuite.id)
                            .join(TestCase, TestCase.suite_id == TestSuite.id)
                            .where(TestSuite.organization_id == org_id)
                            .where(TestCase.status == "active")
                            .where(TestCase.deleted_at.is_(None))
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if suite_id is None:
                        logger.info(
                            "skill-optimize daemon: org %s has skills but no eval suite — skipping",
                            org_id,
                        )
                        continue

                    # Up to N active skills for this org (bounded fan-out).
                    skill_rows = (
                        await session.execute(
                            select(Skill.id)
                            .where(Skill.organization_id == org_id)
                            .where(Skill.status == "active")
                            .where(Skill.invalid_at.is_(None))
                            .where(Skill.deleted_at.is_(None))
                            .order_by(Skill.last_used_at.asc().nullsfirst())
                            .limit(_DAEMON_MAX_PER_ORG)
                        )
                    ).all()
                    skill_ids = [str(r[0]) for r in skill_rows if r and r[0]]

                    for sid in skill_ids:
                        if ran >= _DAEMON_MAX_TOTAL:
                            capped = True
                            logger.info(
                                "skill-optimize daemon: hit global cap %s mid-org %s",
                                _DAEMON_MAX_TOTAL,
                                org_id,
                            )
                            break
                        try:
                            summary = await optimize_skill(
                                session,
                                organization=organization,
                                user=member_user,
                                skill_id=sid,
                                eval_suite_id=str(suite_id),
                                epochs=1,
                            )
                            results.append(summary)
                            ran += 1
                        except Exception as e:  # optimize_skill never raises, but be safe
                            logger.warning(
                                "skill-optimize daemon: optimize_skill(%s) failed: %s",
                                sid,
                                e,
                            )
                except Exception as e:
                    logger.warning(
                        "skill-optimize daemon: org %s failed: %s", org_id, e
                    )
                    continue

        logger.info(
            "skill-optimize daemon: ran=%s capped=%s", ran, capped
        )
        return {"ran": ran, "results": results, "capped": capped}
    except Exception as e:  # never raise into the scheduler
        logger.warning("run_scheduled_skill_optimize failed: %s", e)
        return {"skipped": True, "reason": f"error: {e}"}
