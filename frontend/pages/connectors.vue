<template>
  <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
    <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto text-[#1f2328]">

            <!-- Header: serif title + subtitle + readiness ring -->
            <div class="flex items-start justify-between gap-4 mb-1">
                <div>
                    <h1
                        class="text-2xl font-semibold text-[#1f2328]"
                        style="font-family: 'Spectral', ui-serif, Georgia, serif"
                    >Connectors</h1>
                    <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[460px] leading-relaxed">
                        Configure data connections for your organization. Users pin these inside their Studios — they never see credentials.
                    </p>
                </div>
                <div class="flex items-center gap-3 shrink-0">
                    <div v-if="connections.length > 0" class="text-center">
                        <div class="relative w-[54px] h-[54px] mx-auto">
                            <svg width="54" height="54" style="transform:rotate(-90deg)">
                                <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
                                <circle cx="27" cy="27" r="22" stroke="#1F6F8B" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" stroke-dashoffset="0" />
                            </svg>
                            <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#1F6F8B]" style="font-family: ui-serif, Georgia, serif">{{ connections.length }}</div>
                        </div>
                        <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">connected</div>
                    </div>
                    <button
                        @click="selectedDataSourceType = undefined; showAddConnectionModal = true"
                        class="inline-flex items-center gap-2 rounded-lg bg-[#C2541E] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#A8330F] transition-colors whitespace-nowrap shrink-0"
                    >
                        <UIcon name="heroicons-plus" class="w-4 h-4" />
                        Add Connection
                    </button>
                </div>
            </div>

            <!-- Loading -->
                <div v-if="loading" class="flex items-center justify-center py-20">
                    <Spinner class="w-6 h-6 text-[#1F6F8B] animate-spin" />
                </div>

                <template v-else>
                    <!-- IMPORT section -->
                    <div class="relative mt-4 border border-[#E9E0D3] rounded-2xl bg-white p-4">
                        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">IMPORT</span>
                        <p class="text-xs text-[#6b6b6b] mt-1 mb-3">Bring a file straight into an instant Data Agent — no connection setup needed:</p>
                        <!-- Upload File / Spreadsheet — instant Data Agent (always available) -->
                        <button
                            @click="showUploadModal = true"
                            class="group flex w-full items-center gap-4 rounded-xl border border-[#E9E0D3] bg-gradient-to-b from-white to-[#fdfcf9] p-4 text-start transition hover:border-[#1F6F8B]"
                        >
                            <span class="inline-flex w-11 h-11 items-center justify-center rounded-lg bg-[#E4F0F4] text-[#1F6F8B] shrink-0">
                                <UIcon name="i-heroicons-cloud-arrow-up" class="w-6 h-6" />
                            </span>
                            <div class="min-w-0">
                                <div class="flex items-center gap-2">
                                    <span class="text-[13px] font-semibold text-[#1f2328]">
                                        Upload File / Spreadsheet
                                    </span>
                                    <span class="inline-flex items-center rounded-full bg-[#1F6F8B] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-white">new</span>
                                </div>
                                <p class="mt-0.5 text-[11px] text-[#6b6b6b]">.xlsx · .xls · .csv → instant Data Agent</p>
                            </div>
                            <UIcon name="i-heroicons-arrow-right" class="ms-auto w-5 h-5 text-[#1F6F8B] opacity-0 transition group-hover:opacity-100 shrink-0" />
                        </button>
                    </div>

                    <!-- ALL CONNECTORS — shared table -->
                    <div v-if="connections.length > 0" class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4 mb-6">
                        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">CONNECTORS</span>

                        <!-- Toolbar: filter chips + search -->
                        <div class="flex flex-wrap items-center justify-between gap-3 mt-1 mb-3">
                            <div class="inline-flex rounded-lg border border-[#E9E0D3] bg-white p-0.5 text-[11.5px]">
                                <button
                                    v-for="f in (['all','mine','shared','org'] as const)"
                                    :key="f"
                                    type="button"
                                    @click="rowFilter = f"
                                    :class="['px-2.5 py-1 rounded-md transition capitalize', rowFilter === f ? 'bg-[#FBEFE4] text-[#C2541E] font-semibold' : 'text-[#6b6b6b] hover:text-[#1f2328]']"
                                >{{ f }}</button>
                            </div>
                            <div class="relative">
                                <UIcon name="heroicons-magnifying-glass" class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9a958c]" />
                                <input
                                    v-model="search"
                                    type="text"
                                    placeholder="Search connectors…"
                                    class="w-[220px] rounded-lg border border-[#E9E0D3] bg-white pl-8 pr-3 py-1.5 text-[12.5px] text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none focus:border-[#1F6F8B]"
                                />
                            </div>
                        </div>

                        <ConnectorsTable
                            :rows="tableRows"
                            context="org"
                            @share="openSharing"
                            @edit="onEdit"
                            @delete="onDelete"
                            @test="onTest"
                        />
                        <p v-if="tableRows.length === 0" class="text-xs text-[#9a958c] border border-dashed border-[#E9E0D3] rounded-lg px-3 py-5 text-center mt-2">
                            No connectors match this filter.
                        </p>
                    </div>

                    <!-- Empty state - pick a type (no connections at all) -->
                    <div v-if="connections.length === 0" class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4 mb-6">
                        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">CONNECT A SOURCE</span>
                        <p class="text-xs text-[#6b6b6b] mt-1 mb-3">Pick a data source type to configure your first connection:</p>
                        <DataSourceGrid
                            :show-demos="true"
                            :navigate-on-demo="false"
                            @select="handleDataSourceSelect"
                            @demo-installed="handleDemoInstalled"
                        />
                    </div>
                </template>

            <!-- Modals -->
            <ConnectionDetailModal
                v-model="showConnectionModal"
                :connection="selectedConnection"
                @updated="refreshConnections"
            />
            <AddConnectionModal
                v-model="showAddConnectionModal"
                :initial-selected-type="selectedDataSourceType"
                :can-create-shared="canCreateDataSource"
                :individual-only="false"
                :defer-sharing="true"
                @created="handleConnectionCreated"
                @share-requested="onShareRequested"
            />
            <!-- Per-row sharing (Private/Shared/Org + grants) -->
            <ConnectorSharingPanel
                v-model="showSharing"
                :connection="sharingConn"
                @saved="refreshConnections"
            />
            <!-- Kept for legacy grant flows (e.g. share-requested from create) -->
            <ManageConnectionAccessModal
                v-model="showAccessModal"
                :connection="accessConnection"
            />
            <UploadSpreadsheetModal
                :open="showUploadModal"
                @close="showUploadModal = false"
                @created="handleSpreadsheetCreated"
            />
    </div>
  </div>
