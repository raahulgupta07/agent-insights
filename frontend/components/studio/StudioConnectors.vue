<template>
  <!-- Feature self-gates on HYBRID_AGENT_CONNECTORS. Off / unknown -> render nothing. -->
  <div v-if="flagLoaded && flagEnabled">
    <!-- Header -->
    <div class="flex items-start justify-between mb-4">
      <div>
        <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family:'Spectral',ui-serif,Georgia,serif">Connectors</h2>
        <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[680px]">
          Data sources this agent can use. <b>Activate</b> a connector to let the agent query it —
          only <b>active</b> connectors are used and kept in sync. <b>My connectors</b> are private to you;
          <b>shared connectors</b> are configured by an admin and can be reused.
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

    <!-- Filter chips -->
    <div class="inline-flex rounded-lg border border-[#E9E0D3] bg-white p-0.5 mb-4">
      <button
        type="button"
        @click="tab = 'all'"
        :class="['px-3.5 py-1.5 text-xs rounded-md transition inline-flex items-center gap-1.5', tab === 'all' ? 'bg-[#FBEEDF] text-[#C2541E] font-semibold' : 'text-[#6b6b6b] hover:text-[#1f2328]']"
      >
        All
        <span class="text-[10px] px-1.5 py-px rounded-full" :class="tab === 'all' ? 'bg-[#C2541E] text-white' : 'bg-[#EFEAE0] text-[#6b6b6b]'">{{ mine.length + shared.length }}</span>
      </button>
      <button
        type="button"
        @click="tab = 'mine'"
        :class="['px-3.5 py-1.5 text-xs rounded-md transition inline-flex items-center gap-1.5', tab === 'mine' ? 'bg-[#FBEEDF] text-[#C2541E] font-semibold' : 'text-[#6b6b6b] hover:text-[#1f2328]']"
      >
        🔒 Mine
        <span class="text-[10px] px-1.5 py-px rounded-full" :class="tab === 'mine' ? 'bg-[#C2541E] text-white' : 'bg-[#EFEAE0] text-[#6b6b6b]'">{{ mine.length }}</span>
      </button>
      <button
        type="button"
        @click="tab = 'shared'"
        :class="['px-3.5 py-1.5 text-xs rounded-md transition inline-flex items-center gap-1.5', tab === 'shared' ? 'bg-[#ECF1EC] text-[#2F6F4F] font-semibold' : 'text-[#6b6b6b] hover:text-[#1f2328]']"
      >
        🌐 Shared
        <span class="text-[10px] px-1.5 py-px rounded-full" :class="tab === 'shared' ? 'bg-[#2F6F4F] text-white' : 'bg-[#EFEAE0] text-[#6b6b6b]'">{{ shared.length }}</span>
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading && !loaded" class="flex items-center justify-center py-10 text-[#9a958c]">
      <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">Loading…</span>
    </div>

    <template v-else>
      <!-- Connectors table -->
      <ConnectorsTable
        :rows="tableRows"
        context="studio"
        @activate="activate"
        @deactivate="deactivate"
        @test="testConnection"
        @edit="openEdit"
        @delete="deleteConnector"
        @share="openSharing"
      />

      <!-- Inline test result (latest) -->
      <div v-if="lastTest" class="text-[11.5px] mt-2">
        <span :class="lastTest.success ? 'text-green-600' : 'text-red-600'">
          {{ lastTest.name }}: {{ lastTest.success ? (lastTest.message || 'Connection successful') : (lastTest.message || 'Connection failed') }}
        </span>
      </div>

      <!-- Footer note -->
      <p class="text-[11.5px] text-[#9a958c] mt-4">
        Only <b>active</b> connectors are queryable by this agent and kept in sync. Activating triggers a data sync in the background.
        New connectors are <b>private</b> by default — use <b>Who can use</b> to share.
      </p>
    </template>

    <!-- ── Create / Edit modal (private connectors) ──────────────────────────── -->
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
          <span class="text-[12px]" style="color:#8a6d3b;">🔒 Saved to this agent only · activated automatically</span>
          <div class="flex gap-2">
            <UButton color="gray" variant="ghost" @click="closeModal">Cancel</UButton>
            <UButton color="orange" :loading="saving" :disabled="!canSave" @click="saveConnector">
              {{ editingId ? 'Save changes' : 'Create & activate' }}
            </UButton>
          </div>
        </div>
      </div>
    </UModal>

    <!-- CREATE: full connector catalog (all ~44 types) — forced personal scope,
         bound to this studio. Same component the admin Connectors page uses. -->
    <AddConnectionModal
      v-model="showAddModal"
      :can-create-shared="false"
      :individual-only="true"
      :defer-sharing="true"
      :studio-id="studioId"
      @created="onConnectorCreated"
    />

    <!-- Sliding right-hand sharing panel (Private / Shared / Org-wide + grants) -->
    <ConnectorSharingPanel
      v-model="showSharing"
      :connection="sharingConn"
      @saved="loadConnectors"
    />
  </div>
</template>

<script setup lang="ts">
// Per-agent connectors — two tabs:
//   • My Connectors    — the caller's own PRIVATE connectors (owner_user_id=self,
//                        studio_id=this studio). Create/edit/delete/test here.
//   • Shared Connectors — org/shared connectors the caller may reuse (admin-managed).
//
// "Activate for agent" pins the connector's DataSource to this studio so the agent
// can query it and a data sync runs. Only ACTIVE connectors are used by the agent.
//
// Self-gates on HYBRID_AGENT_CONNECTORS (read from /organization/hybrid-flags).
// Backend GET /studios/{id}/connectors returns { mine:[...], shared:[...] }; each
// item carries { connection_id, name, type, owner_user_id, is_org, active,
// data_source_id, sync_status, last_synced_at }.
import { ref, reactive, computed, onMounted } from 'vue'
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{
  studio: any
  canEdit?: boolean
}>()

const toast = useToast()

const studioId = computed(() => String(props.studio?.id || ''))
const canEdit = computed(() => props.canEdit !== false)

// ── Connector type catalog ─────────────────────────────────────────────────
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
function shortDate(s: string) {
  try { return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) } catch { return '' }
}

