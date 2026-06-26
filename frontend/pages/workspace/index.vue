<template>
  <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
    <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto">

      <!-- header: title + readiness-style ring -->
      <div class="flex items-start justify-between gap-4 mb-1">
        <div>
          <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Workspace</h2>
          <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[460px]">Create anything, organize it into lanes, and ship it. Reports · Dashboards · Decks · Sheets — one place, one flow.</p>
        </div>
        <div class="shrink-0 text-center">
          <div class="relative w-[54px] h-[54px] mx-auto">
            <svg width="54" height="54" style="transform:rotate(-90deg)">
              <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
              <circle cx="27" cy="27" r="22" stroke="#C2541E" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" :stroke-dashoffset="Math.round(138 - 138 * ringPct / 100)" style="transition:stroke-dashoffset .5s" />
            </svg>
            <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#C2541E]" style="font-family: ui-serif, Georgia, serif">{{ totalItems }}</div>
          </div>
          <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">items</div>
        </div>
      </div>

      <!-- STEP 1 · CREATE -->
      <div class="relative mt-4 border border-[#E9E0D3] rounded-2xl bg-white p-4">
        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">1 · CREATE</span>
        <p class="text-xs text-[#6b6b6b] mt-1 mb-3">Three ways to start — ask an agent, build a board, or bring a file:</p>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <button type="button" class="text-left border border-[#E9E0D3] rounded-xl p-3 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#2F6F4F] transition-colors flex flex-col min-h-[120px]" @click="navigateTo('/reports/new')">
            <span class="w-8 h-8 rounded-lg bg-[#E7F1EB] flex items-center justify-center mb-2"><UIcon name="i-heroicons-plus" class="w-4 h-4 text-[#2F6F4F]" /></span>
            <span class="text-[13px] font-semibold text-[#1f2328]">New report</span>
            <span class="text-[11px] text-[#6b6b6b] mt-0.5">Ask an agent a question. It answers with charts, tables and a written summary you can share.</span>
            <span class="mt-auto pt-2 text-[10px] text-[#9a958c]">Start a report →</span>
          </button>
          <button type="button" class="text-left border border-[#E9E0D3] rounded-xl p-3 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#1F6F8B] transition-colors flex flex-col min-h-[120px]" @click="navigateTo('/dashboards')">
            <span class="w-8 h-8 rounded-lg bg-[#E4F0F4] flex items-center justify-center mb-2"><UIcon name="i-heroicons-chart-bar-square" class="w-4 h-4 text-[#1F6F8B]" /></span>
            <span class="text-[13px] font-semibold text-[#1f2328]">New dashboard</span>
            <span class="text-[11px] text-[#6b6b6b] mt-0.5">Pin charts &amp; KPIs into an interactive board. Cross-filter, drill down, schedule it.</span>
            <span class="mt-auto pt-2 text-[10px] text-[#9a958c]">Build a dashboard →</span>
          </button>
          <button type="button" class="text-left border border-[#E9E0D3] rounded-xl p-3 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#C2541E] transition-colors flex flex-col min-h-[120px]" @click="navigateTo('/reports/new')">
            <span class="w-8 h-8 rounded-lg bg-[#F6EBE3] flex items-center justify-center mb-2"><UIcon name="i-heroicons-arrow-up-tray" class="w-4 h-4 text-[#C2541E]" /></span>
            <span class="text-[13px] font-semibold text-[#1f2328]">Import a file</span>
            <span class="text-[11px] text-[#6b6b6b] mt-0.5">Drop a spreadsheet, doc, deck or PDF. It becomes a workspace item your agents can use.</span>
            <span class="mt-auto pt-2 flex flex-wrap gap-1">
              <span class="text-[10px] border border-[#E9E0D3] rounded-full px-1.5 py-0.5 text-[#6b6b6b]">.xlsx</span>
              <span class="text-[10px] border border-[#E9E0D3] rounded-full px-1.5 py-0.5 text-[#6b6b6b]">.csv</span>
              <span class="text-[10px] border border-[#E9E0D3] rounded-full px-1.5 py-0.5 text-[#6b6b6b]">.pdf</span>
              <span class="text-[10px] border border-[#E9E0D3] rounded-full px-1.5 py-0.5 text-[#6b6b6b]">.docx</span>
            </span>
          </button>
        </div>
      </div>

      <!-- STEP 2 · YOUR WORK -->
      <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4">
        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">2 · YOUR WORK</span>
        <p class="text-[10px] uppercase tracking-wide text-[#9a958c] mt-1 mb-3 flex items-center gap-2"><span class="h-px bg-[#EFEDE6] flex-1"></span>everything is organized into four lanes · newest first<span class="h-px bg-[#EFEDE6] flex-1"></span></p>
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2.5">
          <!-- REPORTS -->
          <div class="rounded-xl border border-[#E9E0D3] bg-[#E7F1EB] p-3 flex flex-col min-h-[164px]">
            <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#2F6F4F]"></span><h4 class="text-xs font-semibold text-[#2F6F4F]">Reports</h4><span class="ms-auto text-[10px] text-[#2F6F4F] font-semibold">{{ counts.reports }}</span></div>
            <p class="text-[9.5px] text-[#5f7d6c] mb-1">conversations → answers</p>
            <div v-for="r in reports.slice(0,4)" :key="r.id" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5 cursor-pointer" @click="navigateTo(`/reports/${r.id}`)">
              <div class="flex items-center gap-1.5"><UIcon name="i-heroicons-chat-bubble-left-right" class="w-3.5 h-3.5 text-[#2F6F4F] shrink-0" /><span class="text-[11px] font-medium text-[#1f2328] truncate">{{ r.title || 'Report' }}</span></div>
              <span class="block text-[9.5px] text-[#9a958c] mt-0.5">{{ relTime(r.created_at) }}</span>
            </div>
            <div v-if="!reports.length" class="text-[10.5px] text-[#5f7d6c] mt-1.5">Ask an agent above to create your first report.</div>
            <button type="button" class="mt-auto pt-2 text-[10px] text-[#2F6F4F] font-medium text-left hover:underline" @click="navigateTo('/reports')">Open Reports →</button>
          </div>
          <!-- DASHBOARDS -->
          <div class="rounded-xl border border-[#E9E0D3] bg-[#E4F0F4] p-3 flex flex-col min-h-[164px]">
            <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#1F6F8B]"></span><h4 class="text-xs font-semibold text-[#1F6F8B]">Dashboards</h4><span class="ms-auto text-[10px] text-[#1F6F8B] font-semibold">{{ counts.dashboards }}</span></div>
            <p class="text-[9.5px] text-[#5a7d89] mb-1">pinned charts → boards</p>
            <div v-for="d in dashboards.slice(0,4)" :key="d.id" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5 cursor-pointer" @click="navigateTo(`/reports/${d.id}?focus=dashboard`)">
              <div class="flex items-center gap-1.5"><UIcon name="i-heroicons-chart-bar-square" class="w-3.5 h-3.5 text-[#1F6F8B] shrink-0" /><span class="text-[11px] font-medium text-[#1f2328] truncate">{{ d.title || 'Dashboard' }}</span></div>
            </div>
            <div v-if="!dashboards.length" class="text-[10.5px] text-[#5a7d89] mt-1.5">Pin charts from a report to build a board.</div>
            <button type="button" class="mt-auto pt-2 text-[10px] text-[#1F6F8B] font-medium text-left hover:underline" @click="navigateTo('/dashboards')">Open Dashboards →</button>
          </div>
          <!-- PRESENTATIONS -->
          <div class="rounded-xl border border-[#E9E0D3] bg-[#ECEAFB] p-3 flex flex-col min-h-[164px]">
            <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#5A4FCF]"></span><h4 class="text-xs font-semibold text-[#5A4FCF]">Presentations</h4><span class="ms-auto text-[10px] text-[#5A4FCF] font-semibold">{{ counts.presentations }}</span></div>
            <p class="text-[9.5px] text-[#6f67b0] mb-1">reports → slide decks</p>
            <div v-for="p in presentations.slice(0,4)" :key="p.id" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5 cursor-pointer" @click="navigateTo('/presentations')">
              <div class="flex items-center gap-1.5"><UIcon name="i-heroicons-presentation-chart-line" class="w-3.5 h-3.5 text-[#5A4FCF] shrink-0" /><span class="text-[11px] font-medium text-[#1f2328] truncate">{{ p.title || p.report_title || 'Presentation' }}</span></div>
              <span v-if="p.slide_count" class="block text-[9.5px] text-[#9a958c] mt-0.5">{{ p.slide_count }} slides · .pptx</span>
            </div>
            <div v-if="!presentations.length" class="text-[10.5px] text-[#6f67b0] mt-1.5">Open a report → Slides to generate a deck.</div>
            <button type="button" class="mt-auto pt-2 text-[10px] text-[#5A4FCF] font-medium text-left hover:underline" @click="navigateTo('/presentations')">Open Presentations →</button>
          </div>
          <!-- SPREADSHEETS -->
          <div class="rounded-xl border border-[#E9E0D3] bg-[#F6EEDD] p-3 flex flex-col min-h-[164px]">
            <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#9A6A12]"></span><h4 class="text-xs font-semibold text-[#9A6A12]">Spreadsheets</h4><span class="ms-auto text-[10px] text-[#9A6A12] font-semibold">{{ counts.spreadsheets }}</span></div>
            <p class="text-[9.5px] text-[#8a7333] mb-1">query results → grids</p>
            <div v-if="!counts.spreadsheets" class="text-[10.5px] text-[#8a7333] mt-1.5">Export any query result to a live grid.</div>
            <button type="button" class="mt-auto pt-2 text-[10px] text-[#9A6A12] font-medium text-left hover:underline" @click="navigateTo('/spreadsheets')">Open Spreadsheets →</button>
          </div>
        </div>
        <div class="text-[11px] text-[#6b6b6b] bg-[#F6EBE3] rounded-lg px-3 py-2 mt-2.5">Anything you create lands here automatically. Open a lane to manage, rename, share or schedule its items.</div>
      </div>

      <!-- STEP 3 · LIBRARY & SCHEDULE -->
      <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4 mb-6">
        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">3 · LIBRARY &amp; SCHEDULE</span>
        <p class="text-xs text-[#6b6b6b] mt-1 mb-3">Reuse agent know-how, and put reports on a cadence:</p>
        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <!-- templates -->
          <div class="border border-[#E9E0D3] rounded-xl bg-white p-3">
            <div class="flex items-center gap-2 mb-1"><UIcon name="i-heroicons-square-3-stack-3d" class="w-4 h-4 text-[#A8330F]" /><b class="text-[13px]">Agent Templates</b><span class="ms-auto text-[11px] text-[#9a958c] font-semibold">{{ counts.templates }}</span></div>
            <p class="text-[11px] text-[#6b6b6b] mb-2">Reusable rules, metric formulas &amp; example patterns. Bind one to your columns — your data never leaves.</p>
            <div v-for="t in templates.slice(0,3)" :key="t.id" class="bg-[#FBFAF6] border border-black/5 rounded-lg p-2 mt-1.5 cursor-pointer" @click="navigateTo(`/templates/${t.id}`)">
              <div class="flex items-center gap-1.5"><UIcon name="i-heroicons-square-3-stack-3d" class="w-3.5 h-3.5 text-[#A8330F] shrink-0" /><span class="text-[11px] font-medium text-[#1f2328] truncate">{{ t.name }}</span><span class="ms-auto text-[9.5px] text-[#9a958c]">v{{ t.version || '1.0.0' }}</span></div>
            </div>
            <div v-if="!templates.length" class="text-[10.5px] text-[#9a958c] mt-1.5">No templates yet.</div>
            <button type="button" class="mt-2 text-[10px] text-[#A8330F] font-medium text-left hover:underline" @click="navigateTo('/templates')">Browse templates →</button>
          </div>
          <!-- scheduled -->
          <div class="border border-[#E9E0D3] rounded-xl bg-white p-3">
            <div class="flex items-center gap-2 mb-1"><UIcon name="i-heroicons-clock" class="w-4 h-4 text-[#6b6b6b]" /><b class="text-[13px]">Scheduled</b><span class="ms-auto text-[11px] text-[#9a958c] font-semibold">{{ counts.scheduled }}</span></div>
            <p class="text-[11px] text-[#6b6b6b] mb-2">Reports that re-run on a cadence and deliver to a channel or inbox.</p>
            <div v-if="!counts.scheduled" class="text-[10.5px] text-[#9a958c] mt-1.5">No scheduled tasks yet.</div>
            <button type="button" class="mt-2 text-[10px] text-[#6b6b6b] font-medium text-left hover:underline" @click="navigateTo('/scheduled-tasks')">Open Scheduled →</button>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

