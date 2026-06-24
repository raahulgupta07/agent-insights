// Merges the authored connector-doc content maps and exposes lookup helpers.
// ./databases and ./cloud are authored by other agents; import them regardless —
// they resolve once all content files exist.
import type { ConnectorDoc, ConnectorDocMap, FieldDoc } from './types'
import databases from './databases'
import cloud from './cloud'

export type { ConnectorDoc, ConnectorDocMap, FieldDoc } from './types'

export const CONNECTOR_DOCS: ConnectorDocMap = {
  ...databases,
  ...cloud,
}

/** Return the authored doc for a connector type, or null if none exists. */
export function getConnectorDoc(type: string): ConnectorDoc | null {
  if (!type) return null
  return CONNECTOR_DOCS[type] ?? null
}

/**
 * Synthesize a ConnectorDoc from the form's live field list when no authored
 * doc exists. Uses each field's `title` + `description` for `what`, and marks
 * required from the schema (field.required / required:true / not optional).
 */
export function buildGenericDoc(connectorType: string, fields: any[]): ConnectorDoc {
  const list = Array.isArray(fields) ? fields : []
  const docFields: Record<string, FieldDoc> = {}

  for (const f of list) {
    const name = String(f?.field_name ?? f?.name ?? '').trim()
    if (!name) continue
    const title = f?.title || name
    const desc = f?.description || ''
    const required = inferRequired(f)
    docFields[name] = {
      what: desc ? `${title} — ${desc}` : `Value for ${title}.`,
      example: f?.placeholder || (typeof f?.default === 'string' ? f.default : undefined) || undefined,
      required,
    }
  }

  const label = connectorType || 'this connector'
  return {
    overview:
      `Fill in the connection details for ${label}. We don't have a step-by-step guide for this ` +
      `connector yet, so the fields below are described from the form. Hover a field to highlight its note.`,
    fields: docFields,
  }
}

function inferRequired(f: any): boolean {
  if (typeof f?.required === 'boolean') return f.required
  if (f?.required === true) return true
  // JSON-schema style: explicitly optional when nullable / has a default empty
  if (f?.optional === true) return false
  // Default to required unless the title/description says optional
  const hay = `${f?.title || ''} ${f?.description || ''}`.toLowerCase()
  if (hay.includes('optional')) return false
  return true
}
