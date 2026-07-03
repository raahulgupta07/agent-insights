# TOOL_AUDIT — Agent Tool Consolidation (P6)

> **Audit only. No code was changed.** Goal: rigorously enumerate every agent tool, cluster by
> function, flag overlaps/redundancy, and recommend a lean set — following OpenAI's data-agent
> discipline (~13 tools; "overlapping tools confuse the agent" → cull near-duplicates).
> Verified against source on 2026-07-03. Nothing here is a live edit.

## TL;DR

- **45 planner tool classes** live under `ai/tools/implementations/` (44 files; `memory_tool.py`
  ships 2 classes). **2 are hard-dead** (`create_dashboard`, `create_widget` — `is_active=False`,
  never in the catalog). So **43 planner-reachable** tool classes.
- **9 MCP tool files → 12 MCP tools** (`MCP_TOOLS` in `mcp/__init__.py`) form a *separate* surface
  exposed to external MCP clients (Claude/Cursor) via `routes/mcp.py`. **6 of them are name-for-name
  parallel re-implementations** of planner tools (`create_data`, `create_artifact`, `edit_artifact`,
  `inspect_data`, `send_email`, `create_instruction`). The planner does **not** call these — it calls
  the `implementations/` versions. This is the known `mcp/create_data.py` (unused cache) landmine,
  confirmed platform-wide.
- The agent never sees 45 tools at once — **mode / platform / capability / flag gating** trims the
  default *chat* catalog to **~24**. That's still ~2× OpenAI's 13, and the ~24 contains the real
  confusion: **9 overlap clusters** where two tools do near-identical things.
- **Headline recommendation: 24 always-on chat tools → 13.** Merge 9 overlap clusters, retire the 2
  dead files, and demote the rest to context-gated (they already only surface for excel/file/training/
  skill contexts). Nearly every cut is either already `is_active=False` or flag-gated, so retiring =
  delete-file or default-OFF — **low risk**.

---

## 1. How tools reach the planner (registration truth)

Two fully separate registries:

| Surface | Source | Loaded by | Who calls it |
|---|---|---|---|
| **Planner tools** | `ai/tools/implementations/*.py` (subclass `Tool`) | `ai/registry.py::ToolRegistry._auto_register_all` (pkgutil + `issubclass(Tool)`) | The agent loop (`agent_v2.py` → `registry.get(name)`), catalog via `get_catalog_for_plan_type` |
| **MCP tools** | `ai/tools/mcp/*.py` → `MCP_TOOLS` dict | `mcp/__init__.py` (explicit dict) | External MCP clients over HTTP (`routes/mcp.py`); fast-path inside `execute_mcp` |

**Reachability filters** applied to the planner catalog (`registry.py`):
- `is_active=False` → never in catalog (`create_dashboard`, `create_widget`).
- `allowed_modes` → e.g. `["training","knowledge"]` tools are **absent from normal chat**.
- `allowed_platforms` → `["excel"]` tools only for the Excel add-in surface.
- `requires_capability` → file tools (`list_files`/`read_file`/`search_files`) only when an attached
  connection exposes that capability.
- **Hybrid-flag gating** (hard-coded in `get_catalog_for_plan_type`): `load_skill`/`run_skill_file`/
  `read_skill_file` gated `SKILLS`; `delegate_subtask` gated `SUBAGENTS`; `forecast_df` gated `FORECAST`.
  All three flags default **OFF**.

**Consequence:** the *effective default-chat catalog* (mode=chat, SQL source, no excel/files, flags OFF,
not training) is ~24 tools — that is the surface to lean out. The other ~19 are already context-scoped.

---

## 2. Full tool inventory

### 2a. Planner tools (`implementations/`) — 45 classes

Legend — **Reach**: ✅ default chat · 🎓 training/knowledge mode only · 📊 excel platform only ·
📁 file-capability only · 🚩 flag-gated (default OFF) · ☠️ dead (`is_active=False`).

