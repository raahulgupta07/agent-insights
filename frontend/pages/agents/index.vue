<template>
    <div class="flex justify-center px-4 md:px-6 text-sm bg-[#F6F1EA] min-h-full">
        <div class="w-full max-w-7xl py-2 text-[#1f2328]">
            <!-- Full page loading spinner -->
            <div v-if="loading" class="flex flex-col items-center justify-center py-20">
                <Spinner class="h-4 w-4 text-[#9a958c]" />
                <p class="text-sm text-[#6b6b6b] mt-2">{{ $t('common.loading') }}</p>
            </div>

            <div v-else>
                <!-- Microsoft Connectors Hub (per-user, device-code) -->
                <ConnectorsMsHub :agents="allAgents" @refresh="refreshData" />

                <!-- Data Agents Section - show once the user has any agent -->
                <div v-if="allAgents.length > 0" class="mb-6">
                    <!-- Header: title + subtitle (left), compact search (top-right) -->
                    <div class="flex items-start justify-between gap-4 mb-5">
                        <div>
                            <h1
                                class="text-[32px] font-medium text-[#211B14] tracking-tight flex items-center gap-2"
                                style="font-family: 'Spectral', ui-serif, Georgia, serif"
                            >
                                <GoBackChevron v-if="isExcel" />
                                {{ $t('data.agentsTitle') }}
                            </h1>
                            <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">{{ $t('data.agentsAutoHint') }}</p>
                        </div>
                        <!-- Compact search — only once the user has agents to filter -->
                        <div v-if="allAgents.length > 1" class="relative shrink-0 mt-1.5 w-40 sm:w-56">
                            <input
                                v-model="searchQuery"
                                type="text"
                                :placeholder="$t('data.searchAgents')"
                                class="w-full ps-9 pe-3 py-2 text-[13px] bg-white border border-[#E9E0D3] rounded-lg text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none focus:ring-2 focus:ring-[#C2541E]/40 focus:border-[#C2541E]"
                            />
                            <UIcon
                                name="i-heroicons-magnifying-glass"
                                class="absolute start-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-[#9a958c]"
                            />
                        </div>
                    </div>

                    <!-- Sample databases -->
                    <div v-if="uninstalledDemos.length > 0 && allAgents.length === 0" class="mb-4">
                        <div class="text-xs text-[#9a958c] mb-2">{{ $t('data.trySample') }}</div>
                        <div class="flex flex-wrap gap-2">
                            <button
                                v-for="demo in uninstalledDemos"
                                :key="`demo-${demo.id}`"
                                @click="installDemo(demo.id)"
                                :disabled="installingDemo === demo.id"
                                class="inline-flex items-center gap-2 px-3 py-1.5 text-xs text-[#6b6b6b] rounded-full border border-[#E9E0D3] bg-white hover:bg-[#F4EEE5] hover:border-[#C2541E]/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                                <Spinner v-if="installingDemo === demo.id" class="h-3 w-3" />
                                <DataSourceIcon v-else class="h-4" :type="demo.type" />
                                {{ demo.name }}
                                <span class="text-[9px] font-medium uppercase tracking-wide text-[#C2541E] bg-[#F4EEE5] border border-[#E9E0D3] px-1.5 py-0.5 rounded">{{ $t('data.sampleTag') }}</span>
                            </button>
                        </div>
                    </div>

                    <!-- Data Agents grid — Studios-style cards (DataAgentCard) -->
                    <div v-if="filteredAgents.length > 0" class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
                        <DataAgentCard
                            v-for="ds in filteredAgents"
                            :key="ds.id"
                            :ds="ds"
                            :meta="connectorMeta(ds)"
                            :connected="userHasAccess(ds)"
                            :connecting="connectingId === ds.id"
                            :table-count="getTableCount(ds)"
                            :source-count="(ds.connections || []).length"
                            @open="openAgent(ds)"
                            @connect="openCredentialsModal(ds)"
                        />
                    </div>

                    <!-- Empty state for search with no results -->
                    <div v-else-if="searchQuery.trim()" class="py-12 text-center border border-dashed border-[#E9E0D3] rounded-2xl">
                        <div class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] text-[#C2541E]">
                            <UIcon name="i-heroicons-magnifying-glass" class="w-6 h-6" />
                        </div>
                        <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ $t('data.noAgentsFound') }}</h3>
                        <p class="mt-1 text-sm text-[#9a958c]">{{ $t('data.noAgentsHint') }}</p>
                    </div>
                </div>

                <!-- Empty state: no agents yet → point to the connector hub above -->
                <div v-else-if="!loading" class="mb-6">
                    <h1
                        class="text-[32px] font-medium text-[#211B14] tracking-tight"
                        style="font-family: 'Spectral', ui-serif, Georgia, serif"
                    >{{ $t('data.agentsTitle') }}</h1>
                    <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">{{ $t('data.agentsAutoHint') }}</p>
                    <div class="mt-5 py-14 text-center border border-dashed border-[#E9E0D3] rounded-2xl bg-[#FCFAF6]">
                        <div class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] text-[#C2541E]">
                            <UIcon name="i-heroicons-arrow-up" class="w-6 h-6" />
                        </div>
                        <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ $t('data.emptyNoAgents') }}</h3>
                        <p class="mt-1 text-sm text-[#9a958c]">{{ $t('data.emptyNoAgentsHint') }}</p>
                    </div>
                </div>

                <!-- (Connections chips section removed — connectors are managed via
                     the Microsoft hub tiles + Manage connectors page.) -->
            </div>

            <!-- Connection Detail Modal -->
            <ConnectionDetailModal 
                v-model="showConnectionModal" 
                :connection="selectedConnection" 
                @updated="refreshData"
            />

            <!-- User Credentials Modal (for per-user auth) -->
            <UserDataSourceCredentialsModal v-model="showCredsModal" :data-source="selectedDs" @saved="refreshData" />

            <!-- Add Connection Modal -->
            <AddConnectionModal
                v-model="showAddConnectionModal"
                :initial-selected-type="selectedDataSourceType"
                @created="handleConnectionCreated"
            />
        </div>
    </div>
