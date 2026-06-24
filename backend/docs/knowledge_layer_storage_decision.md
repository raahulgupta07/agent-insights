# Knowledge Layer Storage Decision

## Existing Models

### `MetadataResource` (`app/models/metadata_resource.py`)
Stores catalog artifacts imported via git-indexed metadata jobs (dbt models, dbt sources,
LookML models/views). Key characteristics:
- Keyed by `organization_id` + optional `data_source_id` + `metadata_indexing_job_id`.
- Holds `resource_type` (string tag), `sql_content` (raw SQL text), `raw_data` (arbitrary
  JSON blob from the extractor), and `columns` (JSON list of field defs).
- Lifecycle: created/updated by a MetadataIndexingJob; linked to an `Instruction` for
  context injection into the planner.
- Purpose: read-only catalog artifacts, versioned by sync job, not user-authored meaning.

### `DataSourceTable` (`app/models/datasource_table.py`)
Represents a table that has been activated within a DataSource (Domain). Key characteristics:
- Keyed by `datasource_id` + `connection_table_id`.
- Holds activation flag, domain-specific `metadata_json` override, legacy schema columns
  (nullable, being migrated to `ConnectionTable`), and graph/scoring metrics
  (`centrality_score`, `richness`, `degree_in/out`, `entity_like`).
- Purpose: per-domain table activation + lightweight domain overrides; schema truth lives
  in `ConnectionTable`.
- No free-text semantic descriptions or metric formulas.

## What the Knowledge Layer Needs

The planned `semantic_table`, `semantic_column`, and `metric_definition` records require:

| Concern | Need |
|---------|------|
| Granularity | Per-table AND per-column human/AI-authored semantic descriptions |
| Metric definitions | Named metric → verified SQL expression (not a schema artifact) |
| Lifecycle | User/admin authored, flag-gated, versioned by org — NOT tied to a sync job |
| Context injection | Injected into planner prompt when SEMANTIC_LAYER/METRICS_CATALOG flags are ON |
| Multi-tenancy | Scoped to `org_id` + `data_source_id` (matches Dash's existing pattern) |

## Recommendation: NEW tables

Create three new tables rather than extending existing models:

```
semantic_tables      (id, org_id, data_source_id, table_name, description, created_at, updated_at)
semantic_columns     (id, org_id, data_source_id, table_name, column_name, description, created_at, updated_at)
metric_definitions   (id, org_id, data_source_id, metric_name, display_name, sql_expression, description, created_at, updated_at)
```

### Why not reuse `MetadataResource`

1. **Wrong lifecycle.** MetadataResource is owned by a MetadataIndexingJob (automated sync).
   Semantic descriptions are user/admin-authored and must survive re-syncs without overwrite.
2. **Wrong schema shape.** MetadataResource has a single `resource_type` discriminator and
   stores everything in a `raw_data` JSON blob. Semantic records need typed, queryable columns
   (table_name, column_name) for efficient lookup during context building.
3. **Instruction coupling.** MetadataResource drives Dash's Instruction system; repurposing it
   would pollute the instruction approval flow with semantic catalog records.

### Why not reuse `DataSourceTable`

1. `DataSourceTable` is an activation record (is this table in use for this domain?), not a
   semantic annotation store. Embedding descriptions there mixes concerns.
2. There is no column-level analogue — `DataSourceTable.columns` is a legacy JSON blob, not
   a first-class ORM model, so `semantic_column` has no natural home there.
3. Metric definitions (named SQL expressions) have no relationship to the table activation
   model at all.

### Why new tables are the right call

- Additive — zero changes to existing models, zero rebase risk on the Dash core.
- Clean FK: `(org_id, data_source_id)` mirrors the rest of the platform; table/column names
  are plain strings matching what the planner already uses in prompts.
- Flag-gated: the tables exist but the context-builder only reads them when
  `HYBRID_SEMANTIC_LAYER` / `HYBRID_METRICS_CATALOG` are ON.
- Easy to extend (synonyms, verified-by-user flag, priority weight) without touching
  MetadataResource or DataSourceTable.

DDL scaffolded in migration `k1nowl2edge3`; columns to be added in Phase 1.
