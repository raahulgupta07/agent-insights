<template>
  <!-- Inbox → Train. Files dropped in "inbox" mode queue here (sorted when you Train);
       low-confidence guesses surface in REVIEW for a human call. Warm clay style,
       mirrors StudioSelfLearn / StudioConnectors. Flag-gated by the parent (HYBRID_TRAIN_ROUTING). -->
  <div class="rounded-2xl border border-[#E9E0D3] bg-[#FBFAF6] p-4 mb-4">
    <div class="flex items-center justify-between gap-2 mb-1">
      <h3 class="text-sm font-semibold text-[#1f2328] flex items-center gap-1.5" style="font-family: 'Spectral', ui-serif, Georgia, serif">
        <span class="text-[#C2541E]">&#128229;</span> Inbox &middot; {{ queued.length }} queued
      </h3>
      <button v-if="queued.length" type="button" :disabled="busy"
        class="text-[10.5px] font-semibold text-[#6b6b6b] border border-[#E9E0D3] rounded-md px-2.5 py-1 hover:bg-white disabled:opacity-50"
        @click="clearAll">Clear all</button>
    </div>
    <p class="text-[11.5px] text-[#6b6b6b] mb-3 max-w-[520px]">
      Queued files wait here &mdash; the router sorts each into its lane when you <b>Train</b>. Nothing is imported until then.
    </p>

    <div v-if="loading" class="text-[11px] text-[#9a958c] py-2">Loading inbox&hellip;</div>

    <template v-else>
      <!-- error -->
      <div v-if="error" class="mb-3 rounded-lg border border-[#f0c8b8] bg-[#FFF1EA] px-3 py-2 text-[11.5px] text-[#A8330F]">{{ error }}</div>

      <!-- QUEUED -->
      <div v-if="queued.length" class="space-y-1.5 mb-3">
        <div v-for="f in queued" :key="f.file_id"
          class="flex items-center gap-2.5 bg-white border border-[#ECE7E0] rounded-lg px-3 py-2">
          <span class="text-[#C2541E]">&#128196;</span>
          <div class="min-w-0 flex-1">
            <div class="text-[12.5px] font-medium text-[#1f2328] truncate">{{ f.filename }}</div>
            <div class="text-[10.5px] text-[#9a958c] flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
              <span v-if="fmtWhen(f.queued_at)">{{ fmtWhen(f.queued_at) }}</span>
              <template v-if="fmtWhen(f.queued_at) && humanSize(f.size)">&middot;</template>
              <span v-if="humanSize(f.size)">{{ humanSize(f.size) }}</span>
              <template v-if="typeLabel(f)">&middot;</template>
              <span v-if="typeLabel(f)" class="uppercase tracking-wide">{{ typeLabel(f) }}</span>
            </div>
          </div>
          <!-- instant type-guess chip (guessed lane + confidence) -->
          <span v-if="laneOf(f)" class="shrink-0 inline-flex items-center gap-1 text-[10px] font-semibold rounded-full border px-2 py-0.5" :class="chipFor(laneOf(f)).cls" :title="signalsSummary(f.guess && f.guess.signals)">
            {{ chipFor(laneOf(f)).emoji }} {{ chipFor(laneOf(f)).label }}<span v-if="confPct(confOfFile(f))" class="opacity-70">· {{ confPct(confOfFile(f)) }}</span>
          </span>
          <!-- re-route: change the lane before training (updates the inbox, no import) -->
          <div class="relative shrink-0">
            <select v-model="f._reroute" :disabled="busy" @change="rerouteQueued(f)"
              class="appearance-none text-[10.5px] font-medium rounded-lg border border-[#E9E0D3] bg-white pl-2 pr-6 py-1 cursor-pointer focus:outline-none focus:border-[#C2541E] text-[#6b6b6b] disabled:opacity-50">
              <option value="">Re-route…</option>
              <option v-for="d in DESTS" :key="d" :value="d">{{ destLabel(d) }}</option>
            </select>
            <UIcon name="i-heroicons-chevron-down" class="w-3 h-3 absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none text-[#9a958c]" />
          </div>
          <button type="button" :disabled="busy" title="Remove from inbox"
            class="text-[#b3ac9f] hover:text-[#C0392B] disabled:opacity-50 shrink-0"
            @click="removeQueued(f.file_id)">
            <UIcon name="i-heroicons-x-mark" class="w-4 h-4" />
          </button>
        </div>
      </div>
      <!-- empty state -->
      <div v-else class="text-[11.5px] text-[#9a958c] bg-white border border-dashed border-[#E9E0D3] rounded-lg px-3 py-4 text-center mb-3">
        Inbox empty &mdash; drop files to queue them, they&rsquo;ll be sorted when you Train.
      </div>

      <!-- REVIEW (held / low-confidence) -->
      <template v-if="held.length">
        <div class="flex items-center gap-1.5 mb-2 mt-1">
          <h4 class="text-[11px] font-bold uppercase tracking-wide text-[#9A6A12]">Review ({{ held.length }})</h4>
          <span class="text-[10.5px] text-[#9a958c]">&mdash; the router wasn&rsquo;t sure; pick a home</span>
        </div>
        <div v-for="h in held" :key="h.file_id"
          class="border border-[#F0E3C8] bg-[#FBF6EA] rounded-xl px-3 py-2.5 mb-2">
          <div class="flex items-start gap-2">
            <span class="text-[#9A6A12] mt-0.5">&#9888;</span>
            <div class="min-w-0 flex-1">
              <div class="text-[12.5px] font-semibold text-[#1f2328] truncate">{{ h.filename }}</div>
              <div class="text-[10.5px] text-[#8a7333] mt-0.5">
                guessed <b>{{ destLabel(h.dest) }}</b>
                <template v-if="h.confidence != null"> &middot; {{ Math.round((h.confidence || 0) * (h.confidence > 1 ? 1 : 100)) }}%</template>
              </div>
              <div v-if="h.reason" class="text-[11px] text-[#6b6b6b] mt-1.5 bg-white/70 rounded-md px-2 py-1">{{ h.reason }}</div>
              <div v-if="v2 && (h.source || signalsSummary(h.signals))" class="text-[10px] text-[#9a857a] mt-1 flex flex-wrap items-center gap-1.5">
                <span v-if="h.source" class="inline-flex items-center rounded-full bg-white/70 border border-[#ecdfc1] px-1.5 py-0.5">{{ h.source }}</span>
                <span v-if="signalsSummary(h.signals)" class="truncate">{{ signalsSummary(h.signals) }}</span>
              </div>
            </div>
          </div>
          <div class="flex items-center gap-2 mt-2.5 flex-wrap">
            <div class="relative">
              <select v-model="h._dest"
                class="appearance-none text-[11.5px] font-medium rounded-lg border border-[#E9E0D3] bg-white pl-2.5 pr-7 py-1.5 cursor-pointer focus:outline-none focus:border-[#C2541E] text-[#1f2328]">
                <option v-for="d in DESTS" :key="d" :value="d">{{ destLabel(d) }}</option>
              </select>
              <UIcon name="i-heroicons-chevron-down" class="w-3.5 h-3.5 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none text-[#9a958c]" />
            </div>
            <button type="button" :disabled="busy"
              class="text-[11.5px] font-semibold text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-lg px-3 py-1.5 disabled:opacity-50"
              @click="confirmHeld(h)">Confirm {{ destLabel(h._dest) }}</button>
            <button type="button" :disabled="busy"
              class="text-[11.5px] font-semibold text-[#6b6b6b] border border-[#E9E0D3] rounded-lg px-3 py-1.5 hover:bg-white disabled:opacity-50"
              @click="skipHeld(h)">Skip</button>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
