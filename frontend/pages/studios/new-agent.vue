<template>
  <div class="h-full overflow-y-auto bg-[#F5F4EE] flex items-start justify-center px-4 py-8">
    <div class="w-full max-w-2xl bg-white border border-[#E7E5DD] rounded-2xl shadow-sm overflow-hidden">
      <!-- ── Step crumb ─────────────────────────────────────────────── -->
      <div class="px-6 pt-5">
        <div class="flex items-center gap-1.5">
          <template v-for="(s, i) in stepLabels" :key="s">
            <div class="flex items-center gap-2 text-[11px]"
              :class="step > i + 1 || step === i + 1 ? 'text-[#1f2328] font-semibold' : 'text-[#9a958c]'">
              <span class="w-[22px] h-[22px] rounded-full border flex items-center justify-center text-[11px] font-bold"
                :class="step === i + 1
                  ? 'bg-[#C2683F] border-[#C2683F] text-white'
                  : step > i + 1
                    ? 'bg-[#E7F2EC] border-[#cde6d8] text-[#3f9e6a]'
                    : 'bg-white border-[#E7E5DD] text-[#9a958c]'">
                <UIcon v-if="step > i + 1" name="i-heroicons-check" class="w-3 h-3" />
                <span v-else>{{ i + 1 }}</span>
              </span>
              {{ s }}
            </div>
            <div v-if="i < stepLabels.length - 1" class="flex-1 h-[1.5px] mx-0.5"
              :class="step > i + 1 ? 'bg-[#cde6d8]' : 'bg-[#E7E5DD]'"></div>
          </template>
        </div>
      </div>

      <!-- ── Body ───────────────────────────────────────────────────── -->
      <div class="px-6 pt-2 min-h-[320px]">
        <!-- STEP 1 — NAME -->
        <div v-if="step === 1">
          <h2 class="text-[19px] font-semibold" style="font-family: ui-serif, Georgia, serif">Name your agent</h2>
          <p class="text-[12.5px] text-[#6b6b6b] mt-0.5 mb-4">
            A studio wraps your data and the agent that answers on it. Avatar, voice and summary are auto-written for you.
          </p>

          <label class="block text-xs font-semibold text-[#6b6b6b] mb-1.5">Agent name</label>
          <input
            v-model="name"
            type="text"
            placeholder="e.g. Sales CRM, Finance, Inventory"
            class="w-full border border-[#E7E5DD] rounded-lg px-3 py-2 text-[13px] outline-none focus:border-[#C2683F] focus:ring-2 focus:ring-[#FBF6F2]"
          />

          <label class="block text-xs font-semibold text-[#6b6b6b] mt-3 mb-1.5">
            What is it for?
            <span class="font-normal text-[#9a958c]">(optional — helps the AI tune its voice)</span>
          </label>
          <textarea
            v-model="description"
            rows="2"
            placeholder="e.g. Customer call records & brand switching for the field team"
            class="w-full border border-[#E7E5DD] rounded-lg px-3 py-2 text-[13px] outline-none focus:border-[#C2683F] focus:ring-2 focus:ring-[#FBF6F2]"
          />

          <label class="block text-xs font-semibold text-[#6b6b6b] mt-3 mb-1.5">Who can see it?</label>
          <div class="inline-flex border border-[#E7E5DD] rounded-lg overflow-hidden">
            <button
              v-for="opt in shareOptions"
              :key="opt.value"
              type="button"
              class="text-xs px-3 py-1.5 border-l first:border-l-0 border-[#E7E5DD]"
              :class="shareScope === opt.value ? 'bg-[#FBF6F2] text-[#A8542F] font-semibold' : 'bg-white text-[#6b6b6b]'"
              @click="shareScope = opt.value"
            >{{ opt.label }}</button>
          </div>
        </div>

        <!-- STEP 2 — DATA -->
        <div v-else-if="step === 2">
          <h2 class="text-[19px] font-semibold" style="font-family: ui-serif, Georgia, serif">Add your data</h2>
          <p class="text-[12.5px] text-[#6b6b6b] mt-0.5 mb-4">
            Upload a file or pin a data agent your organization already has.
          </p>

          <div class="inline-flex border border-[#E7E5DD] rounded-lg overflow-hidden mb-3">
            <button
              type="button"
              class="text-xs px-3 py-1.5"
              :class="dataMode === 'upload' ? 'bg-[#FBF6F2] text-[#A8542F] font-semibold' : 'bg-white text-[#6b6b6b]'"
              @click="dataMode = 'upload'"
            >Upload file</button>
            <button
              type="button"
              class="text-xs px-3 py-1.5 border-l border-[#E7E5DD]"
              :class="dataMode === 'pin' ? 'bg-[#FBF6F2] text-[#A8542F] font-semibold' : 'bg-white text-[#6b6b6b]'"
              @click="onSelectPin"
            >Pin existing</button>
          </div>

          <!-- UPLOAD -->
          <div v-if="dataMode === 'upload'">
            <div
              class="border-2 border-dashed border-[#E8C9B5] rounded-xl p-6 text-center cursor-pointer transition hover:border-[#C2683F] hover:bg-[#FBF6F2]"
              @click="fileInput?.click()"
              @dragover.prevent
              @drop.prevent="onDrop"
            >
              <UIcon name="i-heroicons-arrow-up-tray" class="w-8 h-8 mx-auto text-[#C2683F]" />
              <div class="text-[13px] font-semibold text-[#C2683F] mt-2">Click or drag .csv / .xlsx</div>
              <div class="text-[11px] text-[#9a958c] mt-0.5">We discover the tables &amp; columns automatically</div>
            </div>
            <input ref="fileInput" type="file" accept=".csv,.xlsx,.xls" class="hidden" @change="onFilePicked" />

            <div v-if="uploadFileName" class="mt-3 flex items-center gap-2.5 border border-[#F0EEE6] bg-[#FBFAF6] rounded-lg px-3 py-2 text-[12.5px]">
              <span class="w-6 h-6 rounded-md bg-white border border-[#F0EEE6] flex items-center justify-center">
                <UIcon v-if="uploading" name="i-heroicons-arrow-path" class="w-3.5 h-3.5 text-[#C2683F] animate-spin" />
                <UIcon v-else-if="createdDataSourceId" name="i-heroicons-check" class="w-3.5 h-3.5 text-[#3f9e6a]" />
                <UIcon v-else name="i-heroicons-document" class="w-3.5 h-3.5 text-[#9a958c]" />
              </span>
              <span class="truncate">
                {{ uploadFileName }}
                <span v-if="uploading" class="text-[#9a958c]"> · uploading…</span>
                <span v-else-if="discoveredTables" class="text-[#9a958c]"> · {{ discoveredTables }} table(s) discovered</span>
              </span>
            </div>
          </div>

          <!-- PIN EXISTING -->
          <div v-else>
            <div v-if="loadingAgents" class="py-8 text-center text-xs text-[#9a958c]">Loading data agents…</div>
            <div v-else-if="!existingAgents.length" class="py-8 text-center text-xs text-[#9a958c]">
              No existing data agents — switch to Upload file.
            </div>
            <div v-else class="space-y-2 max-h-[220px] overflow-y-auto">
              <button
                v-for="a in existingAgents"
                :key="a.id"
                type="button"
                class="w-full flex items-center gap-2.5 border rounded-lg px-3 py-2 text-[12.5px] text-left transition"
                :class="pinnedAgentId === String(a.id)
                  ? 'border-[#C2683F] bg-[#FBF6F2]'
                  : 'border-[#E7E5DD] hover:border-[#d8d4ca]'"
                @click="pinnedAgentId = String(a.id)"
              >
                <UIcon name="i-heroicons-circle-stack" class="w-4 h-4 text-[#C2683F] shrink-0" />
                <span class="truncate flex-1">{{ a.name || 'Data source' }}</span>
                <UIcon v-if="pinnedAgentId === String(a.id)" name="i-heroicons-check-circle" class="w-4 h-4 text-[#C2683F]" />
              </button>
            </div>
          </div>
        </div>

        <!-- STEP 3 — TRAIN -->
        <div v-else-if="step === 3" class="text-center">
          <h2 class="text-[19px] font-semibold" style="font-family: ui-serif, Georgia, serif">Training your agent</h2>
          <p class="text-[12.5px] text-[#6b6b6b] mt-0.5 mb-4">
            Profiling columns, learning values, writing examples and artifacts — all in the background.
          </p>

          <div class="relative w-24 h-24 mx-auto mb-3">
            <svg width="96" height="96" style="transform: rotate(-90deg)">
              <circle cx="48" cy="48" r="40" stroke="#F0E2D7" stroke-width="9" fill="none" />
              <circle
                cx="48" cy="48" r="40" stroke="#C2683F" stroke-width="9" fill="none" stroke-linecap="round"
                stroke-dasharray="251" :stroke-dashoffset="251 - 251 * trainPct / 100"
                style="transition: stroke-dashoffset .4s ease"
              />
            </svg>
            <div class="absolute inset-0 flex flex-col items-center justify-center">
              <span class="text-2xl" style="font-family: ui-serif, Georgia, serif">{{ trainPct }}</span>
              <span class="text-[9px] uppercase tracking-wide text-[#9a958c]">ready</span>
            </div>
          </div>

          <p class="text-xs text-[#6b6b6b] capitalize">{{ trainStep || 'starting' }}</p>
          <p v-if="trainError" class="text-xs text-red-500 mt-2">{{ trainError }}</p>
        </div>

        <!-- STEP 4 — READY -->
        <div v-else-if="step === 4" class="text-center">
          <div class="w-[52px] h-[52px] rounded-full bg-[#E7F2EC] text-[#3f9e6a] flex items-center justify-center mx-auto mb-2">
            <UIcon name="i-heroicons-check" class="w-6 h-6" />
          </div>
          <h2 class="text-[19px] font-semibold" style="font-family: ui-serif, Georgia, serif">
            {{ name || 'Your agent' }} is ready
          </h2>
          <p class="text-[12.5px] text-[#6b6b6b] mt-0.5 mb-4">
            Grounded on your data. Ask it anything — or open the agent to manage.
          </p>

          <div v-if="readyCounts.length" class="grid grid-cols-3 gap-2 mt-2">
            <div v-for="c in readyCounts" :key="c.label" class="border border-[#E7E5DD] rounded-lg py-2 text-center">
              <div class="text-[17px] font-bold" style="font-family: ui-serif, Georgia, serif">{{ c.n }}</div>
              <div class="text-[9.5px] uppercase text-[#9a958c]">{{ c.label }}</div>
            </div>
          </div>

          <div class="flex flex-col gap-2 mt-5">
            <button
              type="button"
              class="text-[13px] font-semibold rounded-lg px-4 py-2.5 bg-[#C2683F] hover:bg-[#A8542F] text-white"
              @click="openAgent"
            >Open agent</button>
            <button
              type="button"
              class="text-[13px] font-semibold rounded-lg px-4 py-2.5 border border-[#E7E5DD] text-[#1f2328] hover:bg-[#FBFAF6]"
              @click="startChatting"
            >Start chatting</button>
          </div>
        </div>
      </div>

      <!-- ── Footer ─────────────────────────────────────────────────── -->
      <div class="flex justify-between items-center px-6 py-4 border-t border-[#F0EEE6] mt-4">
        <button
          v-if="step < 4"
          type="button"
          class="text-xs text-[#9a958c] hover:text-[#6b6b6b]"
          @click="skipAndSetUpLater"
        >Skip &amp; set up later</button>
        <span v-else></span>

        <div class="flex gap-2">
          <button
            v-if="step > 1 && step < 4"
            type="button"
            class="text-[13px] font-semibold rounded-lg px-4 py-2 text-[#6b6b6b] hover:text-[#1f2328]"
            @click="back"
          >Back</button>

          <button
            v-if="step === 3"
            type="button"
            class="text-[13px] font-semibold rounded-lg px-4 py-2 border border-[#E7E5DD] text-[#6b6b6b] hover:bg-[#FBFAF6]"
            @click="skipTraining"
          >Skip — finish in background</button>

          <button
            v-if="step < 4"
            type="button"
            class="text-[13px] font-semibold rounded-lg px-[18px] py-2 bg-[#C2683F] hover:bg-[#A8542F] text-white disabled:opacity-50 disabled:cursor-default inline-flex items-center gap-1.5"
            :disabled="continueDisabled"
            @click="onContinue"
          >
            <UIcon v-if="busy" name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin" />
            {{ continueLabel }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ auth: true, layout: 'default' })

