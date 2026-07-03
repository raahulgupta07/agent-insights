<template>
    <NuxtLayout name="default">
        <div class="flex bg-[#FAFAF9] text-sm overflow-hidden h-full">

            <!-- Loading skeleton (YouTube-style content-shaped shimmer) -->
            <template v-if="isLoading">
                <!-- rail skeleton -->
                <aside class="cag-side shrink-0 self-stretch flex flex-col">
                    <div class="cag-sk cag-sk-line" style="width:72px;height:12px;margin-bottom:18px"></div>
                    <div class="flex items-center gap-2.5 pb-4 mb-3 border-b border-[#F1EFEC]">
                        <div class="cag-sk" style="width:34px;height:34px;border-radius:9px"></div>
                        <div class="flex-1 min-w-0">
                            <div class="cag-sk cag-sk-line" style="width:80%;height:11px;margin-bottom:6px"></div>
                            <div class="cag-sk cag-sk-line" style="width:48%;height:9px"></div>
                        </div>
                    </div>
                    <template v-for="n in 9" :key="n">
                        <div v-if="n === 4 || n === 7" class="cag-sk cag-sk-line" style="width:38%;height:9px;margin:14px 0 6px"></div>
                        <div class="cag-sk cag-sk-line" :style="{ width: (n % 3 === 0 ? '48%' : '72%'), height: '13px', margin: '9px 4px' }"></div>
                    </template>
                </aside>
                <!-- main skeleton -->
                <div class="flex-1 min-w-0 m-2">
                    <div class="bg-white border border-[#EAE8E4] rounded-xl overflow-hidden h-full">
                        <div class="px-8 py-5 border-b border-[#F1EFEC] flex items-center justify-between">
                            <div class="cag-sk cag-sk-line" style="width:min(46%,360px);height:14px"></div>
                            <div class="flex gap-3">
                                <div class="cag-sk" style="width:88px;height:30px;border-radius:8px"></div>
                                <div class="cag-sk" style="width:112px;height:30px;border-radius:8px"></div>
                            </div>
                        </div>
                        <div class="p-6 flex gap-5">
                            <div class="flex-1 space-y-4">
                                <div class="cag-sk" style="height:120px;border-radius:12px"></div>
                                <div class="cag-sk" style="height:240px;border-radius:12px"></div>
                            </div>
                            <div class="w-[300px] shrink-0 space-y-4 hidden lg:block">
                                <div class="cag-sk" style="height:160px;border-radius:12px"></div>
                                <div class="cag-sk" style="height:120px;border-radius:12px"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </template>

            <!-- Access errors -->
            <div v-else-if="fetchError === 403" class="flex-1 m-2">
                <div class="bg-white border border-[#EAE8E4] rounded-xl p-10 text-center">
                    <Icon name="i-heroicons-lock-closed" class="w-10 h-10 text-[#A8A29E] mx-auto mb-3" />
                    <h2 class="text-base font-medium text-[#1C1917]">Access Restricted</h2>
                    <p class="mt-1.5 text-sm text-[#78716C] max-w-sm mx-auto">This agent is private. Contact the owner or an admin to request access.</p>
                    <NuxtLink to="/agents" class="mt-4 inline-block text-sm text-[#C2541E] hover:underline">← Back to agents</NuxtLink>
                </div>
            </div>
            <div v-else-if="fetchError === 404" class="flex-1 m-2">
                <div class="bg-white border border-[#EAE8E4] rounded-xl p-10 text-center">
                    <Icon name="i-heroicons-exclamation-circle" class="w-10 h-10 text-[#A8A29E] mx-auto mb-3" />
                    <h2 class="text-base font-medium text-[#1C1917]">Agent Not Found</h2>
                    <p class="mt-1.5 text-sm text-[#78716C] max-w-sm mx-auto">The agent you're looking for doesn't exist or has been removed.</p>
                    <NuxtLink to="/agents" class="mt-4 inline-block text-sm text-[#C2541E] hover:underline">← Back to agents</NuxtLink>
                </div>
            </div>
            <div v-else-if="fetchError" class="flex-1 m-2">
                <div class="bg-white border border-[#EAE8E4] rounded-xl p-10 text-center text-sm text-[#78716C]">Failed to load this agent.</div>
            </div>

            <!-- RAIL + MAIN (mirrors /workspace AppRail .cag-rail-card + main card) -->
            <template v-else>

                <!-- LEFT RAIL / AGENT SUB-NAV -->
                <aside class="cag-side shrink-0 self-stretch min-h-0 overflow-y-auto flex flex-col">
                    <!-- back link -->
                    <NuxtLink to="/agents" class="cag-back">
                        <UIcon name="i-heroicons-arrow-left" class="w-3.5 h-3.5" /> All agents
                    </NuxtLink>

                    <!-- agent identity head -->
                    <div class="cag-agenthead">
                        <div class="cag-ic">
                            <img v-if="connectorMeta" :src="connectorMeta.logo" :alt="connectorMeta.name" class="w-4.5 h-4.5 object-contain" />
                            <UIcon v-else name="i-heroicons-circle-stack" class="w-[18px] h-[18px]" />
                        </div>
                        <div class="min-w-0">
                            <div class="cag-nm truncate">{{ connectorMeta ? connectorMeta.name : (integration?.name || 'Agent') }}</div>
                            <div v-if="(integration?.connections || []).length" class="cag-st"><span class="d"></span>Connected</div>
                            <div v-else-if="connectorMeta?.subtitle" class="cag-sub truncate">{{ connectorMeta.subtitle }}</div>
                        </div>
                    </div>

                    <!-- grouped tab nav -->
                    <nav class="flex-1 pb-2">
                        <template v-for="grp in tabGroups" :key="grp.label">
                            <div class="cag-navgrp">{{ grp.label }}</div>
                            <NuxtLink
                                v-for="tab in grp.items"
                                :key="tab.name"
                                :to="tabTo(tab.name)"
                                :class="['cag-navitem', isTabActive(tab.name) ? 'on' : '']"
                            >
                                <UIcon :name="tabIcon(tab.name)" class="cag-navitem-ic" />
                                <span class="flex-1 truncate">{{ tab.label }}</span>
                                <span v-if="tab.name === 'tables' && catalog.shouldShow && catalog.count > 0" class="ct">{{ catalog.count }}</span>
                            </NuxtLink>
                        </template>

                        <!-- lifecycle actions -->
                        <div class="cag-navgrp">Connection</div>
                        <button @click="testConn" :disabled="testing" class="cag-navitem w-full text-left">
                            <Spinner v-if="testing" class="cag-navitem-ic" />
                            <UIcon v-else name="i-heroicons-bolt" class="cag-navitem-ic" />
                            <span class="flex-1 truncate">Test connection</span>
                        </button>
                        <button v-if="isClone" @click="showDisconnect = true" class="cag-navitem cag-danger w-full text-left">
                            <UIcon name="i-heroicons-x-mark" class="cag-navitem-ic" />
                            <span class="flex-1 truncate">Disconnect</span>
                        </button>
                    </nav>
                </aside>

                <!-- MAIN (page card) — own scroll container so the page scrolls
                     internally within the fixed shell (parent app clips body scroll) -->
                <div class="flex-1 min-w-0 m-2 min-h-0 flex flex-col">
                    <div class="flex flex-col min-h-0 flex-1 bg-white border border-[#EAE8E4] rounded-xl overflow-hidden" style="box-shadow: 0 1px 2px rgba(28,25,23,.04), 0 1px 3px rgba(28,25,23,.06)">
                        <!-- FROZEN header (identity / description / actions) — stays put while content scrolls -->
                        <div class="shrink-0 px-6 md:px-8 pt-6 pb-4 border-b border-[#F1EFEC]">
                        <div class="flex items-start justify-between gap-4">
                            <div class="min-w-0 flex-1">
                                <!-- Description (inline-editable) -->
                                <div v-if="integration?.description || useCan('update_data_source')" class="flex items-center gap-2 group max-w-2xl">
                                    <template v-if="editingDesc">
                                        <input
                                            ref="descInputRef"
                                            v-model="descForm"
                                            type="text"
                                            class="flex-1 text-sm text-[#78716C] border-b border-[#C2541E] bg-transparent outline-none py-0.5"
                                            @keydown.enter="saveDesc"
                                            @keydown.escape="cancelDesc"
                                            @blur="saveDesc"
                                        />
                                    </template>
                                    <template v-else>
                                        <p
                                            class="text-sm text-[#78716C] truncate rounded px-1 -mx-1 transition-colors"
                                            :class="useCan('update_data_source') ? 'cursor-pointer hover:bg-[#F1EFEC]' : ''"
                                            @click="useCan('update_data_source') && startEditDesc()"
                                        >{{ integration?.description || 'No description' }}</p>
                                        <button
                                            v-if="useCan('update_data_source')"
                                            class="text-[10px] text-[#C2541E] hover:underline opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                                            @click="startEditDesc"
                                        >Edit</button>
                                    </template>
                                </div>
                            </div>
                            <div class="shrink-0 flex items-center gap-3">
                                <PublishStatusControl
                                    :data-source-id="id"
                                    :status="integration?.publish_status || 'published'"
                                    @updated="onPublishStatusUpdated"
                                />
                                <!-- Sync: re-discover schema (picks up newly-granted reports/
                                     datasets), re-classify relevance, and (diff-gated) re-train.
                                     Split button — caret offers "Re-discover only" (cheap, no
                                     re-train). Clone-only + update permission. Progress streams
                                     to the Activity sync log. -->
                                <div v-if="isClone" class="inline-flex">
                                    <button
                                        type="button"
                                        :disabled="syncing"
                                        class="inline-flex items-center gap-1.5 border border-[#EAE8E4] rounded-l-lg px-3 py-1.5 text-sm font-medium text-[#44403C] hover:bg-[#F1EFEC] disabled:opacity-60"
                                        @click="syncNow(true)"
                                    >
                                        <UIcon name="heroicons-arrow-path" class="w-4 h-4" :class="syncing ? 'animate-spin' : ''" />
                                        {{ syncing ? 'Syncing…' : 'Sync' }}
                                    </button>
                                    <UDropdown :items="syncMenu" :disabled="syncing" :popper="{ placement: 'bottom-end' }">
                                        <button
                                            type="button"
                                            :disabled="syncing"
                                            class="inline-flex items-center border border-l-0 border-[#EAE8E4] rounded-r-lg px-1.5 py-1.5 text-[#44403C] hover:bg-[#F1EFEC] disabled:opacity-60"
                                        >
                                            <UIcon name="heroicons-chevron-down" class="w-4 h-4" />
                                        </button>
                                    </UDropdown>
                                </div>
                                <UButton
                                    color="gray"
                                    size="sm"
                                    class="bg-[#C2541E] hover:bg-[#A8461A] text-white ring-0 rounded-lg font-medium"
                                    :loading="startingChat"
                                    @click="startChat"
                                >
                                    New Report
                                    <UIcon name="heroicons-arrow-right" class="w-3.5 h-3.5 ms-1" />
                                </UButton>
                            </div>
                        </div>
                        </div>

                        <!-- SCROLLING page content -->
                        <div class="flex-1 min-h-0 overflow-y-auto px-6 md:px-8 py-6">
                            <slot />
                        </div>
                    </div>
                </div>
            </template>

            <!-- Disconnect confirm -->
            <UModal v-model="showDisconnect">
                <div class="p-6">
                    <h3 class="text-lg font-semibold text-[#1C1917] mb-1">Disconnect this source?</h3>
                    <p class="text-sm text-[#78716C] mb-4">Removes your private agent and sign-in. Your data stays in Microsoft — you can sign in again anytime.</p>
                    <div class="flex justify-end gap-2">
                        <button @click="showDisconnect = false" class="px-3 py-2 rounded-lg text-sm bg-white border border-[#EAE8E4] hover:bg-[#F1EFEC]">Cancel</button>
                        <button @click="disconnect" :disabled="disconnecting" class="px-3 py-2 rounded-lg text-sm text-[#B4331A] border border-[#F1D4CC] bg-[#FBEAE6] hover:bg-[#FCEEEA]"><Spinner v-if="disconnecting" class="w-3.5 h-3.5 inline" /> Disconnect</button>
                    </div>
                </div>
            </UModal>
        </div>

    </NuxtLayout>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'
