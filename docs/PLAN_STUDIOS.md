# PLAN — Studios (NotebookLM-style shareable agents)

> **STATUS 2026-06-19: ST1-ST5 BUILT, BAKED, LIVE :3007** (head `studio1base1`, then
> extended by harness `studio2harness1`). ST6 (link-share public chat + audio/TTS) DEFERRED.
> Context harness (ST7 auto-born + ST8 self-improve) built on top — see `PLAN_STUDIOS_HARNESS.md`.


Branch `hybrid-brain`. Flag `HYBRID_STUDIOS` default OFF (HARD RULE 4). OFF = upstream-identical.

## Concept
**Studio** = NotebookLM-style container: pinned Data Agents (sources) + persona + grounded
chat + skills + per-studio brain memory + artifacts + members/roles/sharing.

**Additive, NOT a rename.** Existing Data Agent (`/agents`, AgentSelector, all tabs:
connection/context/tables/tools/queries/evals/monitoring/settings) stays UNTOUCHED and
working. Studio is a NEW parallel subsystem that *references* Data Agents as sources.

### Data Agent vs Studio
- **Data Agent** = a connection container (one/many DB+file connections). The ingredient.
- **Studio** = chef + kitchen: wraps many Data Agents + persona + skills + memory + members.

## Data model (ALL NEW tables — no change to `agent` table)
```
studio               id, name, description, persona/system_prompt, avatar,
                     owner_user_id, organization_id,
                     share_scope ('private'|'org'|'link'), share_token (nullable),
                     config (json: skills, memory scope, model pref),
                     created_at, updated_at, deleted_at
studio_data_sources  (studio_id, agent_id)        # pin existing Data Agents as sources
studio_members       (studio_id, user_id, role)   # owner|editor|viewer
studio_skills        (studio_id, skill_id)        # pinned skills
studio_artifacts     (studio_id, kind, content, created_at)  # summary|faq|briefing|note
Report.studio_id     nullable FK                  # a chat "inside" a studio
```
ONE migration off head `sk3skillfiles1` creates all of the above.

## Sharing / roles
| role | chat | add sources/skills | edit config | manage members/delete |
|---|---|---|---|---|
| viewer | yes | no | no | no |
| editor | yes | yes | yes | no |
| owner | yes | yes | yes | yes |

Scopes: `private` (members only) · `org` (every org member = viewer) · `link` (public
read-only token; gate + security review before enabling → ST6).
Thin `resolve_studio_access(studio_id, user) -> role|None` checked on every studio route.

## Phases
- **ST1** Studio model + studio_members + ONE migration + `resolve_studio_access` + CRUD
  routes (`/studios`, `/studios/{id}`, members) + flag + FE nav entry + list/create page.
- **ST2** pin Data Agents (`studio_data_sources`) + `Report.studio_id`; chat inside studio
  inherits pinned sources; retrieval scoped to them. FE workspace (sources rail + chat).
- **ST3** sharing UI (invite email, role, scope) + access enforce every route + tests.
- **ST4** artifacts: auto-summary on source-add (LLM over schemas), FAQ/suggested Qs,
  briefing, notes, SQL `FROM` citation chips.
- **ST5** scope skills + brain memory per studio (wire S1-S5 + 2nd-brain; `agent` skill
  scope). Per-studio learning = the NotebookLM differentiator.
- **ST6** (deferred) link-share public chat (security review) + audio overview (TTS infra).

## Left nav (additive)
```
🎬 Studios     NEW  /studios   (top of mainNavItems)
💬 Reports / 📊 Dashboards / ⏰ Scheduled / 🧊 Instructions / 📚 Queries / 🎓 Knowledge
─ MANAGE ─ Monitoring / Evals
─ bottom ─ 🤖 Data Agents (UNCHANGED /agents) / Settings
```

## Build = 2 waves (sub-agents)
- Wave 1 (blocking): foundation agent — ONE migration (all tables + Report.studio_id),
  models, schemas, flag `HYBRID_STUDIOS`. The contract.
- Wave 2 (parallel, against contract): CRUD+access · sources+chat · artifacts ·
  skills+memory · frontend. Different files, no collision (only Wave 1 writes migrations).

## Constraints
- Flag default OFF; reuse approval gate for learned per-studio memories.
- Single migration head (sk3skillfiles1) → only Wave-1 agent writes migrations.
- Do NOT touch `/agents`, AgentSelector, `agent` table, or the agent loop.
- Cheap tier reuses existing LLM+schema; audio (ST6) = new TTS infra, deferred.
