# PLAN — #7 Skill Optimizer (SkillOpt pattern, native port)

> **STATUS: COMPLETE + baked (2026-06-21).** Loop shipped (migration skillbitemp1, optimizer.py, routes optimize/activate, FE skills.vue+SkillDetailsModal, nightly daemon @04:00). All flag-gated default-OFF, approval-safe, vectorless, OpenRouter-only. Proven live on Music Store + real OpenRouter.
>
> **Post-MVP fixes (all baked):**
> - **Finalize fix (Option B):** rollout's Path-1 (`create_and_execute_background`) never finalized TestResults → pass-rate read 0. Added `TestRunService.finalize_run_results()` (extracted `_finalize_one_result` from stream_run) + optimizer `_await_completions_terminal` → finalize → score. Same gap wired in nightly `eval_harness.run_scheduled_evals`. Landmine: use `select(...).execution_options(populate_existing=True)`, NOT `db.expire_all()` (expire → sync attr access → greenlet_spawn crash).
> - **Improve→draft→activate E2E:** proven via format-token failing baseline → LLM edit → strict-improve gate accepts → new draft row (live active untouched) → activate supersedes (uq_skill_current holds).
> - **Cache no-op fix:** with serve-caches on, pinned candidates were answer-cache-served → optimizer silent no-op. Guard in `agent_v2._serve_from_reasoning_cache` (`if self.pinned_skill: return False`) + skip answer-cache write-back for pinned runs. Proven: pinned rollout `served_by=None` (fresh) despite live cache.
> - **Daemon user bug:** `run_scheduled_skill_optimize` passed `user=None` → `create_and_execute_background` derefs `current_user.id` → every rollout crashed → silent no-op @04:00. Fixed: daemon resolves an org-member user (`_resolve_org_member_user`). Proven: baseline 0.0→1.0.
>
> Expectation rule shape gotcha: TestCase rules must be FieldRule `{"type":"field","target":{"category":"completion","field":"text"},"matcher":{"type":"text.contains","value":...}}` — a flat `{"type":"text.contains",...}` is silently skipped → vacuous pass.


> Lift the PATTERN from microsoft/SkillOpt, NOT the dep. A SKILL.md is a TRAINABLE artifact:
> optimize it with natural-language edits, gated by held-out evals. Frozen LLM, no fine-tune,
> no GPU, OpenRouter-only, approval-gated, vectorless — same idiom as upgrades #1-#6.

## The loop (SkillOpt) -> our seams
```
SkillOpt stage   our existing seam (VERIFIED in code)
--------------   ----------------------------------------------------------------
ROLLOUT          test_run_service.py:566 create_and_execute_background -> drives AgentV2 -> result_json
REFLECT          ai/agents/judge/judge.py:126 Judge.score_response_quality -> int
AGGREGATE        services/skill_authoring.py:265 distill_skill_from_completion (textual edit idiom)
SELECT (gate)    Kepler P4 eval goldens + _compare_result_sets matcher (held-out, strict-improve)
UPDATE/version   #4 bitemporal supersede_prior (skills get versions) + #3 approval gate (pending)
CONDUCTOR        #5 workflow runner run_pipeline = the stage loop + per-item judge gate
```

## Net build
```
NEW    app/ai/skills/optimizer.py        epoch loop + bounded textual-diff aggregate (MAIN work)
NEW    migration skillbitemp1            +valid_at/invalid_at/superseded_by on `skills` (reuse #4)
NEW    routes/skills.py POST /skills/{id}/optimize   flag-gated + auth (+ optional nightly daemon)
EDIT   models/skill.py                   +3 bitemporal cols (copy semantic_table.py:43-46)
EDIT   ai/skills/loader.py               list_visible_skills + AND current_condition(Skill)
EDIT   ai/agent_v2.py                    +pinned_skill ctor param + seed active_skill/inject before loop
EDIT   services/test_run_service.py      +pinned_skill passthrough -> 2 AgentV2() sites (1164,1250)
EDIT   routes/knowledge.py (or skills)   supersede_prior on approve of an optimized version
REUSE  workflow runner · Judge · eval matcher · bitemporal.py (generic) · skill_authoring · approval gate
flag   HYBRID_SKILL_OPTIMIZE (default OFF; +HYBRID_SKILL_OPTIMIZE_DAEMON for nightly, default OFF)
```

## Fix the 2 gaps (both reuse existing hooks)
### GAP 1 — skills lack versioning (1 migration)
1. migration `skillbitemp1`: ADD 3 cols to `skills` + PG partial-unique on current
   (`WHERE invalid_at IS NULL AND status='active'`, dialect-guarded), mirrors bitemp2.