</template>

<script lang="ts" setup>
import GoBackChevron from '@/components/excel/GoBackChevron.vue'
import UserDataSourceCredentialsModal from '~/components/UserDataSourceCredentialsModal.vue'
import ConnectionDetailModal from '~/components/ConnectionDetailModal.vue'
import AddConnectionModal from '~/components/AddConnectionModal.vue'
import ConnectorsMsHub from '~/components/connectors/ConnectorsMsHub.vue'
import DataAgentCard from '~/components/DataAgentCard.vue'
import Spinner from '~/components/Spinner.vue'
import { useCan } from '~/composables/usePermissions'
import {
    publishStatusBadgeClass,
    publishStatusLabel,
    publishStatusDescription,
} from '~/composables/useDataSourcePublishStatus'
import { resolveComponent } from 'vue'

const NuxtLink = resolveComponent('NuxtLink')

const { t } = useI18n()
const { organization } = useOrganization()
const { isExcel } = useExcel()

definePageMeta({ auth: true })

const connected_ds = ref<any[]>([])
const connections = ref<any[]>([])
const demo_ds = ref<any[]>([])
const loadingConnected = ref(true)
const loadingConnections = ref(true)
const loadingDemos = ref(true)
const installingDemo = ref<string | null>(null)

const showConnectionModal = ref(false)
const selectedConnection = ref<any>(null)
const showCredsModal = ref(false)
const selectedDs = ref<any>(null)
const showAddConnectionModal = ref(false)
const selectedDataSourceType = ref<string | undefined>(undefined)

// Filter state
const searchQuery = ref('')

const loading = computed(() => loadingConnected.value || loadingDemos.value || loadingConnections.value)

// Current user id — used to show only the viewer's OWN agents (hide public/org
// demos + other people's agents from this personal view).
const { data: currentUser } = useAuth()
const myUserId = computed(() => (currentUser.value as any)?.id || null)

