<template>
    <!-- INLINE card — no Teleport, no overlay. Embeds in a page; heavy detail streams out via @log. -->
    <div>
        <!-- hidden file input — ALWAYS present so pick() works even when the visible
             card is collapsed (hideDropzone: the page's Upload button drives pick()). -->
        <input ref="fileInput" type="file" multiple class="hidden" accept=".csv,.xlsx,.xls,.pdf,.docx,.pptx,.txt,.tsv,.md" :disabled="canEdit === false" @change="onPick" />
        <!-- card body: shown when the dropzone is visible, or once an upload is in flight / done -->
        <div v-if="!hideDropzone || busy || result || error" class="rounded-2xl border border-[#ECECEC] bg-[#FAF9F8] overflow-hidden">
        <div class="px-4 py-4">
            <!-- drop zone (hidden when hideDropzone — the page's Upload button drives pick()) -->
            <div
                v-if="!hideDropzone"
                class="border-[1.6px] border-dashed border-[#EAD8CD] bg-[#FFF6F1] rounded-2xl px-5 py-6 text-center transition-colors"
                :class="[
                    dragging ? 'bg-[#FCEBE0] border-[#C2541E]' : '',
                    canEdit === false ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
                ]"
                @click="pick"
                @dragover.prevent="canEdit === false ? null : (dragging = true)"
                @dragleave.prevent="dragging = false"
                @drop.prevent="onDrop"
            >
                <div class="text-[24px]">&#128229;</div>
                <div class="font-semibold text-[#C2541E] mt-1.5 text-[14px]">Click or drop files &mdash; we sort + train for you</div>
                <div class="text-[11.5px] text-[#6b7280] mt-1">.csv .xlsx .pdf .docx .pptx .txt &middot; data, definitions, logic, references &mdash; mixed is fine</div>
            </div>

            <!-- error -->
            <div v-if="error" class="mt-3 rounded-xl border border-[#f0c8b8] bg-[#FFF1EA] px-3.5 py-2 text-[12px] text-[#A8330F]">
                {{ error }}
            </div>

            <!-- busy spinner line -->
            <div v-if="busy" class="mt-3 flex items-center gap-2 text-[12px] text-[#6b7280]">
                <UIcon name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin text-[#C2541E]" />
                <span>{{ busyLabel }}</span>
            </div>

            <!-- compact result -->
            <div v-if="result && !busy" class="mt-3 rounded-xl border border-[#cfe7d5] bg-[#EEFAF1] px-3.5 py-3">
                <div class="text-[12.5px] font-semibold text-[#157A43]">&check; {{ result.applied }} file{{ result.applied === 1 ? '' : 's' }} sorted</div>
                <div class="text-[11.5px] text-[#3b4250] mt-1 flex flex-wrap gap-x-2.5 gap-y-1">
                    <span v-for="(n, dest) in resultByDest" :key="dest" class="inline-flex items-center gap-1 rounded-full bg-white/70 px-2 py-0.5">{{ destMeta(dest).ic }} {{ n }} {{ destMeta(dest).short }}</span>
                </div>
                <button
                    v-if="unsureCount && !reviewOpen"
                    type="button"
                    class="mt-2 text-[11.5px] font-semibold text-[#b45309] hover:underline"
                    @click="reviewOpen = true"
                >&#9888; {{ unsureCount }} we weren&rsquo;t sure about &mdash; Review</button>
                <div v-if="result.train_started" class="mt-2 flex items-center gap-1.5 text-[11.5px] text-[#C2541E]">
                    <span class="animate-spin">&#128260;</span>
                    <span>Training your agent now</span>
                </div>
                <div class="mt-2 text-[11px] text-[#9aa1ac]">full logs in the robot &#8600;</div>
            </div>

            <!-- Review expander (collapsed by default) -->
            <template v-if="items.length && !busy && reviewOpen">
                <div class="flex items-center gap-2 mt-3 mb-2">
                    <h3 class="text-[13px] font-semibold text-[#1f2329]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Review &amp; adjust</h3>
                    <span class="flex-1"></span>
                    <span class="text-[11px] text-[#6b7280]">Change any destination, then re-apply.</span>
                </div>

                <div
                    v-for="(it, i) in items"
                    :key="it.file_id"
                    class="flex items-stretch border border-[#ECECEC] rounded-xl bg-white mb-2 overflow-hidden"
                    :class="it.dest === 'skip' ? 'opacity-50' : ''"
                >
                    <!-- left: file + reason -->
                    <div class="flex-1 min-w-0 px-3.5 py-2.5">
                        <div class="font-semibold text-[12.5px] text-[#1f2329] flex items-center gap-2">
                            <span>&#128196;</span>
                            <span class="truncate">{{ it.filename }}</span>
                            <span v-if="it.needs_confirm" class="text-[#b45309]" title="Uncertain — please confirm">&#9888;</span>
                        </div>
                        <div v-if="it.signals" class="text-[11px] text-[#9aa1ac] mt-0.5 truncate">{{ it.signals }}</div>
                        <div v-if="it.reason" class="text-[11.5px] text-[#6b7280] mt-1.5 bg-[#F4F3F1] rounded-lg px-2.5 py-1.5" v-html="it.reason"></div>
                    </div>

                    <!-- right: destination control -->
                    <div class="flex-none w-[220px] border-l border-[#ECECEC] px-3.5 py-2.5 bg-[#FCFBFA]">
                        <div class="text-[9.5px] font-bold uppercase tracking-wide text-[#9aa1ac] mb-1">Routed to</div>
                        <div class="relative">
                            <select
                                v-model="it.dest"
                                class="w-full appearance-none text-[12px] font-semibold rounded-lg border border-[#E9E0D3] pl-2.5 pr-7 py-1.5 cursor-pointer focus:outline-none focus:border-[#C2541E]"
                                :class="destMeta(it.dest).cls"
                            >
                                <option v-for="d in DESTS" :key="d" :value="d">{{ destMeta(d).ic }} {{ destMeta(d).label }}</option>
                            </select>
                            <UIcon name="i-heroicons-chevron-down" class="w-4 h-4 absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none text-[#9aa1ac]" />
                        </div>

                        <!-- confidence bar -->
                        <div class="flex items-center gap-2 text-[10.5px] text-[#6b7280] mt-2">
                            <span>{{ Math.round((it.confidence || 0) * pctScale) }}%</span>
                            <span class="flex-1 h-1.5 rounded-full bg-[#eee] overflow-hidden">
                                <span class="block h-full rounded-full" :class="confClass(it.confidence)" :style="{ width: confPct(it.confidence) + '%' }"></span>
                            </span>
                        </div>

                        <button
                            type="button"
                            class="mt-2 text-[10.5px] font-semibold text-[#3b4250] border border-[#ECECEC] rounded-md px-2 py-1 hover:bg-[#F4F3F1]"
                            @click="toggleSkip(it)"
                        >
                            {{ it.dest === 'skip' ? 'Include' : 'Skip' }}
                        </button>
                    </div>
                </div>

                <div class="flex items-center gap-2 mt-2">
                    <button
                        type="button"
                        class="text-[11.5px] font-semibold text-[#3b4250] bg-white border border-[#ECECEC] rounded-lg px-3 py-1.5 hover:bg-[#F4F3F1]"
                        @click="reviewOpen = false"
                    >
                        Hide review
                    </button>
                    <span class="flex-1"></span>
                    <button
                        type="button"
                        class="text-[12px] font-bold text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-lg px-3.5 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        :disabled="!keepCount || applying || busy"
                        @click="apply"
                    >
                        <span v-if="applying">Applying&hellip;</span>
                        <span v-else>Re-apply changes</span>
                    </button>
                </div>
            </template>
        </div>
        </div>
    </div>
</template>

<script setup lang="ts">
interface SmartItem {
    file_id: string
    filename: string
    dest: string
    confidence: number
    reason?: string
    needs_confirm?: boolean
    sink?: string
    signals?: string
}

const props = withDefaults(
    defineProps<{ studioId: string; dataSourceId?: string; canEdit?: boolean; hideDropzone?: boolean }>(),
    { canEdit: true },
)
// log entry shape (dock pod matches this exactly):
//   { stage: 'upload'|'classify'|'segregate'|'apply', level: 'info'|'done'|'active'|'warn', msg: string, meta?: string }
const emit = defineEmits<{ (e: 'applied', summary: any): void; (e: 'log', entry: any): void }>()

function log(stage: string, level: string, msg: string, meta?: string) {
    emit('log', { stage, level, msg, ...(meta ? { meta } : {}) })
}

// Review reveals the per-file override rows; collapsed by default.
const reviewOpen = ref(false)

const DESTS = ['database', 'semantic', 'instructions', 'examples', 'knowledge', 'skip']
const DEST_META: Record<string, { ic: string; label: string; short: string; cls: string }> = {
    database:     { ic: '🗄️', label: 'Database — data source',      short: 'Database',     cls: 'bg-[#eef2fe] text-[#2C53A8]' },
    semantic:     { ic: '🏷️', label: 'Semantic — column meanings',  short: 'Semantic',     cls: 'bg-[#F6F4FF] text-[#5A41A8]' },
    instructions: { ic: '📐', label: 'Instructions — rules',        short: 'Instructions', cls: 'bg-[#fffaf0] text-[#b45309]' },
    examples:     { ic: '🎓', label: 'Examples — Q→SQL',            short: 'Examples',     cls: 'bg-[#EEFAF1] text-[#157A43]' },
    knowledge:    { ic: '📚', label: 'Knowledge — RAG',             short: 'Knowledge',    cls: 'bg-[#e9f7f4] text-[#0d7a6b]' },
    skip:         { ic: '🚫', label: 'Skip — don’t import',         short: 'Skip',         cls: 'bg-[#f4f3f1] text-[#6b7280]' },
}
function destMeta(d: string) { return DEST_META[d] || DEST_META.skip }

const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const uploading = ref(false)
const classifying = ref(false)
const applying = ref(false)
const error = ref('')
const items = ref<SmartItem[]>([])
const summary = ref<{ auto: number; needs_confirm: number; total: number }>({ auto: 0, needs_confirm: 0, total: 0 })
const result = ref<any>(null)

const busy = computed(() => uploading.value || classifying.value || applying.value)
const busyLabel = computed(() => {
    if (uploading.value) return 'Uploading files…'
    if (classifying.value) return 'Sorting your files…'
    return 'Sorting your files…'
})
const keepCount = computed(() => items.value.filter(it => it.dest !== 'skip').length)
const unsureCount = computed(() => items.value.filter(it => it.needs_confirm).length)
const pctScale = computed(() => (items.value.some(it => (it.confidence || 0) > 1) ? 1 : 100))
function confPct(c: number) { return Math.max(0, Math.min(100, Math.round((c || 0) * pctScale.value))) }
function confClass(c: number) {
    const p = confPct(c)
    return p >= 90 ? 'bg-[#15803d]' : p >= 80 ? 'bg-[#b45309]' : 'bg-[#b91c1c]'
}
const resultByDest = computed(() => {
    const m: Record<string, number> = {}
    for (const r of (result.value?.results || [])) { if (r?.ok && r?.dest && r.dest !== 'skip') m[r.dest] = (m[r.dest] || 0) + 1 }
    return m
})

function pick() { if (props.canEdit === false) return; fileInput.value?.click() }
// Let the page's "Upload file" button drive this inline card's picker (no modal).
defineExpose({ pick })
function toggleSkip(it: SmartItem) {
    if (it.dest === 'skip') it.dest = (it as any)._prevDest || 'database'
    else { (it as any)._prevDest = it.dest; it.dest = 'skip' }
}

function onPick(e: Event) {
    const list = (e.target as HTMLInputElement).files
    if (list && list.length) handleFiles(Array.from(list))
    if (fileInput.value) fileInput.value.value = ''
}
function onDrop(e: DragEvent) {
    dragging.value = false
    if (props.canEdit === false) return
    const list = e.dataTransfer?.files
    if (list && list.length) handleFiles(Array.from(list))
}

async function handleFiles(files: File[]) {
    error.value = ''
    result.value = null
    reviewOpen.value = false
    items.value = []
    uploading.value = true
    log('upload', 'active', `Uploading ${files.length} file${files.length === 1 ? '' : 's'}…`)
    const fileIds: string[] = []
    try {
        for (const f of files) {
            const fd = new FormData()
            fd.append('file', f)
            // POST /files (multipart, field `file`). useMyFetch adds auth + org headers + /api prefix.
            const { data, error: upErr } = await useMyFetch<any>('/files', { method: 'POST', body: fd })
            if (upErr?.value || !data?.value?.id) {
                error.value = (upErr?.value as any)?.data?.detail || `Could not upload “${f.name}”.`
                log('upload', 'warn', f.name, 'upload failed')
                continue
            }
            fileIds.push((data.value as any).id)
            log('upload', 'done', f.name)
        }
    } catch (e: any) {
        error.value = e?.data?.detail || e?.message || 'Upload failed.'
    } finally {
        uploading.value = false
    }
    if (!fileIds.length) return
    await classify(fileIds)
}

async function classify(fileIds: string[]) {
    classifying.value = true
    error.value = ''
    log('classify', 'active', `Sorting ${fileIds.length} file${fileIds.length === 1 ? '' : 's'}…`)
    try {
        const body: any = { file_ids: fileIds }
        if (props.dataSourceId) body.data_source_id = props.dataSourceId
        const { data, error: clErr } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/classify`, { method: 'POST', body })
        if (clErr?.value) {
            error.value = (clErr.value as any)?.data?.detail || 'Could not classify these files.'
            log('classify', 'warn', 'Could not classify these files.')
            return
        }
        const res = data.value as any
        const incoming: SmartItem[] = res?.items || []
        items.value = incoming
        summary.value = {
            auto: items.value.filter(it => !it.needs_confirm).length,
            needs_confirm: items.value.filter(it => it.needs_confirm).length,
            total: items.value.length,
        }
        for (const it of incoming) {
            const pct = Math.round((it.confidence || 0) * (it.confidence > 1 ? 1 : 100))
            log('classify', it.needs_confirm ? 'warn' : 'done', `${it.filename} → ${destMeta(it.dest).short}`, `${pct}%`)
        }
    } catch (e: any) {
        error.value = e?.data?.detail || e?.message || 'Classify failed.'
    } finally {
        classifying.value = false
    }
    // Single flow: place everything immediately, no confirm step.
    if (!error.value && keepCount.value) await apply()
}

async function apply() {
    if (!keepCount.value || applying.value) return
    applying.value = true
    error.value = ''
    log('apply', 'active', 'Placing files…')
    try {
        const payload: any = {
            items: items.value
                .filter(it => it.dest !== 'skip')
                .map(it => ({ file_id: it.file_id, dest: it.dest, filename: it.filename })),
            train: false, // backend auto-trains via flag
        }
        if (props.dataSourceId) payload.data_source_id = props.dataSourceId
        const { data, error: apErr } = await useMyFetch<any>(`/studios/${props.studioId}/smart-upload/apply`, { method: 'POST', body: payload })
        if (apErr?.value) {
            error.value = (apErr.value as any)?.data?.detail || 'Could not apply routing.'
            log('apply', 'warn', 'Could not apply routing.')
            return
        }
        const res = data.value as any
        result.value = res
        reviewOpen.value = false
        log('apply', 'done', `${res.applied} file${res.applied === 1 ? '' : 's'} placed`, res.train_started ? 'training started' : '')
        emit('applied', res)
    } catch (e: any) {
        error.value = e?.data?.detail || e?.message || 'Apply failed.'
    } finally {
        applying.value = false
    }
}
</script>
