# PLAN — Skills produce real answers + sub-agents fire + correct labels

Date: 2026-06-22. Branch hybrid-brain. Image `cityagent-analytics:dev` (:3007).

## Problems (root-caused, verified live)

1. **Skill returns garbage → no answer.** Skill scripts auto-pick the FIRST table that
   returns rows (chinook → `Album`, value=`AlbumId`) and IGNORE the `args` field. They
   cannot do joins/aggregations ("revenue by artist" needs Artist⋈Album⋈Track⋈InvoiceLine).
2. **False-done loop.** `agent_v2.py:2239` `max_repeated_successes = 2` → after the skill is
   re-called twice the planner declares "goal achieved" and stops WITHOUT producing an
   answer/artifact. This is why the run ended with a bogus terminal and zero Pareto.
3. **Generic name in chat.** `pages/reports/[id]/index.vue:350` renders raw `tool_name`
   (`run_skill_file`) instead of the skill name in `arguments_json.skill` (`pareto-8020`).
4. **Sub-agents never fire.** NO code bug — `flags.SUBAGENTS=True`, `delegate_subtask` IS in
   the chat catalog (verified live). The planner just never CHOOSES it: tested questions were
   single-intent + the planner prompt barely advertises fan-out.

## Fixes

### A — `run_skill_file` accepts SQL and feeds rows to the script  (hot-reload)
- `app/ai/tools/schemas/run_skill_file.py`: add
  `sql: Optional[str]` (the query whose rows the skill should analyze) and
  `data_source: Optional[str]` (client key; default = first/only).
- `app/ai/tools/implementations/run_skill_file.py`: when `sql` present →
  `df = ds_clients[key].execute_query(sql)` → pass into the sandbox as an `input_df` kwarg.
- Confirm `StreamingCodeExecutor.execute_code_async` threads the extra kwarg into
  `generate_df(ds_clients, excel_files, **kwargs)` (one-line add if missing).
- Backward compatible: no `sql` → behaves exactly as today (auto-detect).

### B — 12 executable skill scripts use the supplied rows first  (hot-reload, DUAL WRITE)
Skills: ab-test-analysis, segmentation-analysis, business-metrics-calculator,
programmatic-eda, data-profile, anomaly-detection, cohort-retention, funnel-analysis,
kpi-snapshot, pareto-8020, rfm-segmentation, time-series-trend.
- Top of `generate_df`: `df = kwargs.get('input_df')`; if non-empty → use directly
  (agent already shaped item/value); else current auto-detect; FAIL-LOUD unchanged.
- **DUAL WRITE landmine:** edit host `skills_library/*` files + `docker cp` into
  `ca-app:/app/skills_library/` + UPDATE the matching `skill_files.content` DB rows
  (runtime reads the DB row, not disk). `py_compile` all 12.
- Sandbox landmine: no `hasattr/getattr/eval/exec/open/locals` — keep `'x' in dir(obj)`.

### C — tell the agent to pass SQL  (hot-reload)
- `run_skill_file` tool description: "For joins/aggregations pass the exact SQL via `sql=`,
  ideally returning columns `item` and `value`; the script analyzes those rows."
- Prepend one line to the 12 skill bodies: "If the analysis needs a join/aggregation, call
  `run_skill_file` with `sql=` — do not rely on auto-detect."

### D — stop the false-done  (hot-reload, CORE FILE — careful)
- `app/ai/agent_v2.py` ~2239: do NOT terminate-as-success on repeated tool calls when the
  run has produced NO answer content AND NO artifact/widget. Options (pick safest at impl):
  (a) raise `max_repeated_successes` to 3 AND gate the "done" on `produced_output`, or
  (b) when repeats hit the cap with no output, inject a steer ("you have not produced a
  result; run create_data with the correct query") instead of declaring done.
- Minimal, reversible; keep the cap as a backstop so it can't infinite-loop.

### E — show the skill name in chat  (FE — needs rebuild)
- `pages/reports/[id]/index.vue:350`: if `tool_name ∈ {load_skill,run_skill_file,read_skill_file}`
  render `arguments_json.skill` with a friendly verb (e.g. "Pareto 80/20 · ran script").

### F — nudge fan-out (ONLY if the test below still stays inline)  (hot-reload)
- `app/ai/agents/planner/prompt_builder_v3.py`: add a short line — "When the request has
  independent sub-questions, use `delegate_subtask` to research each in parallel, then
  synthesize." Keep it one sentence; don't over-trigger on single-intent Qs.

## Sequencing
1. **Pre-test sub-agents first** (no code): ask the 3-part fan-out question. If SUB-AGENTS
   populates → drop F. If not → include F.
2. Wave 1 (disjoint sub-agents, against this contract): A (BE tool) · B+C (skills) · E (FE).
3. Wave 2 (parent, serial, careful): D (agent_v2 loop) · F (if needed).
4. Bake: BE via `docker cp`+`py_compile`+`docker restart` (no rebuild); FE (E) needs
   `compose build app` + `up -d --force-recreate app` (~40s cached).

## Verify
- Re-ask: "Run an 80/20 Pareto on Music Store revenue by artist." Expect:
  load_skill → run_skill_file(sql=Artist⋈Album⋈Track⋈InvoiceLine SUM, item=artist, value=rev)
  → real Pareto table + chart → written answer. Activity SKILLS USED populated; chat shows
  "Pareto 80/20".
- Fan-out Q → SUB-AGENTS lists workers.
- Regression: a plain "top 5 artists" Q still answers (no `sql` path = unchanged).

## Risk / rollback
- A/B/C/F = additive, flag-respecting, fail-soft. D = core file → back up `agent_v2.py`
  first (`scripts/backup.sh`), keep the cap as backstop, revert if any run won't terminate.
- DB skill_files rows: snapshot before UPDATE.
- NOT touched: flags, migrations, other ArtifactFrame callers.
