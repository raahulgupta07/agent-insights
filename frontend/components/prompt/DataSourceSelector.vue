<template>
    <div class="inline-block relative" ref="containerRef">
        <UPopover :popper="{ strategy: 'absolute', placement: 'bottom-start', offset: [0,8] }">
            <UTooltip :text="isCompactFinal ? dataTooltip : ''" :popper="{ strategy: 'fixed', placement: 'bottom-start' }">
                <button
                    class="inline-flex items-center text-gray-500 hover:text-gray-900 hover:bg-gray-50 rounded-md p-2 text-xs"
                    :disabled="isLoading"
                >
                    <span v-if="isLoading" class="flex items-center">
                        <Spinner class="w-4 h-4 text-gray-400 animate-spin" />
                    </span>
                    <span v-else-if="selectedStudio" class="flex items-center">
                        <span class="text-sm leading-none">{{ selectedStudio.avatar || '🎬' }}</span>
                        <span v-if="!isCompactFinal" class="ms-1 text-xs truncate max-w-[120px]">{{ selectedStudio.name }}</span>
                    </span>
                    <span v-else-if="(isAutoMode || STUDIOS_ONLY) && internalSelectedDataSources.length === 0" class="flex items-center">
                        <Icon name="heroicons-bolt" class="h-4 w-4" />
                        <span v-if="!isCompactFinal" class="ms-1 text-xs">Auto</span>
                    </span>
                    <span v-else-if="internalSelectedDataSources.length > 0" class="flex items-center">
                        <template v-if="isCompactFinal">
                            <!-- Compact: show only first icon (connector logo when known) -->
                            <img v-if="dsLogo(internalSelectedDataSources[0])" :src="dsLogo(internalSelectedDataSources[0])" :alt="dsLabel(internalSelectedDataSources[0])" class="h-4 w-4 object-contain" />
                            <DataSourceIcon v-else :type="internalSelectedDataSources[0].type" class="h-4" />
                        </template>
                        <template v-else>
                            <!-- Non-compact: show stacked icons (connector logo when known) -->
                            <div class="flex -space-x-1">
                                <template v-for="ds in internalSelectedDataSources.slice(0, 3)" :key="ds.id">
                                    <img v-if="dsLogo(ds)" :src="dsLogo(ds)" :alt="dsLabel(ds)" class="h-4 w-4 ring-1 ring-white rounded flex-shrink-0 object-contain bg-white" />
                                    <DataSourceIcon v-else :type="ds.type" class="h-4 ring-1 ring-white rounded flex-shrink-0" />
                                </template>
                            </div>
                            <span v-if="internalSelectedDataSources.length > 3" class="ms-1 text-[10px] text-gray-400">
                                +{{ internalSelectedDataSources.length - 3 }}
                            </span>
                        </template>
                    </span>
                    <span v-else class="flex items-center">
                        <AgentIcon class="h-4 w-4" />
                    </span>
                </button>
            </UTooltip>
            <template #panel>
                <div class="p-2 text-xs max-h-64 overflow-y-auto w-max min-w-[260px] max-w-[420px] rounded-xl">
                    <div v-if="isLoading" class="flex items-center justify-center py-6 text-gray-500 space-x-2">
                        <Spinner class="w-4 h-4 text-gray-400 animate-spin" />
                        <span>Loading data sources…</span>
                    </div>
                    <template v-else>
                        <div v-if="(!STUDIOS_ONLY && visibleDataSources.length === 0 && connectableDataSources.length === 0 && studios.length === 0)" class="text-center text-gray-500 py-4">
                            No data sources found
                        </div>
                        <template v-else>
                            <!-- Auto — let the agent auto-select the right studio/sources
                                 for the question (no manual pin). Active when no studio
                                 is chosen. Always shown in Studios-only mode. -->
                            <template v-if="STUDIOS_ONLY">
                                <div class="px-2 pt-1 pb-1 text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Context</div>
                                <div
                                    class="px-2 py-1.5 rounded hover:bg-gray-50 cursor-pointer flex items-center justify-between"
                                    @click="selectAuto()"
                                >
                                    <div class="flex items-center">
                                        <Icon name="heroicons-bolt" class="h-4 w-4 text-gray-500 me-2" />
                                        <span class="text-[13px]">Auto</span>
                                        <span class="ms-2 text-[11px] text-gray-400">picks for you</span>
                                    </div>
                                    <Icon v-if="!internalSelectedStudioId && autoActive" name="heroicons-check" class="w-4 h-4 text-[#C2541E] flex-shrink-0" />
                                </div>
                                <div class="my-1 border-t border-gray-100" />
                            </template>

                            <!-- Studios (hybrid Studios): wrap Data Agents with persona +
                                 grounded scope. Picking one is exclusive. Hidden when the
                                 feature is off (backend returns no studios). -->
                            <template v-if="studios.length > 0">
                                <div class="px-2 pt-1 pb-1 text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Agent Studios</div>
                                <div
                                    v-for="s in studios"
                                    :key="s.id"
                                    class="px-2 py-1.5 rounded hover:bg-gray-50 cursor-pointer flex items-center justify-between"
                                    @click="selectStudio(s)"
                                    @mouseenter="onStudioHover(s, $event)"
                                    @mouseleave="onDataSourceHoverLeave()"
                                >
                                    <div class="flex items-center min-w-0">
                                        <span class="text-sm leading-none">{{ s.avatar || '🎬' }}</span>
                                        <span class="ms-2 text-[13px] truncate">{{ s.name }}</span>
                                    </div>
                                    <Icon v-if="internalSelectedStudioId === s.id" name="heroicons-check" class="w-4 h-4 text-[#C2541E] flex-shrink-0" />
                                </div>
                                <NuxtLink
                                    v-if="STUDIOS_ONLY"
                                    to="/studios"
                                    class="px-2 py-1.5 rounded hover:bg-gray-50 cursor-pointer flex items-center text-gray-400 hover:text-gray-600"
                                >
                                    <Icon name="heroicons-plus" class="w-4 h-4 me-2" />
                                    <span class="text-[13px]">New Agent Studio</span>
                                </NuxtLink>
                                <div class="my-1 border-t border-gray-100" />
                            </template>

                            <!-- No studios yet: still offer to create one (Auto stays above) -->
                            <NuxtLink
                                v-if="STUDIOS_ONLY && studios.length === 0"
                                to="/studios"
                                class="px-2 py-1.5 rounded hover:bg-gray-50 cursor-pointer flex items-center text-gray-400 hover:text-gray-600"
                            >
                                <Icon name="heroicons-plus" class="w-4 h-4 me-2" />
                                <span class="text-[13px]">New Agent Studio</span>
                            </NuxtLink>

                            <!-- Data Agents: selectable directly (alongside Studios). Auto
                                 is already shown above, so no duplicate here. -->
                            <template v-if="visibleDataSources.length > 0">
                                <div class="my-1 border-t border-gray-100" />
                                <div class="px-2 pt-1 pb-1 text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Data Agents</div>
                                <div
                                    v-for="ds in visibleDataSources"
                                    :key="ds.id"
                                    class="px-2 py-1.5 rounded hover:bg-gray-50 cursor-pointer flex items-center justify-between"
                                    @click="() => { toggleDataSource(ds); }"
                                    @mouseenter="onDataSourceHover(ds.id, $event)"
                                    @mouseleave="onDataSourceHoverLeave()"
                                >
                                    <div class="flex items-center min-w-0">
                                        <img v-if="dsLogo(ds)" :src="dsLogo(ds)" :alt="dsLabel(ds)" class="h-4 w-4 flex-shrink-0 object-contain" />
                                        <DataSourceIcon v-else :type="ds.type" class="h-4 flex-shrink-0" />
                                        <span class="ms-2 text-[13px] truncate">{{ dsLabel(ds) }}</span>
                                        <!-- Non-published agents only reach here for managers; flag
                                             them so it's clear they aren't live for consumers yet. -->
                                        <span
                                            v-if="ds.publish_status && ds.publish_status !== 'published'"
                                            :class="['ms-2 flex-shrink-0 text-[10px] rounded border px-1 py-0.5', publishStatusBadgeClass(ds.publish_status)]"
                                        >{{ publishStatusLabel(ds.publish_status) }}</span>
                                        <!-- Running via the connection's system (service principal) creds -->
                                        <span
                                            v-if="isServiceAccount(ds)"
                                            class="ms-2 flex-shrink-0 text-[10px] text-gray-400 border border-gray-200 rounded px-1 py-0.5"
                                        >Service account</span>
                                    </div>
                                    <div class="flex items-center gap-1.5 flex-shrink-0">
                                        <!-- Readiness pill: green = synced tables, red = connected but empty -->
                                        <span
                                            v-if="readyState(ds).kind !== 'unknown'"
                                            :class="[
                                                'inline-flex items-center gap-1 text-[10px] rounded-full px-1.5 py-0.5 flex-shrink-0',
                                                readyState(ds).kind === 'ready'
                                                    ? 'bg-[#EBF6EF] text-[#3f9e6a]'
                                                    : 'bg-[#FBEAE5] text-[#C2541E]'
                                            ]"
                                        >
                                            <span
                                                :class="['w-1.5 h-1.5 rounded-full', readyState(ds).kind === 'ready' ? 'bg-[#3f9e6a]' : 'bg-[#C2541E]']"
                                            />
                                            {{ readyState(ds).label }}
                                        </span>
                                        <span
                                            class="w-4 h-4 rounded-full bg-gray-100 text-[9px] font-semibold text-gray-500 flex items-center justify-center"
                                            :title="dsEmail(ds)"
                                        >{{ dsInitial(ds) }}</span>
                                        <Icon v-if="!autoActive && isSelected(ds)" name="heroicons-check" class="w-4 h-4 text-[#C2541E]" />
                                    </div>
                                </div>
                            </template>

                            <!-- Not-yet-connected (user_required) data sources: grayed out
                                 with a Connect action. These are NOT selectable and are
                                 never persisted to the report until connected. -->
                            <template v-if="connectableDataSources.length > 0">
                                <div v-if="visibleDataSources.length > 0" class="my-1 border-t border-gray-100" />
                                <div
                                    v-for="ds in connectableDataSources"
                                    :key="ds.id"
                                    class="px-2 py-1.5 rounded hover:bg-gray-50 cursor-pointer flex items-center justify-between gap-2"
                                    @click="openCredentialsModal(ds)"
                                >
                                    <div class="flex items-center min-w-0">
                                        <DataSourceIcon :type="ds.type" class="h-4 flex-shrink-0 opacity-50" />
                                        <span class="ms-2 text-[13px] truncate opacity-50">{{ ds.name }}</span>
                                        <!-- Amber pill: connected source needs a personal sign-in first -->
                                        <span class="ms-2 inline-flex items-center gap-1 text-[10px] rounded-full px-1.5 py-0.5 bg-[#FBF0E1] text-[#B26A16] flex-shrink-0">
                                            <span class="w-1.5 h-1.5 rounded-full bg-[#E0A93B]" />
                                            sign in
                                        </span>
                                    </div>
                                    <button
                                        type="button"
                                        :disabled="connectingId === ds.id"
                                        class="flex-shrink-0 inline-flex items-center gap-1 px-2 py-0.5 text-[11px] text-[#C2541E] bg-[#F6EFEA] border border-[#E8C9B5] rounded-md hover:bg-[#F4E5DA] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
                                        @click.stop="openCredentialsModal(ds)"
                                    >
                                        <Spinner v-if="connectingId === ds.id" class="w-3 h-3" />
                                        <Icon v-else name="heroicons-key" class="w-3 h-3" />
                                        {{ $t('data.connect') }}
                                    </button>
                                </div>
                            </template>
                        </template>
                    </template>
                </div>
            </template>
        </UPopover>

        <!-- Agent flyout component -->
        <AgentFlyout
            v-if="!hoveredStudioId"
            :agent-id="hoveredDataSourceId"
            :visible="flyout.visible"
            :position="flyout"
            @mouseenter="onFlyoutEnter"
            @mouseleave="onFlyoutLeave"
            @connect="openCredentialsModal"
        />

        <!-- Studio flyout component (hover preview for Studio rows) -->
        <StudioFlyout
            v-if="flyout.visible && hoveredStudioId"
            :studio-id="hoveredStudioId"
            :name="hoveredStudioName"
            :avatar="hoveredStudioAvatar"
            :visible="flyout.visible"
            :position="flyout"
            @mouseenter="onFlyoutEnter"
            @mouseleave="onFlyoutLeave"
        />

        <!-- User credentials / OAuth modal for connecting user_required sources -->
        <UserDataSourceCredentialsModal
            v-model="showCredsModal"
            :data-source="selectedConnectDs"
            @saved="onCredentialsSaved"
        />
    </div>