2. models/skill.py: +3 Columns (valid_at/invalid_at/superseded_by), copy from semantic_table.py.
3. read filter: loader.list_visible_skills AND `bitemporal.current_condition(Skill)` (flag-on only).
4. supersede-on-approve: `bitemporal.supersede_prior(db, Skill, key_filters=[org==,name==,scope==],
   keep_id=new_id)` BEFORE the status flip (mirrors #4 approve-before-flip landmine).
   `bitemporal.py` is GENERIC (takes any model) -> ZERO new helper code.

### GAP 2 — pin candidate skill during rollout (ctor passthrough)
active_skill dict shape ALREADY defined (load_skill.py:143 `{name, allowed_tools, disallowed_tools}`),
consumed at agent_v2.py:1478.
1. AgentV2.__init__ : +optional `pinned_skill=None`.
2. at runtime_ctx build (~952), BEFORE the loop: if pinned_skill ->
   `runtime_ctx["active_skill"] = {...}` (tool-narrow) + inject `pinned_skill["skill_md"]` into
   instructions via the S5 `render_injected_skill` renderer (already exists).
3. test_run_service.create_and_execute_background : +pinned_skill passthrough to both AgentV2() sites.
4. optimizer builds the candidate dict from skill_md + frontmatter and passes it down.

## optimizer.py contract (MVP)
```python
async def optimize_skill(db, *, organization, user, skill_id, eval_suite_id=None,
                         epochs=3, max_edits_per_epoch=3, model=None) -> dict:
    # 0 load Skill.skill_md (seed)  +  resolve a held-out golden eval suite for its data source(s)
    # loop epochs:
    #   ROLLOUT   workflow-runner fans the suite cases -> TestRunService(pinned_skill=candidate)
    #   REFLECT   Judge.score_response_quality per case  -> scores + critiques
    #   AGGREGATE optimizer LLM: (skill_md, scores, critiques) -> <=N bounded edits -> candidate_md
    #   SELECT    re-run suite w/ candidate; ACCEPT only if matcher score STRICTLY > current best
    #   UPDATE    on accept: best_md = candidate_md  (in-memory; persisted once at the end)
    # persist best_md as a NEW Skill version row status='draft' (pending Review); never overwrite live
    # returns {skill_id, epochs_run, baseline_score, best_score, accepted_edits, new_version_id}
    # NEVER raises into a caller; flag-gated; OpenRouter-only.
```
Textual learning rate = `max_edits_per_epoch`. Gate = strict-improve on held-out matcher (can't regress).
COMPRESS of trajectories not needed (Judge already distills to a score+critique).

## Build order (sub-agent driven, disjoint files)
```
WAVE 0 (foundation, 1 agent, owns the migration+model)
   migration skillbitemp1 + models/skill.py 3 cols + flag in hybrid_flags/.env/compose
WAVE 1 (parallel, against the WAVE-0 contract)
   A: ai/agent_v2.py pinned_skill param + inject block        (core file — solo owner)
   B: services/test_run_service.py pinned_skill passthrough
   C: ai/skills/optimizer.py (epoch loop + aggregate)  + ai/skills/loader.py read-filter
   D: routes (POST /skills/{id}/optimize) + supersede-on-approve + (opt) daemon
WAVE 2 (parent) verify import + py_compile + migration head + live in-container rollout-of-1 + bake
```

## Verify (live, before declaring done)
```
- alembic single head = skillbitemp1; import main OK (routes++); flag in snapshot.
- seed a tiny 2-case golden suite on Music Store; optimize_skill(epochs=1) ->
  baseline_score, best_score, new_version_id; new version row status='draft' (NOT live).
- approve -> supersede_prior invalidates old version (invalid_at set, superseded_by=new).
- flag OFF -> route 404/short-circuit, loader unfiltered (byte-identical), zero DB hit.
```

## Risk / guards
```
LOW. Deterministic held-out gate => an optimized skill can NEVER ship a regression.
Human approval gate => no auto-live. N× eval tokens => epochs+suite-size capped + flag default OFF +
daemon default OFF. Single-analyst path untouched when flag off. ~4-6d.
```

## NOT in MVP (follow-ons)
```
- optimize bundled scripts/queries.sql too (MVP optimizes the skill_md body only).
- cross-model transfer eval (SkillOpt's headline) — run the optimized skill on the OTHER OpenRouter
  model + record the delta. Easy add once the loop exists.
- WebUI/Gradio dashboard (SkillOpt has one) — we surface progress in the existing Review/Evals UI instead.
```
