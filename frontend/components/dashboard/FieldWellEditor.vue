<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[80] flex items-center justify-center">
      <!-- backdrop -->
      <div class="absolute inset-0 bg-black/30" @click="$emit('close')" />
      <!-- panel -->
      <div class="relative w-[440px] max-w-[92vw] max-h-[85vh] overflow-y-auto bg-white border border-[#E9E0D3] rounded-2xl shadow-lg">
        <div class="flex items-center justify-between px-4 py-3 border-b border-[#E9E0D3]">
          <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif;">Build chart — fields</h3>
          <button class="text-[#9a958c] hover:text-[#1f2328] cursor-pointer" @click="$emit('close')">
            <Icon name="heroicons:x-mark" class="w-4 h-4" />
          </button>
        </div>

        <div class="px-4 py-3 space-y-4">
          <template v-if="kind === 'chart'">
            <!-- Chart type -->
            <div>
              <span class="text-xs font-semibold text-[#6b6b6b] uppercase tracking-wide">Chart type</span>
              <div class="mt-2 flex flex-wrap gap-1.5">
                <button
                  v-for="ct in CHART_TYPES"
                  :key="ct.value"
                  class="text-xs px-2.5 py-1.5 rounded-lg border transition-colors cursor-pointer flex items-center gap-1"
                  :class="chartType === ct.value
                    ? 'border-[#C2541E] bg-[#F4E5DA] text-[#C2541E] font-semibold'
                    : 'border-[#E9E0D3] text-[#6b6b6b] hover:bg-[#F4EEE5]'"
                  @click="chartType = ct.value"
                >
                  <Icon :name="ct.icon" class="w-3.5 h-3.5" />{{ ct.label }}
                </button>
              </div>
            </div>

            <!-- X / category -->
            <div class="flex items-center gap-2">
              <span class="text-xs text-[#6b6b6b] w-24">Category (X)</span>
              <select v-model="xField" class="flex-1 text-xs border border-[#E9E0D3] rounded-md px-1.5 py-1.5 bg-white">
                <option value="">— auto —</option>
                <option v-for="c in columns" :key="'x'+c" :value="c">{{ c }}</option>
              </select>
            </div>

            <!-- Measure (Y) -->
            <div class="flex items-center gap-2">
              <span class="text-xs text-[#6b6b6b] w-24">Measure (Y)</span>
              <select v-model="yField" class="flex-1 text-xs border border-[#E9E0D3] rounded-md px-1.5 py-1.5 bg-white">
                <option value="">— auto —</option>
                <option v-for="c in columns" :key="'y'+c" :value="c">{{ c }}</option>
              </select>
            </div>

            <!-- Aggregation -->
            <div class="flex items-center gap-2">
              <span class="text-xs text-[#6b6b6b] w-24">Aggregation</span>
              <select v-model="aggregation" class="flex-1 text-xs border border-[#E9E0D3] rounded-md px-1.5 py-1.5 bg-white">
                <option v-for="a in AGGS" :key="a.value" :value="a.value">{{ a.label }}</option>
              </select>
            </div>

            <!-- Group / series (not for pie) -->
            <div v-if="chartType !== 'pie_chart'" class="flex items-center gap-2">
              <span class="text-xs text-[#6b6b6b] w-24">Split by (series)</span>
              <select v-model="groupByField" class="flex-1 text-xs border border-[#E9E0D3] rounded-md px-1.5 py-1.5 bg-white">
                <option value="">— none —</option>
                <option v-for="c in columns" :key="'g'+c" :value="c">{{ c }}</option>
              </select>
            </div>

            <p class="text-[11px] text-[#9a958c] italic">Pick fields to re-shape this chart. Leave a field on “auto” to keep the agent's original choice.</p>
          </template>

          <p v-else class="text-xs text-[#9a958c] italic">Field builder is available for bar / line / area / pie / scatter charts.</p>
        </div>

        <div class="flex items-center justify-between gap-2 px-4 py-3 border-t border-[#E9E0D3]">
          <button
            v-if="kind === 'chart'"
            class="text-[11px] font-medium text-[#9a958c] hover:text-[#6b6b6b] cursor-pointer"
            @click="resetFields"
          >Reset to auto</button>
          <span v-else />
          <div class="flex items-center gap-2">
            <button
              class="text-sm font-medium px-3 py-2 rounded-lg border border-[#E9E0D3] text-[#6b6b6b] hover:bg-[#F4EEE5] transition-colors cursor-pointer"
              @click="$emit('close')"
            >Cancel</button>
            <button
              v-if="kind === 'chart'"
              class="text-sm font-medium px-4 py-2.5 rounded-xl bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors cursor-pointer"
              @click="apply"
            >Apply</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  open: boolean
  widget: any | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', payload: { type?: string; x?: string; y?: string; groupBy?: string; aggregation?: string }): void
}>()

