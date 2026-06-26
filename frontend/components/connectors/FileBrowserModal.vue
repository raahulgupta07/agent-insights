<template>
  <!-- Self-gates on HYBRID_FILE_BROWSER. Off / unknown -> render nothing (modal never opens). -->
  <UModal v-if="flagLoaded && flagEnabled" v-model="isOpen" :ui="{ width: 'sm:max-w-2xl' }">
    <div class="relative" style="background:#FBFAF6;">
      <!-- Close -->
      <button @click="isOpen = false" class="absolute top-3.5 end-4 z-10 text-gray-400 hover:text-gray-600 outline-none">
        <UIcon name="heroicons:x-mark" class="w-5 h-5" />
      </button>

      <div class="p-6 pb-4">
        <div class="flex items-center gap-2 mb-1">
          <span class="text-lg">{{ typeEmoji(connection?.type) }}</span>
          <h3 class="text-lg font-semibold text-[#1f2328]" style="font-family:'Spectral',ui-serif,Georgia,serif">
            {{ connection?.name || 'Browse files' }}
          </h3>
        </div>
        <p class="text-xs text-[#6b6b6b]">Pick files you have access to and ingest them as a data source.</p>
      </div>

      <!-- Body -->
      <div class="px-6 pb-2">
        <div class="fb rounded-[14px] overflow-hidden bg-white" style="border:1px solid #E9E0D3;">

          <!-- ── SIGN-IN (connect_required) state ────────────────────────── -->
          <div v-if="needsConnect" class="grid place-items-center text-center px-4 py-9">
            <div class="text-[17px] font-bold text-[#1f2328] mb-1.5">Connect your Microsoft account</div>
            <div class="text-[13px] text-[#6b6b6b] max-w-[440px] mb-4">
              You'll only ever see files <b>you</b> already have access to in SharePoint / OneDrive.
              We store a token for you, encrypted — never your password.
            </div>
            <button
              type="button"
              class="inline-flex items-center gap-2 text-white rounded-[10px] px-4 py-2.5 text-[13.5px] font-semibold disabled:opacity-60"
              style="background:#2B6FC0;"
              :disabled="signingIn"
              @click="signInWithMicrosoft"
            >
              <Spinner v-if="signingIn" class="w-3.5 h-3.5" />
              <span v-else style="font-size:15px">⊞</span>
              Sign in with Microsoft
            </button>
            <div class="mt-3 text-[11.5px] text-[#6b6b6b]">One-time. Revoke anytime in Settings.</div>
            <div v-if="signInError" class="mt-2 text-[11.5px] text-red-600">{{ signInError }}</div>
          </div>

          <!-- ── CONNECTED browser ───────────────────────────────────────── -->
          <template v-else>
            <!-- Search -->
            <div class="flex items-center gap-2 px-4 py-2.5" style="border-bottom:1px solid #E9E0D3;background:#FBFAF6;">
              <UIcon name="heroicons:magnifying-glass" class="w-4 h-4 text-[#9a958c] shrink-0" />
              <input
                v-model="search"
                type="text"
                placeholder="Search your files…"
                class="flex-1 bg-transparent text-[13px] outline-none placeholder:text-[#b3ada2]"
                @input="onSearchInput"
              />
              <button
                type="button"
                class="text-[11.5px] px-2 py-1 rounded-lg bg-white border text-[#1f2328] hover:bg-[#faf8f3] disabled:opacity-50"
                style="border-color:#E9E0D3;"
                :disabled="loading"
                @click="refresh"
              >Refresh</button>
            </div>

            <!-- Breadcrumb -->
            <div class="flex items-center gap-1.5 px-4 py-2.5 text-[12.5px] text-[#6b6b6b]" style="border-bottom:1px solid #F1EADC;">
              <template v-for="(crumb, i) in breadcrumbs" :key="crumb.id || 'root'">
                <span v-if="i > 0" class="text-[#c9c1b4]">›</span>
                <a
                  href="#"
                  class="hover:underline"
                  :class="i === breadcrumbs.length - 1 ? 'font-semibold text-[#1f2328]' : 'text-[#1F6F8B]'"
                  @click.prevent="goToCrumb(i)"
                >{{ crumb.name }}</a>
              </template>
              <span class="ml-auto inline-flex items-center gap-1.5 text-[11.5px]" style="color:#8a6d3b;">
                🔒 your files only
              </span>
            </div>

            <!-- Rows -->
            <div class="max-h-[44vh] overflow-y-auto">
              <!-- Loading -->
              <div v-if="loading" class="flex items-center justify-center py-10 text-[#9a958c]">
                <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">Loading…</span>
              </div>

              <!-- Error -->
              <div v-else-if="loadError" class="px-4 py-8 text-center text-[12.5px] text-red-600">
                {{ loadError }}
              </div>

              <!-- Empty -->
              <div
                v-else-if="!items.length"
                class="m-4 rounded-[12px] grid place-items-center text-center px-4 py-8 text-[#6b6b6b]"
                style="border:1.5px dashed #D8C8AC;background:#FCF8EF;"
              >
                <span class="text-[22px] mb-1">📭</span>
                <span class="text-[13px] font-semibold text-[#1f2328]">{{ search ? 'No matches' : 'This folder is empty' }}</span>
                <span class="text-[12px] mt-0.5">{{ search ? 'Try a different search.' : 'Nothing you can access here.' }}</span>
              </div>

              <!-- Items -->
              <template v-else>
                <div
                  v-for="it in items"
                  :key="it.id"
                  class="flex items-center gap-3 px-4 py-2.5"
                  style="border-bottom:1px solid #F4EEE3;"
                >
                  <!-- file checkbox -->
                  <input
                    v-if="!it.is_folder"
                    type="checkbox"
                    class="w-[17px] h-[17px] accent-[#C2541E]"
                    :checked="selected.has(it.id)"
                    @change="toggleSelect(it.id)"
                  />
                  <span v-else class="w-[17px]"></span>

                  <span class="w-[30px] h-[30px] rounded-[8px] grid place-items-center text-base shrink-0" style="background:#F0E9DB;">
                    {{ fileEmoji(it) }}
                  </span>

                  <div class="flex-1 min-w-0">
                    <div class="text-[13px] font-semibold text-[#1f2328] truncate">{{ it.name }}</div>
                    <div class="text-[11.5px] text-[#6b6b6b] truncate">
                      <template v-if="it.is_folder">folder</template>
                      <template v-else>
                        <span v-if="it.size != null">{{ humanSize(it.size) }}</span>
                        <span v-if="it.modified_at"> · {{ modifiedAgo(it.modified_at) }}</span>
                      </template>
                    </div>
                  </div>

                  <button
                    v-if="it.is_folder"
                    type="button"
                    class="text-[12px] px-2.5 py-1 rounded-lg bg-white border text-[#1f2328] hover:bg-[#faf8f3]"
                    style="border-color:#E9E0D3;"
                    @click="openFolder(it)"
                  >Open</button>
                </div>
              </template>
            </div>

            <!-- Footer -->
            <div class="flex items-center gap-2.5 px-4 py-3" style="border-top:1px solid #E9E0D3;background:#FBFAF6;">
              <span class="text-[12.5px] text-[#6b6b6b]"><b>{{ selected.size }}</b> selected</span>
              <button
                type="button"
                class="ml-auto inline-flex items-center gap-1.5 text-[13px] font-semibold text-white rounded-[10px] px-3.5 py-1.5 disabled:opacity-50"
                style="background:#C2541E;"
                :disabled="!selected.size || ingesting"
                @click="ingestSelected"
              >
                <Spinner v-if="ingesting" class="w-3.5 h-3.5" />
                Use selected → ingest
              </button>
            </div>
          </template>
        </div>

        <!-- Ingest summary -->
        <div v-if="ingestSummary" class="mt-3 text-[12px]">
          <span class="text-[#2F6F4F]">✔ Ingested {{ ingestSummary.ok }} file(s).</span>
          <span v-if="ingestSummary.failed" class="text-red-600 ms-2">{{ ingestSummary.failed }} failed.</span>
        </div>
      </div>

      <div class="px-6 pb-5 pt-1 text-[11.5px]" style="color:#8a6d3b;">
        🔒 Isolation = Microsoft's own ACLs · read with your token, never the admin's.
      </div>
    </div>
  </UModal>