</template>

<script lang="ts" setup>
import Spinner from '@/components/Spinner.vue'
import AgentFlyout from '~/components/AgentFlyout.vue'
import StudioFlyout from '~/components/StudioFlyout.vue'
import AgentIcon from '~/components/icons/AgentIcon.vue'
import UserDataSourceCredentialsModal from '~/components/UserDataSourceCredentialsModal.vue'
import { usePermissions, usePermissionsLoaded, useResourcePermissions } from '~/composables/usePermissions'
import { publishStatusBadgeClass, publishStatusLabel } from '~/composables/useDataSourcePublishStatus'
import { useAgent } from '~/composables/useAgent'

// Global studio state — shared with AgentSelector (top-bar picker).
// Aliased to avoid clashing with the local prop/ref names used below.
const {
    selectedStudioId: globalStudioId,
    studios: globalStudios,
    selectStudio: selectStudioGlobal,
    clearStudio: clearStudioGlobal,
    initStudios,
    // Mirror the raw data-source pick into the shared store so the top-bar
    // AgentSelector reflects it (and vice-versa via the watcher below).
    selectAgents: selectAgentsGlobal,
    selectedAgents: globalSelectedAgents,
} = useAgent()

type DataSource = { id: string; name: string; type?: string; auth_policy?: string; publish_status?: string; connections?: any[]; user_status?: { effective_auth?: string; has_user_credentials?: boolean; uses_fallback?: boolean } }
type Studio = { id: string; name: string; avatar?: string | null }
const internalSelectedDataSources = ref<DataSource[]>([])
const dataSources = ref<DataSource[]>([])
// Studios (hybrid Studios): NotebookLM-style containers that wrap Data Agents.
// Listed as a separate section above data sources. Selecting one is EXCLUSIVE
// (clears data-source selection) — the studio defines its own grounded scope.
// We use the GLOBAL studios list from useAgent() so this dropdown and the top
// AgentSelector share the same fetched list (no double-fetch).
const studios = computed<Studio[]>(() => globalStudios.value as Studio[])
const internalSelectedStudioId = ref<string>('')
// user_required data sources the user hasn't connected yet — shown grayed out
// with a Connect action. Kept separate so they never enter selection/auto-mode
// and are never persisted to the report.
const connectableDataSources = ref<DataSource[]>([])
const isLoading = ref(true)
const isOpen = ref(false)
const containerRef = ref<HTMLElement | null>(null)
const isCompact = ref(false)
const isCompactFinal = computed(() => isCompact.value)
const isAutoMode = computed(() =>
    visibleDataSources.value.length > 0 &&
    visibleDataSources.value.every(ds => internalSelectedDataSources.value.some(s => s.id === ds.id))
)
// EXPLICIT Auto flag. The all-selected heuristic above can't tell "Auto" from
// "the user pinned the only Data Agent" when there is a single source — both
// look like "everything selected". This flag records the user's actual intent
// so the checkmark reflects the real pick even with one Data Agent.
const autoActive = ref(true)

