<template>
  <UModal v-model="isOpen" :ui="{ width: 'sm:max-w-2xl' }">
    <div class="p-5 text-[#1f2328]">
      <!-- Header -->
      <div class="flex items-start justify-between gap-4">
        <div>
          <h2
            class="text-lg font-semibold text-[#1f2328] tracking-tight"
            style="font-family: 'Spectral', ui-serif, Georgia, serif"
          >Upload File / Spreadsheet</h2>
          <p class="mt-1 text-sm text-[#6b6b6b] leading-relaxed">
            Turn a local file into a Data Agent. <span class="text-[#9a958c]">.xlsx · .xls · .csv</span>
          </p>
        </div>
        <button
          @click="close"
          class="text-[#9a958c] hover:text-[#1f2328] hover:bg-[#F4EEE5] rounded-lg p-1.5 transition-colors shrink-0"
          aria-label="Close"
        >
          <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
        </button>
      </div>

      <hr class="my-4 border-[#E9E0D3]" />

      <!-- BATCH: uploading many files at once -->
      <div v-if="batching" class="py-8 text-center">
        <Spinner class="h-6 w-6 mx-auto mb-3 text-[#C2541E]" />
        <p class="text-sm font-medium text-[#1f2328]">Uploading {{ batchDone }} / {{ batchTotal }} files…</p>
        <p class="text-xs text-[#9a958c] mt-1">Each becomes its own source and auto-pins. All sheets included.</p>
        <div class="w-full h-1.5 bg-[#F0EEE6] rounded-full mt-3 overflow-hidden">
          <div class="h-full bg-[#C2541E] transition-all" :style="{ width: `${batchTotal ? Math.round(100*batchDone/batchTotal) : 0}%` }"></div>
        </div>
      </div>

      <!-- STEP 1: pick a file (no file chosen yet) -->
      <div v-else-if="!file">
        <input
          type="file"
          ref="fileInput"
          accept=".xlsx,.xls,.csv"
          multiple
          class="hidden"
          @change="onFileInput"
        />
        <!-- Folder picker: pulls every spreadsheet/CSV out of a chosen folder -->
        <input
          type="file"
          ref="folderInput"
          webkitdirectory
          directory
          multiple
          class="hidden"
          @change="onFolderInput"
        />
        <div
          @dragover.prevent="isDragging = true"
          @dragenter.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="onDrop"
          @click="$refs.fileInput.click()"
          :class="[
            'cursor-pointer rounded-2xl border-2 border-dashed transition-all',
            isDragging
              ? 'border-[#C2541E] bg-[#F6EFEA]'
              : 'border-[#E8C9B5] hover:border-[#C2541E] hover:bg-[#F6EFEA]'
          ]"
        >
          <div class="flex flex-col items-center justify-center py-12 px-4 text-center">
            <UIcon
              name="i-heroicons-cloud-arrow-up"
              :class="['w-12 h-12 transition-colors', isDragging ? 'text-[#C2541E]' : 'text-[#A8330F]']"
            />
            <span class="mt-3 text-sm font-medium text-[#C2541E]">
              {{ isDragging ? 'Drop the file here' : 'Click or drag a file to upload' }}
            </span>
            <span class="mt-1 text-xs text-[#9a958c]">
              Spreadsheet or CSV, up to {{ MAX_SIZE_MB }} MB · drop many at once
            </span>
          </div>
        </div>

        <!-- Or upload a whole folder (every .xlsx/.xls/.csv inside it) -->
        <button
          type="button"
          @click="$refs.folderInput.click()"
          class="mt-3 w-full inline-flex items-center justify-center gap-1.5 rounded-xl border border-[#E8C9B5] bg-white px-3 py-2 text-xs font-semibold text-[#C2541E] hover:bg-[#F6EFEA] transition-colors"
        >
          <UIcon name="i-heroicons-folder-arrow-down" class="w-4 h-4" />
          Upload a whole folder
        </button>
        <p class="mt-1.5 text-[11px] text-[#9a958c] text-center">
          Spreadsheets &amp; CSVs become data agents; PDFs, Word &amp; slides go to the Inbox (routed to Knowledge on Train). For continuous auto-sync, use <span class="text-[#C2541E]">Sync a folder ⟳</span>.
        </p>

        <p v-if="error" class="mt-3 flex items-start gap-1.5 text-xs text-red-600">
          <UIcon name="i-heroicons-exclamation-circle" class="w-4 h-4 shrink-0 mt-px" />
          <span>{{ error }}</span>
        </p>
      </div>

      <!-- STEP 2: file chosen -->
      <div v-else class="space-y-4">
        <!-- File chip -->
        <div class="flex items-center justify-between gap-3 rounded-xl border border-[#E9E0D3] bg-[#F4EEE5] px-3 py-2.5">
          <div class="flex items-center gap-2.5 min-w-0">
            <span class="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-white border border-[#E9E0D3] shrink-0">
              <Spinner v-if="uploading" class="w-4 h-4 text-[#C2541E]" />
              <UIcon v-else-if="uploadError" name="i-heroicons-x-circle" class="w-4 h-4 text-red-500" />
              <UIcon v-else name="i-heroicons-document-check" class="w-4 h-4 text-[#3f9e6a]" />
            </span>
            <div class="min-w-0">
              <div class="text-sm font-medium text-[#1f2328] truncate">{{ file.name }}</div>
              <div class="text-[11px] text-[#9a958c]">{{ prettySize(file.size) }} · {{ uploading ? 'Uploading…' : (uploadError ? 'Failed' : 'Ready') }}</div>
            </div>
          </div>
          <button
            @click="reset"
            :disabled="busy"
            class="text-[#9a958c] hover:text-[#1f2328] hover:bg-white rounded-full p-1 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
            aria-label="Remove file"
          >
            <UIcon name="i-heroicons-x-mark" class="w-4 h-4" />
          </button>
        </div>

        <!-- Upload error -->
        <p v-if="uploadError" class="flex items-start gap-1.5 text-xs text-red-600">
          <UIcon name="i-heroicons-exclamation-circle" class="w-4 h-4 shrink-0 mt-px" />
          <span>{{ uploadError }}</span>
        </p>

        <!-- Preview (when upload succeeded) -->
        <template v-if="uploaded && !uploadError">
          <!-- Sheet selector (excel only) -->
          <div v-if="isExcel && sheetNames.length" class="space-y-1.5">
            <label class="block text-xs font-medium text-[#6b6b6b]">
              Sheets <span class="text-[#9a958c] font-normal">({{ selectedSheets.length }} of {{ sheetNames.length }} selected)</span>
            </label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="s in sheetNames"
                :key="s"
                @click="toggleSheet(s)"
                :class="[
                  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors',
                  selectedSheets.includes(s)
                    ? 'border-[#C2541E] bg-[#F6EFEA] text-[#A8330F] font-medium'
                    : 'border-[#E9E0D3] bg-white text-[#6b6b6b] hover:border-[#E8C9B5]'
                ]"
              >
                <UIcon
                  :name="selectedSheets.includes(s) ? 'i-heroicons-check-circle' : 'i-heroicons-table-cells'"
                  class="w-3.5 h-3.5"
                />
                {{ s }}
              </button>
            </div>
          </div>

          <!-- Column / cell preview -->
          <div v-if="previewRows.length" class="space-y-1.5">
            <div class="flex items-center justify-between">
              <label class="block text-xs font-medium text-[#6b6b6b]">Preview</label>
              <span v-if="activeShape" class="text-[11px] text-[#9a958c]">
                {{ activeShape[0] }} rows · {{ activeShape[1] }} cols
              </span>
            </div>
            <div class="overflow-auto rounded-xl border border-[#E9E0D3] max-h-56">
              <table class="min-w-full text-xs">
                <thead class="bg-[#F4EEE5] sticky top-0">
                  <tr>
                    <th
                      v-for="(h, ci) in previewHeaders"
                      :key="ci"
                      class="px-2.5 py-1.5 text-start font-medium text-[#6b6b6b] whitespace-nowrap border-b border-[#E9E0D3]"
                    >{{ cellText(h) }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, ri) in previewBody" :key="ri" class="even:bg-[#F6F1EA]">
                    <td
                      v-for="(cell, ci) in row"
                      :key="ci"
                      class="px-2.5 py-1.5 text-[#1f2328] whitespace-nowrap border-b border-[#F0EEE7] max-w-[200px] truncate"
                    >{{ cellText(cell) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <p v-else-if="!previewUnavailable" class="text-xs text-[#9a958c]">No preview rows detected for this file.</p>
          <p v-else class="flex items-start gap-1.5 text-xs text-[#9a958c]">
            <UIcon name="i-heroicons-information-circle" class="w-4 h-4 shrink-0 mt-px" />
            <span>Preview unavailable — you can still create the Data Agent.</span>
          </p>

          <!-- Name + description -->
          <div class="space-y-3 pt-1">
            <div class="space-y-1.5">
              <label class="block text-xs font-medium text-[#6b6b6b]">Name</label>
              <input
                v-model="name"
                type="text"
                placeholder="Data Agent name"
                class="w-full rounded-xl border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]"
              />
              <!-- Neutral dup-name hint (backend auto-suffixes; not a blocker) -->
              <p v-if="nameCollides" class="flex items-start gap-1.5 text-xs text-[#9a958c]">
                <UIcon name="i-heroicons-information-circle" class="w-4 h-4 shrink-0 mt-px text-[#A8330F]" />
                <span>A source named “{{ name.trim() }}” exists — this will be saved as “{{ suffixedName }}”.</span>
              </p>
            </div>
            <div class="space-y-1.5">
              <label class="block text-xs font-medium text-[#6b6b6b]">Description <span class="text-[#9a958c] font-normal">(optional)</span></label>
              <textarea
                v-model="description"
                rows="2"
                placeholder="What is this data about?"
                class="w-full resize-none rounded-xl border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]"
              />
            </div>
          </div>

          <!-- Create error -->
          <p v-if="createError" class="flex items-start gap-1.5 text-xs text-red-600">
            <UIcon name="i-heroicons-exclamation-circle" class="w-4 h-4 shrink-0 mt-px" />
            <span>{{ createError }}</span>
          </p>
        </template>
      </div>

      <!-- Footer -->
      <div class="mt-6 flex items-center justify-end gap-2">
        <button
          @click="close"
          :disabled="busy"
          class="px-4 py-2 text-sm font-medium rounded-xl text-[#6b6b6b] hover:bg-[#F4EEE5] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Cancel
        </button>
        <button
          v-if="uploaded && !uploadError"
          @click="createDataSource"
          :disabled="busy || !canCreate"
          class="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-xl bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Spinner v-if="creating" class="w-4 h-4" />
          <UIcon v-else name="i-heroicons-sparkles" class="w-4 h-4" />
          {{ creating ? 'Creating…' : 'Create & use' }}
        </button>
      </div>
    </div>
  </UModal>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  studioId: { type: String, default: null },
})

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'created', dataSource: any): void
}>()

