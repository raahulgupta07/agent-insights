# PLAN — Skills + Tools "like Claude Code"

Branch `hybrid-brain`. Goal: make the self-service Skills subsystem behave like
Claude Code skills — YAML frontmatter, per-skill tool scoping (`allowed-tools`),
L3 bundled resources, invocation flags, slash-invoke. All flag-gated
(`HYBRID_SKILLS`), default OFF, reuse the dash approval gate (HARD RULE 5).
Each phase = small tasks; **user approves each phase before it runs**.

## Baseline facts (verified 2026-06-18)
- True single alembic head: **`b4rain5graph6`** (container `alembic heads`).
- `PyYAML==6.0.2` already pinned — no new dep for frontmatter.
- `skills` table today: name, description, scope, owner_user_id, organization_id,
  skill_md, category, status, hit_count, last_used_at, deleted_at (soft). Model
  `app/models/skill.py`.
- **load_skill IS reachable today** — `agent_v2.py:332-340` merges action+research
  catalogs; `_validate_tool_for_plan_type` = "always allow". The `category="research"`
  is cosmetic (flip to `both` anyway). NOT the historical bug.
- Skill body reaches model via `load_skill` → `ToolEndEvent` observation
  `instructions=skill_md` → `observation_builder.tool_observations` → planner.
- L1 catalog already top-K token-Jaccard (`HYBRID_SKILLS_TOP_K=8`,
  `skill_context_builder.py:_rank_skills`).

## Gap vs Claude Code
| Capability | CC | Now | Phase |
|---|---|---|---|
| L1 metadata always in ctx | ✓ | ✓ top-K | done |
| L2 body on demand | ✓ | ✓ load_skill | done |
| Structured YAML frontmatter | ✓ | ✗ raw Text | **S1** |
| `allowed-tools` per-skill scoping | ✓ | ✗ | **S2** |
| L3 bundled scripts/refs/assets | ✓ | ✗ | **S3** |
| disable-model-invocation / user-invocable | ✓ | ✗ | **S4** |
| slash `/skill` + `$ARGUMENTS` | ✓ | ✗ | **S4** |
| run scripts in sandbox | ✓ | dash has sandbox, unwired | **S3** |
| authoring / promote ladder | skill-creator | ✓ ahead | done |

---

## PHASE S1 · Structured YAML frontmatter  ✅ in progress
Parse SKILL.md frontmatter into structured columns; switch authoring to emit
standard YAML frontmatter; keep raw `skill_md` as source of truth.

**New columns** (`skills`, all nullable/safe-default → old rows behave unchanged):
`allowed_tools` (Text, JSON list), `disallowed_tools` (Text, JSON list),
`disable_model_invocation` (Boolean, default False), `user_invocable` (Boolean,
default True), `skill_metadata` (Text, JSON), `license` (String(100)).

- [ ] S1.1 migration `sk2frontmttr1` off head `b4rain5graph6`, dialect-agnostic
  add_column (PG + SQLite), nullable, no backfill. Register in `alembic/env.py`
  if needed (Skill already imported).
- [ ] S1.2 `app/models/skill.py` — add the 6 columns.
- [ ] S1.3 `app/ai/skills/frontmatter.py` — `parse_frontmatter(md)->(dict,body)`,
  `build_skill_md(fm,body)->str`, `extract_skill_fields(md)->dict` (tolerant of
  `allowed-tools` hyphen alias; never raises; missing fm → ({},md)).
- [ ] S1.4 `skill_authoring.py` — `build_skill_prompt`/`parse_skill_draft` emit &
  accept **YAML frontmatter** SKILL.md; keep legacy `NAME:/DESCRIPTION:/---`
  back-compat path. Persist parsed fields into new columns on author.
- [ ] S1.5 `loader.get_skill_body` returns the new fields; `load_skill`
  `category="research"→"both"`.
- [ ] S1.6 unit tests: `test_skill_frontmatter.py` (parse/build/aliases/empty) +
  extend `test_skill_authoring.py` (YAML emit + legacy back-compat).
- [ ] S1.7 py_compile all; confirm single head; flag-OFF no-op verified.

## PHASE S2 · `allowed-tools` per-skill tool scoping  (core "like CC" win)
When a skill is loaded, narrow the planner's tool catalog to the skill's
`allowed_tools` (∩ normal catalog), pre-approve them, drop `disallowed_tools`.

- [ ] S2.1 `load_skill` sets `runtime_ctx["active_skill"]` = {name, allowed_tools,
  disallowed_tools} on successful load.