import PublishStatusControl from '~/components/datasources/PublishStatusControl.vue'
import {
    getEffectiveStatus,
    hasAnyActiveIndexing,
    indexingSummary,
    statusDotClass,
} from '~/composables/useConnectionStatus'
import { useCan } from '~/composables/usePermissions'

const route = useRoute()
const router = useRouter()
const toast = useToast?.()

const id = computed(() => String(route.params.id || ''))
const { isMcpToolsEnabled } = useOrgSettings()

const canViewMonitoring = computed(() => useCan('full_admin_access'))
const canManageEvals = computed(() => useCan('manage_evals'))

const allTabs = computed(() => {
    // Label the Tables tab to match the agent's data_shape: "Files" for
    // file-shape connectors (OneDrive / SharePoint / Google Drive),
    // "Collections" for object-shape (MongoDB), default "Tables" for SQL.
    const tablesLabel = (() => {
        const s = catalog.value.noun.plural
        if (s === 'tables') return 'Tables'
        // Title-case the noun
        return s.charAt(0).toUpperCase() + s.slice(1)
    })()
    return [
        { name: '', label: 'Overview' },
        { name: 'tables', label: tablesLabel },
        { name: 'context', label: 'Instructions' },
        { name: 'queries', label: 'Queries' },
        { name: 'tools', label: 'Tools' },
        { name: 'activity', label: 'Activity' },
        { name: 'monitoring', label: 'Monitoring', gate: canViewMonitoring },
        { name: 'evals', label: 'Evals', gate: canManageEvals },
        { name: 'settings', label: 'Settings' },
    ]
})