const router = useRouter()
const toast = useToast()

const stepLabels = ['Name', 'Data', 'Train', 'Ready']
const step = ref(1)
const busy = ref(false)

// ── Step 1 state ──────────────────────────────────────────────────────
const name = ref('')
const description = ref('')
const shareScope = ref<'private' | 'org' | 'link'>('private')
const shareOptions = [
  { value: 'private', label: 'Private' },
  { value: 'org', label: 'Org' },
  { value: 'link', label: 'Link' },
] as const

// ── Step 2 state ──────────────────────────────────────────────────────
const dataMode = ref<'upload' | 'pin'>('upload')
const fileInput = ref<HTMLInputElement | null>(null)
const uploadFile = ref<File | null>(null)
const uploadFileName = ref('')
const uploading = ref(false)
const createdDataSourceId = ref<string | null>(null)
const discoveredTables = ref<number>(0)

const existingAgents = ref<any[]>([])
const loadingAgents = ref(false)
const pinnedAgentId = ref<string>('')

// ── Created studio ────────────────────────────────────────────────────
const studioId = ref<string>('')

// ── Step 3 (train) state ──────────────────────────────────────────────
const trainPct = ref(0)
const trainStep = ref('')
const trainError = ref('')
let pollTimer: any = null

// ── Computed ──────────────────────────────────────────────────────────
const continueLabel = computed(() => {
  if (step.value === 1) return 'Add data'
  if (step.value === 2) return 'Auto-train'
  if (step.value === 3) return 'Training…'
  return 'Open agent'
})