const toast = useToast()

const MAX_SIZE_MB = 50
const MAX_SIZE = MAX_SIZE_MB * 1024 * 1024
const ALLOWED_EXT = ['xlsx', 'xls', 'csv']

// ---- modal open/close (UModal needs a writable v-model) ----
const isOpen = computed({
  get: () => props.open,
  set: (v: boolean) => { if (!v) close() },
})

// ---- state ----
const file = ref<File | null>(null)
const isDragging = ref(false)
const error = ref('')              // file-selection error (type/size)

const uploading = ref(false)
const uploaded = ref(false)
const uploadError = ref('')
const fileId = ref<string | null>(null)
const preview = ref<any>(null)

const creating = ref(false)
const createError = ref('')

const name = ref('')
const description = ref('')
const selectedSheets = ref<string[]>([])

// Existing data-source names (lower-cased) — used to preview the auto-suffix the
// backend applies on a duplicate name. Fetched best-effort; empty on failure.
const existingNames = ref<string[]>([])

async function loadExistingNames() {
  try {
    const { data } = await useMyFetch('/data_sources', { method: 'GET' })
    const list = (data.value as any[]) || []
    existingNames.value = list
      .map((d: any) => (d?.name || '').toString().trim().toLowerCase())
      .filter(Boolean)
  } catch {
    existingNames.value = []
  }
}