// Hover flyout state
const hoveredDataSourceId = ref<string | null>(null)
const flyout = reactive({ visible: false, bottom: 0, left: 0, maxHeight: 0 })
let flyoutHideTimer: ReturnType<typeof setTimeout> | null = null

// On touch/coarse-pointer devices there is no hover. Tapping a row would
// otherwise fire `mouseenter` and pop the fixed flyout overlay on top of the
// list, swallowing the tap so the selection never registers. Detect touch and
// skip the flyout entirely so rows stay tappable on mobile.
const isTouchDevice = ref(false)
onMounted(() => {
    if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
        isTouchDevice.value = window.matchMedia('(pointer: coarse)').matches
    }
})

// Connect (user credentials / OAuth) modal state
const showCredsModal = ref(false)
const selectedConnectDs = ref<DataSource | null>(null)
const signIn = useConnectionSignIn()
const { t } = useI18n()
const toast = useToast()

// Mirror the agents page: if the source's pending-sign-in connection has
// OAuth as its only user auth mode, redirect straight to the provider
// instead of showing an empty modal. Falls back to the modal otherwise.
function findPendingSignInConnection(ds: DataSource): any | null {
    for (const conn of (ds.connections || [])) {
        if (conn.auth_policy === 'user_required' && !conn.user_status?.has_user_credentials) {
            return conn
        }
    }
    return null
}