| Tool | Cluster | Purpose (from metadata) | Reach |
|---|---|---|---|
| `clarify` | control | Ask the user clarifying question(s) before proceeding | ✅ |
| `create_data` | data-creation | Generate code from prompt, execute, return data as table/chart (core query tool) | ✅ |
| `create_widget` | data-creation | End-to-end model→code→execute→widget | ☠️ dead |
| `write_csv` | data-creation | Generate/transform tabular data via custom python/pandas | ✅ |
| `forecast_df` | data-creation | Forecast a date+value series (Holt-Winters/ETS) | 🚩 FORECAST |
| `create_artifact` | artifact | Create/rebuild dashboards, pages, slide decks from visualizations | ✅ |
| `create_dashboard` | artifact | Design a dashboard/report layout from widgets | ☠️ dead |
| `edit_artifact` | artifact | Surgical search/replace edits to an existing artifact | ✅ |
| `read_artifact` | artifact | Read an artifact's code/metadata from the current report | ✅ |
| `inspect_data` | inspect | Examine structure + sample content of a dataset before generating | ✅ |
| `describe_tables` | inspect | Describe specific tables (columns, usage metrics) | ✅ |
| `describe_entity` | inspect | Look up a pre-built catalog entity by name/ID | ✅ |
| `read_query` | inspect | Read previously created queries/visualizations from current report | ✅ |
| `read_resources` | inspect | Read metadata resources (dbt/LookML/docs) | ✅ |
| `resolve_metric` | inspect | Look up an APPROVED business metric by name | ✅ |
| `read_report` | reporting | Read one of the user's OWN reports by id | ✅ |
| `search_reports` | reporting | List/substring-search the user's OWN reports | ✅ |
| `create_scheduled_task` | reporting | Schedule a RECURRING task on the current report | ✅ |
| `cancel_scheduled_task` | reporting | Cancel a recurring scheduled task | ✅ |
| `send_email` | reporting | Send an email to the current user (self) | ✅ |
| `remember` (memory_tool) | memory | Save a durable note/learning for future sessions | ✅ |
| `recall` (memory_tool) | memory | Recall saved notes/learnings | ✅ |
| `remember_this` | memory | Save a proven query/approach for teammates with the same data | ✅ |
| `create_instruction` | instructions | Create a new instruction that guides AI behavior | 🎓 |
| `edit_instruction` | instructions | Edit an existing instruction | 🎓 |
| `search_instructions` | instructions | Search existing org instructions | 🎓 |
| `create_eval` | eval | Create an eval test case (after `search_evals`) | 🎓 |
| `run_eval` | eval | Run one or more eval test cases | 🎓 |
| `search_evals` | eval | List/substring-search eval test cases | 🎓 |
| `list_agent_executions` | eval | Query the platform's own agent execution history | 🎓 |
| `load_skill` | skills | Load a saved skill's SKILL.md by name | 🚩 SKILLS |
| `read_skill_file` | skills | Read a bundled reference file from a loaded skill | 🚩 SKILLS |
| `run_skill_file` | skills | Execute a bundled script from a loaded skill | 🚩 SKILLS |
| `list_files` | files | List files in a SharePoint/OneDrive/Drive connection | 📁 list_files |
| `read_file` | files | Read a file from a file connection | 📁 read_file |
| `search_files` | files | Search files by free-text query in a file connection | 📁 search_files |
| `read_excel_as_csv` | excel | Read an Excel range → CSV string | 📊 excel |
| `read_excel_range` | excel | Read cell values/formulas from A1 ranges | 📊 excel |
| `write_officejs_code` | excel | Execute Office.js code in the user's Excel | 📊 excel |
| `write_to_excel` | excel | Write tabular data directly into the user's Excel | 📊 excel |
| `build_data_asset` | engineer | Create a reusable view/matview/table (analytics.*) | ✅ |
| `execute_mcp` | mcp-bridge | Execute a tool on a connected MCP server / custom API | ✅ |
| `search_mcps` | mcp-bridge | Search available MCP/custom-API tools on attached sources | ✅ |
| `web_fetch` | misc | Fetch + extract readable content from a URL | ✅ |
| `delegate_subtask` | misc | Delegate a focused sub-question to a clean-context researcher | 🚩 SUBAGENTS |

### 2b. MCP tools (`MCP_TOOLS`) — 12 (external MCP surface, NOT planner)

| MCP tool | Duplicate of planner tool? | Notes |
|---|---|---|
| `create_data` | **YES** → `implementations/create_data.py` | The `CreateDataMCPTool` cache is **never hit by the agent** (known landmine). |
| `create_artifact` | **YES** | Parallel re-implementation. |
| `edit_artifact` | **YES** | Parallel re-implementation. |
| `inspect_data` | **YES** | Parallel re-implementation. |
| `send_email` | **YES** (only MCP tool with `is_available`) | Parallel re-implementation. |
| `create_instruction` | **YES** | Parallel re-implementation. |
| `create_report` | partial (no planner `create_report`; planner uses `create_data`+`create_artifact`) | External-only. |
| `get_context` | no planner twin | External-only (context fetch for MCP clients). |
| `list_instructions` | ~ `search_instructions` | External-only. |
| `delete_instruction` | no planner twin | External-only. |
| `get_visualization` | app-only (`visibility=["app"]`) | Hidden from LLM. |
| `get_artifact_data` | app-only (`visibility=["app"]`) | Hidden from LLM. |