// All agents. Two filters:
//  1. Connector TEMPLATES (is_user_template) are admin config shells, not usable
//     agents — they live in the hub tiles above, never as a card.
//  2. Personal view: keep only agents YOU own (owner_user_id === me) or private
//     agents; hide public/org demos you don't own (e.g. the Financial Market
//     sample) so signing in to one source doesn't surface everyone else's work.
const allAgents = computed(() => (connected_ds.value || []).filter((ds: any) => {
    if (ds.is_user_template) return false
    if (!ds.is_public) return true                    // your private agents + clones
    return !!myUserId.value && ds.owner_user_id === myUserId.value
}))

// Uninstalled demo data sources
const uninstalledDemos = computed(() => (demo_ds.value || []).filter((demo: any) => !demo.installed))

// Filtered agents based on search query
const filteredAgents = computed(() => {
    if (!searchQuery.value.trim()) {
        return allAgents.value
    }

    const query = searchQuery.value.toLowerCase().trim()
    return allAgents.value.filter(ds =>
        ds.name?.toLowerCase().includes(query) ||
        ds.description?.toLowerCase().includes(query)
    )
})

// Map a per-user connector clone → its Microsoft product logo + clean name.
// A clone carries `template_source_id`; its first connection's type tells us
// which product. The signed-in email (stored as "<Product> · email") becomes
// the card subtitle so the card reads "Power BI / demo@test.com" not "d".
const CONNECTOR_META: Record<string, { logo: string; name: string }> = {
    ms_fabric: { logo: '/data_sources_icons/ms_fabric.png', name: 'Microsoft Fabric' },
    ms_fabric_user: { logo: '/data_sources_icons/ms_fabric.png', name: 'Microsoft Fabric' },
    powerbi: { logo: '/data_sources_icons/powerbi.png', name: 'Power BI' },
    powerbi_user: { logo: '/data_sources_icons/powerbi.png', name: 'Power BI' },
    sharepoint: { logo: '/data_sources_icons/sharepoint.png', name: 'SharePoint' },
    onedrive: { logo: '/data_sources_icons/onedrive.png', name: 'OneDrive' },
}
function connectorMeta(ds: any): { logo: string; name: string; subtitle: string } | null {
    if (!ds?.template_source_id) return null
    const type = ds.connections?.[0]?.type || ds.type
    const m = CONNECTOR_META[type]
    if (!m) return null
    const subtitle = (ds.name || '').includes('·') ? String(ds.name).split('·').pop()!.trim() : ''
    return { ...m, subtitle }
}

function getTableCount(ds: any): number {
    // Sum table counts from all connections
    const connections = ds.connections || []
    if (connections.length > 0) {
        return connections.reduce((sum: number, conn: any) => sum + (conn.table_count || 0), 0)
    }
    return ds.tables?.length || 0
}

// Shape-aware count + sign-in-aware suppression, shared with the agent
// header in layouts/data.vue. See composables/useCatalogCount.ts.
const registryByType = ref<Record<string, any>>({})
onMounted(async () => {
    try {
        const { data } = await useMyFetch('/available_data_sources', { method: 'GET' })
        for (const entry of (data.value as any[]) || []) {
            registryByType.value[entry.type] = entry
        }
    } catch {}
})
const { computeFromAgent } = useCatalogCount()
function catalogFor(ds: any) {
    return computeFromAgent(ds, registryByType.value)
}

// Check if agent requires user auth (any connection)
function requiresUserAuth(ds: any): boolean {
    const connections = ds.connections || []
    return ds.auth_policy === 'user_required' ||
        connections.some((conn: any) => conn.auth_policy === 'user_required')
}

// Check if user needs to connect (user_required but no credentials yet)
function needsUserConnection(ds: any): boolean {
    if (!requiresUserAuth(ds)) return false
    const connections = ds.connections || []
    // Needs a personal connection only when the user has neither their own creds
    // NOR a system fallback (admin/owner). effective_auth === 'system' means the
    // service-principal fallback covers them, so no sign-in prompt.
    for (const conn of connections) {
        if (conn.auth_policy === 'user_required'
            && !conn.user_status?.has_user_credentials
            && conn.user_status?.effective_auth !== 'system') {
            return true
        }
    }
    return ds.user_status?.has_user_credentials !== true && ds.user_status?.effective_auth !== 'system'
}