const continueDisabled = computed(() => {
  if (busy.value) return true
  if (step.value === 1) return !name.value.trim()
  if (step.value === 2) {
    if (dataMode.value === 'upload') return !createdDataSourceId.value
    return !pinnedAgentId.value
  }
  if (step.value === 3) return true
  return false
})

const readyCounts = computed(() => {
  // Best-effort counts pulled from train status detail (fail-soft → []).
  const out: { n: number | string; label: string }[] = []
  const intCount = (v: any): number | null => {
    if (typeof v === 'number') return v
    if (v && typeof v === 'object') {
      for (const k of ['count', 'created', 'written', 'generated']) {
        if (typeof v[k] === 'number') return v[k]
      }
    }
    return null
  }
  const q = intCount(trainDetail.value?.queries)
  const e = intCount(trainDetail.value?.evals)
  if (q != null) out.push({ n: q, label: 'queries' })
  if (e != null) out.push({ n: e, label: 'goldens' })
  if (out.length) out.unshift({ n: discoveredTables.value || '—', label: 'tables' })
  return out
})
const trainDetail = ref<Record<string, any>>({})

// ── Helpers ───────────────────────────────────────────────────────────
function back() {
  if (step.value > 1) step.value -= 1
}

async function ensureStudio(): Promise<string | null> {
  // Create the studio once (idempotent — reuse if already created).
  if (studioId.value) return studioId.value
  try {
    const { data, error } = await useMyFetch<any>('/studios', {
      method: 'POST',
      body: {
        name: name.value.trim(),
        description: description.value.trim() || null,
        share_scope: shareScope.value,
      },
    })
    if (error?.value) throw error.value
    const id = (data.value as any)?.id
    if (!id) throw new Error('no studio id returned')
    studioId.value = String(id)
    return studioId.value
  } catch (e: any) {
    toast.add({ title: 'Could not create the agent', description: e?.data?.detail || String(e?.message || e), color: 'red' })
    return null
  }
}

