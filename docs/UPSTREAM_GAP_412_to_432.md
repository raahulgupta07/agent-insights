# Upstream Gap — bagofwords 0.0.412 → 0.0.432 (CODE-VERIFIED, item by item)

> Fork base = **VERSION 0.0.412** (VERSION_HYBRID 1.90.0). Upstream latest = **0.0.432** (2026-07-03).
> Upstream clone: `~/Downloads/bagofwords-upstream`.
> Every row below verified by grepping BOTH repos (symbol found in upstream first, then checked in fork) — not word-matches, not the release notes alone.
> Legend: **HAVE** = fork equal/better · **PARTIAL** = fork has a variant, gap noted · **MISS** = absent.

---

## Release 417 (Jun 21)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| #425 | Infor OLAP (XMLA/MDX SOAP) connector | **MISS** | no `infor_olap_client`/`xmla_base` | port `xmla_base.py`+`infor_olap_client.py`+registry entry — only if a client runs Infor OLAP 25.x |
| — | Fabric cold-start login timeout | **PARTIAL** | `ms_fabric_client.py` HAS `_connect_with_retry` (6 tries, HYT00/08S01/timeout) but `Connection Timeout=30`, no `ConnectRetryCount` | bump 30→**60s**, add `ConnectRetryCount=4`, add `HYT01`. Small edit, real reliability win |
| — | Tables selector sticky Save | **PARTIAL** | `TablesSelector.vue:519` Save is `mt-3`, not sticky | add `sticky bottom-0 z-10 border-t bg-white py-2` |
| — | Agents connections footer viewport-size | **HAVE** | `ReportAgentPanel.vue:391` `max-height:calc(100vh-280px)` | — |
| — | edit_instruction tool-card flicker (key on block id) | **HAVE** | `reports/[id]/index.vue:349` `:key="block.id"` | — |

## Release 423 (Jun 25)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| #440 | **Cost console** (/monitoring spend by user/agent/model) | **PARTIAL** | Cost tab EXISTS (`pages/monitoring/cost.vue` + `console_service.get_llm_cost_console`) BUT `llm_usage_record.py` has NO `organization_id/user_id/report_id/data_source_id` attribution cols | port mig `b1c2d3e4f5a6` (4 cols + indexes) + populate at record time in `llm_usage_recorder`. Then cost tab reads indexed, not joins |
| #441 | Follow-up suggestion chips | **PARTIAL** | fork has OWN via `HYBRID_FOLLOWUPS` (`ai/knowledge/followups.py`, `routes/followups.py`) — parity present | no `follow_ups` completion column / `enable_follow_ups` org-setting. Port only if you want persisted shape |
| #442 | Report avatar org-brand + per-model provider logo | **MISS** | `reports/[id]/index.vue:324` generic `logo-128.png` only | port brand-image+provider-badge block (claude→anthropic) |

## Release 424 (Jun 25)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| #446 | Single-value card over melted KPI (`derive_kpi_row_filter`) | **PARTIAL** | `defaultFilters` IS carried through `create_data.py`; missing `derive_kpi_row_filter` row-narrowing | port `derive_kpi_row_filter` |
| #447 | Monitoring origin-platform badge | **PARTIAL** | `external_platform` col EXISTS on `completion.py:87` but NOT in `agent_execution_trace_schema.py` | add field to trace schema + badge in diagnosis/trace |

## Release 426 (Jun 27)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| — | Prompts (save/reuse, run-for-users) | **PARTIAL** | basic CRUD+scheduling (`models/prompt.py`, `prompt_service`, mig `6ca8f6939a3d`) | missing rich model (`scope/mode/is_starter/parameters/mentions/data_sources`), `prompt_run` (run-for-users), agent tools, FE library |
| — | **Notifications in-app inbox** | **MISS** | fork `notification_service` = email/Slack DELIVERY only; no inbox model/route/FE | port `models/notification.py`+`routes/notification.py`+mig `notif0001`+`useNotifications.ts`+`NotificationModal.vue` |
| — | Main nav redesign | **MISS/divergent** | fork nav fully rewritten (`useAppNav.ts`/`AppRail.vue`) | not portable 1:1; skip |

