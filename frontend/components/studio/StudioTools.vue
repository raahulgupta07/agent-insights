<template>
  <div class="py-2">
    <!-- No pinned sources -->
    <div v-if="!sources || sources.length === 0" class="py-16 text-center border border-dashed border-gray-200 rounded-lg">
      <UIcon name="i-heroicons-server-stack" class="w-10 h-10 mx-auto text-gray-300 mb-3" />
      <p class="text-sm text-gray-500 mb-1">No data sources pinned</p>
      <p class="text-xs text-gray-400">Pin a Data Agent to this studio to manage its external tools.</p>
    </div>

    <template v-else>
      <!-- Optional-tools note: clarify that tools are NOT required for data analysis. -->
      <div class="mb-4 rounded-lg border border-[#E9E0D3] bg-[#F6F1EA] px-3.5 py-3 flex items-start gap-2.5">
        <UIcon name="i-heroicons-puzzle-piece" class="w-4 h-4 mt-0.5 text-[#C2541E] shrink-0" />
        <div>
          <p class="text-xs font-medium text-gray-700 mb-0.5">No external tools (optional)</p>
          <p class="text-xs text-gray-500 leading-relaxed">
            Your agent already answers from its pinned data. Add an MCP server or custom API only if it
            needs to reach a live external system — e.g. web search, Slack, or your own REST API.
          </p>
        </div>
      </div>

      <!-- Source switcher (only when more than one pinned source) -->
      <div v-if="sources.length > 1" class="flex items-center gap-1.5 mb-4 flex-wrap">
        <button
          v-for="src in sources"
          :key="src.id"
          type="button"
          class="px-2.5 py-1 rounded-md text-xs border transition-colors"
          :class="activeSourceId === String(src.agent_id)
            ? 'border-[#E8C9B5] bg-[#F6EFEA] text-[#A8330F] font-medium'
            : 'border-gray-200 text-gray-600 hover:bg-gray-50'"
          @click="activeSourceId = String(src.agent_id)"
        >
          {{ src.name || 'Data source' }}
        </button>
      </div>

      <!-- Loading the active source's connections -->
      <div v-if="loading" class="text-sm text-gray-500 py-10 flex items-center justify-center">
        <Spinner class="w-4 h-4 me-2" />
        Loading tools...
      </div>

      <!-- Source not found / no access (graceful 404) -->
      <div v-else-if="fetchError" class="py-16 text-center border border-dashed border-gray-200 rounded-lg">
        <UIcon name="i-heroicons-exclamation-triangle" class="w-10 h-10 mx-auto text-gray-300 mb-3" />
        <p class="text-sm text-gray-500 mb-1">Tools unavailable</p>
        <p class="text-xs text-gray-400">This data source could not be loaded.</p>
      </div>

      <!-- Tools for the active pinned source -->
      <ToolsSelector
        v-else
        :key="activeSourceId"
        :ds-id="activeSourceId"
        :connections="mcpConnections"
        :can-update="canEdit"
        @add-mcp="showMCPModal = true"
        @add-custom-api="showCustomAPIModal = true"
        @edit-connection="openEditModal"
        @delete-connection="confirmDelete"
      />
    </template>

    <!-- Add MCP Modal -->
    <AddMCPModal v-model="showMCPModal" :existing-connections="availableMcpConnections" @created="onConnectionCreated" />

    <!-- Add Custom API Modal -->
    <AddCustomAPIModal v-model="showCustomAPIModal" :existing-connections="availableCustomApiConnections" @created="onConnectionCreated" />

    <!-- Edit Modal (type-aware) -->
    <AddMCPModal v-if="editingConnection?.type === 'mcp'" v-model="showEditModal" :edit-connection="editingConnection" @created="onConnectionUpdated" />
    <AddCustomAPIModal v-else-if="editingConnection?.type === 'custom_api'" v-model="showEditModal" :edit-connection="editingConnection" @created="onConnectionUpdated" />

    <!-- Delete confirmation -->
    <UModal v-model="showDeleteModal" :ui="{ width: 'sm:max-w-sm' }">
      <div class="p-6">
        <h3 class="text-sm font-semibold text-gray-900 mb-2">Remove Connection</h3>
        <p class="text-xs text-gray-500 mb-4">
          Remove <strong>{{ deletingConnection?.name }}</strong> from this data source? The connection will remain available for other agents.
        </p>
        <div class="flex justify-end gap-2">
          <UButton color="gray" variant="ghost" size="xs" @click="showDeleteModal = false">Cancel</UButton>
          <UButton color="red" size="xs" :loading="deleting" @click="deleteConnection">Remove</UButton>
        </div>
      </div>
    </UModal>
  </div>
</template>