// Data source id whose Connect button is mid-sign-in (awaiting the authorize
// redirect). Stays set through a redirect so the spinner persists until the
// browser unloads the page.
const connectingId = ref<string | null>(null)

async function openCredentialsModal(ds: DataSource) {
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
    selectedConnectDs.value = ds
    showCredsModal.value = true
}

async function onCredentialsSaved() {
    showCredsModal.value = false
    // Re-fetch so a freshly-connected source moves into the selectable list.
    await getDataSources()
}

const showFlyoutAtEvent = (evt: MouseEvent) => {
    const el = evt.currentTarget as HTMLElement | null
    if (!el) return

    // Find the dropdown panel to align with it
    const panel = el.closest('.rounded-xl') as HTMLElement | null
    const panelRect = panel?.getBoundingClientRect()
    const rect = el.getBoundingClientRect()

    // Matches AgentFlyout's max width (it grows to fit long names) so a
    // left-placed flyout reserves enough room and never overlaps the dropdown.
    const flyoutWidth = 520
    const gap = 8

    // Position to the right of the dropdown panel
    let left = (panelRect?.right ?? rect.right) + gap

    // If not enough space on right, position to the left
    if (left + flyoutWidth > window.innerWidth - 12) {
        left = (panelRect?.left ?? rect.left) - flyoutWidth - gap
    }

    // Clamp left to viewport
    left = Math.max(12, Math.min(left, window.innerWidth - flyoutWidth - 12))

    // Anchor the flyout's BOTTOM to the hovered ROW's bottom, so it sits beside
    // the row (cursor can bridge onto it) and grows UPWARD into the empty space
    // above — the composer picker lives at the bottom of the screen, so there's
    // always room above and never below. Two earlier bugs this avoids: anchoring
    // to the panel bottom detached it from the row (gap → hover dropped); anchor-
    // ing the TOP to a low row pushed it off the bottom of the viewport. Clamp so
    // the top never runs off-screen; content scrolls internally.
    const bottom = Math.max(12, window.innerHeight - rect.bottom - 8)
    flyout.left = left
    flyout.bottom = bottom
    flyout.maxHeight = Math.max(160, window.innerHeight - bottom - 12)
    flyout.visible = true
}