// ── Step 2: file upload ───────────────────────────────────────────────
function onFilePicked(ev: Event) {
  const f = (ev.target as HTMLInputElement).files?.[0]
  if (f) uploadAndCreate(f)
}
function onDrop(ev: DragEvent) {
  const f = ev.dataTransfer?.files?.[0]
  if (f) uploadAndCreate(f)
}

async function uploadAndCreate(f: File) {
  uploadFile.value = f
  uploadFileName.value = f.name
  createdDataSourceId.value = null
  discoveredTables.value = 0
  uploading.value = true
  try {
    // 1. POST /files (multipart, field `file`) → { id }
    const fd = new FormData()
    fd.append('file', f)
    const up = await useMyFetch<any>('/files', { method: 'POST', body: fd })
    if (up.error?.value || !up.data?.value) {
      throw new Error((up.error?.value as any)?.data?.detail || 'upload failed')
    }
    const fileId = (up.data.value as any).id

    // 2. POST /data_sources/from-file → DataSource (+ tables[])
    const ds = await useMyFetch<any>('/data_sources/from-file', {
      method: 'POST',
      body: {
        file_id: fileId,
        data_source_name: name.value.trim() || f.name.replace(/\.[^.]+$/, ''),
        description: description.value.trim() || null,
      },
    })
    if (ds.error?.value || !ds.data?.value) {
      throw new Error((ds.error?.value as any)?.data?.detail || 'could not read the file')
    }
    const dsBody = ds.data.value as any
    createdDataSourceId.value = String(dsBody.id)
    discoveredTables.value = Array.isArray(dsBody.tables) ? dsBody.tables.length : 0
    toast.add({ title: 'File uploaded', color: 'green', icon: 'i-heroicons-check-circle' })
  } catch (e: any) {
    uploadFileName.value = ''
    toast.add({ title: 'Upload failed', description: e?.data?.detail || String(e?.message || e), color: 'red' })
  } finally {
    uploading.value = false
  }
}