</template>

<script lang="ts" setup>
import ConnectionDetailModal from '~/components/ConnectionDetailModal.vue'
import AddConnectionModal from '~/components/AddConnectionModal.vue'
import ManageConnectionAccessModal from '~/components/ManageConnectionAccessModal.vue'
import UploadSpreadsheetModal from '~/components/data/UploadSpreadsheetModal.vue'
import DataSourceGrid from '~/components/datasources/DataSourceGrid.vue'
import DataSourceIcon from '~/components/DataSourceIcon.vue'
import Spinner from '~/components/Spinner.vue'
import { useCan } from '~/composables/usePermissions'

const canCreateDataSource = computed(() => useCan('create_data_source'))

const { data: currentUser } = useAuth()
const currentUserId = computed(() => String((currentUser.value as any)?.id ?? ''))
function isOwner(conn: any): boolean {
  return !!conn?.owner_user_id && String(conn.owner_user_id) === currentUserId.value
}
// Admin can edit/share/delete any connector; reuses the manage-connections
// permission (same gate the old "Manage access" affordance used) + superuser.
const isAdmin = computed(() =>
  !!(currentUser.value as any)?.is_superuser || canCreateDataSource.value
)

const toast = useToast()

const loading = ref(false)
const connections = ref<any[]>([])
const selectedConnection = ref<any>(null)
const showConnectionModal = ref(false)
const showAddConnectionModal = ref(false)
const showUploadModal = ref(false)
const selectedDataSourceType = ref<string | undefined>(undefined)
const showAccessModal = ref(false)
const accessConnection = ref<any>(null)

// Per-row sharing panel (Private/Shared/Org + grants).
const showSharing = ref(false)
const sharingConn = ref<{ id: string; name: string; visibility: string } | null>(null)

// Table filter affordance.
const search = ref('')
const rowFilter = ref<'all' | 'mine' | 'shared' | 'org'>('all')

// Rows for the shared <ConnectorsTable context="org" />.
const tableRows = computed(() => {
    const q = search.value.trim().toLowerCase()
    return connections.value
        .filter((conn: any) => {
            // Filter chips: mine = I own it; shared = visibility shared;
            // org = org-wide (no owner / visibility org).
            const vis = connVisibility(conn)
            if (rowFilter.value === 'mine' && !isOwner(conn)) return false
            if (rowFilter.value === 'shared' && vis !== 'shared') return false
            if (rowFilter.value === 'org' && vis !== 'org') return false
            if (q) {
                const hay = `${conn.name ?? ''} ${conn.type ?? ''}`.toLowerCase()
                if (!hay.includes(q)) return false
            }
            return true
        })
        .map((conn: any) => ({
            id: conn.id,
            name: conn.name,
            type: conn.type,
            owner_user_id: conn.owner_user_id ?? null,
            visibility: connVisibility(conn),
            active: false,
            last_synced_at: conn.last_synced_at ?? null,
            agent_count: conn.agent_count ?? 0,
            is_org: !conn.owner_user_id,
            can_edit: isOwner(conn) || isAdmin.value,
        }))
})