const onDataSourceHover = (dataSourceId: string, evt: MouseEvent) => {
    // No hover flyout on touch devices — keep rows tappable.
    if (isTouchDevice.value) return
    if (flyoutHideTimer) {
        clearTimeout(flyoutHideTimer)
        flyoutHideTimer = null
    }
    if (typeof window !== 'undefined') showFlyoutAtEvent(evt)
    hoveredStudioId.value = null
    hoveredDataSourceId.value = dataSourceId
}

// Plan A — Studios-only composer picker. Raw connectors/data agents and the
// "Auto" toggle are hidden; a connector is only reachable once pinned inside a
// Studio (which the user selects here). Flip to false to restore the legacy
// raw-source picker.
const STUDIOS_ONLY = true

// Studio hover preview (shares the same flyout position object; mutually
// exclusive with the agent flyout).
const hoveredStudioId = ref<string | null>(null)
const hoveredStudioName = ref<string | null>(null)
const hoveredStudioAvatar = ref<string | null>(null)

const onStudioHover = (s: any, evt: MouseEvent) => {
    if (isTouchDevice.value) return
    if (flyoutHideTimer) {
        clearTimeout(flyoutHideTimer)
        flyoutHideTimer = null
    }
    if (typeof window !== 'undefined') showFlyoutAtEvent(evt)
    hoveredDataSourceId.value = null
    hoveredStudioId.value = String(s.id)
    hoveredStudioName.value = s.name || null
    hoveredStudioAvatar.value = s.avatar || null
}

const onDataSourceHoverLeave = () => {
    // Give the user time to move cursor from list → flyout
    if (flyoutHideTimer) clearTimeout(flyoutHideTimer)
    flyoutHideTimer = setTimeout(() => {
        flyout.visible = false
        hoveredDataSourceId.value = null
        hoveredStudioId.value = null
    }, 120)
}

const onFlyoutEnter = () => {
    if (flyoutHideTimer) {
        clearTimeout(flyoutHideTimer)
        flyoutHideTimer = null
    }
    flyout.visible = true
}

const onFlyoutLeave = () => {
    onDataSourceHoverLeave()
}

const props = defineProps({
    selectedDataSources: {
        type: Array,
        default: () => [],
    },
    reportId: {
        type: String,
        default: () => '',
    },
    // Studios (hybrid Studios): currently-bound studio id (v-model). Empty = none.
    selectedStudioId: {
        type: String,
        default: () => '',
    },
    // When set, only show data sources the user has this permission on
    // (either org-wide or via a per-DS resource grant).
    permission: {
        type: String,
        default: '',
    }
});


const emit = defineEmits(['update:selectedDataSources', 'update:selectedStudioId']);

const selectedStudio = computed<Studio | null>(() =>
    // internalSelectedStudioId is kept in sync with both the prop and the global,
    // so a single lookup covers all cases.
    (studios.value as Studio[]).find(s => s.id === internalSelectedStudioId.value) || null
)

// Optionally restrict visible data sources to those the user has `permission`
// for. Uses the resource-grant tier directly (NOT the org-perm implication
// tier) so that org-wide perms don't auto-grant the action on every DS the
// user can access — the user must have an explicit per-DS grant. Org admins
// (full_admin_access) still see everything.
const orgPerms = usePermissions()
const permsLoaded = usePermissionsLoaded()
const resourcePerms = useResourcePermissions()
const visibleDataSources = computed(() => {
    if (!props.permission) return dataSources.value
    if (!permsLoaded.value) return []
    if (orgPerms.value.includes('full_admin_access')) return dataSources.value
    return dataSources.value.filter((ds: any) => {
        const key = `data_source:${ds.id}`
        return resourcePerms.value[key]?.includes(props.permission) ?? false
    })
})