---

## 3. Overlap / redundancy findings (ranked by confusion cost)

| # | Overlap cluster | Why it confuses | Verdict |
|---|---|---|---|
| O1 | **`remember` + `recall` (HYBRID_AGENT_MEMORY) vs `remember_this` (D5 / v1.87)** | Two independent memory systems both expose a "save a durable note/proven query" write. The agent has two ways to persist knowledge and no principled way to choose. Memory notes explicitly flag these as *separate* subsystems. | **Merge** — keep one write + one read. Retire `remember_this` (or fold its shared-memory semantics into `remember`). Both flag-gated ⇒ cheap. |
| O2 | **`inspect_data` vs `describe_tables` vs `describe_entity`** | Three "look at the data/schema/entity" tools, all ✅ default chat. Classic OpenAI overlap — agent burns turns picking. | **Merge to one** `inspect_data` that also covers table + catalog-entity lookup. |
| O3 | **`implementations/create_data` (live) vs `mcp/create_data` (dead-to-agent)** — and the same live-vs-MCP split for `create_artifact`, `edit_artifact`, `inspect_data`, `send_email`, `create_instruction` | Two parallel codebases for the same tool name. The MCP copies aren't in the planner catalog, so edits/caches added there silently no-op (the documented cache landmine). Maintenance + correctness hazard, not agent-facing confusion. | **Keep one implementation.** Make MCP tools thin wrappers that delegate to the `implementations/` class (as `execute_mcp` already does via `get_mcp_tool`), so there's a single source of truth. |
| O4 | **`read_artifact` vs `read_query`** | Both "read a prior output (artifact/query/viz) from the current report." Overlapping surface for the agent inspecting its own work. | **Merge** into one `read_output(kind=)` or fold `read_artifact` into `read_query`. |
| O5 | **`read_report` vs `search_reports`** | Read-one vs list/search-many over the same "my own reports" corpus. | **Merge** into `search_reports` with an optional id (search returns, id reads). |
| O6 | **`create_data` vs `write_csv`** | Both execute custom python/pandas to produce tabular data; `write_csv` is the rawer twin. Two ways to "make a table with code." | **Retire `write_csv`** (fold into `create_data`) unless a distinct non-tracked-scratch use is proven. |
| O7 | **`read_excel_as_csv` vs `read_excel_range`** | Two overlapping Excel readers (CSV-string vs cell/formula values). Both 📊-gated so only bite in the add-in. | **Merge** to one reader with an output-format arg. Low priority (platform-scoped). |
| O8 | **`write_officejs_code` vs `write_to_excel`** | Two overlapping Excel writers (raw Office.js vs structured tabular). | **Merge / keep one** structured writer + escape hatch. Low priority (platform-scoped). |
| O9 | **`list_files` vs `search_files`** | List-all vs free-text-search over the same file connection. | **Merge** (`search_files` with empty query = list). Low priority (capability-scoped). |
| — | **`create_dashboard` + `create_widget`** (`is_active=False`) | Already superseded by `create_artifact` + `create_data`; dead in catalog. | **Delete the files** — dead weight, confirms consolidation direction. |

