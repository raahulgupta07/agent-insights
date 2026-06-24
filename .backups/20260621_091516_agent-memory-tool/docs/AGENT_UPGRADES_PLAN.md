# Agent Upgrades — code-grounded plan (memory tool · subagents · skill-grow · bi-temporal · workflows · context-compress)

> Lift the PATTERN, not the dep. Every item is flag-gated, approval-safe, OpenRouter-only, vectorless —
> consistent with the existing hybrid layer. Integration points are real (verified in code).

## Where it all plugs in (the 4 load-bearing seams)

```
AgentV2 (app/ai/agent_v2.py)   single PlannerV3 plan→tool→rebuild-context→reflect loop.
   - ToolRegistry (app/ai/registry.py) auto-registers anything in tools/implementations/  -> new TOOL = drop a file
   - context built by render_*_section append blocks, rebuilt ~twice/iteration              -> new CONTEXT = new section
Brain (app/ai/brain/*)         answer/query caches + distiller + knowledge_proposer + brain_graph(CTE)
Skills (app/ai/skills/*)       SKILL.md + frontmatter + files + registry.register_skill + authoring
Approval gate                  knowledge_proposer writes status='pending' -> Review tab -> approved-only reaches agent
NO worker queue today          only core/scheduler.py cron + asyncio.create_task  -> subagents need a light runner
```

---

## 1. Agent memory TOOL (MemGPT page-in/out)  ·  ~2-3d  ·  flag HYBRID_AGENT_MEMORY  ·  risk LOW
**What:** two agent-callable tools — `remember(scope, key, text)` and `recall(query)` — so the analyst
DELIBERATELY stows + pages project state, distinct from the passive answer/query caches.
**Where:** new `app/ai/tools/implementations/memory_tool.py` (auto-registered) backing onto a new
`app/ai/brain/agent_memory.py` (Postgres FTS+Jaccard recall, the vectorless idiom). `remember` writes
`status='pending'` (your invariant) into a `dash_agent_memories`-style table; a `render_memory_section`
in agent_v2 pages the top-K approved memories for the current question (mirror docs/joins sections).
**Product win:**
- CROSS-SESSION continuity — "last analysis found Q3 revenue driven by X" recalled in a new chat →
  fewer repeated queries, feels like a colleague, not a stateless bot.