// Does the chosen name collide with an existing source (case-insensitive)?
const nameCollides = computed(() => {
  const n = name.value.trim().toLowerCase()
  return !!n && existingNames.value.includes(n)
})

// Preview the suffix the backend will auto-apply: "X" -> "X (2)" -> "X (3)" ...
const suffixedName = computed(() => {
  const base = name.value.trim()
  if (!base) return ''
  const taken = new Set(existingNames.value)
  let i = 2
  while (taken.has(`${base} (${i})`.toLowerCase())) i++
  return `${base} (${i})`
})

const busy = computed(() => uploading.value || creating.value)

// ---- preview derivations ----
const previewType = computed(() => preview.value?.type || null)
const isExcel = computed(() => previewType.value === 'excel')
const previewUnavailable = computed(() =>
  uploaded.value && (!preview.value || !['excel', 'csv'].includes(previewType.value))
)

const sheetNames = computed<string[]>(() =>
  isExcel.value ? (preview.value?.sheets || preview.value?.sheet_names || []) : []
)

// The sheet whose cells we show in the preview table (first selected, else first sheet)
const activeSheet = computed<string | null>(() => {
  if (!isExcel.value) return null
  return selectedSheets.value[0] || sheetNames.value[0] || null
})

const activeShape = computed<number[] | null>(() => {
  if (isExcel.value) {
    const sp = preview.value?.sheet_previews?.[activeSheet.value as string]
    return sp?.shape || null
  }
  if (previewType.value === 'csv') return preview.value?.shape || null
  return null
})