interface Guess { dest?: string; confidence?: number; source?: string; signals?: any }
interface QueuedFile {
  file_id: string; filename: string; size?: number; status?: string
  dest?: string; confidence?: number; content_type?: string; ext?: string
  queued_at?: string; dest_source?: string; guess?: Guess; _reroute?: string
}
interface HeldFile { file_id: string; filename: string; dest: string; confidence?: number; reason?: string; source?: string; signals?: any; _dest?: string }

const props = withDefaults(defineProps<{ studioId: string; v2?: boolean }>(), { v2: false })

const DESTS = ['database', 'semantic', 'instructions', 'examples', 'knowledge', 'skip']
const DEST_LABEL: Record<string, string> = {
  database: 'Database', semantic: 'Semantic', instructions: 'Instructions',
  examples: 'Examples', knowledge: 'Knowledge', skip: 'Skip',
}
const destLabel = (d?: string) => DEST_LABEL[d || ''] || d || 'database'

// v2 type-guess chip: dest → {emoji, label, lane color}.
const DEST_CHIP: Record<string, { emoji: string; label: string; cls: string }> = {
  database: { emoji: '📊', label: 'data', cls: 'bg-[#E7F1EB] text-[#2F6F4F] border-[#cfe3d6]' },
  semantic: { emoji: '🔖', label: 'glossary', cls: 'bg-[#E4F0F4] text-[#1F6F8B] border-[#cfe2e8]' },
  instructions: { emoji: '📋', label: 'instr', cls: 'bg-[#F6EEDD] text-[#9A6A12] border-[#ecdfc1]' },
  examples: { emoji: '📋', label: 'instr', cls: 'bg-[#F6EEDD] text-[#9A6A12] border-[#ecdfc1]' },
  knowledge: { emoji: '📖', label: 'def', cls: 'bg-[#ECEAFB] text-[#5A4FCF] border-[#dcd8f3]' },
  skip: { emoji: '⏸', label: '?', cls: 'bg-[#F3F0E9] text-[#9a958c] border-[#E9E0D3]' },
}
const chipFor = (d?: string) => DEST_CHIP[d || ''] || DEST_CHIP.skip
function confPct(c?: number): string {
  if (c == null) return ''
  return `${Math.round((c || 0) * (c > 1 ? 1 : 100))}%`
}
function signalsSummary(sig: any): string {
  if (!sig) return ''
  if (typeof sig === 'string') return sig
  if (Array.isArray(sig)) return sig.slice(0, 3).map(String).join(' · ')
  if (typeof sig === 'object') {
    return Object.entries(sig).slice(0, 3).map(([k, v]) => (v === true ? k : `${k}: ${v}`)).join(' · ')
  }
  return String(sig)
}