// ── Visibility (3-level: private | shared | org) ─────────────────────────────
// Prefer the explicit `visibility` field; fall back to is_org/owner_user_id.
function connVisibility(conn: any): 'private' | 'shared' | 'org' {
  const v = conn?.visibility
  if (v === 'private' || v === 'shared' || v === 'org') return v
  return conn?.is_org ? 'org' : 'private'
}
function visBadge(conn: any): { label: string; style: string } {
  switch (connVisibility(conn)) {
    case 'org':
      return { label: '🌐 Org-wide', style: 'background:#ECF1EC;color:#2F6F4F;border:1px solid #d4e3d4;' }
    case 'shared':
      return { label: '👥 Shared', style: 'background:#E4F0F4;color:#1F6F8B;border:1px solid #cfe2e8;' }
    default:
      return { label: '🔒 Private', style: 'background:#FBF3E2;color:#8a6d3b;border:1px solid #ECDCBB;' }
  }
}

// ── Flag self-gate ──────────────────────────────────────────────────────────
const flagLoaded = ref(false)
const flagEnabled = ref(false)
async function loadFlag() {
  try {
    const { data } = await useMyFetch<any[]>('/organization/hybrid-flags')
    const rows = (data.value as any[]) || []
    const row = rows.find(r => r?.env_name === 'HYBRID_AGENT_CONNECTORS')
    flagEnabled.value = !!row?.effective
  } catch {
    flagEnabled.value = false
  } finally {
    flagLoaded.value = true
  }
}

// ── List (two tabs) ──────────────────────────────────────────────────────────
const tab = ref<'all' | 'mine' | 'shared'>('all')
const mine = ref<any[]>([])
const shared = ref<any[]>([])
const loading = ref(false)
const loaded = ref(false)

// Build table rows from the {mine, shared} payload. Each row keeps the original
// connection_id (handlers key off it) plus normalized id/can_edit/is_org.
const tableRows = computed(() => {
  const mineRows = mine.value.map((item: any) => ({ ...item, id: item.connection_id, can_edit: true, is_org: false }))
  const sharedRows = shared.value.map((item: any) => ({ ...item, id: item.connection_id, can_edit: false, is_org: true }))
  if (tab.value === 'mine') return mineRows
  if (tab.value === 'shared') return sharedRows
  return [...mineRows, ...sharedRows]
})

async function loadConnectors() {
  if (!studioId.value) { loaded.value = true; return }
  loading.value = true
  try {
    const { data, error } = await useMyFetch<any>(`/studios/${studioId.value}/connectors`, { method: 'GET' })
    if (error?.value) { mine.value = []; shared.value = []; return }
    const v: any = data.value || {}
    mine.value = Array.isArray(v?.mine) ? v.mine : []
    shared.value = Array.isArray(v?.shared) ? v.shared : []
  } catch {
    mine.value = []
    shared.value = []
  } finally {
    loading.value = false
    loaded.value = true
  }
}