<script setup lang="ts">
// Studio "Tools" tab — Data Agent parity, scoped to the studio's pinned sources.
// A studio wraps N pinned Data Agents; this surfaces the same MCP + Custom API
// tool connections each pinned source exposes on its own /agents/{id}/tools tab.
// All work is parameterized by the pinned source's agent_id (= data-source id).
//
// Props contract (shared by all studio parity tabs):
//   studioId: string         -> the studio id
//   sources:  Source[]       -> pinned data agents [{ id, agent_id, name, type }]
//   canEdit:  boolean        -> caller may mutate
import ToolsSelector from '@/components/datasources/ToolsSelector.vue'
import AddMCPModal from '@/components/AddMCPModal.vue'
import AddCustomAPIModal from '@/components/AddCustomAPIModal.vue'
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{ studioId: string; sources: any[]; canEdit: boolean }>()

const toast = useToast()

// Which pinned source we're managing (defaults to the first). Value is the
// data-source/agent id that ToolsSelector + the connection routes expect.
const activeSourceId = ref<string>('')

// The active source's full integration record (= GET /data_sources/{id}).
const sourceData = ref<any>(null)
const loading = ref(false)
const fetchError = ref(false)

// All org-level MCP/custom API connections (for the "use existing" picker).
const allOrgToolConnections = ref<any[]>([])

// Pick the first pinned source on mount and whenever the pinned set changes
// (and the current selection is no longer present).
watch(
  () => props.sources,
  (list) => {
    const ids = (list || []).map((s: any) => String(s.agent_id))
    if (!activeSourceId.value || !ids.includes(activeSourceId.value)) {
      activeSourceId.value = ids[0] || ''
    }
  },
  { immediate: true, deep: true }
)

// Reload the integration record whenever the active source changes.
watch(activeSourceId, () => fetchSource(), { immediate: true })

async function fetchSource() {
  if (!activeSourceId.value) {
    sourceData.value = null
    return
  }
  loading.value = true
  fetchError.value = false
  try {
    const res = await useMyFetch(`/data_sources/${activeSourceId.value}`, { method: 'GET' })
    if (res.data.value) {
      sourceData.value = res.data.value
    } else if (res.error?.value) {
      fetchError.value = true
    }
  } catch {
    fetchError.value = true
  } finally {
    loading.value = false
  }
}

async function fetchOrgToolConnections() {
  try {
    const res = await useMyFetch('/connections', { method: 'GET' })
    if (res.data.value) {
      allOrgToolConnections.value = (res.data.value as any[]).filter(
        (c: any) => c.type === 'mcp' || c.type === 'custom_api'
      )
    }
  } catch {}
}

onMounted(fetchOrgToolConnections)

// Tool connections already linked to the active source.
const mcpConnections = computed(() => {
  const connections = sourceData.value?.connections || []
  return connections.filter((c: any) => c.type === 'mcp' || c.type === 'custom_api')
})

// Connections not yet linked to the active source (for the "use existing" picker).
const availableMcpConnections = computed(() => {
  const linkedIds = new Set(mcpConnections.value.map((c: any) => String(c.id)))
  return allOrgToolConnections.value.filter((c: any) => c.type === 'mcp' && !linkedIds.has(String(c.id)))
})
const availableCustomApiConnections = computed(() => {
  const linkedIds = new Set(mcpConnections.value.map((c: any) => String(c.id)))
  return allOrgToolConnections.value.filter((c: any) => c.type === 'custom_api' && !linkedIds.has(String(c.id)))
})

// Add / edit / delete UI state
const showMCPModal = ref(false)
const showCustomAPIModal = ref(false)
const showEditModal = ref(false)
const editingConnection = ref<any>(null)
const showDeleteModal = ref(false)
const deletingConnection = ref<any>(null)
const deleting = ref(false)

async function onConnectionCreated(conn: any) {
  // Link the new/selected connection to the active pinned source, then refresh
  // its discovered tools, then reload so it shows with effective state.
  try {
    await useMyFetch(`/data_sources/${activeSourceId.value}/connections/${conn.id}`, { method: 'POST' })
  } catch { /* link endpoint may not exist yet */ }
  try {
    await useMyFetch(`/connections/${conn.id}/refresh-tools`, { method: 'POST' })
  } catch {}
  await fetchSource()
  await fetchOrgToolConnections()
}

async function onConnectionUpdated() {
  editingConnection.value = null
  await fetchSource()
}

function openEditModal(conn: any) {
  editingConnection.value = conn
  showEditModal.value = true
}

function confirmDelete(conn: any) {
  deletingConnection.value = conn
  showDeleteModal.value = true
}

async function deleteConnection() {
  if (!deletingConnection.value) return
  deleting.value = true
  try {
    await useMyFetch(`/data_sources/${activeSourceId.value}/connections/${deletingConnection.value.id}`, { method: 'DELETE' })
    toast.add({ title: 'Connection removed', color: 'green' })
    showDeleteModal.value = false
    deletingConnection.value = null
    await fetchSource()
    await fetchOrgToolConnections()
  } catch (e: any) {
    toast.add({ title: 'Failed to remove connection', description: e?.data?.detail, color: 'red' })
  } finally {
    deleting.value = false
  }
}
</script>