- frees context (page in only what's relevant = MemGPT RAM↔disk) → cheaper, longer sessions.
- it's the agent's OWN scratchpad vs your auto-caches → captures reasoning, not just answers.

## 2. SUBAGENT fan-out (orchestrator-worker)  ·  ~1-2wk  ·  flag HYBRID_SUBAGENTS  ·  risk MED (cost)
**What:** an orchestrator spawns N CLEAN-context worker runs, each its own scoped sub-question + tool
budget, each returns a DISTILLED ~1-2k summary; orchestrator synthesizes. (Anthropic multi-agent pattern.)
**Where:** new `app/ai/runner/orchestrator.py` that instantiates AgentV2 as the worker (reuse the existing
loop + StreamingCodeExecutor + per-user creds + skills), fan-out via `asyncio.gather` with a concurrency
cap + a hard token-budget guard. Surface two ways: (a) a planner tool `delegate_subtask(question, scope)`,
(b) a "Deep / multi-source" report mode. Studios (which already wrap multiple data agents) are the natural
orchestrator home.
**Product win:**
- CROSS-DATASET questions ("sales vs target vs market") — one worker per source, clean context, no
  cross-source confusion → markedly better answers where the single-analyst struggles today.
- heavy builds (deep dashboard / deck) — per-panel/section workers in parallel → faster + higher quality.
- audits/reconciliation — fan out across tables. **The single biggest capability jump.**
**Guard:** N× tokens — hard per-run budget + concurrency cap + only on opt-in heavy modes.

## 3. Voyager SKILL auto-grow  ·  ~3-5d  ·  flag HYBRID_SKILL_AUTOGROW  ·  risk LOW
**What:** proven runs (👍 / verified-good answers with reusable SQL/code) auto-draft a new parameterized
SKILL → register `status='pending'` → Review. Skill library grows from use (Voyager curriculum).
**Where:** you already have skills + authoring + `registry.register_skill` + `query_cache_store` (proven
SQL). Add a hook in `completion_feedback_service` (the same place the distiller fires on 👎) — on 👍 with
reusable SQL, LLM-draft a SKILL.md + `scripts/queries.sql` (you already auto-emit this in authoring) →
register pending. Exact sibling of `knowledge_proposer`, but for PROCEDURES not facts.
**Product win:**
- agent gets FASTER + cheaper on repeat tasks (run_skill_file/apply_skill vs re-derive) → makes the
  "self-learning" promise real for *how to do things*, not just *what is true*.
- per-org institutional procedure library accumulates automatically.

## 4. BI-TEMPORAL memory (Zep/Graphiti)  ·  ~4-5d  ·  flag HYBRID_BITEMPORAL  ·  risk LOW-MED
**What:** facts that change over time get `valid_at/invalid_at/superseded_by`; never delete — invalidate +
supersede. Reads filter `invalid_at IS NULL`; time-travel passes an as-of. (City-Dash did exactly this.)
**Where:** migration adds the 3 cols to `brain_graph_edges` + `company_brain` + `semantic_table`/
`metric_definition` (where defs evolve). On a contradicting approve, invalidate old + insert new.
brain_graph's recursive-CTE traversal already exists — bi-temporal makes it trustworthy.
**Product win:**
- correctness on evolving definitions/prices/policies → no stale-fact contradictions → trust.
- audit / time-travel: "what did the agent know as of date X" — enterprise/compliance ask.

## 5. Deterministic WORKFLOW runner (+ MetaGPT verifier gate)  ·  ~1wk  ·  flag HYBRID_WORKFLOWS  ·  risk LOW
**What:** a DAG script that fans a work-list through stages deterministically, each stage gated by a
reviewer/judge agent before commit. Less model-driven than the free loop → reliable bulk ops.
**Where:** new `app/ai/workflows/runner.py`. Targets: autotrain a whole warehouse, eval-golden backfill,
drift sweeps, schema reconciliation. The reviewer gate reuses your existing `judge` agent (MetaGPT's
verifier pattern, +15.6% in their study). Conductor for #2's workers.
**Product win:** reliability on bulk/structured ops (no one-big-agent drift); pairs with subagents
(workflow = conductor, subagent = worker).

## 6. CONTEXT compress / checkpoint (GCC + OpenDerisk)  ·  ~3-4d  ·  flag HYBRID_CONTEXT_COMPACT  ·  risk LOW
**What:** between turns — EDIT (drop answered/superseded sections) + COMPRESS (summarize old turns) +
AWARENESS (put "context: X of Y tokens" in the prompt so the model self-manages). You rank top-K already;
add edit+compress+awareness.
**Where:** the agent_v2 context-rebuild path (the "twice per loop" rebuild) + `context_hub`. A compaction
step summarizes old turns to a rolling digest, drops superseded sections, enforces a token budget.
**Product win:** longer, cheaper sessions (less bloat) → cost down + fewer "context full" failures on long
multi-turn investigations; agent stays focused.

---

## Synergy stacks
```
MEMORY stack       #1 memory tool  +  #4 bi-temporal      = deliberate, time-correct memory
MULTI-AGENT stack  #2 subagents    +  #5 workflow runner  = worker + deterministic conductor
EFFICIENCY stack   #3 skill-grow   +  #6 context-compact  = faster over time + cheaper per run
```

## Recommended sequencing
```
PHASE 1 (quick wins, extend what exists, ~2wk total, low risk)
   #1 memory tool · #3 skill auto-grow · #6 context compress
   -> each reuses brain/skills/context; ships Anthropic's newest memory pattern + your self-learning promise.
PHASE 2 (biggest lever, ~2-3wk)
   #2 subagent fan-out  (+ #5 workflow runner as the conductor)
   -> closes your only real gap (single-analyst) — multi-source answers + parallel builds.
PHASE 3 (correctness hardening, ~1wk)
   #4 bi-temporal  -> trustable evolving facts + time-travel audit.
```

## Cross-cutting rules (same as the rest of the repo)
```
- flag-gated default OFF (.env + docker-compose.build.yaml both)
- approval-safe: agent-authored memory/skills land 'pending' -> Review -> approved-only reaches the agent
- vectorless: FTS + token-Jaccard recall (no embedding dep)
- OpenRouter only; never raise into the agent loop (fail-soft sections/tools)
- alembic from current head; Postgres-only DDL dialect-guarded
- backup.sh before structural edits; build cityagent-analytics:dev (never bagofwords:latest)
```

## Highest-ROI first move
```
#1 memory tool (small, ships the newest Anthropic pattern, leverages your brain)
THEN #2 subagents (your genuine gap + the biggest capability jump; Opus is built to manage subagent teams).
```