// raw_cells: first row = headers
const previewRows = computed<any[][]>(() => {
  if (isExcel.value) {
    const sp = preview.value?.sheet_previews?.[activeSheet.value as string]
    return Array.isArray(sp?.raw_cells) ? sp.raw_cells : []
  }
  if (previewType.value === 'csv') {
    if (Array.isArray(preview.value?.raw_cells)) return preview.value.raw_cells
    // CSV fallback: build raw_cells from columns + head records
    const cols = preview.value?.columns
    const head = preview.value?.head
    if (Array.isArray(cols) && Array.isArray(head)) {
      return [cols, ...head.map((r: any) => cols.map((c: string) => r?.[c]))]
    }
  }
  return []
})

const previewHeaders = computed<any[]>(() => previewRows.value[0] || [])
const previewBody = computed<any[][]>(() => previewRows.value.slice(1, 21))

const canCreate = computed(() =>
  !!fileId.value && name.value.trim().length > 0 &&
  (!isExcel.value || selectedSheets.value.length > 0 || sheetNames.value.length === 0)
)

// ---- helpers ----
function cellText(v: any): string {
  if (v === null || v === undefined) return ''
  return String(v)
}

function prettySize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function extOf(filename: string): string {
  return (filename || '').toLowerCase().split('.').pop() || ''
}

function baseName(filename: string): string {
  const i = filename.lastIndexOf('.')
  return i > 0 ? filename.slice(0, i) : filename
}

function validate(f: File): string {
  if (!ALLOWED_EXT.includes(extOf(f.name))) {
    return 'Unsupported file type. Use .xlsx, .xls or .csv.'
  }
  if (f.size > MAX_SIZE) {
    return `File is too large (max ${MAX_SIZE_MB} MB).`
  }
  return ''
}

function toggleSheet(s: string) {
  const i = selectedSheets.value.indexOf(s)
  if (i === -1) selectedSheets.value.push(s)
  else selectedSheets.value.splice(i, 1)
}

