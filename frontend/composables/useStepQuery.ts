/**
 * Composable for server-side querying of large (Parquet-backed) step results.
 *
 * Mirrors the new backend contract:
 *   POST /api/steps/{step_id}/query
 *     body: { select?, filters?:[{col,op,val}], group_by?, aggs?:[{col,fn,as}],
 *             order_by?:[{col,dir}], limit?, offset? }
 *     resp: { rows:[...], columns:[{headerName,field}], total_rows:int,
 *             source:"parquet"|"inline", ms:int }
 *
 * Used only when a step reports `data.source === "parquet"` (rows NOT shipped to
 * the client). For normal inline steps the dashboard keeps its existing
 * client-side filtering and this composable is never called.
 *
 * Fail-soft: any error returns `null` so callers can gracefully fall back.
 */
import { useMyFetch } from '~/composables/useMyFetch'

export interface StepQueryFilter {
  col: string
  op: string
  val: any
}

export interface StepQueryAgg {
  col: string
  fn: string
  as?: string
}

export interface StepQueryOrderBy {
  col: string
  dir?: 'asc' | 'desc'
}

export interface StepQuerySpec {
  select?: string[]
  filters?: StepQueryFilter[]
  group_by?: string[]
  aggs?: StepQueryAgg[]
  order_by?: StepQueryOrderBy[]
  limit?: number
  offset?: number
}

export interface StepQueryResult {
  rows: any[]
  columns: Array<{ headerName: string; field: string }>
  total_rows: number
  source: 'parquet' | 'inline'
  ms: number
}

export function useStepQuery() {
  /**
   * POST a query spec to the server-side step query endpoint.
   * Returns the parsed result, or `null` on any error (fail-soft).
   */
  async function queryStep(
    stepId: string,
    spec: StepQuerySpec = {}
  ): Promise<StepQueryResult | null> {
    if (!stepId) return null
    try {
      const { data, error } = await useMyFetch<StepQueryResult>(
        `/api/steps/${stepId}/query`,
        {
          method: 'POST',
          body: spec,
        }
      )
      if (error.value) return null
      const res = data.value as StepQueryResult | null
      if (!res || !Array.isArray(res.rows)) return null
      return {
        rows: res.rows,
        columns: Array.isArray(res.columns) ? res.columns : [],
        total_rows: typeof res.total_rows === 'number' ? res.total_rows : res.rows.length,
        source: res.source || 'parquet',
        ms: typeof res.ms === 'number' ? res.ms : 0,
      }
    } catch {
      return null
    }
  }

  return { queryStep }
}
