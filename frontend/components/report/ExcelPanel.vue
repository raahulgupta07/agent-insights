<template>
  <div class="flex-1 flex flex-col min-h-0 bg-white">
    <!-- Toolbar -->
    <div class="h-11 px-3 flex items-center gap-2 border-b border-gray-100 shrink-0">
      <span class="text-sm font-medium text-gray-800">Workbook</span>
      <span class="text-xs text-gray-400">· {{ normalizedSheets.length }} sheets</span>
      <div class="ml-auto flex items-center gap-1.5">
        <button
          class="px-2 py-1 rounded-md text-xs border border-gray-200 text-gray-500 hover:text-gray-700 transition-colors"
          title="Refresh"
          @click="$emit('refresh')"
        >
          <Icon name="heroicons:arrow-path" class="w-3.5 h-3.5" />
        </button>
        <button
          class="px-2.5 py-1.5 rounded-md bg-[#C2683F] hover:bg-[#A8542F] text-white text-xs flex items-center gap-1 transition-colors disabled:opacity-50"
          :disabled="!normalizedSheets.length || exporting"
          @click="exportXlsx"
        >
          <Icon name="heroicons:arrow-down-tray" class="w-3.5 h-3.5" />
          {{ exporting ? 'Exporting…' : 'Export .xlsx' }}
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="!normalizedSheets.length"
      class="flex-1 flex flex-col items-center justify-center text-gray-400 px-6"
    >
      <Icon name="heroicons:table-cells" class="w-8 h-8 mb-2" />
      <span class="text-sm text-center">No sheets yet — run a query or Save Query.</span>
    </div>

    <template v-else>
      <!-- Formula bar -->
      <div class="h-8 px-3 flex items-center gap-2 border-b border-gray-100 bg-gray-50 text-xs text-gray-500 shrink-0">
        <span class="font-mono px-2 py-0.5 bg-white border border-gray-200 rounded">{{ activeCellRef }}</span>
        <span class="font-mono text-gray-400 truncate">{{ activeCellValue }}</span>
      </div>

      <!-- Grid -->
      <div class="flex-1 overflow-auto min-h-0">
        <table class="border-collapse">
          <thead>
            <tr class="bg-gray-50 text-gray-500">
              <th class="border border-gray-200 text-xs px-2 py-1 w-10"></th>
              <th
                v-for="(col, c) in activeSheet.columns"
                :key="c"
                class="border border-gray-200 text-xs px-2 py-1 whitespace-nowrap font-medium text-left"
              >
                {{ colLetter(c) }} · {{ col }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, r) in visibleRows" :key="r">
              <td class="border border-gray-200 text-xs px-2 py-1 bg-gray-50 text-gray-400 text-center">
                {{ r + 1 }}
              </td>
              <td
                v-for="(col, c) in activeSheet.columns"
                :key="c"
                class="border border-gray-200 text-xs px-2 py-1 whitespace-nowrap cursor-cell"
                :class="{ 'bg-[#FBF7F4]': active.r === r && active.c === c }"
                @click="selectCell(r, c)"
              >
                {{ cellText(row?.[c]) }}
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="truncated" class="px-3 py-1.5 text-xs text-gray-400">
          … {{ activeSheet.rows.length - MAX_ROWS }} more rows
        </div>
      </div>

      <!-- Sheet tabs -->
      <div class="h-9 border-t border-gray-200 flex items-center gap-1 px-2 bg-gray-50 text-xs shrink-0">
        <span
          v-for="(sheet, i) in normalizedSheets"
          :key="i"
          class="sheet-tab px-3 py-1 rounded-t cursor-pointer transition-colors"
          :class="i === activeIndex
            ? 'bg-white border border-b-0 border-gray-200 text-[#C2683F] font-medium'
            : 'text-gray-500 hover:text-gray-800'"
          @click="setActive(i)"
        >
          {{ sheet.name }}
        </span>
        <span class="px-2 text-gray-300 cursor-not-allowed select-none" title="Coming soon">+ New sheet</span>
        <span class="ml-auto text-gray-400">{{ activeSheet.rows.length }} rows · {{ activeSheet.columns.length }} cols</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

interface SheetInput {
  name?: string
  columns?: string[]
  rows?: any[][] | Record<string, any>[]
}