const tabs = computed(() =>
    allTabs.value.filter(tab => {
        if (tab.name === 'tools' && !isMcpToolsEnabled.value) return false
        if (tab.gate && !tab.gate.value) return false
        return true
    })
)

function tabTo(tabName: string) {
    if (!id.value) return '/agents'
    if (tabName === '') return `/agents/${id.value}`
    return `/agents/${id.value}/${tabName}`
}

// Per-tab heroicon (rail nav), matching the Manage/Workspace rail icon style.
const TAB_ICONS: Record<string, string> = {
    '': 'i-heroicons-squares-2x2',
    tables: 'i-heroicons-table-cells',
    context: 'i-heroicons-document-text',
    queries: 'i-heroicons-command-line',
    tools: 'i-heroicons-wrench-screwdriver',
    activity: 'i-heroicons-signal',
    monitoring: 'i-heroicons-chart-bar',
    evals: 'i-heroicons-check-badge',
    settings: 'i-heroicons-cog-6-tooth',
}
function tabIcon(name: string) {
    return TAB_ICONS[name] || 'i-heroicons-squares-2x2'
}

function isTabActive(tabName: string) {
    const path = route.path
    if (tabName === '') {
        return path === `/agents/${id.value}` || path === `/agents/${id.value}/`
    }
    return path === `/agents/${id.value}/${tabName}`
}