</template>

<script setup lang="ts">
// Per-user file browser for the SharePoint / OneDrive / Google Drive connectors.
//
// Self-gates on HYBRID_FILE_BROWSER (read from /organization/hybrid-flags, same
// shape StudioConnectors reads HYBRID_AGENT_CONNECTORS — array of rows each with
// { env_name, effective }). Fail-soft: any error -> OFF -> hidden.
//
// OAuth sign-in is NOT reinvented: we reuse the exact trigger used in
// UserDataSourceCredentialsModal / useConnectionSignIn —
//   GET /connections/{id}/oauth/authorize  ->  window.location.href = authorization_url
//
// Browse endpoints (built in parallel):
//   GET  /connections/{id}/files?folder_id=&q=  -> { items:[...], folder_id }
//        409 { error:'connect_required' } -> show the sign-in state.
//   POST /connections/{id}/files/ingest  body { file_ids, studio_id?, data_source_name? }
//        -> { ingested:[{file_id,data_source_id,name}], errors:[] }
import { ref, reactive, computed, watch } from 'vue'
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{
  connection: any            // { id, type, name }
  organizationId?: string
  studioId?: string          // optional: pin ingested sources to this studio
  modelValue: boolean        // open
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'ingested', payload: any): void
}>()

const toast = useToast()

