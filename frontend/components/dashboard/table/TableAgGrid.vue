<template>
  <div 
    class="h-full w-full"
    :style="{
      backgroundColor: tokens.cardBackground || tokens.background,
      color: tokens.textColor,
      fontFamily: tokens.fontFamily
    }"
  >
    <div
      v-if="columns.length"
      class="h-full ag-grid-themed ag-theme-custom"
      :style="agGridStyles"
    >
      <AgGridComponent 
        class="text-[9px] h-full" 
        :columnDefs="columns" 
        :rowData="rows" 
      />
    </div>
    <div 
      v-else 
      class="text-xs p-2"
      :style="{ color: tokens.textColor }"
    >
      Loading..
    </div>
  </div>
</template>

<script setup lang="ts">
import { toRefs, ref, watch, computed } from 'vue'
import { useDashboardTheme } from '../composables/useDashboardTheme'
import AgGridComponent from '../../AgGridComponent.vue'

const props = defineProps<{
  widget?: any
  step?: any
  view?: Record<string, any> | null
  reportThemeName?: string | null
  reportOverrides?: Record<string, any> | null
}>()

const { reportThemeName, reportOverrides } = toRefs(props)
const { tokens } = useDashboardTheme(reportThemeName?.value, reportOverrides?.value, props.view || null)

// Create AG Grid themed styles using CSS custom properties
const agGridStyles = computed(() => {
  // Extract primary color from palette (handle both string and gradient objects)
  const primaryColor = (() => {
    const palette = tokens.value.palette
    if (!palette || !palette[0]) return '#C2683F'
    
    const firstColor = palette[0]
    if (typeof firstColor === 'string') return firstColor
    if (typeof firstColor === 'object' && firstColor && 'colorStops' in firstColor) {
      return (firstColor as any).colorStops?.[0]?.color || '#C2683F'
    }
    return '#C2683F'
  })()

  return {
    '--ag-background-color': tokens.value.cardBackground || tokens.value.background,
    '--ag-foreground-color': tokens.value.textColor,
    '--ag-header-background-color': tokens.value.cardBackground || tokens.value.background,
    '--ag-header-foreground-color': tokens.value.textColor,
    '--ag-border-color': tokens.value.cardBorder || tokens.value.axis?.gridLineColor || '#e5e7eb',
    '--ag-row-hover-color': `${primaryColor}20`, // 20% opacity
    '--ag-selected-row-background-color': `${primaryColor}30`, // 30% opacity
    '--ag-odd-row-background-color': tokens.value.cardBackground || tokens.value.background,
    '--ag-even-row-background-color': tokens.value.cardBackground || tokens.value.background,
    '--ag-font-family': tokens.value.fontFamily,
    '--ag-font-size': '9px',
    fontFamily: tokens.value.fontFamily,
  }
})

const columns = ref<any[]>([])
const rows = ref<any[]>([])

// P3 data-bars: read rule off the widget view JSON (view.view.dataBars)
const dataBars = computed<any>(() => {
  const db = props.view?.view?.dataBars
  return db && typeof db === 'object' ? db : null
})

// Pick the data-bar target field + min/max across rows. Returns null when
// data-bars are disabled / no numeric column / no rows.
const resolveDataBarSpec = (cols: any[], rowsData: any[]) => {
  try {
    const db = dataBars.value
    if (!db || db.enabled !== true) return null
    if (!Array.isArray(cols) || !cols.length || !Array.isArray(rowsData) || !rowsData.length) return null

    const fields: string[] = cols.map((c: any) => c?.field).filter((f: any) => typeof f === 'string')
    const isNumericField = (field: string) =>
      rowsData.some((r: any) => {
        const v = r?.[field]
        return v != null && v !== '' && typeof v !== 'boolean' && !Number.isNaN(Number(v))
      })

    let target: string | null = null
    if (typeof db.column === 'string' && db.column) {
      const want = db.column.toLowerCase()
      target = fields.find((f) => f.toLowerCase() === want) || null
    }
    if (!target) target = fields.find((f) => isNumericField(f)) || null
    if (!target) return null

    let min = Infinity
    let max = -Infinity
    for (const r of rowsData) {
      const n = Number(r?.[target])
      if (r?.[target] == null || r?.[target] === '' || Number.isNaN(n)) continue
      if (n < min) min = n
      if (n > max) max = n
    }
    if (!Number.isFinite(min) || !Number.isFinite(max)) return null

    const color = typeof db.color === 'string' && db.color ? db.color : '#C2683F'
    return { field: target, min, max, color }
  } catch {
    return null
  }
}

