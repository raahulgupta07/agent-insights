<template>
  <!-- Auto-pilot v2 — reordered ADD → QUEUE → TRAIN → RESULT. Flag-gated by the parent
       (HYBRID_AUTOPILOT_V2). Self-contained, fail-soft on every fetch. Warm clay theme. -->
  <div>
    <!-- HEADER -->
    <div class="flex items-start justify-between gap-4 mb-1">
      <div>
        <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">AI Auto-pilot</h2>
        <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[460px]">Drop anything in — queue it, train once, and the router sorts each input into Data &middot; Knowledge &middot; Skill &middot; Rule. No per-dataset code.</p>
      </div>
      <div class="shrink-0 text-center">
        <div class="relative w-[54px] h-[54px] mx-auto">
          <svg width="54" height="54" style="transform:rotate(-90deg)">
            <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
            <circle cx="27" cy="27" r="22" stroke="#C2541E" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" :stroke-dashoffset="Math.round(138 - 138 * (readiness?.score || 0) / 100)" style="transition:stroke-dashoffset .5s" />
          </svg>
          <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#C2541E]" style="font-family: ui-serif, Georgia, serif">{{ readiness?.score || 0 }}</div>
        </div>
        <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">readiness</div>
      </div>
    </div>

    <!-- MODEL (compact — pick the LLM this agent uses for analysis + file routing) -->
    <div class="mt-4 border border-[#E9E0D3] rounded-xl bg-white px-3 py-2.5">
      <div class="flex items-center gap-3 flex-wrap">
        <span class="text-[12.5px] font-semibold text-[#1f2328] shrink-0">Model</span>
        <div class="relative">
          <select
            v-model="selectedModelId"
            :disabled="modelSaving"
            class="appearance-none text-[12px] text-[#1f2328] bg-[#fdfcf9] border border-[#E9E0D3] rounded-lg pl-2.5 pr-7 py-1.5 focus:outline-none focus:border-[#C2541E] disabled:opacity-60"
            @change="saveModel">
            <option :value="null">Default (org)</option>
            <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
          <UIcon name="i-heroicons-chevron-down" class="w-3.5 h-3.5 text-[#9a958c] absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
        <Spinner v-if="modelSaving" class="h-3.5 w-3.5 text-[#C2541E]" />
        <span v-else-if="modelSaved" class="inline-flex items-center gap-1 text-[11px] font-semibold text-[#2F6F4F]">
          <UIcon name="i-heroicons-check-circle" class="w-4 h-4" /> Saved
        </span>
        <span v-else-if="modelError" class="text-[11px] text-[#A8330F]">{{ modelError }}</span>
        <span class="text-[10.5px] text-[#9a958c] ms-auto">Used for analysis and file routing.</span>
      </div>
    </div>

    <!-- LLM-key gate notice (shown only when the org has no model key) -->
    <div v-if="llmConfigured === false" class="mt-4 flex items-center gap-2 text-[11.5px] text-[#9A6A12] bg-[#FBF1DD] border border-[#EBD9AE] rounded-xl px-3 py-2">
      <UIcon name="i-heroicons-key" class="w-4 h-4 shrink-0" />
      <span>Add your model key in
        <NuxtLink to="/settings/models" class="font-semibold underline hover:text-[#C2541E]">Settings &rarr; Models</NuxtLink>
        to start adding data.</span>
    </div>

    <!-- 1 · ADD (compact) -->
    <div class="relative mt-4 border border-[#E9E0D3] rounded-2xl bg-white p-3">
      <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">1 &middot; ADD</span>
      <!-- One row of source buttons: Database · Upload · OneDrive · SharePoint · Folder.
           Each opens its existing connect flow via @add. Scrolls horizontally if narrow. -->
      <div class="flex gap-2 mt-1.5 overflow-x-auto pb-1">
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#2F6F4F] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','database')">
          <span class="w-7 h-7 rounded-lg bg-[#E7F1EB] flex items-center justify-center shrink-0"><UIcon name="i-heroicons-circle-stack" class="w-4 h-4 text-[#2F6F4F]" /></span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">Database</span><span class="block text-[10.5px] text-[#9a958c] truncate">Postgres · MySQL · Snowflake</span></span>
        </button>
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#C2541E] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','upload')">
          <span class="w-7 h-7 rounded-lg bg-[#F6EBE3] flex items-center justify-center shrink-0"><UIcon name="i-heroicons-arrow-up-tray" class="w-4 h-4 text-[#C2541E]" /></span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">Upload file</span><span class="block text-[10.5px] text-[#9a958c] truncate">.csv .xlsx .pdf .docx</span></span>
        </button>
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#2C6EB5] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','onedrive')">
          <span class="w-7 h-7 rounded-lg bg-[#E6F0FA] flex items-center justify-center shrink-0"><UIcon name="i-heroicons-cloud" class="w-4 h-4 text-[#2C6EB5]" /></span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">OneDrive</span><span class="block text-[10.5px] text-[#9a958c] truncate">personal files</span></span>
        </button>
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#2C6EB5] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','sharepoint')">
          <span class="w-7 h-7 rounded-lg bg-[#E6F0FA] flex items-center justify-center shrink-0"><UIcon name="i-heroicons-building-office-2" class="w-4 h-4 text-[#2C6EB5]" /></span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">SharePoint</span><span class="block text-[10.5px] text-[#9a958c] truncate">team library</span></span>
        </button>
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#C2541E] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','folder')">
          <span class="w-7 h-7 rounded-lg bg-[#F4E5DA] flex items-center justify-center shrink-0 text-[#C2541E] text-base">⟳</span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">Folder</span><span class="block text-[10.5px] text-[#9a958c] truncate">desktop auto-sync</span></span>
        </button>
      </div>
    </div>

    <!-- 2 · QUEUE (the heart) -->
    <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4">
      <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">2 &middot; QUEUE</span>
      <p class="text-[11px] text-[#6b6b6b] mt-1 mb-3">Everything you add waits here with an instant type-guess. Re-route anything the router got wrong before you train.</p>
      <StudioInbox v-if="studioId" :studio-id="studioId" :v2="true" ref="inboxRef" />
      <div v-else class="text-[11.5px] text-[#9a958c]">Loading agent…</div>
    </div>

    <!-- 3 · TRAIN (button + segregation receipt) -->
    <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4">
      <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">3 &middot; TRAIN</span>
      <div class="flex items-center justify-between gap-3 mt-1 flex-wrap">
        <div class="text-[11.5px] text-[#6b6b6b]"><b class="text-[#1f2328]">{{ (sources || []).length }} source{{ (sources || []).length === 1 ? '' : 's' }} &middot; {{ (docs || []).length }} doc{{ (docs || []).length === 1 ? '' : 's' }} &middot; queued</b> → one pass</div>
        <div class="flex gap-2 shrink-0">
          <button type="button" class="text-[11.5px] border border-[#E9E0D3] rounded-lg px-3 py-2 text-[#6b6b6b] hover:bg-[#faf8f3] font-medium" @click="$emit('openTab','sources')">Review routing</button>
          <button type="button" :disabled="trainingAll || !canTrain" class="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-lg px-3.5 py-2 transition-colors disabled:opacity-50" @click="$emit('train')">
            <Spinner v-if="trainingAll" class="h-3.5 w-3.5 text-white" />
            <UIcon v-else name="i-heroicons-bolt" class="w-3.5 h-3.5" />
            {{ trainingAll ? 'Training…' : '⚡ Auto-train everything' }}
          </button>
        </div>
      </div>
      <p class="text-[11px] text-[#9a958c] mt-2">One pass: classify → segregate → ingest → write goldens → reconcile → coverage. Needs ≥1 pinned source or a file queued above.</p>

      <!-- RECEIPT (only once a train status exists) -->
      <div v-if="hasTrainStatus" class="mt-3 border-t border-[#E9E0D3] pt-3">
        <!-- LIVE PROCESS FLOW — 6 phases → arrows → live sub-stage nodes -->
        <div class="flow mb-2.5">
          <div class="flow-bar-row">
            <div class="flow-bar"><div class="flow-bar-fill" :style="{ width: flowPct + '%' }"></div></div>
            <span v-if="trainingAll" class="flow-status flow-status-run">running &middot; {{ flowPct }}%</span>
            <span v-else-if="flowAllDone" class="flow-status flow-status-done">✓ agent ready &middot; 100%</span>
            <span v-else class="flow-status">{{ flowPct }}%</span>
          </div>
          <div class="flow-phases">
            <template v-for="(ph, pi) in trainFlow" :key="ph.id">
              <div class="flow-phase" :class="{ 'flow-phase-active': ph.nodes.some(n => n.state === 'running') }">
                <div class="flow-phase-head">{{ ph.label }}</div>
                <div class="flow-nodes">
                  <div v-for="n in ph.nodes" :key="n.key" class="flow-node" :class="'st-' + n.state">
                    <span class="flow-glyph">{{ n.state === 'done' ? '✓' : n.state === 'running' ? '⟳' : n.state === 'held' ? '◌' : '·' }}</span>
                    <span class="flow-node-label">{{ n.label }}</span>
                  </div>
                </div>
              </div>
              <div v-if="pi < trainFlow.length - 1" class="flow-arrow" aria-hidden="true">›</div>
            </template>
          </div>
        </div>

        <!-- RECONCILE + COVERAGE pills -->
        <div class="flex flex-wrap items-center gap-2 mb-2.5">
          <span v-if="routeInbox"
            class="inline-flex items-center gap-1 text-[10.5px] font-semibold rounded-full px-2.5 py-1"
            :class="(routeInbox.held || 0) === 0 ? 'bg-[#E7F2EC] text-[#2f7a52]' : 'bg-[#FBF1DD] text-[#9A6A12]'">
            {{ routeInbox.files_in || 0 }} in → {{ routeInbox.placed || 0 }} placed &middot; {{ routeInbox.held || 0 }} held
          </span>
          <span v-if="coverageTotalPeriods != null"
            class="inline-flex items-center gap-1 text-[10.5px] font-semibold rounded-full px-2.5 py-1 bg-[#E4F0F4] text-[#1F6F8B]">
            coverage {{ coverageTotalPeriods }} period{{ coverageTotalPeriods === 1 ? '' : 's' }}
          </span>
        </div>

        <!-- per-dest breakdown (compact) -->
        <div v-if="byDestEntries.length" class="flex flex-wrap gap-1.5 mb-2.5">
          <span v-for="[dest, n] in byDestEntries" :key="dest"
            class="inline-flex items-center gap-1 text-[10px] rounded-md px-2 py-0.5 border border-[#ECE7E0] bg-white text-[#6b6b6b]">
            {{ destEmoji(dest) }} {{ destShort(dest) }} <b class="text-[#1f2328]">{{ n }}</b>
          </span>
        </div>

      </div>
    </div>

    <!-- 4 · RESULT (4 lanes) -->
    <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4 mb-4">
      <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">4 &middot; RESULT</span>
      <p class="text-[10px] uppercase tracking-wide text-[#9a958c] mt-1 mb-3 flex items-center gap-2"><span class="h-px bg-[#EFEDE6] flex-1"></span>each input lands in one of 4 lanes · all born pending (review gate)<span class="h-px bg-[#EFEDE6] flex-1"></span></p>
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2.5">
        <!-- DATA -->
        <div class="rounded-xl border border-[#E9E0D3] bg-[#E7F1EB] p-3 flex flex-col min-h-[164px]">
          <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#2F6F4F]"></span><h4 class="text-xs font-semibold text-[#2F6F4F]">Data</h4><span class="ms-auto text-[10px] text-[#2F6F4F] font-semibold">{{ (sources || []).length }}</span></div>
          <p class="text-[9.5px] text-[#5f7d6c] mb-1">tables → profiled &amp; queryable</p>
          <div v-for="s in (sources || []).slice(0,4)" :key="s.id" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <div class="flex items-center gap-1.5"><DataSourceIcon v-if="s.type" class="h-3.5 shrink-0" :type="s.type" /><UIcon v-else name="i-heroicons-circle-stack" class="w-3.5 h-3.5 text-[#9a958c] shrink-0" /><span class="text-[11px] font-medium text-[#1f2328] truncate">{{ s.name || s.agent_id }}</span></div>
          </div>
          <div v-if="!(sources || []).length" class="text-[10.5px] text-[#5f7d6c] mt-1.5">Add a sheet or connect a source above.</div>
          <div class="mt-auto pt-2 flex items-center gap-3">
            <button type="button" class="text-[10px] text-[#2F6F4F] font-medium text-left hover:underline" @click="$emit('openTab','sources')">Manage in Sources →</button>
            <button v-if="(sources || []).length" type="button" :disabled="repairing" class="text-[10px] text-[#9A6A12] font-medium hover:underline disabled:opacity-50" title="Stitch same-schema tables that were uploaded in separate sessions back into one table" @click="repairData">{{ repairing ? 'Repairing…' : 'Repair data' }}</button>
          </div>
        </div>
        <!-- KNOWLEDGE -->
        <div class="rounded-xl border border-[#E9E0D3] bg-[#E4F0F4] p-3 flex flex-col min-h-[164px]">
          <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#1F6F8B]"></span><h4 class="text-xs font-semibold text-[#1F6F8B]">Knowledge</h4><span class="ms-auto text-[10px] text-[#1F6F8B] font-semibold">{{ (docs || []).length }}</span></div>
          <p class="text-[9.5px] text-[#5a7d89] mb-1">docs → definitions extracted</p>
          <div v-for="d in (docs || []).slice(0,4)" :key="d.id" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <div class="flex items-center gap-1.5"><UIcon name="i-heroicons-document-text" class="w-3.5 h-3.5 text-[#1F6F8B] shrink-0" /><span class="text-[11px] font-medium text-[#1f2328] truncate">{{ d.title || d.name || d.filename || 'Knowledge doc' }}</span></div>
          </div>
          <div v-if="!(docs || []).length" class="text-[10.5px] text-[#5a7d89] mt-1.5">Upload a PDF / deck, or extract from a source.</div>
          <button type="button" class="mt-auto pt-2 text-[10px] text-[#1F6F8B] font-medium text-left hover:underline" @click="$emit('openTab','sources')">Manage in Knowledge →</button>
        </div>
        <!-- SKILL -->
        <div class="rounded-xl border border-[#E9E0D3] bg-[#ECEAFB] p-3 flex flex-col min-h-[164px]">
          <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#5A4FCF]"></span><h4 class="text-xs font-semibold text-[#5A4FCF]">Skill</h4></div>
          <p class="text-[9.5px] text-[#6f67b0] mb-1">a method/recipe → pack</p>
          <div class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <span class="text-[11px] text-[#1f2328]">Paste an analysis method — the router classifies it and binds it to your columns.</span>
          </div>
          <button type="button" class="mt-auto pt-2 text-[10px] text-[#5A4FCF] font-medium text-left hover:underline" @click="$emit('openTab','skills')">Open Skills →</button>
        </div>
        <!-- RULE / INSTRUCTION -->
        <div class="rounded-xl border border-[#E9E0D3] bg-[#F6EEDD] p-3 flex flex-col min-h-[164px]">
          <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#9A6A12]"></span><h4 class="text-xs font-semibold text-[#9A6A12]">Rule / Instruction</h4><span class="ms-auto text-[10px] text-[#9A6A12] font-semibold">{{ (activeInstr || 0) + (activeExamples || 0) }}</span></div>
          <p class="text-[9.5px] text-[#8a7333] mb-1">a constraint you type</p>
          <div v-if="activeInstr" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <span class="text-[11px] text-[#1f2328]">{{ activeInstr }} instruction{{ activeInstr === 1 ? '' : 's' }} applied to every answer</span>
          </div>
          <div v-if="activeExamples" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <span class="text-[11px] text-[#1f2328]">{{ activeExamples }} example{{ activeExamples === 1 ? '' : 's' }} grounding the agent</span>
          </div>
          <div v-if="!activeInstr && !activeExamples" class="text-[10.5px] text-[#8a7333] mt-1.5">Type a rule like “FY starts in April”.</div>
          <button type="button" class="mt-auto pt-2 text-[10px] text-[#9A6A12] font-medium text-left hover:underline" @click="$emit('openTab','instructions')">Manage in Instructions →</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useLlmConfigured } from '~/composables/useLlmConfigured'

const props = defineProps<{
  studioId: string
  sources: any[]
  docs: any[]
  readiness: { score: number }
  canEdit: boolean
  trainingAll: boolean
  canTrain: boolean
  trainLog: any
  trainStages: any[]
  trainLogLines: any[]
  activeInstr: number
  activeExamples: number
  showTrainLogPanel: boolean
}>()

defineEmits<{
  (e: 'add', payload: 'connector' | 'database' | 'upload' | 'onedrive' | 'sharepoint' | 'folder'): void
  (e: 'train'): void
  (e: 'openTab', payload: string): void
}>()

const inboxRef = ref<any>(null)

// Repair data: stitch same-schema orphan tables (files uploaded in separate
// sessions) back into each pinned source's ONE bound table. POSTs the generic
// self-heal route for every pinned source and surfaces a single result toast.
const toast = useToast()
const repairing = ref(false)
async function repairData() {
  if (repairing.value) return
  repairing.value = true
  let stitched = 0
  let rows = 0
  let failed = 0
  try {
    for (const s of (props.sources || [])) {
      const dsId = s.agent_id || s.data_source_id || s.id
      if (!dsId) continue
      try {
        const { data, error } = await useMyFetch<any>(`/data_sources/${dsId}/repair`, { method: 'POST' })
        if (error.value) { failed++; continue }
        const rep = (data.value as any)?.report
        if (rep && rep.ok) { stitched += (rep.tables_stitched || 0); rows += (rep.rows_added || 0) }
        else if (rep && rep.ok === false) { failed++ }
      } catch { failed++ }
    }
    if (failed && !stitched) {
      toast.add({ title: 'Repair failed', description: 'Could not repair this agent’s data.', color: 'red', icon: 'i-heroicons-exclamation-triangle' })
    } else if (stitched) {
      toast.add({ title: 'Data repaired', description: `Stitched ${stitched} orphaned table(s), added ${rows} row(s).`, color: 'green', icon: 'i-heroicons-check-circle' })
    } else {
      toast.add({ title: 'Nothing to repair', description: 'No split tables found — data is already unified.', color: 'green', icon: 'i-heroicons-check-circle' })
    }
  } finally {
    repairing.value = false
  }
}

// LLM-key gate (fail-open: llmConfigured defaults true, flips false only on explicit no-key).
const { llmConfigured } = useLlmConfigured()

// ─── Model selection card ───────────────────────────────────────────────────
// Lists the org's enabled models (same endpoint/shape as PromptBoxV2.loadModels).
// Value = model slug/id; null = org default. Reads/writes studio.config.model_id.
const models = ref<any[]>([])
const studioConfig = ref<Record<string, any>>({})   // full existing config (backend REPLACES it wholesale)
const selectedModelId = ref<string | null>(null)
const modelSaving = ref(false)
const modelSaved = ref(false)
const modelError = ref('')
let savedTimer: any = null

async function loadModelList() {
  try {
    const { data } = await useMyFetch<any>('/llm/models?is_enabled=true')
    if (Array.isArray(data.value)) models.value = data.value
  } catch { /* fail-soft — dropdown just shows Default (org) */ }
}

async function loadStudioModel() {
  if (!props.studioId) return
  try {
    const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}`)
    if (error?.value) return
    const cfg = ((data.value as any)?.config) || {}
    studioConfig.value = cfg
    selectedModelId.value = cfg.model_id != null ? cfg.model_id : null
  } catch { /* fail-soft */ }
}

async function saveModel() {
  modelError.value = ''
  modelSaved.value = false
  modelSaving.value = true
  // Spread the FULL existing config (backend replaces it wholesale), set/omit model_id.
  const nextConfig: Record<string, any> = { ...studioConfig.value }
  if (selectedModelId.value) nextConfig.model_id = selectedModelId.value
  else delete nextConfig.model_id
  try {
    const { error } = await useMyFetch<any>(`/studios/${props.studioId}`, {
      method: 'PATCH',
      body: { config: nextConfig },
    })
    if (error?.value) throw error.value
    studioConfig.value = nextConfig
    modelSaved.value = true
    if (savedTimer) clearTimeout(savedTimer)
    savedTimer = setTimeout(() => { modelSaved.value = false }, 2000)
  } catch {
    modelError.value = 'Save failed'
  } finally {
    modelSaving.value = false
  }
}

// Own train-status fetch (parent already polls for the log lines we render as a prop,
// but the segregation receipt — detail.route_inbox — we resolve here, fail-soft).
const status = ref<any>(null)
const routeInbox = computed<any>(() => (status.value && status.value.detail && status.value.detail.route_inbox) || null)
const hasTrainStatus = computed(() => !!(status.value && (status.value.status || status.value.step || status.value.detail)) || !!(props.trainLog && (props.trainLog.status || props.trainLog.step)))

const RECEIPT_STAGES = [
  { key: 'classify', label: 'classify' },
  { key: 'segregate', label: 'segregate' },
  { key: 'ingest', label: 'ingest' },
  { key: 'goldens', label: 'goldens' },
  { key: 'reconcile', label: 'reconcile' },
  { key: 'coverage', label: 'coverage' },
]
const receiptStages = computed(() => {
  const detail = (status.value && status.value.detail) || (props.trainLog && props.trainLog.detail) || {}
  const ri = routeInbox.value
  return RECEIPT_STAGES.map(s => {
    let done = false
    if (s.key === 'classify' || s.key === 'segregate') done = !!ri
    else if (s.key === 'ingest') done = !!(ri && (ri.placed || 0) >= 0 && (ri.files_in != null))
    else if (s.key === 'goldens') done = !!detail.goldens || !!detail.golden_queries
    else if (s.key === 'reconcile') done = !!ri
    else if (s.key === 'coverage') done = coverageTotalPeriods.value != null
    if (detail[s.key]) done = true
    return { ...s, done }
  })
})

// ─── LIVE PROCESS FLOW ──────────────────────────────────────────────────────
// 6 phases, each with real sub-stage nodes. State derived fail-soft from the
// same signals in scope: receiptStages done-flags (classify/segregate/ingest/
// goldens/reconcile/coverage), the train-status detail map (other nodes, via
// aliases), coverage=0 → held, and the newest `▸ <stage>` train-log marker →
// running. Missing data → 'queued'. Never throws.
const FLOW_PHASES: { id: string; label: string; keys: string[] }[] = [
  { id: 'route',   label: '① ROUTE',   keys: ['classify', 'segregate'] },
  { id: 'land',    label: '② LAND',    keys: ['ingest', 'self-heal'] },
  { id: 'profile', label: '③ PROFILE', keys: ['profile', 'deep-profile', 'index'] },
  { id: 'enrich',  label: '④ ENRICH',  keys: ['code-enrich', 'domain-packs', 'brain-graph'] },
  { id: 'learn',   label: '⑤ LEARN',   keys: ['auto-eda', 'agent-kpis', 'agent-overview'] },
  { id: 'verify',  label: '⑥ VERIFY',  keys: ['goldens', 'reconcile', 'coverage'] },
]
// keys that map straight onto receiptStages done-flags
const RECEIPT_NODE_KEYS = new Set(['classify', 'segregate', 'ingest', 'goldens', 'reconcile', 'coverage'])
// detail-map + log-marker aliases for every node
const NODE_ALIASES: Record<string, string[]> = {
  classify: ['classify'],
  segregate: ['segregate', 'segregation'],
  ingest: ['ingest', 'ingestion', 'load'],
  'self-heal': ['self-heal', 'selfheal', 'self_heal', 'heal'],
  profile: ['profile', 'profiling', 'column_profile', 'column-profile'],
  'deep-profile': ['deep-profile', 'deep_profile', 'profile_v2', 'profilev2', 'deepprofile'],
  index: ['index', 'hybrid_index', 'hybridindex', 'indexer', 'indexing'],
  'code-enrich': ['code-enrich', 'code_enrich', 'codeenrich', 'enrich'],
  'domain-packs': ['domain-packs', 'domain_packs', 'domainpacks', 'packs'],
  'brain-graph': ['brain-graph', 'brain_graph', 'braingraph', 'graph'],
  'auto-eda': ['auto-eda', 'auto_eda', 'autoeda', 'eda'],
  'agent-kpis': ['agent-kpis', 'agent_kpis', 'agentkpis', 'kpis', 'kpi'],
  'agent-overview': ['agent-overview', 'agent_overview', 'agentoverview', 'overview'],
  goldens: ['goldens', 'golden', 'golden_queries', 'goldenqueries', 'goldensql', 'golden_sql'],
  reconcile: ['reconcile', 'reconciliation'],
  coverage: ['coverage'],
}
const _norm = (s: string) => s.trim().toLowerCase().replace(/[ _]+/g, '-')

// Which node (if any) the newest `▸ <stage>` train-log line names. Only used
// while training. Returns a node key or null (never throws).
function runningNodeKey(): string | null {
  try {
    const raw = (props.trainLogLines && props.trainLogLines.length)
      ? props.trainLogLines
      : ((props.trainLog && Array.isArray((props.trainLog as any).log)) ? (props.trainLog as any).log : [])
    if (!Array.isArray(raw) || !raw.length) return null
    for (let i = raw.length - 1; i >= 0; i--) {
      const li = raw[i]
      const text = String((li && (li.text ?? li.message ?? li.line)) ?? li ?? '')
      const m = text.match(/▸\s*([a-z0-9 _-]+)/i)
      if (!m) continue
      const tok = _norm(m[1])
      for (const [k, aliases] of Object.entries(NODE_ALIASES)) {
        if (aliases.some(a => { const na = _norm(a); return na === tok || tok.startsWith(na) })) return k
      }
      return null   // a marker we don't map → no running node
    }
  } catch { /* fail-soft */ }
  return null
}

const trainFlow = computed(() => {
  const phases = FLOW_PHASES.map(p => ({ id: p.id, label: p.label, nodes: [] as { key: string; label: string; state: string }[] }))
  try {
    const rs: Record<string, boolean> = {}
    for (const s of receiptStages.value) rs[s.key] = s.done
    const detail = (status.value && status.value.detail) || (props.trainLog && (props.trainLog as any).detail) || {}
    const running = props.trainingAll ? runningNodeKey() : null
    const cov = coverageTotalPeriods.value

    const stateFor = (key: string): string => {
      if (running && running === key) return 'running'
      if (RECEIPT_NODE_KEYS.has(key)) {
        if (rs[key]) return 'done'
        if (key === 'coverage' && cov === 0) return 'held'
        return 'queued'
      }
      for (const a of (NODE_ALIASES[key] || [key])) {
        const entry = (detail as any)[a]
        if (entry == null) continue
        if (typeof entry === 'object') {
          const st = String(entry.state || entry.status || '').toLowerCase()
          if (['ok', 'done', 'complete', 'completed', 'success'].includes(st)) return 'done'
          if (['err', 'error', 'failed', 'skip', 'skipped', 'held'].includes(st)) return 'held'
          if (['running', 'active', 'in_progress', 'in-progress'].includes(st)) return 'running'
          return 'done'   // recorded object, no recognizable state → treat as done
        }
        if (entry) return 'done'
      }
      return 'queued'
    }

    for (const p of phases) {
      const src = FLOW_PHASES.find(x => x.id === p.id)!
      p.nodes = src.keys.map(k => ({ key: k, label: k, state: stateFor(k) }))
    }
  } catch {
    for (const p of phases) {
      const src = FLOW_PHASES.find(x => x.id === p.id)
      p.nodes = (src ? src.keys : []).map(k => ({ key: k, label: k, state: 'queued' }))
    }
  }
  return phases
})

const _flowNodes = computed(() => trainFlow.value.flatMap(p => p.nodes))
const flowPct = computed(() => {
  const nodes = _flowNodes.value
  if (!nodes.length) return 0
  return Math.round(100 * nodes.filter(n => n.state === 'done').length / nodes.length)
})
const flowAllDone = computed(() => {
  const nodes = _flowNodes.value
  return nodes.length > 0 && nodes.every(n => n.state === 'done')
})

const byDestEntries = computed<[string, number][]>(() => {
  const bd = (routeInbox.value && routeInbox.value.by_dest) || {}
  return Object.entries(bd).filter(([, n]) => Number(n) > 0) as [string, number][]
})

const DEST_EMOJI: Record<string, string> = {
  database: '📊', semantic: '🔖', instructions: '📋', examples: '📋', knowledge: '📖', skip: '⏸',
}
const DEST_SHORT: Record<string, string> = {
  database: 'data', semantic: 'glossary', instructions: 'instr', examples: 'examples', knowledge: 'def', skip: '?',
}
const destEmoji = (d: string) => DEST_EMOJI[d] || '•'
const destShort = (d: string) => DEST_SHORT[d] || d

// Coverage pill — fail-soft (hide if endpoint 404s).
const coverageTotalPeriods = ref<number | null>(null)
async function loadCoverage() {
  if (!props.studioId) return
  try {
    const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/coverage`)
    if (error?.value) { coverageTotalPeriods.value = null; return }
    const srcs: any[] = Array.isArray((data.value as any)?.sources) ? (data.value as any).sources : []
    let total = 0
    for (const s of srcs) for (const t of (s.tables || [])) total += Number(t.n_periods || (Array.isArray(t.periods) ? t.periods.length : 0)) || 0
    coverageTotalPeriods.value = srcs.length ? total : null
  } catch { coverageTotalPeriods.value = null }
}

async function loadStatus() {
  if (!props.studioId) return
  try {
    const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/train/status`, { method: 'GET' })
    if (error?.value) return
    const st = (data.value as any) || {}
    if (st && (st.status || st.step || st.detail)) status.value = st
  } catch { /* fail-soft */ }
}

// Poll train status every 2s while training; refresh coverage when training ends.
let timer: any = null
watch(() => props.trainingAll, (now, prev) => {
  if (now && !timer) {
    timer = setInterval(() => { loadStatus() }, 2000)
  } else if (!now && timer) {
    clearInterval(timer); timer = null
    loadStatus(); loadCoverage()
    try { inboxRef.value?.refresh?.() } catch { /* */ }
  }
})

// Parent calls this (via ref) after an inline upload queues files → refresh the
// embedded Inbox rows + train status so the newly-queued files appear.
function refresh() {
  try { inboxRef.value?.refresh?.() } catch { /* fail-soft */ }
  loadStatus()
}
defineExpose({ refresh })

onMounted(() => { loadStatus(); loadCoverage(); loadModelList(); loadStudioModel() })
onBeforeUnmount(() => {
  if (timer) { clearInterval(timer); timer = null }
  if (savedTimer) { clearTimeout(savedTimer); savedTimer = null }
})
</script>

<style scoped>
/* LIVE PROCESS FLOW — warm clay/cream palette to match the TRAIN card */
.flow-bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.flow-bar { flex: 1; height: 5px; border-radius: 999px; background: #EDE5D8; overflow: hidden; }
.flow-bar-fill { height: 100%; background: #C2541E; border-radius: 999px; transition: width .4s ease; }
.flow-status { font-size: 10.5px; font-weight: 600; color: #9a958c; white-space: nowrap; }
.flow-status-run { color: #C2541E; }
.flow-status-done { color: #3f9e6a; }

.flow-phases { display: flex; flex-wrap: wrap; align-items: flex-start; gap: 6px; }
.flow-phase {
  display: flex; flex-direction: column; gap: 4px; min-width: 96px;
  padding: 6px 8px; border: 1px solid #ECE3D6; border-radius: 10px; background: #FBF8F3;
}
.flow-phase-active { border-color: #E7C79E; background: #FBF3E7; }
.flow-phase-head {
  font-size: 9.5px; font-weight: 700; letter-spacing: .04em;
  color: #9a958c; text-transform: uppercase;
}
.flow-phase-active .flow-phase-head { color: #C2541E; }

.flow-nodes { display: flex; flex-direction: column; gap: 2px; }
.flow-node { display: flex; align-items: center; gap: 5px; font-size: 10.5px; line-height: 1.3; }
.flow-glyph { width: 11px; flex-shrink: 0; text-align: center; font-size: 10px; }

.flow-node.st-done { color: #3f9e6a; }
.flow-node.st-done .flow-glyph { color: #3f9e6a; }
.flow-node.st-running { color: #c98a2e; font-weight: 600; }
.flow-node.st-running .flow-glyph { color: #c98a2e; display: inline-block; animation: flow-spin 1s linear infinite; }
.flow-node.st-held { color: #9a958c; }
.flow-node.st-held .flow-glyph { color: #b7b0a4; }
.flow-node.st-queued { color: #b7b0a4; }
.flow-node.st-queued .flow-glyph { color: #cfc8bb; }

.flow-arrow {
  align-self: center; padding: 0 1px;
  color: #cbb9a3; font-size: 15px; font-weight: 400; user-select: none;
}

@keyframes flow-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .flow-node.st-running .flow-glyph { animation: none; }
}
</style>