const isOpen = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

// ── Flag self-gate ──────────────────────────────────────────────────────────
const flagLoaded = ref(false)
const flagEnabled = ref(false)
async function loadFlag() {
  try {
    const { data } = await useMyFetch<any[]>('/organization/hybrid-flags')
    const rows = (data.value as any[]) || []
    const row = rows.find(r => r?.env_name === 'HYBRID_FILE_BROWSER')
    flagEnabled.value = !!row?.effective
  } catch {
    flagEnabled.value = false
  } finally {
    flagLoaded.value = true
  }
}

// ── State ───────────────────────────────────────────────────────────────────
const loading = ref(false)
const loadError = ref<string | null>(null)
const needsConnect = ref(false)
const items = ref<any[]>([])
const search = ref('')
const selected = ref<Set<string>>(new Set())
const ingesting = ref(false)
const ingestSummary = ref<{ ok: number; failed: number } | null>(null)

// Breadcrumb trail: [{ id: null, name: 'Root' }, { id, name }, …]
const breadcrumbs = ref<{ id: string | null; name: string }[]>([{ id: null, name: 'Root' }])
const currentFolderId = computed(() => breadcrumbs.value[breadcrumbs.value.length - 1]?.id ?? null)

// ── Icons / formatting ──────────────────────────────────────────────────────
function typeEmoji(t: string) {
  if (t === 'onedrive') return '☁️'
  if (t === 'google_drive') return '🗂️'
  return '📁'
}
function fileEmoji(it: any) {
  if (it.is_folder) return '📂'
  const n = (it.name || '').toLowerCase()
  const m = (it.mime_type || '').toLowerCase()
  if (n.endsWith('.xlsx') || n.endsWith('.xls') || m.includes('spreadsheet')) return '📊'
  if (n.endsWith('.csv')) return '📄'
  if (n.endsWith('.pdf')) return '📕'
  if (n.endsWith('.doc') || n.endsWith('.docx')) return '📝'
  return '📄'
}
function humanSize(bytes: number) {
  if (bytes == null) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}