async function getDataSources() {
    try {
        const response = await useMyFetch('/data_sources/active', {
            method: 'GET',
            query: { include_unconnected: true },
        })
        const allSources = (response.data.value as any[]) || []
        // A source is usable (selectable) when it doesn't require per-user
        // credentials, or the user already has them / falls back to system auth.
        const isUsable = (ds: any) => {
            if (ds.auth_policy !== 'user_required') return true
            const status = ds.user_status
            if (status?.has_user_credentials) return true
            // effective_auth === 'system' means the user can run via system/service-
            // principal creds — including the owner/admin fallback (uses_fallback).
            // Treat that as usable so admins aren't forced through "Connect" for a
            // source they can already query.
            return status?.effective_auth === 'system'
        }
        dataSources.value = allSources.filter(isUsable)
        // Everything else returned is a user_required source the user can connect.
        connectableDataSources.value = allSources.filter((ds: any) => !isUsable(ds))
        // Initialize selection from prop if provided, otherwise leave empty for parent to decide
        if ((props.selectedDataSources as any[])?.length) {
            // Align to the objects from the current dataSources list by id
            const ids = new Set((props.selectedDataSources as any[]).map((x: any) => x.id))
            const picked = dataSources.value.filter((ds: any) => ids.has(ds.id))
            internalSelectedDataSources.value = picked
            // Explicit pin unless it happens to equal every source (= Auto).
            autoActive.value = picked.length > 0 && picked.length === visibleDataSources.value.length
            handleSelectionChange()
        } else if (!props.reportId) {
            // Landing page (no report): default to all data sources (auto).
            autoActive.value = true
            internalSelectedDataSources.value = [...visibleDataSources.value]
            handleSelectionChange()
        }
        // Reflect any sticky selection made in the top-bar AgentSelector (landing
        // page only) now that the concrete source objects are loaded.
        if (!props.reportId && globalSelectedAgents.value?.length) {
            applyGlobalSelection([...globalSelectedAgents.value])
        }
    } finally {
        isLoading.value = false
    }
}


function handleSelectionChange() {
    emit('update:selectedDataSources', internalSelectedDataSources.value);
}

function selectStudio(studio: Studio) {
    if (internalSelectedStudioId.value === studio.id) {
        // Deselect -> back to no studio (data-source mode)
        internalSelectedStudioId.value = ''
        // Propagate clear to global (explicit user action — no watcher feedback loop)
        clearStudioGlobal()
    } else {
        internalSelectedStudioId.value = studio.id
        // Exclusive: a studio defines its own grounded scope. Clear any
        // ad-hoc data-source selection so the two pickers don't fight.
        internalSelectedDataSources.value = []
        handleSelectionChange()
        // Propagate to global so AgentSelector (top bar) reflects this pick
        // and the selection persists to localStorage workspace-wide.
        selectStudioGlobal(studio.id)
    }
    emit('update:selectedStudioId', internalSelectedStudioId.value)
    persistStudioIfReport()
}

function clearStudio() {
    if (!internalSelectedStudioId.value) return
    internalSelectedStudioId.value = ''
    emit('update:selectedStudioId', '')
    // Propagate clear to global so AgentSelector and localStorage stay in sync.
    clearStudioGlobal()
}

function isSelected(option: any) {
    return internalSelectedDataSources.value.some((ds: any) => ds.id === option.id)
}

// Clean connector display (parity with the top-nav AgentSelector): show the
// product logo + short name ("Power BI") + signed-in user initial instead of
// the raw stored name "Power BI (User Sign-in) · email".
const CONNECTOR_NAMES: Record<string, string> = {
    powerbi: 'Power BI', powerbi_user: 'Power BI',
    ms_fabric: 'Microsoft Fabric', ms_fabric_user: 'Microsoft Fabric',
    sharepoint: 'SharePoint', onedrive: 'OneDrive',
}
const CONNECTOR_LOGOS: Record<string, string> = {
    powerbi: '/data_sources_icons/powerbi.png', powerbi_user: '/data_sources_icons/powerbi.png',
    ms_fabric: '/data_sources_icons/ms_fabric.png', ms_fabric_user: '/data_sources_icons/ms_fabric.png',
    sharepoint: '/data_sources_icons/sharepoint.png', onedrive: '/data_sources_icons/onedrive.png',
}
function dsType(ds: any): string { return ds?.connections?.[0]?.type || ds?.type || '' }
function dsLogo(ds: any): string { return CONNECTOR_LOGOS[dsType(ds)] || '' }
function dsLabel(ds: any): string {
    const t = dsType(ds)
    if (CONNECTOR_NAMES[t]) return CONNECTOR_NAMES[t]
    return String(ds?.name || '').split('·')[0].replace(/\(user\s*sign-?in\)/i, '').trim() || 'Data Agent'
}
function dsEmail(ds: any): string {
    const n = String(ds?.name || '')
    return n.includes('·') ? n.split('·').pop()!.trim() : (ds?.owner_email || '')
}
function dsInitial(ds: any): string {
    const src = dsEmail(ds) || dsLabel(ds)
    return (src.trim()[0] || '?').toUpperCase()
}

