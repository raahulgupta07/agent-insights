// Shared type contract for connector "how to get each value" documentation.
// Content maps (./databases, ./cloud) are authored against these types.

export type FieldDoc = {
  what: string
  where?: string
  steps?: string[]
  example?: string
  gotcha?: string
  required?: boolean
}

export type ConnectorDoc = {
  overview: string
  prerequisites?: string[]
  fields: Record<string, FieldDoc>
  troubleshooting?: string[]
  docsUrl?: string
}

// Keyed by connector type, e.g. 'ms_fabric', 'postgresql'
export type ConnectorDocMap = Record<string, ConnectorDoc>