// ---- file selection ----
function onFileInput(e: Event) {
  const files = Array.from((e.target as HTMLInputElement).files || [])
  if (files.length > 1) batchUpload(files)
  else if (files[0]) chooseFile(files[0])
  ;(e.target as HTMLInputElement).value = ''
}

function onDrop(e: DragEvent) {
  isDragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length > 1) batchUpload(files)
  else if (files[0]) chooseFile(files[0])
}

// ---- whole-folder upload (webkitdirectory) -------------------------------
// The browser hands back every file in the picked folder (recursively). Keep
// every SUPPORTED file, drop Office lock files (~$...), then reuse batchUpload —
// which type-splits: spreadsheets → Data sources, docs (pdf/docx/pptx) → the
// studio Inbox (routed to Knowledge on Train). Nothing supported is dropped.
const DATA_EXTS = ['.xlsx', '.xls', '.csv', '.tsv', '.txt']
const DOC_EXTS = ['.pdf', '.docx', '.doc', '.pptx', '.md']
const FOLDER_EXTS = [...DATA_EXTS, ...DOC_EXTS]
// 'data' → queryable table path; 'doc' → Inbox; null → unsupported.
function fileKind(name: string): 'data' | 'doc' | null {
  const n = (name || '').toLowerCase()
  if (DATA_EXTS.some((x) => n.endsWith(x))) return 'data'
  if (DOC_EXTS.some((x) => n.endsWith(x))) return 'doc'
  return null
}
function onFolderInput(e: Event) {
  const all = Array.from((e.target as HTMLInputElement).files || [])
  ;(e.target as HTMLInputElement).value = ''
  const files = all.filter((f) => {
    const n = f.name.toLowerCase()
    return !f.name.startsWith('~$') && FOLDER_EXTS.some((x) => n.endsWith(x))
  })
  if (!files.length) {
    error.value = 'No supported files (.xlsx, .csv, .pdf, .docx, .pptx) found in that folder.'
    return
  }
  error.value = ''
  batchUpload(files)
}

// ---- batch: many files at once (skip the per-sheet picker) ----------------
// Each file goes straight through upload (/files) → create (/data_sources/from-file)
// → the parent pins it via the `created` emit. Excel files use all sheets.
const batching = ref(false)
const batchTotal = ref(0)
const batchDone = ref(0)
const batchErrors = ref<string[]>([])

// Phase 5 (HYBRID_INGEST_RECONCILE): the from-file response carries
// `ingest_coverage` when the ingest reconcile gate ran. If a multi-file merge
// dropped any file, surface it loudly instead of a green "ready" toast — so the
// user sees the gap at upload time, not weeks later in a wrong answer.
function coverageOf(ds: any): string | null {
  const c = ds?.ingest_coverage
  if (!c || c.status !== 'degraded') return null
  const failed = (c.failed || [])
    .map((f: any) => f?.label || f?.path)
    .filter(Boolean)
    .join(', ')
  let msg = `Only ${c.loaded_files} of ${c.expected_files} file(s) loaded.`
  if (failed) msg += ` Missing: ${failed}.`
  return msg
}

const MAX_UPLOAD_BYTES = 50 * 1024 * 1024  // 50 MB, matches validate()