const updateData = () => {
  try {
    const step = props.step || {}
    const data = step?.data || {}
    if (Array.isArray(data.columns)) {
      const rowsData = Array.isArray(data.rows) ? data.rows : []
      const barSpec = resolveDataBarSpec(data.columns, rowsData)
      columns.value = data.columns.map((col: any) => {
        const info = data?.info?.column_info?.[col.field]
        let statsText = ''
        if (info) {
          if (info.dtype === 'int64' || info.dtype === 'float64') {
            statsText = `${info.dtype}\nmin: ${info.min}\nmax: ${info.max}\nmean: ${Number(info.mean).toFixed(2)}`
          } else if (info.dtype === 'object') {
            statsText = `${info.dtype}\nunique: ${info.unique_count}/${info.count}`
          }
        }
        const colDef: any = {
          field: col.field,
          headerName: col.headerName,
          sortable: true,
          filter: true,
          headerTooltip: statsText,
          headerComponent: 'CustomHeader',
          headerComponentParams: {
            statsText,
            themeTokens: tokens.value
          },
          valueGetter: (params: any) => params.data[col.field]
        }
        // P3: paint an inline proportional bar background on the target column.
        if (barSpec && col.field === barSpec.field) {
          const { min, max, color } = barSpec
          colDef.cellStyle = (params: any) => {
            const n = Number(params?.value)
            if (params?.value == null || params?.value === '' || Number.isNaN(n)) return null
            const pct = max === min ? 100 : Math.max(0, Math.min(100, ((n - min) / (max - min)) * 100))
            return {
              backgroundImage: `linear-gradient(90deg, ${color}33 0%, ${color}33 ${pct}%, transparent ${pct}%, transparent 100%)`
            }
          }
        }
        return colDef
      })
    } else {
      columns.value = []
    }
    rows.value = Array.isArray(data.rows) ? data.rows : []
  } catch {
    columns.value = []
    rows.value = []
  }
}

watch(() => props.step, updateData, { deep: true, immediate: true })
// Re-build colDefs when the data-bars rule changes (no-op rebuild when absent).
watch(() => props.view?.view?.dataBars, updateData, { deep: true })
</script>

<style>
/* Custom AG Grid theme that overrides the default Balham theme */
.ag-theme-custom {
  /* Apply CSS custom properties to override AG Grid theme */
  --ag-cell-horizontal-padding: 8px;
  --ag-cell-vertical-padding: 4px;
  --ag-header-cell-hover-background-color: var(--ag-header-background-color);
  --ag-header-cell-moving-background-color: var(--ag-header-background-color);
  --ag-cell-focus-border-color: var(--ag-border-color);
  --ag-range-selection-border-color: var(--ag-border-color);
  --ag-input-focus-border-color: var(--ag-border-color);
}

.ag-theme-custom .ag-root-wrapper {
  border: 1px solid var(--ag-border-color) !important;
  border-radius: 6px !important;
  overflow: hidden !important;
  background-color: var(--ag-background-color) !important;
}

.ag-theme-custom .ag-header {
  background-color: var(--ag-header-background-color) !important;
  border-bottom: 1px solid var(--ag-border-color) !important;
}

.ag-theme-custom .ag-header-cell {
  background-color: var(--ag-header-background-color) !important;
  color: var(--ag-header-foreground-color) !important;
  font-family: var(--ag-font-family) !important;
  font-weight: 500 !important;
  border-right: 1px solid var(--ag-border-color) !important;
}

.ag-theme-custom .ag-header-cell-label {
  color: var(--ag-header-foreground-color) !important;
}

.ag-theme-custom .ag-row {
  background-color: var(--ag-background-color) !important;
  color: var(--ag-foreground-color) !important;
  font-family: var(--ag-font-family) !important;
  border-bottom: 1px solid var(--ag-border-color) !important;
}

.ag-theme-custom .ag-row:hover {
  background-color: var(--ag-row-hover-color) !important;
}

.ag-theme-custom .ag-row-selected {
  background-color: var(--ag-selected-row-background-color) !important;
}

.ag-theme-custom .ag-cell {
  border-right: 1px solid var(--ag-border-color) !important;
  font-family: var(--ag-font-family) !important;
  color: var(--ag-foreground-color) !important;
  background-color: transparent !important;
}

.ag-theme-custom .ag-paging-panel {
  background-color: var(--ag-background-color) !important;
  color: var(--ag-foreground-color) !important;
  border-top: 1px solid var(--ag-border-color) !important;
}

.ag-theme-custom .ag-paging-button {
  color: var(--ag-foreground-color) !important;
  background-color: transparent !important;
  border: 1px solid var(--ag-border-color) !important;
}

.ag-theme-custom .ag-paging-button:not(.ag-disabled):hover {
  background-color: var(--ag-row-hover-color) !important;
}

.ag-theme-custom .ag-paging-description {
  color: var(--ag-foreground-color) !important;
}

.ag-theme-custom .ag-paging-page-summary-panel {
  color: var(--ag-foreground-color) !important;
}

/* Additional overrides for input elements */
.ag-theme-custom .ag-input-field-input {
  background-color: var(--ag-background-color) !important;
  color: var(--ag-foreground-color) !important;
  border: 1px solid var(--ag-border-color) !important;
}

.ag-theme-custom .ag-picker-field-wrapper {
  background-color: var(--ag-background-color) !important;
  color: var(--ag-foreground-color) !important;
  border: 1px solid var(--ag-border-color) !important;
}
</style>