// ── Step 2: pin existing ──────────────────────────────────────────────
async function onSelectPin() {
  dataMode.value = 'pin'
  if (existingAgents.value.length || loadingAgents.value) return
  loadingAgents.value = true
  try {
    const { data, error } = await useMyFetch<any[]>('/data_sources', { method: 'GET' })
    if (error?.value) throw error.value
    existingAgents.value = data.value || []
  } catch (e: any) {
    existingAgents.value = []
    toast.add({ title: 'Could not load data agents', color: 'red' })
  } finally {
    loadingAgents.value = false
  }
}

async function pinSourceToStudio(sid: string, agentId: string): Promise<boolean> {
  try {
    const { error } = await useMyFetch(`/studios/${sid}/sources`, {
      method: 'POST',
      body: { agent_id: String(agentId) },
    })
    if (error?.value) throw error.value
    return true
  } catch (e: any) {
    toast.add({ title: 'Could not attach the data', description: e?.data?.detail || String(e?.message || e), color: 'red' })
    return false
  }
}

// ── Continue dispatcher ───────────────────────────────────────────────
async function onContinue() {
  if (busy.value) return
  busy.value = true
  try {
    if (step.value === 1) {
      const sid = await ensureStudio()
      if (!sid) return
      step.value = 2
      return
    }
    if (step.value === 2) {
      const sid = await ensureStudio()
      if (!sid) return
      const agentId = dataMode.value === 'upload' ? createdDataSourceId.value : pinnedAgentId.value
      if (!agentId) return
      const ok = await pinSourceToStudio(sid, agentId)
      if (!ok) return
      step.value = 3
      await startTraining(sid)
      return
    }
  } finally {
    busy.value = false
  }
}

// ── Step 3: training (non-blocking poll) ──────────────────────────────
async function startTraining(sid: string) {
  trainPct.value = 0
  trainStep.value = 'starting'
  trainError.value = ''
  try {
    // Kick the async pipeline — returns immediately.
    await useMyFetch(`/studios/${sid}/train`, { method: 'POST' }).catch(() => {})
  } catch { /* fail-soft — keep polling */ }
  pollStatus(sid)
}

function pollStatus(sid: string) {
  stopPolling()
  pollTimer = setInterval(async () => {
    if (step.value !== 3) { stopPolling(); return }
    try {
      const { data } = await useMyFetch<any>(`/studios/${sid}/train/status`, { method: 'GET' })
      const s = (data.value as any) || {}
      if (typeof s.pct === 'number') trainPct.value = Math.max(0, Math.min(100, s.pct))
      if (s.step) trainStep.value = String(s.step)
      if (s.detail && typeof s.detail === 'object') trainDetail.value = s.detail
      if (s.status === 'done') { trainPct.value = 100; finishTraining() }
      else if (s.status === 'error') { trainError.value = s.error || 'Training failed'; finishTraining() }
    } catch { /* fail-soft — keep polling */ }
  }, 1500)
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function finishTraining() {
  stopPolling()
  step.value = 4
}

// "Skip — finish in background": jump to ready, training keeps running.
function skipTraining() {
  stopPolling()
  step.value = 4
}

// ── Footer actions ────────────────────────────────────────────────────
async function skipAndSetUpLater() {
  // Create studio (if not yet) without training, then land on it.
  const sid = await ensureStudio()
  if (sid) router.push(`/studios/${sid}`)
}

function openAgent() {
  if (studioId.value) router.push(`/studios/${studioId.value}`)
  else router.push('/studios')
}

function startChatting() {
  router.push('/reports/new')
}

onBeforeUnmount(stopPolling)
</script>