async function batchUpload(files: File[]) {
  batching.value = true
  batchTotal.value = files.length
  batchDone.value = 0
  batchErrors.value = []
  const coverageWarnings: string[] = []
  const skipped: string[] = []           // unsupported / no-agent — reported, never silent
  const docFileIds: string[] = []        // doc file_ids to queue into the Inbox
  const docNames: string[] = []
  let dataOk = 0
  for (const f of files) {
    const kind = fileKind(f.name)
    if (!kind) { skipped.push(`${f.name}: unsupported type`); batchDone.value++; continue }
    if (f.size > MAX_UPLOAD_BYTES) { batchErrors.value.push(`${f.name}: too large (max 50MB)`); batchDone.value++; continue }
    try {
      const fd = new FormData()
      fd.append('file', f)
      const up = await useMyFetch('/files', { method: 'POST', body: fd })
      const upRes = up.data?.value as any
      if (up.error?.value || !upRes?.id) { batchErrors.value.push(`${f.name}: upload failed`); batchDone.value++; continue }

      if (kind === 'doc') {
        // pdf/docx/pptx/md → stash for the Inbox (routed to Knowledge on Train).
        docFileIds.push(String(upRes.id)); docNames.push(f.name)
        batchDone.value++; continue
      }

      // spreadsheet → today's queryable Data-source path.
      const payload: Record<string, any> = {
        file_id: upRes.id,
        data_source_name: baseName(f.name),
        sheet_names: null,   // batch = all sheets
        description: null,
      }
      if (props.studioId) payload.studio_id = props.studioId
      const cr = await useMyFetch('/data_sources/from-file', {
        method: 'POST',
        body: JSON.stringify(payload),
        headers: { 'Content-Type': 'application/json' },
      })
      const ds = cr.data?.value as any
      if (cr.error?.value || !ds) { batchErrors.value.push(`${f.name}: create failed`); batchDone.value++; continue }
      emit('created', ds)   // parent pins it
      const cw = coverageOf(ds)
      if (cw) coverageWarnings.push(`${f.name}: ${cw}`)
      dataOk++
    } catch (e: any) {
      batchErrors.value.push(`${f.name}: ${detailOf(e, 'failed')}`)
    } finally {
      batchDone.value++
    }
  }

  // ---- Phase 2/4: queue docs into the studio Inbox (one call, fail-soft) ----
  let queued = 0
  const docFailed: string[] = []
  if (docFileIds.length) {
    if (!props.studioId) {
      // No agent context → can't route docs. Report, don't drop silently.
      docNames.forEach((n) => skipped.push(`${n}: open from an agent to add docs`))
    } else {
      try {
        const res = await useMyFetch(`/studios/${props.studioId}/smart-upload/inbox`, {
          method: 'POST',
          body: JSON.stringify({ file_ids: docFileIds }),
          headers: { 'Content-Type': 'application/json' },
        })
        if (res.error?.value) throw new Error('inbox unavailable')
        const d = res.data?.value as any
        queued = typeof d?.added === 'number' ? d.added : docFileIds.length
      } catch {
        // Smart-Upload flag off / endpoint missing → fail-soft, surface it.
        docNames.forEach((n) => docFailed.push(`${n}: docs need Smart-Upload enabled`))
      }
    }
  }

  batching.value = false

  // ---- Phase 3: honest receipt ----
  const lanes: string[] = []
  if (dataOk) lanes.push(`${dataOk} → Data`)
  if (queued) lanes.push(`${queued} → Inbox`)
  const problems = [...skipped, ...docFailed, ...batchErrors.value]
  toast.add({
    title: `${dataOk + queued} of ${files.length} file${files.length === 1 ? '' : 's'} added`,
    description: (lanes.join(' · ') || 'Nothing added')
      + (queued ? ' — run Train to route docs → Knowledge.' : ''),
    icon: (problems.length || coverageWarnings.length) ? 'i-heroicons-exclamation-triangle' : 'i-heroicons-check-circle',
    color: (problems.length || coverageWarnings.length) ? 'orange' : 'green',
  })

  // Loud, separate warning per incomplete merged source (ingest-reconcile).
  if (coverageWarnings.length) {
    toast.add({
      title: 'Data incomplete — some files did not load',
      description: coverageWarnings.join(' · '),
      icon: 'i-heroicons-exclamation-triangle',
      color: 'red',
      timeout: 0,
    })
    console.warn('Ingest coverage gaps:', coverageWarnings)
  }
  // No-silent-drop: anything skipped/failed gets its own loud toast.
  if (problems.length) {
    toast.add({
      title: 'Some files were not added',
      description: problems.join(' · '),
      icon: 'i-heroicons-exclamation-triangle',
      color: 'red',
      timeout: 0,
    })
    console.warn('Folder upload problems:', problems)
  }
  emit('close')
  resetAll()
}

