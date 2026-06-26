<template>
  <!-- Feature self-gates on HYBRID_AGENT_CONNECTORS. Off / unknown -> render nothing. -->
  <div v-if="flagLoaded && flagEnabled">
    <!-- Header -->
    <div class="flex items-start justify-between mb-4">
      <div>
        <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family:'Spectral',ui-serif,Georgia,serif">Connectors</h2>
        <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[640px]">
          Data sources this agent can use. <b>Private connectors</b> belong only to you — credentials,
          config and tables are never visible to members, and they can't be shared or reused by anyone else.
        </p>
      </div>
      <button
        v-if="canEdit"
        type="button"
        class="shrink-0 inline-flex items-center gap-1.5 text-xs font-semibold text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-lg px-3.5 py-1.5 transition-colors"
        @click="openCreate"
      >
        <UIcon name="i-heroicons-plus" class="w-3.5 h-3.5" /> Add connector
      </button>
    </div>

    <!-- Legend -->
    <div class="flex flex-wrap items-center gap-4 text-[12px] text-[#6b6b6b] mb-4">
      <span class="inline-flex items-center gap-1.5">
        <span class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full" style="background:#FBF3E2;color:#8a6d3b;border:1px solid #ECDCBB;">🔒 Private</span>
        only you
      </span>
      <span class="inline-flex items-center gap-1.5">
        <span class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full" style="background:#ECF1EC;color:#2F6F4F;border:1px solid #d4e3d4;">🌐 Org</span>
        shared infra
      </span>
    </div>

    <!-- Loading -->
    <div v-if="loading && !loaded" class="flex items-center justify-center py-10 text-[#9a958c]">
      <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">Loading…</span>
    </div>

    <!-- Grid -->
    <div v-else class="grid gap-3.5" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr));">

      <!-- Connector cards -->
      <div
        v-for="conn in connectors"
        :key="conn.id"
        class="rounded-[14px] p-4 relative"
        :class="conn.is_org ? 'border bg-white' : 'border'"
        :style="conn.is_org
          ? 'border-color:#E9E0D3;'
          : 'border-color:#E7D7B8;background:linear-gradient(180deg,#FFFDF7,#FBF6EA);'"
      >
        <div class="flex items-center gap-3 mb-2.5">
          <div class="w-9 h-9 rounded-[10px] grid place-items-center text-lg" style="background:#F0E9DB;">
            {{ typeEmoji(conn.type) }}
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-bold text-[#1f2328] truncate">{{ conn.name }}</div>
            <div class="text-[12px] text-[#6b6b6b] truncate">
              {{ typeLabel(conn.type) }}<span v-if="conn.is_org"> · org connector</span>
            </div>
          </div>
          <span
            v-if="conn.is_org"
            class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full shrink-0"
            style="background:#ECF1EC;color:#2F6F4F;border:1px solid #d4e3d4;"
          >🌐 Org</span>
          <span
            v-else
            class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full shrink-0"
            style="background:#FBF3E2;color:#8a6d3b;border:1px solid #ECDCBB;"
          >🔒 Private</span>
        </div>

        <div class="flex items-center gap-3.5 text-[12px] text-[#6b6b6b] mt-2.5 mb-3">
          <span class="inline-flex items-center">
            <span class="w-2 h-2 rounded-full inline-block me-1.5" :style="`background:${conn.is_org || isConnected(conn) ? '#2F6F4F' : '#d8b48f'}`"></span>
            {{ isConnected(conn) ? 'Connected' : 'Not tested' }}
          </span>
          <span v-if="conn.is_org">admin-managed</span>
          <span v-else-if="conn.table_count != null">{{ conn.table_count }} tables</span>
        </div>

        <!-- Inline test result -->
        <div v-if="testResults[conn.id]" class="text-[11.5px] mb-2">
          <span :class="testResults[conn.id]?.success ? 'text-green-600' : 'text-red-600'">
            {{ testResults[conn.id]?.success ? (testResults[conn.id]?.message || 'Connection successful') : (testResults[conn.id]?.message || 'Connection failed') }}
          </span>
        </div>

        <!-- Owner actions (private only) -->
        <div v-if="!conn.is_org" class="flex flex-wrap gap-1.5 pt-2.5 border-t" style="border-color:#F1EADC;">
          <button class="text-[12.5px] px-2.5 py-1 rounded-lg bg-white border border-[#E9E0D3] text-[#1f2328] hover:bg-[#faf8f3] disabled:opacity-50"
            :disabled="!canEdit || testingId === conn.id" @click="testConnection(conn)">
            <Spinner v-if="testingId === conn.id" class="inline w-3 h-3" /> <template v-else>Test</template>
          </button>
          <button class="text-[12.5px] px-2.5 py-1 rounded-lg bg-white border border-[#E9E0D3] text-[#1f2328] hover:bg-[#faf8f3] disabled:opacity-50"
            :disabled="!canEdit" @click="openEdit(conn)">Edit</button>
          <button class="text-[12.5px] px-2.5 py-1 rounded-lg bg-white border border-[#E9E0D3] text-[#1f2328] hover:bg-[#faf8f3] disabled:opacity-50"
            :disabled="!canEdit || reindexingId === conn.id" @click="reindexConnection(conn)">
            <Spinner v-if="reindexingId === conn.id" class="inline w-3 h-3" /> <template v-else>Reindex</template>
          </button>
          <button class="text-[12.5px] px-2.5 py-1 rounded-lg bg-white border text-[#a13d3d] hover:bg-[#fdf6f6] disabled:opacity-50" style="border-color:#e3c4c4;"
            :disabled="!canEdit || deletingId === conn.id" @click="deleteConnector(conn)">
            <Spinner v-if="deletingId === conn.id" class="inline w-3 h-3" /> <template v-else>Delete</template>
          </button>
        </div>
        <!-- Org connector: read-only -->
        <div v-else class="flex flex-wrap gap-1.5 pt-2.5 border-t" style="border-color:#F1EADC;">
          <button class="text-[12.5px] px-2.5 py-1 rounded-lg bg-white border border-[#E9E0D3] text-[#9a958c] cursor-not-allowed" disabled>Edit (admin only)</button>
        </div>

        <div v-if="!conn.is_org" class="text-[11.5px] mt-2 flex items-center gap-1.5" style="color:#8a6d3b;">
          🔒 Owned by you · not shareable
        </div>
      </div>

      <!-- Add card (dashed) -->
      <button
        v-if="canEdit"
        type="button"
        class="rounded-[14px] p-4 flex flex-col items-center justify-center gap-2 text-[#6b6b6b] transition-colors min-h-[150px]"
        style="border:1.5px dashed #D8C8AC;background:#FCF8EF;"
        @click="openCreate"
      >
        <span class="text-[26px] leading-none text-[#C2541E]">+</span>
        <span class="font-semibold text-[#1f2328] text-sm">New private connector</span>
        <span class="text-[12px]">Only this agent · only you</span>
      </button>
    </div>

    <!-- ── Create / Edit modal ───────────────────────────────────────────── -->
    <UModal v-model="showModal" :ui="{ width: 'sm:max-w-xl' }">
      <div class="p-6 relative" style="background:#FBFAF6;">
        <button @click="closeModal" class="absolute top-4 end-4 text-gray-400 hover:text-gray-600 outline-none">
          <UIcon name="heroicons:x-mark" class="w-5 h-5" />
        </button>
        <h3 class="text-lg font-semibold" style="color:#1f2328;">{{ editingId ? 'Edit private connector' : 'New private connector' }}</h3>
        <p class="text-sm" style="color:#6b6b6b;">For agent <b>{{ studio?.name || 'this agent' }}</b></p>

        <!-- Lock banner -->
        <div class="flex gap-2.5 items-start rounded-xl p-3 my-4 text-[12.5px]" style="background:#FBF3E2;border:1px solid #ECDCBB;color:#6f5829;">
          <span class="text-base leading-none">🔒</span>
          <div><b style="color:#5a4720;">Private &amp; non-shareable.</b> Bound to this agent and owned by you. Credentials are
            encrypted and never shown to members. It can't be made public or shared to groups.</div>
        </div>

        <!-- Type picker -->
        <div class="mb-4">
          <label class="block text-[12.5px] font-semibold mb-2" style="color:#1f2328;">Connector type</label>
          <div class="grid grid-cols-3 gap-2.5">
            <button
              v-for="ct in connectorTypes"
              :key="ct.type"
              type="button"
              class="rounded-[11px] border bg-white px-2 py-3 text-center text-[12px] transition-colors"
              :class="form.type === ct.type ? 'font-semibold' : ''"
              :style="form.type === ct.type
                ? 'border-color:#C2541E;background:#FBEEDF;'
                : 'border-color:#E9E0D3;'"
              @click="form.type = ct.type"
            >
              <span class="text-[20px] block mb-1">{{ ct.emoji }}</span>{{ ct.label }}
            </button>
          </div>
        </div>

        <!-- Name -->
        <div class="mb-3.5">
          <label class="block text-[12.5px] font-semibold mb-1.5" style="color:#1f2328;">Name</label>
          <UInput v-model="form.name" placeholder="prod-postgres" />
        </div>

        <!-- Connection fields -->
        <template v-if="showDbFields">
          <div class="grid grid-cols-2 gap-3">
            <div class="mb-3.5">
              <label class="block text-[12.5px] font-semibold mb-1.5" style="color:#1f2328;">Host</label>
              <UInput v-model="form.config.host" placeholder="db.internal.host" />
            </div>
            <div class="mb-3.5">
              <label class="block text-[12.5px] font-semibold mb-1.5" style="color:#1f2328;">Port</label>
              <UInput v-model="form.config.port" :placeholder="defaultPort" />
            </div>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div class="mb-3.5">
              <label class="block text-[12.5px] font-semibold mb-1.5" style="color:#1f2328;">Database</label>
              <UInput v-model="form.config.database" placeholder="analytics" />
            </div>
            <div class="mb-3.5">
              <label class="block text-[12.5px] font-semibold mb-1.5" style="color:#1f2328;">User</label>
              <UInput v-model="form.config.user" placeholder="readonly" />
            </div>
          </div>
          <div class="mb-3.5">
            <label class="block text-[12.5px] font-semibold mb-1.5" style="color:#1f2328;">Password <span class="text-[#8a6d3b]">🔒 encrypted</span></label>
            <UInput v-model="form.credentials.password" type="password" :placeholder="editingId ? 'Leave blank to keep current' : '••••••••••'" />
          </div>
        </template>

        <!-- REST API / CSV : single endpoint/url field -->
        <template v-else>
          <div class="mb-3.5">
            <label class="block text-[12.5px] font-semibold mb-1.5" style="color:#1f2328;">{{ form.type === 'csv' ? 'File URL / path' : 'Base URL' }}</label>
            <UInput v-model="form.config.url" :placeholder="form.type === 'csv' ? 'https://… or /path/to.csv' : 'https://api.example.com'" />
          </div>
          <div v-if="form.type === 'rest_api'" class="mb-3.5">
            <label class="block text-[12.5px] font-semibold mb-1.5" style="color:#1f2328;">API key <span class="text-[#8a6d3b]">🔒 encrypted</span></label>
            <UInput v-model="form.credentials.api_key" type="password" :placeholder="editingId ? 'Leave blank to keep current' : '••••••••••'" />
          </div>
        </template>

        <!-- Test row -->
        <div class="flex items-center gap-2.5 my-1.5">
          <button type="button"
            class="text-[12.5px] px-3 py-1.5 rounded-lg bg-white border border-[#E9E0D3] text-[#1f2328] hover:bg-[#faf8f3] disabled:opacity-50"
            :disabled="testingModal" @click="testModalConnection">
            <Spinner v-if="testingModal" class="inline w-3 h-3 me-1" />Test connection
          </button>
          <span v-if="modalTestResult" class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full"
            :style="modalTestResult.success ? 'background:#EAF3EE;color:#2F6F4F;' : 'background:#FBEAEA;color:#a13d3d;'">
            {{ modalTestResult.success ? `✔ ${modalTestResult.message || 'Connected'}` : `✕ ${modalTestResult.message || 'Failed'}` }}
          </span>
        </div>

        <!-- Footer -->
        <div class="flex justify-between items-center gap-2.5 border-t pt-4 mt-2" style="border-color:#E9E0D3;">
          <span class="text-[12px]" style="color:#8a6d3b;">🔒 Saved to this agent only</span>
          <div class="flex gap-2">
            <UButton color="gray" variant="ghost" @click="closeModal">Cancel</UButton>
            <UButton color="orange" :loading="saving" :disabled="!canSave" @click="saveConnector">
              {{ editingId ? 'Save changes' : 'Create & pin to agent' }}
            </UButton>
          </div>
        </div>
      </div>
    </UModal>
  </div>
</template>

<script setup lang="ts">
// Per-agent PRIVATE connectors. A connector created here is owned by the caller
// and bound to this studio (owner_user_id + studio_id set on the Connection row).
// It is NEVER shareable: no share/members/make-public surface exists in this tab.
//
// Self-gates on HYBRID_AGENT_CONNECTORS (read from /organization/hybrid-flags,
// same shape MyGroupsManager reads HYBRID_USER_GROUPS — an array of rows each
// carrying { env_name, effective }). Fail-soft: any error -> treated as OFF -> hidden.
//
// Body shapes mirror ConnectForm.vue exactly so the backend connection-create
// schema matches: { type, name, config:{host,port,database,user,...}, credentials:{password|api_key} }.
import { ref, reactive, computed, onMounted } from 'vue'
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{
  // The studio object — derive studioId/organizationId like StudioConnection.vue does.
  studio: any
  canEdit?: boolean
}>()

const toast = useToast()

// Derive ids from the studio object (same approach as StudioConnection: id off the
// passed studio; org id is carried on the studio row when present).
const studioId = computed(() => String(props.studio?.id || ''))
const canEdit = computed(() => props.canEdit !== false)

// ── Connector type catalog (matches the mockup grid) ──────────────────────
const connectorTypes = [
  { type: 'postgresql', label: 'PostgreSQL', emoji: '🐘' },
  { type: 'mysql', label: 'MySQL', emoji: '🐬' },
  { type: 'snowflake', label: 'Snowflake', emoji: '❄️' },
  { type: 'ms_fabric', label: 'MS Fabric', emoji: '🟦' },
  { type: 'rest_api', label: 'REST API', emoji: '📦' },
  { type: 'csv', label: 'CSV / File', emoji: '📁' },
]
const DB_TYPES = new Set(['postgresql', 'mysql', 'snowflake', 'ms_fabric'])
const DEFAULT_PORTS: Record<string, string> = { postgresql: '5432', mysql: '3306', snowflake: '443', ms_fabric: '1433' }

function typeEmoji(t: string) {
  return connectorTypes.find(c => c.type === t)?.emoji || '🔌'
}
function typeLabel(t: string) {
  return connectorTypes.find(c => c.type === t)?.label || (t || 'Connector')
}

// ── Flag self-gate ────────────────────────────────────────────────────────
const flagLoaded = ref(false)
const flagEnabled = ref(false)
async function loadFlag() {
  try {
    const { data } = await useMyFetch<any[]>('/organization/hybrid-flags')
    const rows = (data.value as any[]) || []
    const row = rows.find(r => r?.env_name === 'HYBRID_AGENT_CONNECTORS')
    flagEnabled.value = !!row?.effective
  } catch {
    // Fail-soft: hide the feature rather than render a broken UI.
    flagEnabled.value = false
  } finally {
    flagLoaded.value = true
  }
}

// ── List ──────────────────────────────────────────────────────────────────
const connectors = ref<any[]>([])
const loading = ref(false)
const loaded = ref(false)

function isConnected(conn: any) {
  const local = testResults.value[conn.id]
  if (local) return !!local.success
  const s = (conn.status || conn.user_status?.status || '').toLowerCase()
  return s === 'success' || s === 'connected' || s === 'completed' || conn.connected === true
}

async function loadConnectors() {
  if (!studioId.value) { loaded.value = true; return }
  loading.value = true
  try {
    // Private connectors pinned to this studio. Backend scopes by studio_id +
    // owner_user_id and may also echo org connectors flagged is_org=true.
    const { data, error } = await useMyFetch<any>(`/studios/${studioId.value}/connectors`, { method: 'GET' })
    if (error?.value) { connectors.value = []; return }
    const v: any = data.value
    connectors.value = (Array.isArray(v) ? v : (v?.connectors || v?.items || [])) as any[]
  } catch {
    // Graceful: never crash the tab on a fetch failure.
    connectors.value = []
  } finally {
    loading.value = false
    loaded.value = true
  }
}

// ── Per-card actions ────────────────────────────────────────────────────────
const testingId = ref<string | null>(null)
const reindexingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const testResults = ref<Record<string, any>>({})

async function testConnection(conn: any) {
  if (testingId.value) return
  testingId.value = conn.id
  testResults.value[conn.id] = null
  try {
    const { data } = await useMyFetch<any>(`/connections/${conn.id}/test`, { method: 'POST' })
    testResults.value[conn.id] = (data.value as any) || { success: false }
  } catch (e: any) {
    testResults.value[conn.id] = { success: false, message: e?.message || 'Connection failed' }
  } finally {
    testingId.value = null
  }
}

async function reindexConnection(conn: any) {
  if (reindexingId.value) return
  reindexingId.value = conn.id
  try {
    await useMyFetch(`/connections/${conn.id}/reindex`, { method: 'POST' })
    toast.add({ title: 'Reindexing started', color: 'green' })
    await loadConnectors()
  } catch (e: any) {
    toast.add({ title: 'Failed to start reindexing', description: e?.message || '', color: 'red' })
  } finally {
    reindexingId.value = null
  }
}

async function deleteConnector(conn: any) {
  if (!window.confirm(`Delete private connector "${conn.name}"? This can't be undone.`)) return
  deletingId.value = conn.id
  try {
    const { error } = await useMyFetch(`/studios/${studioId.value}/connectors/${conn.id}`, { method: 'DELETE' })
    if (error?.value) {
      toast.add({ title: (error.value as any).data?.detail || 'Failed to delete connector', color: 'red' })
      return
    }
    toast.add({ title: 'Connector deleted', color: 'green' })
    await loadConnectors()
  } catch (e: any) {
    toast.add({ title: e?.data?.detail || e?.message || 'Failed to delete connector', color: 'red' })
  } finally {
    deletingId.value = null
  }
}

// ── Create / Edit modal ─────────────────────────────────────────────────────
const showModal = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const testingModal = ref(false)
const modalTestResult = ref<any>(null)

const form = reactive<{ type: string; name: string; config: Record<string, any>; credentials: Record<string, any> }>({
  type: 'postgresql',
  name: '',
  config: {},
  credentials: {},
})

const showDbFields = computed(() => DB_TYPES.has(form.type))
const defaultPort = computed(() => DEFAULT_PORTS[form.type] || '')
const canSave = computed(() => !!form.type && !!form.name.trim())

function resetForm() {
  form.type = 'postgresql'
  form.name = ''
  form.config = {}
  form.credentials = {}
  modalTestResult.value = null
}

function openCreate() {
  editingId.value = null
  resetForm()
  showModal.value = true
}

function openEdit(conn: any) {
  editingId.value = conn.id
  form.type = conn.type || 'postgresql'
  form.name = conn.name || ''
  // Config is non-secret and safe to prefill; credentials are never returned.
  form.config = { ...(conn.config || {}) }
  form.credentials = {}
  modalTestResult.value = null
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

// Build the connection-create body — mirrors ConnectForm.vue field names exactly.
function buildBody() {
  const config: Record<string, any> = { ...form.config }
  if (showDbFields.value && config.port != null && config.port !== '') {
    const n = Number(config.port)
    if (!Number.isNaN(n)) config.port = n
  }
  // Drop blank credential values so an edit keeps the existing secret.
  const credentials: Record<string, any> = {}
  for (const [k, v] of Object.entries(form.credentials)) {
    if (v != null && String(v).trim()) credentials[k] = v
  }
  return { type: form.type, name: form.name.trim(), config, credentials }
}

async function testModalConnection() {
  if (testingModal.value || !form.type) return
  testingModal.value = true
  modalTestResult.value = null
  try {
    const body = buildBody()
    // Same test endpoint ConnectForm uses for new connections.
    const { data } = await useMyFetch<any>('/data_sources/test_connection', {
      method: 'POST',
      body: JSON.stringify({ ...body, is_public: false }),
      headers: { 'Content-Type': 'application/json' },
    })
    const v: any = data.value
    modalTestResult.value = { success: !!v?.success, message: v?.message || (v?.success ? 'Connected' : 'Connection failed') }
  } catch (e: any) {
    modalTestResult.value = { success: false, message: e?.message || 'Request failed' }
  } finally {
    testingModal.value = false
  }
}

async function saveConnector() {
  if (!canSave.value || saving.value) return
  saving.value = true
  try {
    const body = buildBody()
    if (editingId.value) {
      const { error } = await useMyFetch(`/studios/${studioId.value}/connectors/${editingId.value}`, {
        method: 'PUT',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      })
      if (error?.value) {
        toast.add({ title: (error.value as any).data?.detail || 'Failed to update connector', color: 'red' })
        return
      }
      toast.add({ title: 'Connector updated', color: 'green' })
    } else {
      const { error } = await useMyFetch(`/studios/${studioId.value}/connectors`, {
        method: 'POST',
        body: JSON.stringify(body),
        headers: { 'Content-Type': 'application/json' },
      })
      if (error?.value) {
        toast.add({ title: (error.value as any).data?.detail || 'Failed to create connector', color: 'red' })
        return
      }
      toast.add({ title: 'Private connector pinned to this agent', color: 'green' })
    }
    showModal.value = false
    await loadConnectors()
  } catch (e: any) {
    toast.add({ title: e?.data?.detail || e?.message || 'Failed to save connector', color: 'red' })
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadFlag()
  if (flagEnabled.value) await loadConnectors()
})
</script>
