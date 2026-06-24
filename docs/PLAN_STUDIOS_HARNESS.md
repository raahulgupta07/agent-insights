# PLAN — Studio Context Harness + Self-Improvement (ST7 + ST8)

> **STATUS 2026-06-19: BUILT, BAKED, e2e-verified, LIVE :3007** (image `4a618a2a`, head
> `studio2harness1`, dev `HYBRID_STUDIOS=1`, code default OFF). Built by sub-agents
> (1 foundation + 5 parallel). 2 bugs caught+fixed: JSON `bootstrap_state` not persisting
> (`flag_modified`) + not serialized (`_serialize` missing key). Auto-born avatar/voice/
> summary proven; CRUD+approve+improve+regenerate 200; assembler in `agent_v2`.
> GAPS (not blockers): on-source-pin auto-proposal not exercised end-to-end (needs a pinned
> Data Agent); FE tabs baked but not browser-driven. See CLAUDE.md 2026-06-19 STUDIOS for landmines.


Branch `hybrid-brain`. Flag `HYBRID_STUDIOS` (default OFF). Builds on ST1-ST5 (live).
Goal: kill the dead "persona" pattern. A Studio is **auto-born** with engineered context
(ST7) and then **learns from its own traffic** (ST8). Capture hooks baked from day one.

## Why
Research: standalone persona prompts give ~0 accuracy and can cost up to 30pts on
irrelevant detail (arxiv 2311.10054, 2603.18507). Accuracy comes from context engineering:
instructions + grounding + few-shot examples + memory (Anthropic/Karpathy 2025). This fork
already has the engines (brain: distiller, query-curator, answer-cache, starter-chips,
dynamic-schema) — ST7/ST8 just scope them per-studio and gate drafts behind review.

## Create modal = 3 fields only
name, description, sharing. Persona + avatar fields REMOVED from create (columns stay,
filled by machine). Everything else is auto-born inside the studio.

## Auto-born pipeline (ST7) — no user typing
```
ON CREATE (name+desc only):
   avatar   → pick emoji from name+desc                 → LIVE
   voice    → tone+reply-language draft                 → LIVE (editable; reuse `persona` col)
   summary0 → "what this studio is for"                 → LIVE
ON SOURCE PINNED (schemas now available):
   summary1 → regenerate over real schemas              → LIVE
   suggestedQs → starter questions                      → LIVE
   instructions → propose rules from schema             → PENDING (review)
   examples → mine query bank + generate Q→answer       → PENDING (review)
```
Bootstrap runs in a BACKGROUND task so create/pin stay fast.

## Self-improving loop (ST8) — learns from data
Capture is FREE: Report.studio_id already links chats→studio (ST2). Read existing
completion + feedback + query_bank rows filtered by the studio's reports. No capture table.
```
chat traffic (per studio)
  proven Q→SQL (uses>=N, no 👎)  → curator   → propose EXAMPLE   → PENDING
  recurring 👎 / repeated fail   → distiller → propose RULE      → PENDING
  popular questions              → bandit    → refresh suggestedQs → LIVE
  schema drift                   → adapt     → regrounding         → LIVE
  repeated identical Q           → answer-cache → serve cached     → AUTO
human approves pending → studio sharper → next chats use it
```

## Context assembler (the payoff)
ONE new builder injected when report.studio_id set (flag ON):
```
[voice/boundary] + [active instructions] + [pinned skills] + [active golden examples]
+ [grounded schemas of pinned sources]
```
Active = approved only. Pending never reaches the model.

## Guardrails
- rules + examples = ALWAYS pending → human approve (reuse existing review gate).
- avatar/voice/summary/suggestedQs/cache/grounding = auto (mechanical, safe).
- voice ≠ accuracy lever; kept thin and optional.
- flag OFF = byte-identical upstream; Data Agent untouched.

## Data model (ONE migration off head studio1base1 → rev studio2harness1)
```
studio_instructions  (studio_id, content, source 'auto'|'manual', status 'pending'|'active',
                      score, instruction_id nullable→reuse dash Instructions, created_at)
studio_examples      (studio_id, question, answer, sql nullable, source, status,
                      uses int default 0, score, created_at)
studios  +column     bootstrap_state JSON (tracks which auto-steps ran)
```
(persona col reused as "voice"; avatar col already exists; no capture table — reuse
completions/feedback/query_bank via Report.studio_id.)

## WAVES + SUB-TASKS

### Wave 1 — Foundation (blocking, 1 agent)
- F1: ONE migration `studio2harness1` (down=studio1base1): create studio_instructions,
  studio_examples + studios.bootstrap_state column. Models + schemas. Register models in
  alembic env. Verify single head. = the contract.

### Wave 2 — Parallel (5 agents, against contract)
- A (bootstrap/ST7): app/services/studio_bootstrap.py — LLM gen avatar/voice/summary
  (on-create) + suggestedQs/instructions/examples (on-source-pin). Wire BACKGROUND triggers
  into create (routes/studio.py) + pin (routes/studio_sources.py). Drafts: rules/examples→pending.
- B (instructions+examples API + review): app/routes/studio_instructions.py +
  app/routes/studio_examples.py — CRUD + /approve + /reject + /regenerate. OWNS main.py
  router registration (these two + studio_learning from D). 
- C (assembler/ST7): app/ai/context/builders/studio_context_builder.py — assemble
  voice+active-instructions+skills+active-examples+schema when report.studio_id; wire into
  context_hub. Flag-gated; no-op when studio_id None.
- D (self-improve/ST8): app/services/studio_learning.py + leader-gated daemon —
  curator→example, distiller→rule, bandit→suggestedQs, schema-adapt; all read
  completion/feedback/query_bank filtered by Report.studio_id; output→pending. Manual
  "improve now" route (registered by B). Reuse brain engines, scope per studio.
- E (frontend): slim create modal (name/desc/sharing only); Settings auto-fields
  (avatar/voice + ✨Regenerate); Instructions tab + Examples tab (list + Review/approve +
  pending badge); suggestedQs in chat empty-state; i18n. Only touches frontend/.

## Collision control
- Only Wave-1 writes a migration (single head).
- Only B edits main.py (registers studio_instructions, studio_examples, studio_learning routers).
- A owns edits to routes/studio.py + routes/studio_sources.py (triggers).
- C owns context_hub wiring + new builder.
- D owns brain-engine edits + new learning service.
- E owns frontend only.
- All back up edited files via scripts/backup.sh; py compile; container alembic head + import verify.
