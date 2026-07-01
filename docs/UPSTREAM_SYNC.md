# Upstream Sync — porting bagofwords releases into our fork

Our fork (`raahulgupta07/rahulai-dash`) has **no shared git ancestry** with upstream
(`bagofwords1/bagofwords`) — `git merge-base HEAD v0.0.428` is empty. So we **cannot cherry-pick
commits or merge**. Porting is **patch/file-level**, feature-by-feature, behind hybrid flags.

Upstream versions `v0.0.4xx` (latest v0.0.428). Our version = `VERSION_HYBRID` (1.63.0), independent.

## Golden rules
- Never `git merge upstream` — clobbers the hybrid layer + bow→dash rename.
- Every ported feature = flag-gated `HYBRID_*`, default OFF, prove ON + inert OFF.
- Keep the rename: upstream `bow_`/`bagofwords` → our `dash`; DO keep bow_ token prefixes + X-BOW headers.
- Bake = docker-commit (our existing flow). Bump VERSION_HYBRID + CHANGELOG_HYBRID.

## One-time setup (done 2026-07-01)
```
git remote add upstream https://github.com/bagofwords1/bagofwords.git
git fetch upstream --tags
```

## The loop — per release
```
1 WATCH   — new tag drops (check monthly)
2 DIFF    — see exactly what that release changed (adjacent-tag diff)
3 TRIAGE  — each feature → WANT / SKIP / HAVE-ALREADY / CONFLICTS
4 PORT    — copy new files; re-implement conflicting edits behind a HYBRID_* flag
5 TEST    — flag ON prove, flag OFF unchanged
6 BAKE    — docker-commit + version bump
```

### 2 — DIFF commands (ancestry-free, always work)
```bash
# what a single release changed (the triage unit):
git diff --stat  v0.0.427 v0.0.428
git diff         v0.0.427 v0.0.428 -- backend/app/services   # a feature area

# a specific upstream file's current version, to compare with ours:
git show v0.0.428:backend/app/ai/agent_v2.py > /tmp/upstream_agent_v2.py
git diff --no-index backend/app/ai/agent_v2.py /tmp/upstream_agent_v2.py

# list NEW files a release added (pure adds = easiest to port, low conflict):
git diff --stat --diff-filter=A v0.0.427 v0.0.428
```

### 3 — TRIAGE buckets
| Bucket | Action |
|---|---|
| **New standalone files** (new service/route/component, `--diff-filter=A`) | copy in, wire, flag-gate. Low risk. |
| **HAVE-ALREADY** (we built our own: follow-ups, skills, notifications, self-learning) | skip or compare for ideas |
| **CONFLICTS** (edits to files we heavily changed: agent_v2, prompt boxes, hybrid_flags) | re-implement by hand behind a flag; never overwrite |
| **SKIP** (locales, upstream sandbox-notes `.md`, icons we don't need) | ignore |
| **Security/infra** (uv migration, vuln fixes v0.0.416) | evaluate separately, high value |

### 4 — PORT patterns
- Pure-add feature → `git checkout upstream/<tag> -- path/to/newfile` then adapt names (bow→dash).
- Conflicting edit → read upstream hunk, write our own version guarded by `if flags.HYBRID_X:`.
- New migration → re-author as our own idempotent alembic rev (don't import upstream's chain).

## Helper
`scripts/upstream_triage.sh <fromTag> <toTag>` → prints grouped changed-files (backend/frontend/
migrations/new-files) so triage is one glance. See script.

## Recent releases — headline features (triage backlog)
| Ver | Feature | Likely status in our fork |
|---|---|---|
| v0.0.428 | prompts in training mode · service accounts (API) · agent-manager RBAC · MCP materialization | TRIAGE |
| v0.0.427 | run scheduled prompts on demand · global evals in agent tree · audit coverage | TRIAGE (we have scheduled reports) |
| v0.0.426 | **Prompts** (save/reuse) · **Notifications** · nav redesign | Notifications: HAVE (bell); Prompts: TRIAGE |
| v0.0.423 | **Cost console** (LLM spend by user/agent) · follow-up suggestions · report avatar | follow-ups: HAVE; cost console: WANT |
| v0.0.417 | Infor OLAP connector | SKIP unless needed |
| v0.0.416 | **uv migration** · security vuln fixes | WANT (infra) |
| v0.0.415 | **Knowledge Explorer** · agent mgmt wizard · **continual self-learning** · skills smart-loading | skills: HAVE; others: TRIAGE |

Confirm each by diffing before porting — the table is a starting guess, not verified.