definePageMeta({ auth: true })

const { railCounts } = useAppNav()

const reports = ref<any[]>([])
const dashboards = ref<any[]>([])
const presentations = ref<any[]>([])
const templates = ref<any[]>([])
const counts = reactive({ reports: 0, dashboards: 0, presentations: 0, spreadsheets: 0, templates: 0, scheduled: 0 })

const totalItems = computed(() =>
  counts.reports + counts.dashboards + counts.presentations + counts.spreadsheets + counts.templates + counts.scheduled)
// ring fills by how many surfaces have any content (0..6 → 0..100%)
const ringPct = computed(() => {
  const filled = [counts.reports, counts.dashboards, counts.presentations, counts.spreadsheets, counts.templates, counts.scheduled].filter(n => n > 0).length
  return Math.round((filled / 6) * 100)
})

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

async function loadReports() {
  try {
    const { data } = await useMyFetch<any>('/reports', { method: 'GET', query: { page: 1, limit: 6, filter: 'my' } })
    const d = data.value || {}
    reports.value = Array.isArray(d.reports) ? d.reports : (Array.isArray(d) ? d : [])
    counts.reports = d.pagination?.total ?? reports.value.length
  } catch { /* fail-soft */ }
}
async function loadDashboards() {
  try {
    const { data } = await useMyFetch<any>('/reports', { method: 'GET', query: { page: 1, limit: 6, filter: 'my', has_artifacts: 'yes' } })
    const d = data.value || {}
    dashboards.value = Array.isArray(d.reports) ? d.reports : (Array.isArray(d) ? d : [])
    counts.dashboards = d.pagination?.total ?? dashboards.value.length
  } catch { /* fail-soft */ }
}
async function loadPresentations() {
  try {
    const { data } = await useMyFetch<any[]>('/api/artifacts/presentations', { method: 'GET' })
    presentations.value = Array.isArray(data.value) ? data.value : []
    counts.presentations = presentations.value.length
  } catch { /* fail-soft */ }
}
async function loadTemplates() {
  try {
    const { data } = await useMyFetch<any>('/templates?scope=all', { method: 'GET' })
    const d = data.value || {}
    templates.value = Array.isArray(d.templates) ? d.templates : (Array.isArray(d) ? d : [])
    counts.templates = templates.value.length
  } catch { /* fail-soft */ }
}
async function loadScheduled() {
  try {
    const { data } = await useMyFetch<any>('/scheduled-tasks', { method: 'GET' })
    const d = data.value || {}
    const arr = Array.isArray(d.tasks) ? d.tasks : (Array.isArray(d) ? d : [])
    counts.scheduled = d.pagination?.total ?? arr.length
  } catch { /* fail-soft */ }
}

// Feed the left-rail count badges from this page's counts.
watchEffect(() => {
  railCounts.value = {
    templates: counts.templates,
    reports: counts.reports,
    dashboards: counts.dashboards,
    presentations: counts.presentations,
    spreadsheets: counts.spreadsheets,
    scheduled: counts.scheduled,
  }
})

onMounted(() => {
  loadReports(); loadDashboards(); loadPresentations(); loadTemplates(); loadScheduled()
})
</script>
