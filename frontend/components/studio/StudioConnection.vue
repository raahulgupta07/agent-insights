<template>
  <div>
    <div class="flex items-start justify-between mb-4">
      <div>
        <h2 class="text-sm font-semibold text-gray-900">Connections</h2>
        <p class="text-xs text-gray-500 mt-0.5">Database connections for this studio's pinned sources.</p>
      </div>
      <UButton color="gray" variant="ghost" size="2xs" icon="i-heroicons-arrow-path" :loading="loading" @click="loadAll">
        Refresh
      </UButton>
    </div>

    <!-- No pinned sources -->
    <div v-if="sources.length === 0" class="py-10 text-center border border-dashed border-gray-200 rounded-lg">
      <UIcon name="i-heroicons-link" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
      <p class="text-xs text-gray-500">{{ $t('studio.noSources') }}</p>
    </div>

    <!-- Loading -->
    <div v-else-if="loading && !loaded" class="flex items-center justify-center py-10 text-gray-400">
      <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
    </div>

    <!-- Per-source connection groups -->
    <div v-else class="space-y-5">
      <section
        v-for="s in sources"
        :key="s.id"
        class="rounded-lg border border-gray-100 bg-white"
      >
        <!-- Source header -->
        <div class="flex items-center gap-2 px-3 py-2.5 border-b border-gray-50">
          <DataSourceIcon v-if="s.type" class="h-4 shrink-0" :type="s.type" />
          <UIcon v-else name="i-heroicons-circle-stack" class="w-4 h-4 shrink-0 text-gray-400" />
          <span class="text-xs font-semibold text-gray-800 truncate">{{ s.name || s.agent_id }}</span>
        </div>

        <!-- Connections under this source -->
        <div class="p-3">
          <!-- Per-source error (e.g. 404 / no access) -> graceful empty, never crash -->
          <div v-if="errors[s.agent_id]" class="text-[11px] text-gray-400 py-2">
            Connection details are unavailable for this source.
          </div>

          <div v-else-if="(connectionsBySource[s.agent_id] || []).length === 0" class="text-[11px] text-gray-400 py-2">
            No connections linked to this source.
          </div>

          <div v-else class="space-y-3">
            <div
              v-for="conn in connectionsBySource[s.agent_id]"
              :key="conn.id"
              class="rounded-lg border border-gray-100 p-3"
            >
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 min-w-0">
                  <DataSourceIcon :type="conn.type" class="h-6 shrink-0" />
                  <div class="min-w-0">
                    <div class="text-xs font-medium text-gray-900 truncate">{{ conn.name }}</div>
                    <div class="text-[10px] text-gray-500">{{ conn.type }}</div>
                  </div>
                </div>

                <div class="flex items-center gap-2 shrink-0">
                  <!-- Status badge (active dot via shared state machine) -->
                  <span :class="['px-2 py-0.5 rounded text-[10px] border flex items-center gap-1', getStatusClass(conn)]">
                    <span :class="['inline-block w-1.5 h-1.5 rounded-full', getStatusDotClass(conn)]" />
                    {{ getStatusLabel(conn) }}
                  </span>
                  <!-- Last synced -->
                  <span v-if="getLastSynced(conn)" class="text-[10px] text-gray-400">
                    {{ getLastSynced(conn) }}
                  </span>

                  <template v-if="canEdit">
                    <!-- Test -->
                    <button
                      class="p-1 rounded hover:bg-gray-100 disabled:opacity-50"
                      :disabled="testingId === conn.id"
                      title="Test connection"
                      @click="testConnection(conn, s.agent_id)"
                    >
                      <Spinner v-if="testingId === conn.id" class="w-3.5 h-3.5" />
                      <UIcon v-else name="i-heroicons-bolt" class="w-3.5 h-3.5 text-gray-500" />
                    </button>
                    <!-- Reindex -->
                    <button
                      class="p-1 rounded hover:bg-gray-100 disabled:opacity-50"
                      :disabled="reindexingId === conn.id"
                      title="Reindex connection"
                      @click="reindexConnection(conn, s.agent_id)"
                    >
                      <Spinner v-if="reindexingId === conn.id" class="w-3.5 h-3.5" />
                      <UIcon v-else name="i-heroicons-arrow-path" class="w-3.5 h-3.5 text-gray-500" />
                    </button>
                    <!-- Edit (reuses the data-agent ConnectionDetailModal) -->
                    <button
                      class="p-1 rounded hover:bg-gray-100"
                      :title="$t('studio.edit')"
                      @click="openDetail(conn, s.agent_id)"
                    >
                      <UIcon name="i-heroicons-pencil-square" class="w-3.5 h-3.5 text-gray-500" />
                    </button>
                  </template>
                </div>
              </div>

              <!-- Indexing progress (shared component) -->
              <div v-if="conn.indexing" class="mt-3">
                <ConnectionIndexingProgress :indexing="conn.indexing" :show-logs="false" />
              </div>

              <!-- Inline test result -->
              <div v-if="testResults[conn.id]" class="mt-2 text-[11px]">
                <span :class="testResults[conn.id]?.success ? 'text-green-600' : 'text-red-600'">
                  {{ testResults[conn.id]?.success ? 'Connection successful' : (testResults[conn.id]?.message || 'Connection failed') }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- Detail / edit modal (reused from the Data Agent connection page) -->
    <ConnectionDetailModal
      v-if="canEdit"
      v-model="showDetail"
      :connection="detailConnection"
      @updated="onDetailUpdated"
    />
  </div>
</template>

<script setup lang="ts">
// Data Agent parity tab — Connection. Props contract (shared by all parity tabs):
//   studioId: string         -> the studio id
//   sources:  Source[]       -> pinned data agents [{ id, agent_id, name, type }]
//   canEdit:  boolean        -> caller may mutate
//
// A studio wraps N pinned Data Agents (data sources). This tab surfaces, scoped
// to those pinned sources, what each Data Agent's own Connection tab shows: the
// DB connection(s) per source with status + last synced, plus test / reindex /
// edit when the user canEdit. It reuses the SAME backend routes and components
// the data-agent connection page uses, so no logic is rebuilt here.
import ConnectionDetailModal from '~/components/ConnectionDetailModal.vue'
import ConnectionIndexingProgress from '~/components/ConnectionIndexingProgress.vue'
import Spinner from '~/components/Spinner.vue'
import {
  getEffectiveStatus as deriveStatus,
  statusBadgeClass,
  statusDotClass,
  statusLabel,
} from '~/composables/useConnectionStatus'

const props = defineProps<{ studioId: string; sources: any[]; canEdit: boolean }>()

const toast = useToast()

// agent_id -> connections[] (from GET /data_sources/{agent_id}, same shape the
// data layout feeds the data-agent Connection page).
const connectionsBySource = ref<Record<string, any[]>>({})
// agent_id -> truthy when its fetch failed (flag off / 404 / no access).
const errors = ref<Record<string, boolean>>({})
const loading = ref(false)
const loaded = ref(false)

const testingId = ref<string | null>(null)
const reindexingId = ref<string | null>(null)
const testResults = ref<Record<string, any>>({})

const showDetail = ref(false)
const detailConnection = ref<any>(null)
const detailSourceId = ref<string | null>(null)

// --- Status helpers (shared state machine; mirrors the data-agent page) ---
function getConnectionEffective(conn: any) {
  const local = testResults.value[conn.id]
  if (local) return local.success ? 'success' : 'error'
  return deriveStatus(conn)
}
function getStatusClass(conn: any) {
  return statusBadgeClass(getConnectionEffective(conn) as any)
}
function getStatusDotClass(conn: any) {
  return statusDotClass(getConnectionEffective(conn) as any)
}
function getStatusLabel(conn: any) {
  return statusLabel(getConnectionEffective(conn) as any)
}

function getLastSynced(conn: any) {
  const at = conn.last_synced_at || conn.user_status?.last_checked_at
  if (!at) return null
  return `Synced ${timeAgo(at)}`
}
function timeAgo(date: string) {
  const seconds = Math.floor((Date.now() - new Date(date).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

// --- Data loading ---
async function loadSource(agentId: string) {
  if (!agentId) return
  try {
    const { data, error } = await useMyFetch<any>(`/data_sources/${agentId}`, { method: 'GET' })
    if (error.value) {
      errors.value[agentId] = true
      connectionsBySource.value[agentId] = []
      return
    }
    errors.value[agentId] = false
    connectionsBySource.value[agentId] = ((data.value as any)?.connections) || []
  } catch (e) {
    // Graceful: never crash the tab on a single source's fetch failure.
    errors.value[agentId] = true
    connectionsBySource.value[agentId] = []
  }
}

async function loadAll() {
  const ids = props.sources.map((s: any) => s.agent_id).filter(Boolean)
  if (ids.length === 0) {
    loaded.value = true
    return
  }
  loading.value = true
  try {
    await Promise.all(ids.map((id: string) => loadSource(id)))
  } finally {
    loading.value = false
    loaded.value = true
  }
}

// --- Actions (same connection routes the data-agent page calls) ---
async function testConnection(conn: any, agentId: string) {
  if (testingId.value) return
  testingId.value = conn.id
  testResults.value[conn.id] = null
  try {
    const { data } = await useMyFetch<any>(`/connections/${conn.id}/test`, { method: 'POST' })
    testResults.value[conn.id] = (data.value as any) || null
    await loadSource(agentId)
  } catch (e: any) {
    testResults.value[conn.id] = { success: false, message: e?.message || '' }
  } finally {
    testingId.value = null
  }
}

async function reindexConnection(conn: any, agentId: string) {
  if (reindexingId.value) return
  reindexingId.value = conn.id
  try {
    await useMyFetch(`/connections/${conn.id}/reindex`, { method: 'POST' })
    await loadSource(agentId)
    toast.add({ title: 'Reindexing started', color: 'green' })
  } catch (e: any) {
    toast.add({ title: 'Failed to start reindexing', description: e?.message || '', color: 'red' })
  } finally {
    reindexingId.value = null
  }
}

function openDetail(conn: any, agentId: string) {
  detailConnection.value = conn
  detailSourceId.value = agentId
  showDetail.value = true
}

async function onDetailUpdated() {
  if (detailSourceId.value) await loadSource(detailSourceId.value)
}

// Reload when the pinned source set changes (e.g. a source is pinned/unpinned
// on another tab and this tab is reopened).
watch(
  () => props.sources.map((s: any) => s.agent_id).join(','),
  () => { loaded.value = false; loadAll() },
)

onMounted(loadAll)
</script>