// True when the user can use this source via the connection's system (service
// principal) credentials — i.e. admin/owner fallback, no personal sign-in.
function usesServiceAccount(ds: any): boolean {
    if (!requiresUserAuth(ds)) return false
    const connections = ds.connections || []
    if (connections.length > 0) {
        return connections.some((conn: any) =>
            conn.auth_policy === 'user_required'
            && !conn.user_status?.has_user_credentials
            && conn.user_status?.effective_auth === 'system'
        )
    }
    return ds.user_status?.has_user_credentials !== true && ds.user_status?.effective_auth === 'system'
}

// Check if user has access to this data source (for clickability / table count)
function userHasAccess(ds: any): boolean {
    if (!requiresUserAuth(ds)) return true
    const connections = ds.connections || []
    if (connections.length > 0) {
        return connections.every((conn: any) =>
            conn.auth_policy !== 'user_required' || conn.user_status?.has_user_credentials || conn.user_status?.effective_auth === 'system'
        )
    }
    return ds.user_status?.has_user_credentials === true || ds.user_status?.effective_auth === 'system'
}

// Open credentials modal for an agent
async function openCredentialsModal(ds: any) {
    // Direct-redirect path: if the agent's pending-sign-in connection has
    // OAuth as its only user auth mode, skip the modal and jump straight to
    // the provider — there's nothing to type or pick.
    const pending = findPendingSignInConnection(ds)
    if (pending) {
        // Spin the clicked button while we fetch the authorize URL — for
        // SSO/Entra/OBO this round-trip hits Azure and is slow enough that the
        // button otherwise looks frozen before the browser navigates away.
        connectingId.value = ds.id
        const result = await signIn.triggerUserSignIn(pending)
        if (result.redirecting) return // keep spinning; the page is navigating to the provider
        connectingId.value = null
        if (result.error) {
            toast.add({ title: t('data.oauthStartFailed'), description: result.error, color: 'red' })
        }
    }
    selectedDs.value = ds
    showCredsModal.value = true
}

// Data source id whose Connect button is mid-sign-in (awaiting the authorize
// redirect). Stays set through a redirect so the spinner persists until the
// browser unloads the page.
const connectingId = ref<string | null>(null)

// Locate the first attached connection that's user_required without
// credentials — that's what the sign-in flow should target.
function findPendingSignInConnection(ds: any): any | null {
    for (const conn of (ds.connections || [])) {
        if (conn.auth_policy === 'user_required' && !conn.user_status?.has_user_credentials) {
            return conn
        }
    }
    return null
}

const signIn = useConnectionSignIn()

// Open a connected agent's chat. (Not-connected cards emit `connect` instead,
// which routes to openCredentialsModal.)
function openAgent(ds: any) {
    if (!userHasAccess(ds)) return
    navigateTo(`/agents/${ds.id}`)
}

// Check if connection is healthy - uses agent data to derive status
function isConnectionHealthy(conn: any): boolean {
    // Check connection's own status fields
    if (conn.last_status === 'success' || conn.status === 'success') return true
    if (conn.last_status === 'error' || conn.status === 'error') return false
    
    // Check user_status if available
    const userStatus = conn.user_status?.connection
    if (userStatus === 'success') return true
    if (userStatus === 'error' || userStatus === 'offline') return false
    
    // Fallback: check if any agent using this connection is connected
    const agentsUsingConn = connected_ds.value.filter(ds =>
        ds.connection?.id === conn.id || ds.connection_id === conn.id
    )
    if (agentsUsingConn.length > 0) {
        // If we have agents, check their connection status
        const anyConnected = agentsUsingConn.some(ds => {
            const status = ds.user_status?.connection || ds.connection?.user_status?.connection
            return status === 'success'
        })
        if (anyConnected) return true
    }
    
    // Default: assume healthy if we have the connection in the list
    return true
}

function openConnectionDetail(conn: any) {
    selectedConnection.value = conn
    showConnectionModal.value = true
}

function handleDataSourceSelect(ds: any) {
    selectedDataSourceType.value = ds.type
    showAddConnectionModal.value = true
}

function handleConnectionCreated() {
    selectedDataSourceType.value = undefined
    refreshData()
}

const toast = useToast()

