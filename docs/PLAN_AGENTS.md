# PLAN — NotebookLM-style Agents + Sharing

Branch `hybrid-brain`. Goal: turn the platform into shareable, source-grounded
**Agents** (≈ NotebookLM notebooks): a named container with pinned data sources,
grounded chat, generated artifacts, per-agent learning, and **members/roles**.
New flag-gated subsystem `HYBRID_AGENTS`, default OFF (HARD RULE 4). Reuse Report
as the chat thread (add `agent_id`); do NOT rewrite the agent loop (HARD RULE 3).

## Concept map (NotebookLM → this repo)
| NotebookLM | repo primitive | gap |
|---|---|---|
| Notebook (container) | `Report` (per-thread only) | **new `Agent` entity** |
| Sources | `DataSource` (46 connectors) + files | pin to agent (M2M) |
| Grounded chat | AgentV2 loop + Knowledge Layer + RAG | scope retrieval to pinned sources |
| Citations | SQL `FROM` tables in blocks | surface as source chips |
| Auto-summary / guide | — | generate on source-add |
| FAQ / suggested Qs | suggestions pattern | per-agent generation |
| Briefing / study guide | report/artifact engine | one artifact |
| Audio overview (podcast) | **none** (OpenRouter = no TTS) | needs TTS provider (defer) |
| Learning/memory | **Karpathy 2nd-brain + Skills (built)** | scope to `agent_id` = differentiator |
| Share w/ members | org membership + permissions | **new `agent_members` + roles** |

~80% exists. The two genuinely new things: **Agent entity** + **membership/sharing**.

## Data model (new, flag-gated)
```
Agent: id, name, description, avatar, persona/system_prompt,
       owner_user_id, organization_id,
       share_scope ('private'|'org'|'link'), share_token (nullable),
       config (json: enabled skills, knowledge scope, model pref),
       created/updated, deleted_at
agent_data_sources  (agent_id, data_source_id)     # pinned sources
agent_skills        (agent_id, skill_id)           # optional pin skills to agent
agent_members       (agent_id, user_id, role)      # owner|editor|viewer
agent_artifacts     (agent_id, kind, content, ...) # summary|faq|briefing|note
```
Chat reuse: add nullable `Report.agent_id` FK. A chat "inside" an agent = a Report
with `agent_id`; pinned sources auto-populate `Report.data_sources`. No loop rewrite.

## Sharing / members
Roles (`agent_members.role`):
| role | chat | add sources/skills/instr | edit config | manage members/delete |
|---|---|---|---|---|
| viewer | yes | no | no | no |
| editor | yes | yes | yes | no |
| owner | yes | yes | yes | yes |

Share scopes (`agent.share_scope`):
- `private` — only listed members.
- `org` — every org member auto-viewer.
- `link` — public read-only token URL (gate behind setting; **security review** before enabling).

Reuse dash org membership + permission resolver. Add thin
`resolve_agent_access(agent_id, user) -> effective role`
(owner > explicit member > org-viewer if scope=org > link). Every agent route checks it.
Do NOT build a new global gate (HARD RULE 5 spirit).

## Phases (each self-gates on flags.AGENTS; OFF = upstream-identical)
- **N1** Agent model + `agent_members` + migration (off current head); `resolve_agent_access`;
  CRUD routes (`/agents`, `/agents/{id}`, members). FE: agent list + create. Tests.
- **N2** Pin sources (`agent_data_sources`) + `Report.agent_id`; chats inside agent
  inherit pinned sources; retrieval scoped to them. FE: agent workspace (sources rail + chat).
- **N3** Sharing UI (invite by email, role, scope) + access enforcement on every route + tests.
- **N4** Artifacts: auto-summary on source-add (LLM over `get_schemas()`), suggested Qs/FAQ,
  briefing/study-guide, saved notes (`agent_artifacts kind=note`), source citation chips.
- **N5** Scope **skills + brain memories** to `agent_id` (wire S1-S5 + 2nd-brain per agent;
  add `agent` skill scope). Each agent learns its own domain — the NotebookLM differentiator.
- **N6** (optional) link-share public chat (security review); audio overview (add TTS
  integration — ElevenLabs/OpenAI-TTS, separate gated provider; highest effort/lowest analytics value → defer).

## Open decisions (user)
1. Agent = **new entity** (recommended) vs extend Report.
2. Feature depth: N1-N4 (shareable grounded agent) only, + N5 (per-agent learning), + N6 (audio)?
3. Link-share public chat: yes (needs security review) or members-only.

## Constraints
- Flag `HYBRID_AGENTS` default OFF; reuse approval gate for learned per-agent memories.
- Cost tiers: Tier-cheap (summary/FAQ/briefing/notes/citations reuse existing LLM+schema);
  Tier-expensive (audio overview = new TTS infra, defer).