function chooseFile(f: File) {
  error.value = ''
  const v = validate(f)
  if (v) { error.value = v; return }
  file.value = f
  name.value = baseName(f.name)
  uploadFile()
}

// ---- upload (POST /api/files, multipart, field `file`) ----
async function uploadFile() {
  if (!file.value) return
  uploading.value = true
  uploaded.value = false
  uploadError.value = ''
  fileId.value = null
  preview.value = null

  try {
    const formData = new FormData()
    formData.append('file', file.value)

    const { data, error: err } = await useMyFetch('/files', {
      method: 'POST',
      body: formData,
    })

    if (err?.value || !data?.value) {
      uploadError.value = detailOf(err?.value, 'Upload failed. Please try again.')
      return
    }

    const res = data.value as any
    fileId.value = res.id
    preview.value = res.preview || null
    uploaded.value = true

    // Pre-select all sheets for excel files
    if (preview.value?.type === 'excel') {
      selectedSheets.value = [...(preview.value.sheets || preview.value.sheet_names || [])]
    }
  } catch (e: any) {
    uploadError.value = detailOf(e, 'Upload failed. Please try again.')
  } finally {
    uploading.value = false
  }
}

// ---- create data source (POST /api/data_sources/from-file, JSON) ----
async function createDataSource() {
  if (!canCreate.value || !fileId.value) return
  creating.value = true
  createError.value = ''

  try {
    const payload: Record<string, any> = {
      file_id: fileId.value,
      data_source_name: name.value.trim(),
      sheet_names: isExcel.value && selectedSheets.value.length ? selectedSheets.value : null,
      description: description.value.trim() || null,
    }
    if (props.studioId) payload.studio_id = props.studioId

    const { data, error: err } = await useMyFetch('/data_sources/from-file', {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json' },
    })

    if (err?.value || !data?.value) {
      // The backend now auto-suffixes duplicate names, so a 409 should no longer
      // occur — but if one ever surfaces, don't treat it as a hard blocker: the
      // name simply collided. Surface a soft hint, not a red error wall.
      const status = (err?.value as any)?.statusCode || (err?.value as any)?.status
      if (status === 409) {
        createError.value = ''
        toast.add({
          title: 'Name already in use',
          description: `Saved under a different name (e.g. “${suffixedName.value}”). Try again to confirm.`,
          icon: 'i-heroicons-information-circle',
          color: 'orange',
        })
      } else {
        createError.value = detailOf(err?.value, 'Could not create the Data Agent.')
      }
      return
    }

    const ds = data.value as any
    const cw = coverageOf(ds)
    if (cw) {
      toast.add({
        title: 'Created — but data is incomplete',
        description: `“${ds.name || name.value}”: ${cw} Missing periods will NOT be answered.`,
        icon: 'i-heroicons-exclamation-triangle',
        color: 'red',
        timeout: 0,
      })
    } else {
      toast.add({
        title: 'Data Agent created',
        description: `“${ds.name || name.value}” is ready to use.`,
        icon: 'i-heroicons-check-circle',
        color: 'green',
      })
    }
    emit('created', ds)
    emit('close')
    resetAll()
  } catch (e: any) {
    createError.value = detailOf(e, 'Could not create the Data Agent.')
  } finally {
    creating.value = false
  }
}

function detailOf(err: any, fallback: string): string {
  const e = (err && (err.value || err)) || {}
  return e?.data?.detail || e?.data?.message || e?.message || fallback
}

// ---- reset ----
function reset() {
  file.value = null
  uploading.value = false
  uploaded.value = false
  uploadError.value = ''
  fileId.value = null
  preview.value = null
  selectedSheets.value = []
  error.value = ''
  createError.value = ''
  name.value = ''
  description.value = ''
}
function resetAll() { reset() }

function close() {
  if (busy.value) return
  emit('close')
}

// reset internal state whenever the modal is (re)opened fresh
watch(() => props.open, (v) => {
  if (v) {
    reset()
    loadExistingNames()
  }
})
</script>