**Honest non-overlaps (look similar, keep both):**
- `create_instruction`/`edit_instruction`/`search_instructions` — a coherent CRUD trio, training-mode only; not chat clutter.
- `create_eval`/`run_eval`/`search_evals` — coherent eval trio, training-only.
- `create_scheduled_task`/`cancel_scheduled_task` — genuine create/delete pair; keep both.
- `execute_mcp` + `search_mcps` — discover-then-call pair for external MCP; keep both (or fold search into execute's discovery).
- `resolve_metric` — governed-metric lookup, distinct from raw schema inspection; **keep**, it's a safety feature.
- `build_data_asset` — Engineer-asset creation (DDL), distinct from `create_data` (ephemeral query). Keep, but note it's `ENGINEER_ASSETS`-adjacent.

---

## 4. Recommended lean set

**Always-on chat core → 13 tools** (matches OpenAI's target):

| Keep | Role | Absorbs |
|---|---|---|
| `clarify` | ask before acting | — |
| `inspect_data` | look at schema/tables/entities/sample | **O2**: `describe_tables`, `describe_entity` |
| `resolve_metric` | governed metric lookup | — |
| `create_data` | prompt→SQL/python→data (core) | **O6**: `write_csv` |
| `create_artifact` | dashboards / pages / slides | (`create_dashboard`, `create_widget` already dead) |
| `edit_artifact` | edit an artifact | — |
| `read_query` | read prior queries/artifacts of this report | **O4**: `read_artifact` |
| `search_reports` | find/read my own reports | **O5**: `read_report` |
| `remember` + `recall` | write/read agent memory | **O1**: `remember_this` |
| `execute_mcp` | call external MCP/API tools | (discovery via `search_mcps` folded in) |
| `web_fetch` | fetch a URL | — |
| `send_email` | deliver to user | — |
| `create_scheduled_task` (+`cancel_scheduled_task`) | recurring runs | — |

(That's 13 primary entries; `recall` and `cancel_scheduled_task` ride along as the read/undo halves of a pair.)

**Context-gated extras (keep, but they never inflate the chat catalog — already gated):**
- Training/knowledge: instruction trio + eval quartet (7).
- Excel add-in: reduce `read_excel_*`→1 (**O7**), `write_*`→1 (**O8**) ⇒ 2 tools.
- File connections: `read_file` + one merged list/search (**O9**) ⇒ 2 tools.
- Flag-gated: skills trio (`SKILLS`), `delegate_subtask` (`SUBAGENTS`), `forecast_df` (`FORECAST`).
- Engineer: `build_data_asset` (`ENGINEER_ASSETS`).

**Quantify:**
- Planner tool classes: **45 → ~32** (delete 2 dead + retire/merge `remember_this`, `write_csv`,
  `describe_tables`, `describe_entity`, `read_artifact`, `read_report`, `search_mcps`, +2 excel, +1 file).
- **Effective default-chat catalog: ~24 → 13** (−46%). This is the number that governs agent confusion.
- MCP surface: **12 → thin wrappers over 1 implementation each** (kills the parallel-code hazard; no
  net change to what external clients can call).

---

## 5. Recommended actions, ranked

Ranked by (confusion reduction × safety). Every top action is default-OFF or dead ⇒ reversible.

1. **Unify memory: retire `remember_this`, keep `remember`/`recall` (O1).** Highest agent-facing
   confusion — two "save knowledge" verbs. Both flag-gated ⇒ retiring = default-OFF. *Risk: low.*
2. **Collapse the inspection trio into one `inspect_data` (O2).** Three always-on schema/entity tools →
   one. Biggest always-on catalog shrink. *Risk: low-med (verify `describe_entity` catalog-lookup and
   `describe_tables` usage-metrics survive as modes of `inspect_data`).*
3. **Deduplicate live-vs-MCP tools (O3) + delete the 2 dead files (`create_dashboard`, `create_widget`).**
   Make MCP tools delegate to the `implementations/` class (single source of truth) so cache/logic
   edits can't silently no-op again. Deleting dead files is zero-risk. *Risk: low.*
4. **Merge the read-overlaps: `read_artifact`→`read_query` (O4) and `read_report`→`search_reports` (O5).**
   Two fewer always-on tools; both are read-only so merges are safe. *Risk: low.*
5. **Retire `write_csv` into `create_data` (O6); fold `search_mcps` discovery into `execute_mcp`.**
   Removes the "two ways to make a table with code" ambiguity and the discover/call split. *Risk: low-med
   (confirm no scratch-only `write_csv` path is depended on).*

*(Lower priority, platform/capability-scoped, do last:* O7/O8 excel readers+writers → 1 each, O9 file
list/search → 1 — these only affect the add-in / file agents and are already gated out of chat.)*

---

## 6. Caveats

- This is a **static** audit (metadata + registry logic). Before deleting any tool, grep for its name in
  prompts (`prompt_builder_v3.py`), goldens, skills, and tests — a retired name that a prompt still
  advertises = a phantom tool.
- Merges that change a tool's input shape need the paired schema in `ai/tools/schemas/` updated and any
  golden/eval fixtures rebound.
- The MCP-dedup (O3) touches `routes/mcp.py` contract for external clients — keep the **names/schemas**
  stable, change only the **implementation** to delegate.