function handleDemoInstalled(result: any) {
    toast.add({
        title: t('data.sampleAdded'),
        description: t('data.sampleAddedDesc'),
        icon: 'i-heroicons-check-circle',
        color: 'green'
    })
    refreshData()
}

async function getConnectedDataSources() {
    loadingConnected.value = true
    try {
        // Admins (full_admin_access / manage_connections) can toggle a
        // governance "show all" view that reveals private data sources they
        // aren't a member of. The backend ignores show_all for everyone else.
        const url = showAllAgents.value ? '/data_sources?show_all=true' : '/data_sources'
        const response = await useMyFetch(url, { method: 'GET' })
        if (response.data.value) {
            connected_ds.value = response.data.value as any[]
        }
    } finally {
        loadingConnected.value = false
    }
}

async function getConnections() {
    loadingConnections.value = true
    try {
        const response = await useMyFetch('/connections', { method: 'GET' })
        if (response.data.value) {
            connections.value = response.data.value as any[]
        }
    } finally {
        loadingConnections.value = false
    }
}

async function getDemoDataSources() {
    loadingDemos.value = true
    try {
        const response = await useMyFetch('/data_sources/demos', { method: 'GET' })
        if (response.data.value) {
            demo_ds.value = response.data.value as any[]
        }
    } finally {
        loadingDemos.value = false
    }
}

async function installDemo(demoId: string) {
    installingDemo.value = demoId
    try {
        const response = await useMyFetch(`/data_sources/demos/${demoId}`, { method: 'POST' })
        const result = response.data.value as any
        if (result?.success) {
            const demoName = demo_ds.value.find((d: any) => d.id === demoId)?.name || t('data.sampleDataFallback')
            toast.add({
                title: t('data.sampleAdded'),
                description: t('data.sampleAddedNamed', { name: demoName }),
                icon: 'i-heroicons-check-circle',
                color: 'green'
            })
            await refreshData()
        }
    } finally {
        installingDemo.value = null
    }
}

async function refreshData() {
    await Promise.all([
        getConnectedDataSources(),
        getConnections(),
        getDemoDataSources(),
    ])
    maybeStartPolling()
}

// Poll while any connection (standalone or under a data source) is currently
// indexing. The `/data_sources` and `/connections` endpoints both inline the
// latest `indexing` row, so a single re-fetch updates badges everywhere.
const POLL_INTERVAL_MS = 5000000
let pollTimer: ReturnType<typeof setInterval> | null = null

function anyIndexingActive(): boolean {
    const isActive = (idx: any) =>
        idx && (idx.status === 'pending' || idx.status === 'running')
    if ((connections.value || []).some((c: any) => isActive(c?.indexing))) return true
    for (const ds of (connected_ds.value || [])) {
        if ((ds.connections || []).some((c: any) => isActive(c?.indexing))) return true
    }
    return false
}

function maybeStartPolling() {
    if (anyIndexingActive() && !pollTimer) {
        pollTimer = setInterval(async () => {
            await Promise.all([getConnectedDataSources(), getConnections()])
            if (!anyIndexingActive()) stopPolling()
        }, POLL_INTERVAL_MS)
    } else if (!anyIndexingActive()) {
        stopPolling()
    }
}

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
    }
}

onBeforeUnmount(() => stopPolling())

// Agents are created automatically from a Microsoft sign-in above; the manual
// "show all" toggle and Create-Agent button were retired with that revamp.
// showAllAgents stays false — kept only so the fetch URL below is unchanged.
const showAllAgents = ref(false)

onMounted(async () => {
    nextTick(async () => {
        await refreshData()
    })

    // Handle OAuth callback redirect
    const route = useRoute()
    if (route.query.oauth === 'success') {
        const toast = useToast()
        toast.add({ title: t('data.connectedSuccess'), color: 'green', icon: 'i-heroicons-check-circle' })
        // Clean up query params
        navigateTo('/agents', { replace: true })
    } else if (route.query.oauth === 'error') {
        const toast = useToast()
        toast.add({ title: t('data.connectionFailed'), description: route.query.message as string || '', color: 'red', icon: 'i-heroicons-x-circle' })
        navigateTo('/agents', { replace: true })
    }
})
</script>

<style scoped>
.line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
</style>
