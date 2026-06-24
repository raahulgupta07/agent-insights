# Research — Obsidian & Claude "second brain": data-type handling (design input)

Date: 2026-06-18 · Method: deep-research workflow (23 sources, 107 claims → 23 confirmed 3-0, 2 refuted).
Purpose: inform the Karpathy 2nd-Brain (Bands 6/8, Phases 4/5/8) of CityAgent Analytics.
Verdict: **our DB-backed model is the stronger base; steal Obsidian's data-type honesty + retrieval recipe, not its file-native storage.**

## How Obsidian works (primary: obsidian.md/help)
- **Vault = folder of plain markdown** on disk. Non-md (PDF/image/audio/video) = "attachments" = **regular filesystem files, NOT a DB**. Internal caches index metadata *about* files; files stay flat.
- `[[wikilinks]]` → navigable graph. YAML frontmatter + tags = first-class metadata.

## PKM philosophy (Matuschak, Appleton — primary)
Notes = cumulative unit: **atomic** (one self-contained idea), **concept-oriented** (by concept not folder/date), **densely linked** organic associations → networked not hierarchical. Zettelkasten/evergreen share atomicity + concept-orientation + linkage + serendipity.

## Claude ↔ Obsidian — TWO architectures
**(a) REST/CRUD bridge** (LLM treats markdown as live read/write KB):
- `MarkusPfundstein/mcp-obsidian` → Local REST API plugin `127.0.0.1:27124`, API-key. `patch_content` = surgical insert relative to **heading / block / frontmatter** (no whole-file rewrite). ⚠️ exact 7-tool list REFUTED (1-2) — don't trust the names.
- `cyanheads/obsidian-mcp-server` → **14 tools**. Note retrievable 4 ways: raw / full(content+frontmatter+tags+links) / document-map / single-section. 3 search modes: substring, JSONLogic over properties, BM25-Omnisearch (PDF+OCR). Frontmatter/tags atomically get/set/delete. (BM25 = lexical, not embeddings.)

**(b) RAG-over-vault** (chunk→embed→vector store):
- `robbiemu/vault-mcp` → LlamaIndex structure-aware parse → 2-stage chunk + quality filter → Sentence-Transformers → **ChromaDB** + Watchdog live-reindex. Agentic + static modes.
- `mthehang/obsidian-agentic-rag` → **hybrid**: ChromaDB cosine top-20 + BM25 top-20 → merge/dedup → **cross-encoder rerank** (mmarco-mMiniLMv2-L12-H384-v1) → 7 MCP tools (Claude picks which).

**Bridge skill** `NicholasSpisak/second-brain`: drop raw into `raw/` inbox → LLM synthesizes structured wiki pages + entities + concepts + index. ⚠️ its retrieval mechanism uncertain (wikilink-vs-vector claim REFUTED 1-2).

## ⚠️ DATA-TYPE handling (the core question)
| Data | Storage | Semantically indexed/retrieved? |
|---|---|---|
| Markdown | file | ✅ fully decomposable (raw / structured / map / section) |
| Frontmatter / tags | in-file YAML | ✅ atomically addressable |
| PDF / image / audio | file (attachment) | ❌ **stored but NOT semantically indexed** by most RAG MCP servers |

- **vault-mcp + agentic-rag = markdown-ONLY.** PDF/OCR explicitly out of scope. Marketplace listings **overstate** multi-format support (agentic-rag caught overstating).
- Non-text indexed ONLY with an extra layer: Omnisearch plugin (PDF+OCR) or a separate skill.

## Obsidian model vs our DB-backed agentic brain
- **Obsidian** = file-native, human-editable, LLM = CRUD/RAG client over flat files.
- **Ours** = centralized queryable DB: memories=Instructions(source_type='ai'), reasoning-cache=`query_cache`, entity graph=AGE, embeds=pgvector. Derived/cached/relational, approval-gated.

## Takeaways for our design
1. **DB-backed model is the right base** for analytics — markdown-RAG can't semantically index our structured/tabular data. We already have pgvector + AGE planned (Phase 8). Don't pivot to file-vault storage.
2. **Steal data-type honesty** — be explicit which modalities are *semantically indexed* vs *only referenced*. Don't overstate (same discipline as the PixelRAG rejection / reference_pixelrag_rejected).
3. **Steal progressive disclosure + atomic/concept-oriented** — maps to Skills L1/L2/L3 (Band 5) and memories-as-atomic-Instructions.
4. **Surgical-edit pattern** (`patch_content` heading/block/frontmatter) — model for how the agent writes back learned memories without clobbering. Consider for the DISTILLER write path (Phase 5).
5. **Hybrid retrieval recipe** (vector + BM25 + cross-encoder rerank) is the proven 2025-26 pattern. Our reasoning-cache recall currently = exact-hash + token-Jaccard; **cross-encoder rerank = future upgrade** for `recall_proven_queries` / BrainContextBuilder (Phase 4) and skill/qbank top-K (Band 5/6).

## Differentiator / open gap
No 2025-26 Obsidian setup solves **end-to-end non-text semantic ingest** well (image-caption / audio-transcribe / PDF-extract / CSV-parse) — markdown-RAG punts. Our connector + vision lane (cf. DocSensei vision-once + page-image answer) could close this — a real edge if folded into Band 7 ingest + Phase 8 unstructured→pgvector/AGE.

## Refuted (excluded)
- mcp-obsidian exact 7-tool enumeration (1-2) — REST-bridge + patch_content confirmed, tool names not.
- NicholasSpisak/second-brain "relies on wikilinks/graph not vector index" (1-2) — retrieval mechanism unknown; don't assume vector-free.

## Sources (primary)
obsidian.md/help/attachments · /file-formats · notes.andymatuschak.org/Evergreen_notes · maggieappleton.com/evergreens · github: MarkusPfundstein/mcp-obsidian · cyanheads/obsidian-mcp-server · robbiemu/vault-mcp · mthehang/obsidian-agentic-rag · NicholasSpisak/second-brain · arxiv.org/pdf/2504.19413 (agent memory survey).