const tableCount = computed(() =>
    (integration.value?.connections || []).reduce((sum: number, c: any) => sum + (c.table_count || 0), 0)
)
const connectionCount = computed(() => (integration.value?.connections || []).length)

// Shape-aware catalog count: respects each connection's data_shape (files
// vs tables vs objects) and hides the number entirely when any attached
// connection is user_required + the current user hasn't signed in (the "0"
// would lie — per-user catalog hasn't been fetched yet).
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
const catalog = computed(() => computeFromAgent(integration.value, registryByType.value))

// Connector-clone identity: product logo + clean name + signed-in email, so the
// rail reads "Power BI / demo@test.com" instead of the raw stored name.
const CONNECTOR_META: Record<string, { logo: string; name: string }> = {
    ms_fabric: { logo: '/data_sources_icons/ms_fabric.png', name: 'Microsoft Fabric' },
    ms_fabric_user: { logo: '/data_sources_icons/ms_fabric.png', name: 'Microsoft Fabric' },
    powerbi: { logo: '/data_sources_icons/powerbi.png', name: 'Power BI' },
    powerbi_user: { logo: '/data_sources_icons/powerbi.png', name: 'Power BI' },
    sharepoint: { logo: '/data_sources_icons/sharepoint.png', name: 'SharePoint' },
    onedrive: { logo: '/data_sources_icons/onedrive.png', name: 'OneDrive' },
}
const isClone = computed(() => !!integration.value?.template_source_id)
const connectorMeta = computed(() => {
    if (!isClone.value) return null
    const type = integration.value?.connections?.[0]?.type || integration.value?.type
    const m = CONNECTOR_META[type]
    if (!m) return null
    const name = integration.value?.name || ''
    const subtitle = name.includes('·') ? name.split('·').pop().trim() : ''
    return { ...m, subtitle }
})