// ── Activate / Deactivate ─────────────────────────────────────────────────────
const activatingId = ref<string | null>(null)

async function activate(conn: any) {
  if (activatingId.value) return
  activatingId.value = conn.connection_id
  try {
    const { error } = await useMyFetch(`/studios/${studioId.value}/connectors/${conn.connection_id}/activate`, { method: 'POST' })
    if (error?.value) {
      toast.add({ title: (error.value as any).data?.detail || 'Failed to activate connector', color: 'red' })
      return
    }
    toast.add({ title: 'Connector activated · syncing in background', color: 'green' })
    await loadConnectors()
  } catch (e: any) {
    toast.add({ title: e?.data?.detail || e?.message || 'Failed to activate connector', color: 'red' })
  } finally {
    activatingId.value = null
  }
}

async function deactivate(conn: any) {
  if (activatingId.value) return
  activatingId.value = conn.connection_id
  try {
    const { error } = await useMyFetch(`/studios/${studioId.value}/connectors/${conn.connection_id}/activate`, { method: 'DELETE' })
    if (error?.value) {
      toast.add({ title: (error.value as any).data?.detail || 'Failed to deactivate connector', color: 'red' })
      return
    }
    toast.add({ title: 'Connector deactivated', color: 'green' })
    await loadConnectors()
  } catch (e: any) {
    toast.add({ title: e?.data?.detail || e?.message || 'Failed to deactivate connector', color: 'red' })
  } finally {
    activatingId.value = null
  }
}

// ── Per-card actions (private only) ───────────────────────────────────────────
const testingId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const lastTest = ref<{ name: string; success: boolean; message?: string } | null>(null)

async function testConnection(conn: any) {
  if (testingId.value) return
  testingId.value = conn.connection_id
  lastTest.value = null
  try {
    const { data } = await useMyFetch<any>(`/connections/${conn.connection_id}/test`, { method: 'POST' })
    const r = (data.value as any) || { success: false }
    lastTest.value = { name: conn.name, success: !!r.success, message: r.message }
  } catch (e: any) {
    lastTest.value = { name: conn.name, success: false, message: e?.message || 'Connection failed' }
  } finally {
    testingId.value = null
  }
}

async function deleteConnector(conn: any) {
  if (!window.confirm(`Delete private connector "${conn.name}"? This can't be undone.`)) return
  deletingId.value = conn.connection_id
  try {
    const { error } = await useMyFetch(`/studios/${studioId.value}/connectors/${conn.connection_id}`, { method: 'DELETE' })
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

// ── Create / Edit modal ───────────────────────────────────────────────────────
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

// CREATE uses the full AddConnectionModal (all ~44 connector types incl
// SharePoint/BigQuery/Databricks/Fabric — same catalog as the admin page),
// forced to PERSONAL scope and bound to this studio. The old hand-built form
// below is now used for EDIT only.
const showAddModal = ref(false)
function openCreate() {
  showAddModal.value = true
}

// AddConnectionModal emits 'created' with the new connection. Bind it to this
// agent (studio_id already set server-side) and activate it so the agent can
// query it immediately.
async function onConnectorCreated(conn: any) {
  showAddModal.value = false
  tab.value = 'mine'
  await loadConnectors()
  const cid = conn?.id || conn?.connection_id
  if (cid) await activate({ connection_id: cid })
}

// ── Sharing panel (owner) ────────────────────────────────────────────────────
// Opened from the table's "Who can use" badge. Sets Private/Shared/Org-wide +
// manages grants via ConnectorSharingPanel; refresh the list on save.
const showSharing = ref(false)
const sharingConn = ref<{ id: string; name: string; visibility: string } | null>(null)

function openSharing(row: any) {
  sharingConn.value = {
    id: row.id || row.connection_id,
    name: row.name,
    visibility: connVisibility(row),
  }
  showSharing.value = true
}

function openEdit(conn: any) {
  editingId.value = conn.connection_id
  form.type = conn.type || 'postgresql'
  form.name = conn.name || ''
  form.config = { ...(conn.config || {}) }
  form.credentials = {}
  modalTestResult.value = null
  showModal.value = true
}

function closeModal() {
  showModal.value = false
}

function buildBody() {
  const config: Record<string, any> = { ...form.config }
  if (showDbFields.value && config.port != null && config.port !== '') {
    const n = Number(config.port)
    if (!Number.isNaN(n)) config.port = n
  }
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
      toast.add({ title: 'Private connector created & activated', color: 'green' })
    }
    showModal.value = false
    tab.value = 'mine'
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
