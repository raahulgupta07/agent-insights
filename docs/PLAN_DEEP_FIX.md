# Deep-fix plan — verified root causes (2026-06-22)

4 research agents ran; I verified every claim against the live container + DB.
**Two agent root-causes were WRONG** — corrected below. Don't act on the agents'
raw reports; act on this.

## Verified facts
- Container Python = **3.12.3** → the "union-syntax bug on 3.8" theory is FALSE
  (`X | None` is valid). `utils.py` imports fine.
- `delegate_subtask` **IS** registered + in the chat catalog (action+research,
  confirmed live) → "not registered" theory is FALSE. The F nudge IS active.
- Skill steps in DB: `status=success`, `is_default=TRUE`, `code` + `data`
  populated → "skill steps not marked default → invisible to available_steps"
  theory is FALSE. They ARE discoverable.
- pgbouncer: `pool_mode=session`, `default_pool_size=25`, NO `query_wait_timeout`
  (→ default **120s**). CONFIRMED.

## Root causes (corrected, verified)

**R1 — 120s connection death → "Thinking…" hangs (Q5).** REAL.
pgbouncer `pool_mode=session` + `default_pool_size=25` + default `query_wait_timeout=120s`
+ report page polling `/default_step` every 1.2s + agent holding a DB conn across
long LLM streams → pool exhaustion → query waits 120s → `ConnectionDoesNotExistError`
→ agent task dies. UI never gets a terminal SSE → spins forever.

**R2 — Agent re-runs skills, never assembles dashboard (Q6).** REAL, but NOT the
default_step bug. Actual cause: **every skill step is titled the bare skill name
("pareto-8020")**. After 3 runs (artist/genre/country) the planner sees SEVEN
identical "pareto-8020" entries in available_steps — indistinguishable. It can't
map them to the 3 angles, so it can't confidently pass viz_ids to create_artifact
→ re-runs hoping to get the right one → never converges. create_data steps have
descriptive titles ("Top Genre by Revenue") and DO converge.

**R3 — Sub-agents never fire.** NOT a code/registration bug (tool is in catalog +
nudge active). Cause: **model preference** — planner does the first analysis with
the salient pareto skill instead of delegating; one-tool-per-turn + a one-line
nudge isn't enough to change behavior.

**R4 — "What each skill did" unclear.** Same root as R2: generic identical titles
+ no skill-run→result link. SKILLS USED shows N× "Ran skill · pareto-8020".

**R5 — Blank chart for a scalar (Q1, "412 invoices").** viz-inference made a
chart for a 1-row/1-col scalar; nothing to plot. Should be a number/KPI card or table.

**R6 — Q4 red text under "Dashboard Created".** Cosmetic. Dashboard WAS created;
the red line is plan reasoning rendered in the error style.

## Fix plan (sequenced)

### Theme A — Infra stability (do first; unblocks everything)
- **A1** pgbouncer `pool_mode: session → transaction` + set `query_wait_timeout`
  (e.g. 30s). CAUTION: transaction mode + asyncpg needs `statement_cache_size=0`
  / disabled prepared statements — verify `database.py` engine (asyncpg) and set it,
  else "prepared statement does not exist" errors. Config + small code.
- **A2** Always emit a terminal `completion.error` SSE on agent failure + a
  frontend watchdog so "Thinking…" can never hang (defensive; cheap).
- **A3** (defer) release the agent's DB connection across long LLM/tool calls
  (real refactor) — only if A1 insufficient.

### Theme B — Convergence (the core UX win)
- **B1** Give skill-created steps a **descriptive title** instead of the bare skill
  name. Add an optional `title` arg to `run_skill_file` (agent supplies, e.g.
  "Artist Revenue Pareto"); fall back to deriving from the SQL/question. This alone
  likely fixes R2 + R4.
- **B2** Planner guidance: "when the independent results already exist in
  available_steps, STOP computing and call create_artifact to assemble; never
  recompute an existing step."

### Theme C — Skill observability (mostly falls out of B1)
- **C1** Distinct titles → SKILLS USED rows become distinguishable.
- **C2** (optional) surface a per-run result summary ("165 artists, top 66 = 80%").

### Theme D — Sub-agents — DECISION NEEDED
Not broken, just unused. Options: (D1) stronger steering / a decompose pre-step, or
(D2) **deprioritize** — single-analyst sequential already works; sub-agents add
cost/complexity for little gain here. Recommend D2 unless you specifically want fan-out.

### Theme E — Cosmetics
- **E1** scalar (1×1) result → render number/KPI card or table, not an empty chart.
- **E2** don't render plan-reasoning narration in the error/red style.

## Suggested order
A1+A2 (stability) → B1+B2 (convergence) → C2/E1/E2 (polish) → D decision last.
