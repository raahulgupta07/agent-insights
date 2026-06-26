<template>
  <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
    <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto">

      <!-- header: serif title + subtitle + grids ring -->
      <div class="flex items-start justify-between gap-4 mb-1">
        <div>
          <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Spreadsheets</h2>
          <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[480px]">Live grids exported from query results. Sort, filter and re-run without leaving the page.</p>
        </div>
        <div class="shrink-0 text-center">
          <div class="relative w-[54px] h-[54px] mx-auto">
            <svg width="54" height="54" style="transform:rotate(-90deg)">
              <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
              <circle cx="27" cy="27" r="22" stroke="#9A6A12" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" :stroke-dashoffset="ringOffset" style="transition:stroke-dashoffset .5s" />
            </svg>
            <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#9A6A12]" style="font-family: ui-serif, Georgia, serif">{{ grids.length }}</div>
          </div>
          <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">grids</div>
        </div>
      </div>

      <!-- toolbar: search + open-a-report -->
      <div class="flex items-center gap-2 mt-4 mb-4">
        <div class="relative flex-1 max-w-[420px]">
          <UIcon name="i-heroicons-magnifying-glass" class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9a958c]" />
          <input
            v-model="search"
            type="text"
            placeholder="Search grids…"
            class="w-full pl-8 pr-3 py-2 text-[13px] rounded-lg border border-[#E9E0D3] bg-white text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none focus:border-[#C2541E]"
          />
        </div>
        <button
          type="button"
          class="ms-auto inline-flex items-center gap-1.5 px-3 py-2 text-[13px] font-semibold rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors"
          @click="navigateTo('/reports')"
        >
          Open a report →
        </button>
      </div>

      <!-- section card with band pill -->
      <div class="relative border border-[#E9E0D3] rounded-2xl bg-white p-4">
        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">YOUR GRIDS</span>

        <!-- table (when grids exist) -->
        <div v-if="filtered.length" class="border border-[#E9E0D3] rounded-xl overflow-hidden bg-white mt-1">
          <table class="w-full border-collapse">
            <thead>
              <tr class="text-[10px] uppercase tracking-wide text-[#9a958c] bg-[#FAF7F1]">
                <th class="text-left font-semibold px-4 py-2.5">Name</th>
                <th class="text-left font-semibold px-4 py-2.5">Source</th>
                <th class="text-left font-semibold px-4 py-2.5">Rows</th>
                <th class="text-left font-semibold px-4 py-2.5">Updated</th>
                <th class="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="g in filtered"
                :key="g.id"
                class="border-t border-[#EFEDE6] hover:bg-[#FCFAF6] cursor-pointer transition-colors"
                @click="openGrid(g)"
              >
                <td class="px-4 py-3">
                  <span class="inline-flex items-center gap-1.5 text-[13px] font-medium text-[#1f2328]">
                    <UIcon name="i-heroicons-table-cells" class="w-3.5 h-3.5 text-[#9A6A12] shrink-0" />
                    {{ g.name || g.title || 'Untitled grid' }}
                  </span>
                </td>
                <td class="px-4 py-3 text-[12px] text-[#6b6b6b]">{{ g.source || '—' }}</td>
                <td class="px-4 py-3 text-[12px] text-[#6b6b6b]">{{ g.row_count != null ? Number(g.row_count).toLocaleString() : '—' }}</td>
                <td class="px-4 py-3 text-[12px] text-[#6b6b6b]">{{ relTime(g.updated_at) }}</td>
                <td class="px-4 py-3 text-right text-[12px] font-semibold text-[#A8330F] whitespace-nowrap">Open →</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- empty state -->
        <div
          v-else
          class="border border-dashed border-[#d8cfc0] rounded-xl bg-gradient-to-b from-white to-[#fdfcf9] flex flex-col items-center justify-center text-center py-12 mt-1"
        >
          <span class="w-12 h-12 rounded-xl bg-[#F6EEDD] flex items-center justify-center text-[#9A6A12] mb-3">
            <UIcon name="i-heroicons-table-cells" class="w-6 h-6" />
          </span>
          <div class="text-[13px] font-semibold text-[#1f2328]">
            {{ search ? 'No grids match your search' : 'No grids yet' }}
          </div>
          <div class="text-[11px] text-[#9a958c] mt-1 max-w-[280px]">
            Export any query result from a report to a live grid and it shows up here.
          </div>
          <button
            v-if="!search"
            type="button"
            class="mt-3 inline-flex items-center gap-1.5 border border-[#E9E0D3] rounded-lg px-3 py-1.5 text-[12px] bg-white text-[#1f2328] hover:border-[#C2541E] transition-colors"
            @click="navigateTo('/reports')"
          >
            Open a report
          </button>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ auth: true })

// Client-side toolbar state. No spreadsheets backend yet → list stays empty (empty-state renders).
const search = ref('')
const scope = ref<'All' | 'Mine'>('All')
const grids = ref<any[]>([])

// ring fills with grid count (0 → empty ring at full 138 offset)
const ringOffset = computed(() => {
  const n = grids.value.length
  const pct = Math.min(100, n > 0 ? Math.min(100, n * 20) : 0)
  return Math.round(138 - (138 * pct) / 100)
})

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q) return grids.value
  return grids.value.filter((g) =>
    `${g.name || g.title || ''} ${g.source || ''}`.toLowerCase().includes(q),
  )
})

function openGrid(g: any) {
  if (g?.report_id) navigateTo(`/reports/${g.report_id}`)
  else if (g?.id) navigateTo(`/reports/${g.id}`)
  else navigateTo('/reports')
}

function relTime(ts?: string) {
  if (!ts) return ''
  const d = new Date(ts).getTime()
  if (isNaN(d)) return ''
  const s = Math.floor((Date.now() - d) / 1000)
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  if (s < 604800) return `${Math.floor(s / 86400)}d ago`
  return `${Math.floor(s / 604800)}w ago`
}
</script>