// Group the flat tab list into rail sections (mirrors the Manage page layout).
const TAB_GROUPS: { label: string; names: string[] }[] = [
    { label: 'Explore', names: ['', 'tables', 'queries'] },
    { label: 'Configure', names: ['context', 'tools', 'settings'] },
    { label: 'Observe', names: ['activity', 'monitoring', 'evals'] },
]
const tabGroups = computed(() => {
    const byName: Record<string, any> = Object.fromEntries(tabs.value.map(t => [t.name, t]))
    return TAB_GROUPS
        .map(g => ({ label: g.label, items: g.names.map(n => byName[n]).filter(Boolean) }))
        .filter(g => g.items.length > 0)
})

// Test connection (per-user token round-trip).
const testing = ref(false)
async function testConn() {
    if (testing.value) return
    testing.value = true
    try {
        const { data, error } = await useMyFetch(`/data_sources/${id.value}/test_connection`, { method: 'GET' })
        if (error?.value) throw error.value
        const r = data.value as any
        toast?.add?.({
            title: r?.success ? 'Connection OK' : 'Connection failed',
            description: r?.message || '',
            color: r?.success ? 'green' : 'red',
            icon: r?.success ? 'i-heroicons-check-circle' : 'i-heroicons-x-circle',
        })
    } catch (e: any) {
        toast?.add?.({ title: 'Connection failed', description: e?.data?.detail || e?.message || '', color: 'red' })
    } finally {
        testing.value = false
    }
}

// Disconnect: delete the private clone + its owned connection(s). Deleting the
// data source cascades its tables/memberships; deleting each connection removes
// the now-orphaned private connection (owner-guarded server-side).
const showDisconnect = ref(false)
const disconnecting = ref(false)
async function disconnect() {
    if (disconnecting.value) return
    disconnecting.value = true
    try {
        const conns = [...(integration.value?.connections || [])]
        const { error } = await useMyFetch(`/data_sources/${id.value}`, { method: 'DELETE' })
        if (error?.value) throw error.value
        for (const conn of conns) {
            try { await useMyFetch(`/connections/${conn.id}`, { method: 'DELETE' }) } catch {}
        }
        toast?.add?.({ title: 'Disconnected', icon: 'i-heroicons-check-circle' })
        router.push('/agents')
    } catch (e: any) {
        toast?.add?.({ title: 'Disconnect failed', description: e?.data?.detail || e?.message || '', color: 'red' })
        disconnecting.value = false
    }
}

const integration = ref<any>(null)
const isLoading = ref(true)
const fetchError = ref<number | null>(null)
const startingChat = ref(false)