## Release 427 (Jun 28)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| #479 | Reports sidebar sort by last activity | **MISS** | orders by `created_at` (`report_service.py:1289`); no `last_activity_at` col | add col+index, bump on message + turn-finalize, change order_by |
| #474 | Run scheduled prompt on demand | **PARTIAL** | endpoint exists (`scheduled_prompt.py:115`) but no `force=True`, runs inline, no audit | add `force=True` (bypass claim+paused), bg task, existence pre-check, audit |
| #478 | Global Evals node in tree | **MISS** | none | FE-only port of `KnowledgeExplorer.vue` global-evals filter |
| #466 | Audit coverage ~75 endpoints | **PARTIAL** | full audit infra + ~100 call-sites vs **182** upstream | add `audit_service.log` to prompt/rbac/webhook/oauth/scheduled_prompt/instruction/llm/connection routes |
| #475 | Report title never set (Postgres) | **PARTIAL** | fork STILL background `asyncio.create_task` (`agent_v2.py:4144`) — the exact pre-fix bug | move title gen inline + self-heal on empty + `report:updated` FE event |
| #477 | Notification inbox order fix | **MISS/N-A** | no in-app inbox | N/A unless inbox ported |
| #476 | Slow /agents instr N+1 | **N/A** | fork uses different per-instruction design; function absent | no direct port |
| #473 | TraceModal scrollbar clip | **PARTIAL** | `console/TraceModal.vue` present, UCard padding fix unconfirmed | diff+port `:ui` body-padding removal |
| #468 | OpenShift: stdout-only logs + asyncpg ssl | **MISS** | `logging_config.py:72` still `RotatingFileHandler`; `database.py:155` returns `{}` not `{"ssl":False}` on unset ssl_mode | remove file handler; return `{"ssl":False}` |

## Release 428 (Jun 29)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| #497 | File references + MCP file materialization | **MISS** | fork `execute_mcp` does inline CSV/JSON only; no `FileReference` rows | port model/route/service + migs `filesrc01`+`fileref01` + Graph-mail path |
| #494 | /agents tree lazy-load (counts + search) | **MISS** | no `/instructions/counts`, `/knowledge/search`, `global_only` | port 3 endpoints |
| #495 | Prompt tools in Training mode | **MISS** | `routes/prompt.py:create_prompt` is REST, NOT a planner tool | port `create/edit/search_prompt` tool schemas, `allowed_modes=["training"]` |
| #493 | **Service accounts** (API principals) | **MISS** | none (FE hits = BigQuery JSON, unrelated) | port `models/service_account.py`, `is_service_account`, `manage_service_accounts`, mig `c2d3e4f5a6b7`, Settings→Members tab |
| #489 | **Agent-manager RBAC tier** + per-connection grants | **PARTIAL** | registry lists `manage` + loads ResourceGrants, but NO `RESOURCE_PERM_IMPLIES` cascade and NO `connection` resource type | port `RESOURCE_PERM_IMPLIES`+`_grant_implies` cascade + `connection` block |
| #489/#494 | Agent admins auto-publish own instructions | **MISS** | fork auto-approves only for org-admin (`instruction_service.py:2656`); no `_can_auto_publish_build` | port DS-scoped auto-publish (needs #489 cascade) |
| #487 | External MCP tool gateway | **PARTIAL** | fork has INTERNAL `execute_mcp` tool; no `ConnectionToolGateway`/`list_agent_tools` on `/api/mcp` | port gateway service + external MCP tools |
| #486 | Gate low-confidence notifications | **MISS** | `low_confidence` used only as query filter | port 5×<3/5-in-7-days window gate |
| #485 | Release DB conn before serialization | **PARTIAL** | fork has agent-loop variant `_release_db_between_steps`; no per-route `release_request_db` | add `release_request_db` to hot read handlers |
| #467 | Connectors without agents (Notion DCR) | **MISS** | fork has connector-AS-agent instead; no `is_connector`/`connector_key` | port standalone provider + Notion DCR OAuth |
| #488 | Quota monthly USD cap | **MISS** | no `usage_policy` model / `llm_cost_micro_usd` | port `monthly_spend_limit_usd` + micro-USD counter + enforcement |
| #492 | Localize Cost tab (i18n) | **MISS** | no `tabCost`/`cost.*` keys | low pri, follows #440 |
| #491 | Custom API headers `[object Object]` fix | **HAVE** | `ConnectForm.vue:29` keyvalue editor present (fork ahead) | — |

