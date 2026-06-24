<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-[80] flex items-center justify-center">
      <!-- backdrop -->
      <div class="absolute inset-0 bg-black/30" @click="$emit('close')" />
      <!-- panel -->
      <div class="relative w-[420px] max-w-[92vw] max-h-[85vh] overflow-y-auto bg-white border border-[#E7E5DD] rounded-2xl shadow-lg">
        <div class="flex items-center justify-between px-4 py-3 border-b border-[#E7E5DD]">
          <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: ui-serif, Georgia, serif;">Conditional formatting</h3>
          <button class="text-[#9a958c] hover:text-[#1f2328] cursor-pointer" @click="$emit('close')">
            <Icon name="heroicons:x-mark" class="w-4 h-4" />
          </button>
        </div>

        <div class="px-4 py-3 space-y-4">
          <!-- CHART: conditional color rules -->
          <section v-if="kind === 'chart'">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-[#6b6b6b] uppercase tracking-wide">Color rules</span>
              <button
                class="text-[11px] font-semibold px-2 py-1 rounded-lg border border-[#E7E5DD] text-[#6b6b6b] hover:bg-[#F4F1EA] transition-colors cursor-pointer"
                @click="addRule"
              >+ Add rule</button>
            </div>
            <p v-if="!rules.length" class="text-xs text-[#9a958c] italic">No rules — bars/slices use the palette. Add a rule to color by value (first match wins).</p>
            <div v-for="(r, i) in rules" :key="r.id" class="flex items-center gap-1.5 mb-2">
              <span class="text-xs text-[#6b6b6b]">if value</span>
              <select v-model="r.op" class="text-xs border border-[#E7E5DD] rounded-md px-1.5 py-1 bg-white">
                <option value=">">&gt;</option>
                <option value=">=">&ge;</option>
                <option value="<">&lt;</option>
                <option value="<=">&le;</option>
                <option value="==">=</option>
                <option value="!=">&ne;</option>
                <option value="between">between</option>
              </select>
              <input v-model.number="r.value" type="number" class="w-16 text-xs border border-[#E7E5DD] rounded-md px-1.5 py-1" />
              <template v-if="r.op === 'between'">
                <span class="text-xs text-[#6b6b6b]">and</span>
                <input v-model.number="r.value2" type="number" class="w-16 text-xs border border-[#E7E5DD] rounded-md px-1.5 py-1" />
              </template>
              <input v-model="r.color" type="color" class="w-7 h-7 border border-[#E7E5DD] rounded-md cursor-pointer p-0" />
              <button class="text-red-400 hover:bg-red-50 rounded p-1 cursor-pointer" @click="rules.splice(i, 1)">
                <Icon name="heroicons:trash" class="w-3.5 h-3.5" />
              </button>
            </div>
          </section>

          <!-- TABLE: data bars -->
          <section v-else-if="kind === 'table'">
            <span class="text-xs font-semibold text-[#6b6b6b] uppercase tracking-wide">Data bars</span>
            <label class="flex items-center gap-2 mt-2 text-sm text-[#1f2328] cursor-pointer">
              <input v-model="dataBars.enabled" type="checkbox" class="rounded border-[#E7E5DD] text-[#C2683F] focus:ring-[#C2683F]" />
              Show inline bars in a numeric column
            </label>
            <div v-if="dataBars.enabled" class="mt-3 space-y-2 ps-6">
              <div class="flex items-center gap-2">
                <span class="text-xs text-[#6b6b6b] w-14">Column</span>
                <select v-model="dataBars.column" class="flex-1 text-xs border border-[#E7E5DD] rounded-md px-1.5 py-1 bg-white">
                  <option value="">Auto (first numeric)</option>
                  <option v-for="c in columns" :key="c" :value="c">{{ c }}</option>
                </select>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-xs text-[#6b6b6b] w-14">Color</span>
                <input v-model="dataBars.color" type="color" class="w-7 h-7 border border-[#E7E5DD] rounded-md cursor-pointer p-0" />
              </div>
            </div>
          </section>

          <!-- KPI: target vs actual -->
          <section v-else-if="kind === 'kpi'">
            <span class="text-xs font-semibold text-[#6b6b6b] uppercase tracking-wide">KPI target</span>
            <label class="flex items-center gap-2 mt-2 text-sm text-[#1f2328] cursor-pointer">
              <input v-model="kpiEnabled" type="checkbox" class="rounded border-[#E7E5DD] text-[#C2683F] focus:ring-[#C2683F]" />
              Compare to a target value
            </label>
            <div v-if="kpiEnabled" class="mt-3 space-y-2 ps-6">
              <div class="flex items-center gap-2">
                <span class="text-xs text-[#6b6b6b] w-16">Target</span>
                <input v-model.number="kpiTarget.value" type="number" class="flex-1 text-xs border border-[#E7E5DD] rounded-md px-1.5 py-1" />
              </div>
              <div class="flex items-center gap-2">
                <span class="text-xs text-[#6b6b6b] w-16">Good when</span>
                <select v-model="kpiTarget.direction" class="flex-1 text-xs border border-[#E7E5DD] rounded-md px-1.5 py-1 bg-white">
                  <option value="higher">Actual ≥ target (higher is better)</option>
                  <option value="lower">Actual ≤ target (lower is better)</option>
                </select>
              </div>
            </div>
          </section>

          <p v-else class="text-xs text-[#9a958c] italic">No formatting options for this widget type.</p>
        </div>

        <div class="flex items-center justify-end gap-2 px-4 py-3 border-t border-[#E7E5DD]">
          <button
            class="text-sm font-medium px-3 py-2 rounded-lg border border-[#E7E5DD] text-[#6b6b6b] hover:bg-[#F4F1EA] transition-colors cursor-pointer"
            @click="$emit('close')"
          >Cancel</button>
          <button
            class="text-sm font-medium px-4 py-2.5 rounded-xl bg-[#C2683F] text-white hover:bg-[#A8542F] transition-colors cursor-pointer"
            @click="apply"
          >Apply</button>
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
  (e: 'apply', payload: { conditionalRules?: any[]; dataBars?: any; kpiTarget?: any }): void
}>()

// Resolve the widget type → which editor section to show.
const widgetType = computed(() => {
  const w = props.widget
  const v = w?.view
  return String(v?.view?.type || v?.type || w?.last_step?.data_model?.type || '').toLowerCase()
})

const kind = computed<'chart' | 'table' | 'kpi' | 'none'>(() => {
  const t = widgetType.value
  if (t === 'table') return 'table'
  if (t === 'metric_card' || t === 'count' || t === 'scalar') return 'kpi'
  if (['bar_chart', 'line_chart', 'area_chart', 'pie_chart'].includes(t)) return 'chart'
  return 'none'
})

// Column keys (for table data-bar column picker).
const columns = computed<string[]>(() => {
  const w = props.widget
  const row = w?.last_step?.data?.rows?.[0]
  if (row && typeof row === 'object') return Object.keys(row)
  const cols = w?.last_step?.data?.columns
  if (Array.isArray(cols)) return cols.map((c: any) => c?.field || c?.headerName || c?.colId).filter(Boolean)
  return []
})

// Editable local state.
const rules = ref<any[]>([])
const dataBars = ref<{ enabled: boolean; column: string; color: string }>({ enabled: false, column: '', color: '#C2683F' })
const kpiEnabled = ref(false)
const kpiTarget = ref<{ value: number | null; direction: string }>({ value: null, direction: 'higher' })

let ruleSeq = 0
function addRule() {
  rules.value.push({ id: `r${Date.now()}_${ruleSeq++}`, op: '>', value: 0, value2: null, color: '#C2683F' })
}

// Seed from the widget's existing view config whenever the editor opens.
function seed() {
  const v = props.widget?.view?.view || {}
  rules.value = Array.isArray(v.conditionalRules)
    ? v.conditionalRules.map((r: any) => ({ id: r.id || `r${Date.now()}_${ruleSeq++}`, op: r.op || '>', value: r.value ?? 0, value2: r.value2 ?? null, color: r.color || '#C2683F' }))
    : []
  const db = v.dataBars || {}
  dataBars.value = { enabled: !!db.enabled, column: db.column || '', color: db.color || '#C2683F' }
  const kt = v.kpiTarget
  kpiEnabled.value = !!(kt && typeof kt.value === 'number')
  kpiTarget.value = { value: kt?.value ?? null, direction: kt?.direction || 'higher' }
}

watch(() => props.open, (o) => { if (o) seed() }, { immediate: true })

function apply() {
  const payload: { conditionalRules?: any[]; dataBars?: any; kpiTarget?: any } = {}
  if (kind.value === 'chart') {
    payload.conditionalRules = rules.value
      .filter(r => r.color && r.value != null && !Number.isNaN(Number(r.value)))
      .map(r => ({ id: r.id, op: r.op, value: Number(r.value), value2: r.op === 'between' ? Number(r.value2) : undefined, color: r.color }))
  } else if (kind.value === 'table') {
    payload.dataBars = dataBars.value.enabled
      ? { enabled: true, column: dataBars.value.column || undefined, color: dataBars.value.color }
      : { enabled: false }
  } else if (kind.value === 'kpi') {
    payload.kpiTarget = (kpiEnabled.value && kpiTarget.value.value != null && !Number.isNaN(Number(kpiTarget.value.value)))
      ? { value: Number(kpiTarget.value.value), direction: kpiTarget.value.direction }
      : null
  }
  emit('apply', payload)
}
</script>