// The user can use this user_required source via the connection's system
// (service principal) credentials — admin/owner fallback, no personal sign-in.
function isServiceAccount(ds: any) {
    return ds?.auth_policy === 'user_required'
        && ds?.user_status?.effective_auth === 'system'
        && !ds?.user_status?.has_user_credentials
}

// Auto (Studios-only): clear any pinned studio and fall back to auto scope so
// the agent selects the right sources/skills for the question itself.
function selectAuto() {
    if (internalSelectedStudioId.value) {
        internalSelectedStudioId.value = ''
        clearStudioGlobal()
        emit('update:selectedStudioId', '')
    }
    autoActive.value = true
    internalSelectedDataSources.value = [...visibleDataSources.value]
    handleSelectionChange()
    mirrorSelectionToGlobal()
    persistSelectionIfReport()
}

function toggleAutoMode() {
    clearStudio()
    if (isAutoMode.value) {
        internalSelectedDataSources.value = []
    } else {
        internalSelectedDataSources.value = [...visibleDataSources.value]
    }
    handleSelectionChange()
    persistSelectionIfReport()
}

function toggleDataSource(ds: DataSource) {
    clearStudio()
    if (autoActive.value) {
        // Leaving Auto: pin only this source (explicit pick).
        autoActive.value = false
        internalSelectedDataSources.value = [ds]
    } else {
        const exists = internalSelectedDataSources.value.find((x) => x.id === ds.id)
        if (exists) {
            const next = internalSelectedDataSources.value.filter((x) => x.id !== ds.id)
            // Deselecting the last pinned source falls back to Auto rather than
            // an empty (invalid) selection.
            if (next.length === 0) {
                selectAuto()
                return
            }
            internalSelectedDataSources.value = next
        } else {
            internalSelectedDataSources.value = [...internalSelectedDataSources.value, ds]
        }
    }
    handleSelectionChange()
    // Mirror the pick into the shared store so the top-bar AgentSelector highlights it.
    mirrorSelectionToGlobal()
    // If we are in a report context, persist selection at report level immediately
    persistSelectionIfReport()
}

// Write the current logical selection into the shared useAgent store so the
// top-bar AgentSelector mirrors it. Auto (all sources) → empty selection (the
// store's "Auto"); an explicit pin → those ids. Single-write only; the watcher
// below reads back but skips when the id set already matches (no feedback loop).
function mirrorSelectionToGlobal() {
    if (autoActive.value) {
        selectAgentsGlobal([])
    } else {
        selectAgentsGlobal(internalSelectedDataSources.value.map((x: any) => x.id))
    }
}

// Apply a selection coming FROM the shared store (a pick made in the top-bar
// AgentSelector) into this composer picker. Guarded by an id-set diff so it
// never fights the local write above.
function applyGlobalSelection(ids: string[]) {
    const globalIds = [...(ids || [])]
    const internalIds = internalSelectedDataSources.value.map((x: any) => x.id)
    // Empty global selection = Auto. Only react if we're not already in Auto.
    if (globalIds.length === 0) {
        if (!autoActive.value) {
            autoActive.value = true
            internalSelectedDataSources.value = [...visibleDataSources.value]
            handleSelectionChange()
        }
        return
    }
    const sameSet = globalIds.length === internalIds.length
        && globalIds.every((id) => internalIds.includes(id))
    if (sameSet && !autoActive.value) return
    const picked = dataSources.value.filter((ds: any) => globalIds.includes(ds.id))
    if (picked.length === 0) return  // ids not in our list yet (still loading)
    autoActive.value = false
    internalSelectedDataSources.value = picked
    handleSelectionChange()
}

// A specific source is "ready" when it has synced tables (table_count > 0).
// ready===true is the backend's authoritative flag; table_count is the fallback.
// When neither field is present yet (backend contract not deployed) → 'unknown'
// so we render no pill and never falsely flag a source as empty.
function readyState(ds: any): { kind: 'ready' | 'blocked' | 'unknown'; label: string } {
    const hasReady = typeof ds?.ready === 'boolean'
    const hasCount = ds?.table_count !== undefined && ds?.table_count !== null
    if (!hasReady && !hasCount) return { kind: 'unknown', label: '' }
    const tc = Number(ds?.table_count ?? 0)
    const ready = ds?.ready === true || tc > 0
    if (ready) return { kind: 'ready', label: `ready · ${tc} table${tc === 1 ? '' : 's'}` }
    return { kind: 'blocked', label: 'no data' }
}