function modifiedAgo(ts: string) {
  const seconds = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (Number.isNaN(seconds)) return ''
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `modified ${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `modified ${Math.floor(seconds / 3600)}h ago`
  return `modified ${Math.floor(seconds / 86400)}d ago`
}

// ── Fetch files ─────────────────────────────────────────────────────────────
async function fetchFiles(folderId: string | null, q: string) {
  if (!props.connection?.id) return
  loading.value = true
  loadError.value = null
  needsConnect.value = false
  try {
    const query: Record<string, any> = {}
    if (folderId) query.folder_id = folderId
    if (q && q.trim()) query.q = q.trim()
    const { data, error } = await useMyFetch<any>(`/connections/${props.connection.id}/files`, {
      method: 'GET',
      query,
    })
    if (error?.value) {
      const status = (error.value as any)?.status || (error.value as any)?.statusCode
      const body = (error.value as any)?.data || {}
      if (status === 409 || body?.error === 'connect_required') {
        needsConnect.value = true
        items.value = []
        return
      }
      loadError.value = body?.detail || body?.error || 'Could not load files.'
      items.value = []
      return
    }
    const v: any = data.value
    items.value = (Array.isArray(v) ? v : (v?.items || [])) as any[]
  } catch (e: any) {
    // $fetch throws on non-2xx — inspect the status for the 409 sign-in case.
    const status = e?.status || e?.statusCode || e?.response?.status
    const body = e?.data || e?.response?._data || {}
    if (status === 409 || body?.error === 'connect_required') {
      needsConnect.value = true
      items.value = []
    } else {
      loadError.value = body?.detail || body?.error || e?.message || 'Could not load files.'
      items.value = []
    }
  } finally {
    loading.value = false
  }
}

function refresh() {
  fetchFiles(currentFolderId.value, search.value)
}

// ── Navigation ──────────────────────────────────────────────────────────────
function openFolder(folder: any) {
  selected.value = new Set()
  search.value = ''
  breadcrumbs.value.push({ id: folder.id, name: folder.name })
  fetchFiles(folder.id, '')
}
function goToCrumb(i: number) {
  if (i === breadcrumbs.value.length - 1) return
  selected.value = new Set()
  search.value = ''
  breadcrumbs.value = breadcrumbs.value.slice(0, i + 1)
  fetchFiles(currentFolderId.value, '')
}

// ── Search (debounced) ──────────────────────────────────────────────────────
let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => fetchFiles(currentFolderId.value, search.value), 350)
}

// ── Selection ───────────────────────────────────────────────────────────────
function toggleSelect(id: string) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

// ── Sign in with Microsoft (reuses the existing oauth/authorize trigger) ─────
const signingIn = ref(false)
const signInError = ref<string | null>(null)
async function signInWithMicrosoft() {
  if (!props.connection?.id || signingIn.value) return
  signingIn.value = true
  signInError.value = null
  try {
    const { data, error } = await useMyFetch<any>(`/connections/${props.connection.id}/oauth/authorize`, { method: 'GET' })
    if (error?.value) throw error.value
    const result = data.value as any
    if (result?.authorization_url) {
      // Navigates away to Microsoft; after the callback the user returns and
      // re-opening the browser re-fetches (token now present).
      window.location.href = result.authorization_url
      return
    }
    signInError.value = 'Sign-in did not return an authorization URL.'
  } catch (e: any) {
    signInError.value = e?.data?.detail || e?.message || 'Could not start sign-in.'
  } finally {
    signingIn.value = false
  }
}

// ── Ingest ──────────────────────────────────────────────────────────────────
async function ingestSelected() {
  if (!selected.value.size || ingesting.value) return
  ingesting.value = true
  ingestSummary.value = null
  try {
    const body: Record<string, any> = { file_ids: Array.from(selected.value) }
    if (props.studioId) body.studio_id = props.studioId
    const { data, error } = await useMyFetch<any>(`/connections/${props.connection.id}/files/ingest`, {
      method: 'POST',
      body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json' },
    })
    if (error?.value) {
      toast.add({ title: (error.value as any)?.data?.detail || 'Ingest failed', color: 'red' })
      return
    }
    const v: any = data.value || {}
    const ok = (v.ingested || []).length
    const failed = (v.errors || []).length
    ingestSummary.value = { ok, failed }
    if (ok) {
      toast.add({ title: `Ingested ${ok} file${ok === 1 ? '' : 's'}`, color: 'green' })
      emit('ingested', v)
      // Close shortly after so the user sees the toast/summary.
      isOpen.value = false
    } else {
      toast.add({ title: 'No files were ingested', description: (v.errors?.[0]?.error || ''), color: 'red' })
    }
  } catch (e: any) {
    toast.add({ title: e?.data?.detail || e?.message || 'Ingest failed', color: 'red' })
  } finally {
    ingesting.value = false
  }
}

// ── Open lifecycle ──────────────────────────────────────────────────────────
function resetBrowser() {
  breadcrumbs.value = [{ id: null, name: 'Root' }]
  items.value = []
  selected.value = new Set()
  search.value = ''
  loadError.value = null
  ingestSummary.value = null
  needsConnect.value = false
}

watch(isOpen, async (open) => {
  if (!open) return
  if (!flagLoaded.value) await loadFlag()
  if (!flagEnabled.value) { isOpen.value = false; return }
  resetBrowser()
  fetchFiles(null, '')
})

// Load the flag eagerly so the modal is allowed to render on first open.
loadFlag()
</script>