// Sync now: re-run the full connector pipeline (re-discover schema → relevance
// classify → re-seed → re-learn) via the existing owner-gated endpoint, then poll
// the live sync log until done and toast the result. Use after gaining access to
// a new Power BI report/dataset so the agent picks it up + re-trains.
const syncing = ref(false)
const syncMenu = computed(() => [[
    { label: 'Sync now', icon: 'i-heroicons-arrow-path', click: () => syncNow(true) },
    { label: 'Re-discover only', icon: 'i-heroicons-magnifying-glass', click: () => syncNow(false) },
]])
async function syncNow(learn = true) {
    if (syncing.value || !id.value) return
    syncing.value = true
    toast?.add?.({ title: 'Sync started', description: learn ? 'Re-discovering data and re-training…' : 'Re-discovering schema (no re-training)…', icon: 'i-heroicons-arrow-path' })
    try {
        const { error } = await useMyFetch(`/connectors/${id.value}/sync?learn=${learn}`, { method: 'POST' })
        if (error?.value) throw error.value
        const deadline = Date.now() + 5 * 60 * 1000
        while (Date.now() < deadline) {
            await new Promise((r) => setTimeout(r, 2000))
            const { data } = await useMyFetch(`/data_sources/${id.value}/sync-status`, { method: 'GET' })
            const run: any = (data as any)?.value || {}
            if (run.phase === 'done') {
                const n = run.tables_done ?? run.tables_total
                toast?.add?.({ title: 'Sync complete', description: n != null ? `${n} tables synced — agent re-trained` : 'Agent re-trained', icon: 'i-heroicons-check-circle' })
                setTimeout(() => window.location.reload(), 800)
                return
            }
            if (run.phase === 'error') {
                toast?.add?.({ title: 'Sync failed', description: run.error || 'See the Activity tab for details', color: 'red' })
                return
            }
        }
        toast?.add?.({ title: 'Sync still running', description: 'Check the Activity tab for progress', icon: 'i-heroicons-clock' })
    } catch (e: any) {
        toast?.add?.({ title: 'Sync failed', description: e?.data?.detail || e?.message || '', color: 'red' })
    } finally {
        syncing.value = false
    }
}

const editingDesc = ref(false)
const descForm = ref('')
const descInputRef = ref<HTMLInputElement | null>(null)

function startEditDesc() {
    descForm.value = integration.value?.description || ''
    editingDesc.value = true
    nextTick(() => descInputRef.value?.focus())
}

function cancelDesc() {
    editingDesc.value = false
}

async function saveDesc() {
    if (!editingDesc.value) return
    editingDesc.value = false
    const newVal = (descForm.value || '').trim()
    if (newVal === (integration.value?.description || '')) return
    if (integration.value) integration.value.description = newVal
    const { error } = await useMyFetch(`/data_sources/${id.value}`, {
        method: 'PUT',
        body: { description: newVal },
    })
    if (error?.value) {
        if (integration.value) integration.value.description = descForm.value
        toast?.add?.({ title: 'Failed to save description', color: 'red' })
    } else {
        toast?.add?.({ title: 'Description updated' })
        await fetchIntegration()
    }
}

function onPublishStatusUpdated(value: string) {
    // Optimistic local update; refetch keeps derived views in sync.
    if (integration.value) integration.value.publish_status = value
    fetchIntegration()
}

async function startChat() {
    if (startingChat.value || !integration.value?.id) return
    startingChat.value = true
    try {
        const response = await useMyFetch('/reports', {
            method: 'POST',
            body: JSON.stringify({
                title: 'untitled report',
                files: [],
                data_sources: [integration.value.id],
            }),
        })
        const data = (response.data as any)?.value
        if (data?.id) {
            await router.push(`/reports/${data.id}`)
        }
    } finally {
        startingChat.value = false
    }
}

async function fetchIntegration(silent = false) {
    if (!id.value) return
    // Background sync polls refetch every 2s — do NOT toggle the global loading
    // flag on those, or the Overview flips to its loading skeleton on every tick
    // (the "screen blinks again and again" during sync). Only the first/initial
    // load + id-change show the loader.
    if (!silent) isLoading.value = true
    fetchError.value = null

    try {
        const config = useRuntimeConfig()
        const { token } = useAuth()
        const { organization } = useOrganization()

        const data = await $fetch(`/data_sources/${id.value}`, {
            baseURL: config.public.baseURL,
            method: 'GET',
            headers: {
                Authorization: `${token.value}`,
                'X-Organization-Id': organization.value?.id || '',
            }
        })

        integration.value = data as any
    } catch (e: any) {
        console.error('Failed to fetch integration:', e)
        fetchError.value = e?.response?.status || e?.status || e?.statusCode || 500
    }

    if (!silent) isLoading.value = false
    maybeStartPolling()
}