- [ ] S2.2 `agent_v2` catalog build (~:332) — when `active_skill` present & flag on,
  filter catalog: keep ∩ allowed_tools, remove disallowed_tools (never remove
  load_skill/clarify/done). Empty allowed_tools = no narrowing (CC semantics).
- [ ] S2.3 clear `active_skill` on completion end / new user turn (mirror CC
  "clears next message").
- [ ] S2.4 pre-approval: skill-scoped tools skip confirmation path (reuse existing
  confirmation gate; honor org deny rules).
- [ ] S2.5 unit tests: narrowing math (∩, disallow, empty=no-op, never-drop set).

## PHASE S3 · L3 bundled resources
- [ ] S3.1 `skill_files` table (skill_id FK, path, kind[script|reference|asset],
  content Text or `s3:<key>`) + migration + model.
- [ ] S3.2 frontmatter references one level deep; authoring auto-emits
  `scripts/queries.sql` from executed SQL, `references/*` from built views.
- [ ] S3.3 new tool `read_skill_file(skill,path)` (category research) → reference
  content into observation; scripts route through `code_execution.py` sandbox
  (AST + DB-RO), **output-only** into context (never raw code).
- [ ] S3.4 loader lists a skill's files; L2 body lists available files for model.
- [ ] S3.5 tests: file load, sandbox-run output-only, path-escape guard.

## PHASE S4 · Invocation parity  ✅ DONE (2026-06-19, flag-OFF no-op)
- [x] S4.1 honor `disable_model_invocation` — dropped from planner catalog via
  `list_visible_skills(for_model=True)` (builder passes it) + defense-in-depth in
  `get_skill_body` (model load path). `user_invocable=false` rejected at the
  human invoke endpoint (403). NULL (pre-migration) treated as enabled/invocable.
  `GET /skills` stays UNfiltered (FE list + slash autocomplete need full set).
- [x] S4.2 FE composer `/skill-name args` → `PromptBoxV2.submit()` now async,
  `parseSlash` + `resolveSkillInvocation` (GET /skills → match name → POST
  invoke → replace text with substituted prompt; miss falls through to raw send).
  **Needs FE rebuild / `yarn dev` :3000 to take effect.**
- [x] S4.3 `POST /skills/{id}/invoke` body `{arguments}` → strips frontmatter,
  `substitute_arguments`, records use, returns `{id,name,prompt,arguments}`.
- [x] S4.4 unit tests: `test_skill_invocation.py` 31 (slash parse + `$ARGUMENTS`/
  `$0..$N` substitution). Endpoint + FE = no unit test (DB/browser) → e2e in S6.
  New pure module `app/ai/skills/invocation.py`. 99 skill tests green total.

## PHASE S5 · Activation polish + retrieval  ✅ DONE (2026-06-19, flag/env-OFF no-op)
- [x] S5.1 strengthened L1 catalog prompt — `render_skill_catalog` now hard-tells
  the model: scan first, ANY description match → `load_skill("<name>")` FIRST,
  follow verbatim, prefer skill over ad-hoc, most-specific wins, none → proceed.
- [x] S5.2 auto-inject top-1 body — `skill_context_builder`: top-1 ranked skill's
  Jaccard ≥ floor → `get_skill_body` → inline full SKILL.md via new
  `render_injected_skill` (no load_skill hop). Env-gated `HYBRID_SKILLS_AUTOINJECT`
  (default OFF) + `HYBRID_SKILLS_AUTOINJECT_FLOOR` (default 0.5). Catalog still
  emitted for other skills; disabled top match won't inline (get_skill_body drops
  it). New `SkillsSection.injected_name/injected_body` fields carry it.
- [ ] S5.3 pgvector top-K when >~50 skills — **BLOCKED on Phase-8 embeddings**, deferred.

## PHASE S6 · Verify + bake
- [ ] S6.1 e2e: author skill w/ allowed-tools + bundled script → matching Q →
  body loads + catalog narrows + script runs sandboxed + hit_count bumps.
- [ ] S6.2 FE skills page surfaces frontmatter fields + files.
- [ ] S6.3 bake into image (currently `docker cp` only), commit.

---
## Execution rules
- Parallel subagents, **disjoint file ownership** (project pattern), confirm on
  disk after.
- Every phase flag-gated `HYBRID_SKILLS`, default OFF = byte-identical upstream.
- Learned/shared skills stay `draft`/`pending` → approval (no new gate).
- Verify single alembic head after every migration.