## Release 429 (Jul 2)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| #513 | **Faster page nav** (batched whoami RBAC, N+1 kills, indexes, 1 DB conn/req) | **MISS** | `release_request_db` = 0 hits | port helper + batched whoami RBAC + monitoring/reports N+1 fixes + hot-path indexes |

## Release 430 (Jul 2)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| — | Faster instruction loading | **MISS** | (follows #476/#494, fork base 412) | port bulk-query + lazy counts |
| — | Instructions view: reportagent vs knowledge | **MISS** | depends on Knowledge Explorer (415+) | port two render contexts |
| — | Prompt week-day start | **MISS** | no `weekStart` | add setting + cron interp + i18n |

## Release 431 (Jul 3)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| #522 | CSV data source connector | **PARTIAL** | fork `spreadsheet` = upload→DuckDB; upstream `csv` = path/glob+SQL | port dedicated `CSVClient` only if path-based CSV wanted |
| #523 | Claude Sonnet 5 / Opus 4.8 | **HAVE** | OpenRouter passthrough, any model_id; Opus 4.8 already seeded | add `anthropic/claude-sonnet-5` seed line (no code) |
| #524 | Enforce prompt write policy at route | **MISS** | `routes/prompt.py` guarded only by `current_user`, no `@requires_permission` | add permission decorator to create/update/delete_prompt |
| #521 | Localized, direction-aware follow-ups | **PARTIAL** | fork followups not localized/RTL | port i18n + `dir="auto"` layer |
| #520 | Single-value card wrong cell | **MISS** | `derive_kpi_row_filter`=0 hits (dup of #446) | port `derive_kpi_row_filter` |

## Release 432 (Jul 3)
| # | Item | Verdict | Fork state | Port |
|---|---|---|---|---|
| #531 | Large-data report/artifact slowness | **MISS** | fork has parquet offload (different mitigation) | port the specific report/artifact-page fix |
| #527 | PDF export missing numbers/empty charts | **MISS** | fork has dashboard-PDF email but not this fix | port data-hydration into PDF render |
| #528 | Pending-changes badge over-count | **MISS** | pending-view absent (415+) | follows pending-view port |
| #530 | Training-mode verification plan | **MISS** | docs/tests only | low value |
| #529 | **RBAC↔legacy divergence + sso_only lockout + `rbacbf01`** | **PARTIAL** | sso_only break-glass already in `auth.py:82`; but `rbacbf01` backfill + reconciliation MISSING | port `rbacbf01` backfill — **directly fixes the fork's own "wipe destroyed seeded system roles" bug** |

## Not in the paste but critical
| Rel | Item | Verdict | Note |
|---|---|---|---|
| #416 | **Security dep bumps** | **MISS** | fork on old starlette/cryptography/fastapi/nuxt/vite → live SSRF/smuggling/OOB CVEs. Bump pins (fork uses pip). **Do first.** |

---

## Tally
- **HAVE (3):** #491 custom-API-headers · #523 Claude5/Opus (via OpenRouter) · footer-viewport + flicker-key (417)
- **PARTIAL (14):** Cost console · follow-ups · melted-KPI · origin-platform · Prompts · run-scheduled-now · audit coverage · report-title · TraceModal · agent-manager RBAC · external-MCP · release-db-conn · CSV · localized-followups · Fabric-timeout · sticky-Save · rbacbf01
- **MISS (~22):** Infor OLAP · avatar branding · Notifications inbox · sidebar sort · global evals · OpenShift · file refs · tree lazy-load · prompt-training-tools · service accounts · auto-publish · low-conf gate · connectors-w/o-agents · quota USD · localize-cost · faster-nav · faster-instr · reportagent-view · week-start · prompt-write-policy · derive_kpi · large-data · PDF-export · pending-badge · training-plan · **security bumps**

## Recommended build order
1. **#416 security dep bumps** — CVE exposure, do first, bake.
2. **#529 `rbacbf01`** — self-contained, fixes the fork's known RBAC-wipe bug.
3. **#513/#485 `release_request_db` + N+1** — cheap high-impact perf.
4. **#440 cost attribution cols** — finishes the already-built Cost tab.
5. **#520/#446 `derive_kpi_row_filter`** — small correctness fix, KPI cards.
6. **Fabric 60s timeout + #524 prompt-policy + #475 inline title** — small, real.
7. Bigger subsystems as needed: service accounts, agent-manager RBAC cascade, Notifications inbox, file refs.