interface NormalSheet {
  name: string
  columns: string[]
  rows: any[][]
}

const MAX_ROWS = 200

const props = defineProps<{
  sheets?: SheetInput[]
  workbookTitle?: string
}>()

defineEmits(['refresh'])

const activeIndex = ref(0)
const active = ref<{ r: number; c: number }>({ r: 0, c: 0 })
const exporting = ref(false)

const safeTitle = computed(() => props.workbookTitle?.trim() || 'Workbook')

function normalizeSheet(s: SheetInput, i: number): NormalSheet {
  const name = s?.name?.trim() || `Sheet ${i + 1}`
  const rawRows = Array.isArray(s?.rows) ? s.rows : []

  // Array-of-objects → derive columns from keys + rows from values.
  const first = rawRows[0]
  if (first && !Array.isArray(first) && typeof first === 'object') {
    const cols = Array.isArray(s?.columns) && s.columns.length
      ? s.columns
      : Object.keys(first as Record<string, any>)
    const rows = (rawRows as Record<string, any>[]).map((obj) =>
      cols.map((k) => (obj ? obj[k] : undefined))
    )
    return { name, columns: cols, rows }
  }

  // Array-of-arrays.
  const rows = (rawRows as any[][]).map((row) => (Array.isArray(row) ? row : [row]))
  let cols = Array.isArray(s?.columns) ? [...s.columns] : []
  const widest = rows.reduce((m, r) => Math.max(m, r.length), 0)
  while (cols.length < widest) cols.push(colLetter(cols.length))
  return { name, columns: cols, rows }
}

const normalizedSheets = computed<NormalSheet[]>(() => {
  const raw = Array.isArray(props.sheets) ? props.sheets.filter(Boolean) : []
  return raw.map(normalizeSheet)
})

const activeSheet = computed<NormalSheet>(() =>
  normalizedSheets.value[activeIndex.value] || { name: '', columns: [], rows: [] }
)

const truncated = computed(() => activeSheet.value.rows.length > MAX_ROWS)
const visibleRows = computed(() => activeSheet.value.rows.slice(0, MAX_ROWS))

function colLetter(c: number): string {
  let n = c
  let s = ''
  do {
    s = String.fromCharCode(65 + (n % 26)) + s
    n = Math.floor(n / 26) - 1
  } while (n >= 0)
  return s
}

function cellText(v: any): string {
  if (v === null || v === undefined) return ''
  if (typeof v === 'object') {
    try { return JSON.stringify(v) } catch { return String(v) }
  }
  return String(v)
}

const activeCellRef = computed(() => `${colLetter(active.value.c)}${active.value.r + 1}`)
const activeCellValue = computed(() => {
  const row = activeSheet.value.rows[active.value.r]
  return row ? cellText(row[active.value.c]) : ''
})

function selectCell(r: number, c: number) {
  active.value = { r, c }
}

function setActive(i: number) {
  activeIndex.value = i
  active.value = { r: 0, c: 0 }
}

// Clamp active index if the sheet set shrinks.
watch(normalizedSheets, (s) => {
  if (activeIndex.value >= s.length) {
    activeIndex.value = Math.max(0, s.length - 1)
    active.value = { r: 0, c: 0 }
  }
})

async function exportXlsx() {
  if (!normalizedSheets.value.length) return
  exporting.value = true
  try {
    const XLSX: any = await import('xlsx')
    const wb = XLSX.utils.book_new()
    normalizedSheets.value.forEach((sheet, i) => {
      const aoa = [sheet.columns, ...sheet.rows]
      const ws = XLSX.utils.aoa_to_sheet(aoa)
      // Excel sheet names: max 31 chars, no []:*?/\
      const safeName = (sheet.name || `Sheet${i + 1}`).replace(/[[\]:*?/\\]/g, ' ').slice(0, 31) || `Sheet${i + 1}`
      XLSX.utils.book_append_sheet(wb, ws, safeName)
    })
    XLSX.writeFile(wb, `${safeTitle.value}.xlsx`)
  } catch (e) {
    console.warn('export library not installed', e)
    try { (globalThis as any).useToast?.().add({ title: 'Export failed', description: 'export library not installed' }) } catch {}
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.no-scrollbar::-webkit-scrollbar { display: none; }
.no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }
</style>