provide('integration', integration)
provide('fetchIntegration', fetchIntegration)
provide('isLoading', isLoading)
provide('fetchError', fetchError)

const POLL_INTERVAL_MS = 2000
let pollTimer: ReturnType<typeof setInterval> | null = null

function stopPolling() {
    if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
    }
}

function maybeStartPolling() {
    const hasActive = hasAnyActiveIndexing(integration.value?.connections)
    if (hasActive && !pollTimer) {
        pollTimer = setInterval(() => {
            if (fetchError.value) {
                stopPolling()
                return
            }
            fetchIntegration(true).then(() => {
                if (!hasAnyActiveIndexing(integration.value?.connections)) {
                    stopPolling()
                }
            })
        }, POLL_INTERVAL_MS)
    } else if (!hasActive) {
        stopPolling()
    }
}

watch(id, () => {
    stopPolling()
    fetchIntegration()
})

onMounted(() => {
    fetchIntegration()
})

onBeforeUnmount(() => {
    stopPolling()
})
</script>

<style scoped>
/* Agent sub-nav — matches the redesign mockup (.side / .agenthead / .navgrp / .navitem). */
.cag-side { width: 224px; background: #FFFFFF; border-right: 1px solid #EAE8E4; padding: 16px 12px; font-family: 'Hanken Grotesk', system-ui, sans-serif; }

.cag-back { display: inline-flex; align-items: center; gap: 6px; color: #78716C; font-size: 13px; margin-bottom: 16px; text-decoration: none; }
.cag-back:hover { color: #1C1917; }

.cag-agenthead { display: flex; align-items: center; gap: 10px; padding: 0 6px 16px; border-bottom: 1px solid #F1EFEC; margin-bottom: 14px; }
.cag-ic { width: 34px; height: 34px; border-radius: 9px; background: #FBEDE4; display: flex; align-items: center; justify-content: center; color: #C2541E; flex: none; }
.cag-nm { font-weight: 600; font-size: 13.5px; line-height: 1.25; color: #1C1917; }
.cag-st { font-size: 11px; color: #15803D; display: flex; align-items: center; gap: 4px; margin-top: 2px; }
.cag-st .d { width: 6px; height: 6px; border-radius: 50%; background: #15803D; }
.cag-sub { font-size: 11px; color: #A8A29E; margin-top: 2px; }

.cag-navgrp { font-size: 10.5px; font-weight: 600; letter-spacing: .06em; color: #A8A29E; text-transform: uppercase; padding: 14px 8px 6px; }
.cag-navitem { display: flex; align-items: center; gap: 10px; padding: 7px 9px; border-radius: 8px; color: #44403C; font-weight: 500; font-size: 13.5px; cursor: pointer; margin-bottom: 1px; text-decoration: none; background: none; border: none; transition: background .12s, color .12s; }
.cag-navitem:hover { background: #F1EFEC; }
.cag-navitem.on { background: #FBEDE4; color: #C2541E; font-weight: 600; }
.cag-navitem:disabled { opacity: .55; cursor: default; }
.cag-navitem-ic { width: 16px; height: 16px; flex: 0 0 16px; }
.cag-navitem .ct { margin-left: auto; font-size: 11.5px; color: #A8A29E; font-weight: 600; }
.cag-navitem.on .ct { color: #C2541E; }

.cag-danger { color: #B4331A; }
.cag-danger:hover { background: #FCEEEA; color: #B4331A; }

/* YouTube-style shimmer skeleton */
.cag-sk { background: #EEECE8; position: relative; overflow: hidden; }
.cag-sk-line { border-radius: 6px; }
.cag-sk::after {
    content: '';
    position: absolute;
    inset: 0;
    transform: translateX(-100%);
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.65), transparent);
    animation: cag-shimmer 1.4s ease-in-out infinite;
}
@keyframes cag-shimmer { 100% { transform: translateX(100%); } }
</style>
