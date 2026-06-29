# Smart Upload Router

> Drop ANY file → it's classified and routed to the right knowledge home, at the
> highest confidence we can, asking you to confirm only the uncertain or
> answer-changing ones. Flag `HYBRID_SMART_UPLOAD` (default **OFF**).

## Why
Uploading was fragmented: data went to Sources, glossaries to Semantic, rules to
Teach/Instructions, docs to Knowledge — the user had to know which door. One drop
zone removes that. Same idea as **Teach** (classify pasted text → homes), but for
**files**.

## The 6 destinations (sinks — all reused, none rewritten)
| dest | home | sink (existing) |
|---|---|---|
| `database` | data source the agent queries | `data_source_from_file.create_data_source_from_file` |
| `semantic` | column meanings | `doc_extractor.extract_proposal` → `DataSourceTable.columns` |
| `instructions` | always-on rules | `teach.classify` → `teach.apply_spans` (pending) |
| `examples` | Q→answer→SQL few-shot | `teach.apply_spans` (pending) |
| `knowledge` | RAG reference | `docs_index.ingest_doc` (pending) |
| `skip` | unsupported/empty | no-op |

## Flow
```
upload (/api/files)  →  classify  →  [you confirm flagged rows]  →  apply  →  (train)
```
- **Classify** `POST /api/studios/{id}/smart-upload/classify {file_ids, data_source_id?}`
  → `{items:[RouteRecord], summary:{auto, needs_confirm, total}}`
- **Apply** `POST /api/studios/{id}/smart-upload/apply {items, data_source_id?, train?}`
  → per-item dispatch to the sink, each fail-soft.

## Classification (highest accuracy, cheap)
1. **Heuristic** (`classifier.sniff_file`) — ext + content shape (rows/cols, 2-col
   glossary, rule patterns `=`/`AND`/`must`/`filter`, Q&A `Q:`/`A:`, narrative).
2. **Small-LLM tie-break** (`classifier.llm_route`) — ONE batched cheap-model call,
   only on `<85%` or conflicting signals. Ensemble: agree→auto, disagree→confirm.
   Fail-soft (LLM down → heuristic).

## Confirm policy (`_needs_confirm`)
Ask the user only when: confidence `<85`, OR classifiers disagreed, OR the dest is
answer-changing (`semantic|instructions|examples|metrics`) and confidence `<95`.
Otherwise auto-route. Answer-changing writes land **pending** (Review gate).

## UI
Sources tab → `✦ Smart Upload` (flag-gated) → `SmartUploadModal.vue`
(`<UploadSmartUploadModal>`): drop zone, per-file `detected → [dest ▾] · confidence
· reason · skip`, "N auto · M need-a-look" banner, Auto-train toggle, Apply.
Flag OFF → button hidden, page identical.

## Files
- `services/smart_upload/{contract,classifier,apply}.py`, `routes/smart_upload.py`
- `main.py` (+2 lines: import + include), `settings/hybrid_flags.py` (+flag 3-place)
- `frontend/components/upload/SmartUploadModal.vue`, `pages/studios/[id]/index.vue` (+~36 additive)
- Backups of the 3 edited files: `backups/smart-upload/*.bak`

## Verified
Compile-clean (py + Vue). Classifier proven on real files: MM Conso csv→database(90,
auto), Definitions.xlsx→semantic(72, confirm), CRM Logic.docx→examples(82, confirm).
Live apply E2E deferred to a clean deploy (avoid regressing live hot-patches on the
shared dev container).

## Notes / follow-ups
- Semantic path writes column descriptions (schema metadata, not approval-gated) via
  the canonical `studio_autoconfigure` path; swap to a pending `SemanticColumn` path
  if you want it gated.
- The Logic doc is both rules + Q&A; heuristic picks one (examples) and flags confirm.
  The LLM tie-break (live) splits it better; could also route one file to multiple sinks.
- Persistent warehouse still pending for the `database` path (spreadsheets = in-memory DuckDB).