async function refreshConnections() {
    loading.value = true
    try {
        const res = await useMyFetch('/connections', { method: 'GET' })
        if (res.data.value) connections.value = res.data.value as any[]
    } catch (e) {
        console.error('Failed to load connectors:', e)
    } finally {
        loading.value = false
    }
}

function isConnectionHealthy(conn: any): boolean {
    if (conn.last_status === 'success' || conn.status === 'success') return true
    if (conn.last_status === 'error' || conn.status === 'error') return false
    const userStatus = conn.user_status?.connection
    if (userStatus === 'success') return true
    if (userStatus === 'error' || userStatus === 'offline') return false
    return true
}

function openConnectionDetail(conn: any) {
    selectedConnection.value = conn
    showConnectionModal.value = true
}
function openManageAccess(conn: any) {
    accessConnection.value = conn
    showAccessModal.value = true
}

// Resolve the full fetched connection from a table row (rows carry a subset).
function connById(row: any): any {
    return connections.value.find((c: any) => String(c.id) === String(row?.id)) || row
}

// ── ConnectorsTable row events ───────────────────────────────────────────────
function openSharing(row: any) {
    sharingConn.value = { id: row.id, name: row.name, visibility: row.visibility }
    showSharing.value = true
}
function onEdit(row: any) {
    // Reuse the existing detail/edit modal.
    openConnectionDetail(connById(row))
}
async function onDelete(row: any) {
    if (!row?.id) return
    if (!confirm(`Delete connector "${row.name}"? This cannot be undone.`)) return
    try {
        const res = await useMyFetch(`/connections/${row.id}`, { method: 'DELETE' })
        if ((res.error as any)?.value) {
            toast.add({ title: (res.error as any).value?.data?.detail || 'Failed to delete connector', color: 'red' })
            return
        }
        toast.add({ title: 'Connector deleted', color: 'green' })
        await refreshConnections()
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || e?.message || 'Failed to delete connector', color: 'red' })
    }
}
async function onTest(row: any) {
    if (!row?.id) return
    try {
        const res = await useMyFetch(`/connections/${row.id}/test`, { method: 'POST' })
        if ((res.error as any)?.value) {
            toast.add({ title: (res.error as any).value?.data?.detail || 'Connection test failed', color: 'red' })
            return
        }
        const ok = (res.data as any)?.value?.success !== false
        toast.add({ title: ok ? 'Connection OK' : 'Connection test failed', color: ok ? 'green' : 'red' })
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || e?.message || 'Connection test failed', color: 'red' })
    }
}

// ── Visibility (3-level: private | shared | org) ─────────────────────────────
function connVisibility(conn: any): 'private' | 'shared' | 'org' {
    const v = conn?.visibility
    if (v === 'private' || v === 'shared' || v === 'org') return v
    // Fallback: no owner = org-wide; owned = private.
    return conn?.owner_user_id ? 'private' : 'org'
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

const visibilityBusyId = ref<string | null>(null)

async function setVisibility(conn: any, level: 'private' | 'shared' | 'org') {
    if (visibilityBusyId.value) return
    visibilityBusyId.value = conn.id
    try {
        const res = await useMyFetch(`/connections/${conn.id}/visibility`, {
            method: 'PATCH',
            body: JSON.stringify({ visibility: level }),
            headers: { 'Content-Type': 'application/json' },
        })
        if ((res.error as any)?.value) {
            toast.add({ title: (res.error as any).value?.data?.detail || 'Failed to update visibility', color: 'red' })
            return
        }
        toast.add({ title: level === 'org' ? 'Published org-wide' : level === 'private' ? 'Made private' : 'Sharing updated', color: 'green' })
        await refreshConnections()
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || e?.message || 'Failed to update visibility', color: 'red' })
    } finally {
        visibilityBusyId.value = null
    }
}

// Share… = set visibility to 'shared' then open the grant picker.
async function shareConn(conn: any) {
    await setVisibility(conn, 'shared')
    accessConnection.value = { id: conn.id, name: conn.name }
    showAccessModal.value = true
}

// AddConnectionModal asks us to open the grant picker after a shared-visibility
// connection was created.
function onShareRequested(conn: any) {
    const cid = conn?.id || conn?.connection_id
    if (!cid) return
    accessConnection.value = { id: cid, name: conn?.name || 'connection' }
    showAccessModal.value = true
    refreshConnections()
}
function handleDataSourceSelect(ds: any) {
    selectedDataSourceType.value = ds.type
    showAddConnectionModal.value = true
}
function handleConnectionCreated() {
    selectedDataSourceType.value = undefined
    refreshConnections()
}
function handleDemoInstalled() {
    refreshConnections()
}
function handleSpreadsheetCreated(_ds: any) {
    showUploadModal.value = false
    refreshConnections()
}

onMounted(() => {
    refreshConnections()
})
</script>