const CHART_TYPES = [
  { value: 'bar_chart', label: 'Bar', icon: 'heroicons:chart-bar' },
  { value: 'line_chart', label: 'Line', icon: 'heroicons:presentation-chart-line' },
  { value: 'area_chart', label: 'Area', icon: 'heroicons:chart-bar-square' },
  { value: 'pie_chart', label: 'Pie', icon: 'heroicons:chart-pie' },
  { value: 'scatter_plot', label: 'Scatter', icon: 'heroicons:ellipsis-horizontal' },
]
const AGGS = [
  { value: 'sum', label: 'Sum' },
  { value: 'avg', label: 'Average' },
  { value: 'count', label: 'Count' },
  { value: 'min', label: 'Min' },
  { value: 'max', label: 'Max' },
]

// Resolve widget type → only charts get the field builder.
const widgetType = computed(() => {
  const w = props.widget
  const v = w?.view
  return String(v?.view?.type || v?.type || w?.last_step?.data_model?.type || '').toLowerCase()
})
const kind = computed<'chart' | 'none'>(() => {
  const t = widgetType.value
  if (['bar_chart', 'line_chart', 'area_chart', 'pie_chart', 'scatter_plot', 'bar', 'line', 'area', 'pie', 'scatter'].includes(t)) return 'chart'
  return 'none'
})

// Column keys from the result rows (same source as the renderer).
const columns = computed<string[]>(() => {
  const w = props.widget
  const row = w?.last_step?.data?.rows?.[0]
  if (row && typeof row === 'object') return Object.keys(row)
  const cols = w?.last_step?.data?.columns
  if (Array.isArray(cols)) return cols.map((c: any) => c?.field || c?.headerName || c?.colId || c).filter(Boolean)
  return []
})

const chartType = ref('bar_chart')
const xField = ref('')
const yField = ref('')
const groupByField = ref('')
const aggregation = ref('sum')

function normType(t: string): string {
  if (t === 'bar') return 'bar_chart'
  if (t === 'line') return 'line_chart'
  if (t === 'area') return 'area_chart'
  if (t === 'pie') return 'pie_chart'
  if (t === 'scatter') return 'scatter_plot'
  return t || 'bar_chart'
}

// Seed local state from the widget's existing view config whenever the editor opens.
function seed() {
  const v = props.widget?.view?.view || {}
  chartType.value = normType(widgetType.value) || 'bar_chart'
  xField.value = typeof v.x === 'string' ? v.x : ''
  yField.value = Array.isArray(v.y) ? (v.y[0] || '') : (typeof v.y === 'string' ? v.y : '')
  groupByField.value = typeof v.groupBy === 'string' ? v.groupBy : ''
  aggregation.value = typeof v.aggregation === 'string' ? v.aggregation : 'sum'
}
watch(() => props.open, (o) => { if (o) seed() }, { immediate: true })

function resetFields() {
  emit('apply', { type: undefined, x: undefined, y: undefined, groupBy: undefined, aggregation: undefined })
}

function apply() {
  emit('apply', {
    type: chartType.value || undefined,
    x: xField.value || undefined,
    y: yField.value || undefined,
    groupBy: chartType.value === 'pie_chart' ? undefined : (groupByField.value || undefined),
    aggregation: aggregation.value || undefined,
  })
}
</script>