onMounted(() => {
    nextTick(async () => {
        const { organization, ensureOrganization } = useOrganization()
        
        try {
            // Wait for organization to be available before making API calls
            await ensureOrganization()
            
            if (organization.value?.id) {
                getDataSources()
                // Use the global studios list (shared with AgentSelector). initStudios()
                // is a no-op if AgentSelector already called it; the shared ref stays
                // populated so no double-fetch in practice.
                initStudios()
                // Seed internal studio id from the global sticky selection when the
                // parent hasn't provided one via the prop yet (e.g. landing page).
                if (!props.selectedStudioId && globalStudioId.value) {
                    internalSelectedStudioId.value = globalStudioId.value
                }
            } else {
                console.warn('DataSourceSelectorComponentExcel: Organization not available, skipping API calls')
            }
        } catch (error) {
            console.error('DataSourceSelectorComponentExcel: Error during initialization:', error)
        }
        // Setup resize observer for compact mode
        // Look for the nearest parent container that's likely the prompt box
        const findPromptContainer = () => {
            let parent = containerRef.value?.parentElement
            while (parent && parent.clientWidth < 300) {
                parent = parent.parentElement
            }
            return parent || containerRef.value
        }
        
        const ro = new ResizeObserver(() => {
            const targetEl = findPromptContainer()
            const w = targetEl?.clientWidth || 0
            // Use a more reasonable threshold - compact if container is less than 420px
            isCompact.value = w > 0 && w < 420
        })
        
        // Observe the container initially, then try to find a better parent
        if (containerRef.value) {
            ro.observe(containerRef.value)
            // Also try to observe a parent container after a short delay
            setTimeout(() => {
                const betterTarget = findPromptContainer()
                if (betterTarget && betterTarget !== containerRef.value) {
                    ro.unobserve(containerRef.value!)
                    ro.observe(betterTarget)
                }
            }, 100)
        }
    })
})
// Keep internal selection in sync with parent-provided selectedDataSources
watch(() => props.selectedDataSources, (newVal: any[]) => {
    if (!Array.isArray(newVal)) return
    const ids = new Set(newVal.map((x: any) => x.id))
    // Map to known dataSources, or fall back to the raw objects if not present yet
    const mapped = dataSources.value.length
        ? dataSources.value.filter((ds: any) => ids.has(ds.id))
        : newVal
    internalSelectedDataSources.value = mapped as any
}, { immediate: true, deep: true })

async function persistSelectionIfReport() {
    try {
        if (!props.reportId) return
        const ids = internalSelectedDataSources.value.map((x: any) => x.id)
        await useMyFetch(`/reports/${props.reportId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data_sources: ids })
        })
    } catch (e) {
        console.error('Failed to update report data sources:', e)
    }
}

// Bind the studio to an existing report immediately (composer opened on a
// live report). On the landing page (no reportId) the studio_id is carried
// into the create call by the parent instead.
async function persistStudioIfReport() {
    try {
        if (!props.reportId || !internalSelectedStudioId.value) return
        await useMyFetch(`/reports/${props.reportId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ studio_id: internalSelectedStudioId.value })
        })
    } catch (e) {
        console.error('Failed to bind report to studio:', e)
    }
}

// Keep internal studio selection in sync with parent-provided prop.
watch(() => props.selectedStudioId, (v) => {
    internalSelectedStudioId.value = v || ''
}, { immediate: true })

// Mirror global sticky selection → internal display.
// Only reads from the global; never writes back (avoids feedback loops).
// The prop watcher above takes priority when a prop value is set (PromptBoxV2
// explicitly passes a studio id). When the prop is empty the global wins.
watch(globalStudioId, (v) => {
    // Avoid overwriting a locally-set prop value — prop takes priority.
    if (!props.selectedStudioId) {
        internalSelectedStudioId.value = v || ''
    }
})

// Mirror a data-source pick made in the top-bar AgentSelector into this composer
// picker. Landing page only — on a live report the report owns its bound sources,
// so we don't let the sticky top-bar selection rewrite them. The guarded id-set
// diff inside applyGlobalSelection prevents any feedback loop with mirrorSelectionToGlobal.
watch(globalSelectedAgents, (ids) => {
    if (props.reportId) return
    applyGlobalSelection([...(ids || [])])
}, { deep: true })

const dataTooltip = computed<string>(() => {
    if (internalSelectedDataSources.value.length <= 1) return ''
    const rest = internalSelectedDataSources.value.slice(1).map(s => s.name).join(', ')
    return rest
})

</script>