const loading = ref(true)
const busy = ref(false)
const error = ref('')
const queued = ref<QueuedFile[]>([])
const held = ref<HeldFile[]>([])

function humanSize(n?: number): string {
  if (!n && n !== 0) return ''
  const b = Number(n)
  if (!isFinite(b) || b < 0) return ''
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  if (b < 1024 * 1024 * 1024) return `${(b / (1024 * 1024)).toFixed(1)} MB`
  return `${(b / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

// queued_at (ISO) → "Jul 5, 2:14 PM". Empty if unparseable.
function fmtWhen(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

// Short type label from ext or filename (e.g. "CSV", "PDF").
function typeLabel(f: QueuedFile): string {
  let e = (f.ext || '').replace(/^\./, '')
  if (!e && f.filename && f.filename.includes('.')) e = f.filename.split('.').pop() || ''
  return e ? e.toUpperCase() : ''
}

// Effective guessed lane + confidence: the stored classify result first,
// falling back to the v2 sniff guess.
function laneOf(f: QueuedFile): string | undefined { return f.dest || f.guess?.dest }
function confOfFile(f: QueuedFile): number | undefined {
  return f.confidence != null ? f.confidence : f.guess?.confidence
}

function applyResult(d: any) {
  queued.value = (Array.isArray(d?.queued) ? d.queued : []).map((q: QueuedFile) => ({ ...q, _reroute: q.dest || '' }))
  held.value = (Array.isArray(d?.held) ? d.held : []).map((h: HeldFile) => ({ ...h, _dest: h.dest || 'database' }))
}

// v2 only: instant (no-LLM) type-guess per queued file → merged by file_id. Fail-soft.
async function sniffGuesses() {
  if (!props.v2 || !queued.value.length) return
  try {
    const { data, error: e } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/sniff`, { method: 'POST' })
    if (e?.value) return
    const items: any[] = Array.isArray((data.value as any)?.items) ? (data.value as any).items : []
    const byId: Record<string, Guess> = {}
    for (const it of items) {
      if (it?.file_id) byId[it.file_id] = { dest: it.dest, confidence: it.confidence, source: it.source, signals: it.signals }
    }
    queued.value = queued.value.map(q => (byId[q.file_id] ? { ...q, guess: byId[q.file_id] } : q))
  } catch { /* no chips if sniff 404s */ }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data, error: e } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/inbox`)
    if (e?.value) throw e.value
    applyResult(data.value)
  } catch (e: any) {
    error.value = e?.data?.detail || 'Could not load the inbox.'
  }
  loading.value = false
  await sniffGuesses()
}

// Re-route a queued file to a different lane BEFORE training — updates the
// stored dest in the inbox (marked user-pinned). Nothing is placed/trained here;
// the Train button honors the pinned lane.
async function rerouteQueued(f: QueuedFile) {
  const dest = f._reroute
  if (!dest || dest === f.dest || busy.value) return
  busy.value = true; error.value = ''
  try {
    const { data, error: e } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/inbox/${f.file_id}`, {
      method: 'POST',
      body: { dest },
    })
    if (e?.value) throw e.value
    applyResult(data.value)
  } catch (e: any) {
    error.value = e?.data?.detail || 'Could not re-route that file.'
  }
  busy.value = false
}

async function removeQueued(fileId: string) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const { data, error: e } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/inbox/${fileId}`, { method: 'DELETE' })
    if (e?.value) throw e.value
    applyResult(data.value)
  } catch (e: any) {
    error.value = e?.data?.detail || 'Could not remove that file.'
  }
  busy.value = false
}

async function clearAll() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const { data, error: e } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/inbox/clear`, { method: 'POST' })
    if (e?.value) throw e.value
    applyResult(data.value)
  } catch (e: any) {
    error.value = e?.data?.detail || 'Could not clear the inbox.'
  }
  busy.value = false
}

async function deleteHeldRow(fileId: string) {
  const { data, error: e } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/inbox/${fileId}`, { method: 'DELETE' })
  if (e?.value) throw e.value
  applyResult(data.value)
}

async function confirmHeld(h: HeldFile) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const { error: e } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/apply`, {
      method: 'POST',
      body: { items: [{ file_id: h.file_id, dest: h._dest || h.dest, filename: h.filename }], train: false },
    })
    if (e?.value) throw e.value
    await deleteHeldRow(h.file_id)
  } catch (e: any) {
    error.value = e?.data?.detail || 'Could not place that file.'
  }
  busy.value = false
}

async function skipHeld(h: HeldFile) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    await deleteHeldRow(h.file_id)
  } catch (e: any) {
    error.value = e?.data?.detail || 'Could not skip that file.'
  }
  busy.value = false
}

// Parent calls this (via ref) after a Train run or an inbox-updated event.
function refresh() { return load() }
defineExpose({ refresh })

onMounted(load)
</script>
