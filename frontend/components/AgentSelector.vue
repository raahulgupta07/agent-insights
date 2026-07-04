<template>
  <div class="agent-selector">
    <!-- Loading / empty placeholder — reserves layout space while agents load -->
    <div
      v-if="loading || (!loading && agents.length === 0)"
      :class="[
        'flex items-center w-full rounded-lg',
        'bg-white border border-gray-200 shadow-sm',
        collapsed ? 'justify-center p-2' : 'gap-1.5 px-2.5 py-2'
      ]"
    >
      <UTooltip v-if="collapsed" :text="loading ? $t('common.loading') : $t('nav.noAgents')" :popper="{ placement: 'right' }">
        <Spinner v-if="loading" class="w-4 h-4 text-gray-300 animate-spin" />
        <AgentIcon class="w-4 h-4 text-gray-300" />
      </UTooltip>
      <template v-else>
        <span v-if="showText" class="flex-1 text-start min-w-0">
          <span v-if="showLabel" class="block text-[8px] uppercase tracking-wide text-gray-400 font-semibold leading-none">{{ $t('nav.context') }}</span>
          <span :class="['flex items-center gap-1.5', showLabel ? 'mt-0.5' : '']">
            <Spinner v-if="loading" class="w-3 h-3 text-gray-300 animate-spin flex-shrink-0" />
            <span class="text-xs font-medium text-gray-400 truncate">
              {{ loading ? $t('common.loading') : $t('nav.noAgents') }}
            </span>
          </span>
        </span>
      </template>
    </div>

    <UPopover
      v-else
      :popper="{ placement: 'bottom-start', offsetDistance: 4, strategy: 'fixed' }"
      :ui="{
        width: 'max-w-none',
        container: 'overflow-visible',
        inner: 'overflow-visible'
      }"
    >
      <button
        :class="[
          'flex items-center w-full rounded-lg transition-all duration-200',
          'bg-white hover:bg-gray-50',
          'border border-gray-200 shadow-sm hover:shadow hover:border-gray-300',
          collapsed ? 'justify-center p-2' : 'gap-1.5 px-2.5 py-2'
        ]"
      >
        <UTooltip v-if="collapsed" :text="contextLabel" :popper="{ placement: 'right' }">
          <span class="flex items-center justify-center w-5 h-5">
            <Spinner v-if="loading" class="w-4 h-4 text-gray-400 animate-spin" />
            <span v-else-if="selectedStudio" class="text-sm leading-none">{{ selectedStudio.avatar || '🎬' }}</span>
            <UIcon v-else-if="STUDIOS_ONLY" name="heroicons-bolt" class="w-4 h-4 text-gray-500" />
            <UIcon v-else name="heroicons-chevron-down" class="w-4 h-4 text-gray-500" />
          </span>
        </UTooltip>
        <template v-else>
          <span class="flex-shrink-0">
            <span v-if="selectedStudio" class="text-sm leading-none">{{ selectedStudio.avatar || '🎬' }}</span>
            <img v-else-if="pinnedAgentLogo" :src="pinnedAgentLogo" alt="" class="h-3.5 w-3.5 object-contain" />
            <DataSourceIcon v-else-if="singleSelectedConnection" :type="singleSelectedConnection" class="h-3.5 w-3.5" />
            <UIcon v-else-if="STUDIOS_ONLY" name="heroicons-bolt" class="w-3.5 h-3.5 text-gray-400" />
            <AgentIcon v-else class="w-3.5 h-3.5 text-gray-400" />
          </span>
          <span v-if="showText" class="flex-1 text-start min-w-0">
            <span v-if="showLabel" class="block text-[8px] uppercase tracking-wide text-gray-400 font-semibold leading-none">{{ $t('nav.context') }}</span>
            <span :class="['flex items-center gap-1.5', showLabel ? 'mt-0.5' : '']">
              <Spinner v-if="loading" class="w-3 h-3 text-gray-400 animate-spin flex-shrink-0" />
              <span class="text-xs font-medium text-gray-700 truncate">{{ contextLabel }}</span>
            </span>
          </span>
          <UIcon v-if="showText" name="heroicons-chevron-up-down" class="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
        </template>
      </button>

      <template #panel>
        <div class="overflow-visible">
          <!-- Agent list -->
          <div class="w-max min-w-[14rem] max-w-[24rem] bg-white rounded-xl shadow-xl border border-gray-200 overflow-hidden">
            <div class="p-1.5">
              <div v-if="loading" class="flex items-center justify-center py-6">
                <Spinner class="w-5 h-5 text-gray-400 animate-spin" />
              </div>

              <template v-else>
                <!-- Auto (Studios-only) — agent auto-selects the right studio/sources
                     for the question. Active when no studio is pinned. -->
                <template v-if="STUDIOS_ONLY">
                  <div class="px-2 pt-1 pb-0.5">
                    <span class="text-[8px] uppercase tracking-wide text-gray-400 font-semibold leading-none">Context</span>
                  </div>
                  <button
                    @click="selectAuto()"
                    @mouseenter="hideFlyoutNow()"
                    :class="[
                      'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-start transition-colors',
                      !selectedStudio ? 'bg-indigo-50' : 'hover:bg-gray-50'
                    ]"
                  >
                    <UIcon name="heroicons-bolt" :class="['w-4 h-4 flex-shrink-0', !selectedStudio ? 'text-indigo-600' : 'text-gray-400']" />
                    <span :class="['text-xs font-medium flex-1', !selectedStudio ? 'text-indigo-700' : 'text-gray-700']">Auto</span>
                    <span class="text-[10px] text-gray-400">picks for you</span>
                    <UIcon v-if="!selectedStudio" name="heroicons-check" class="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" />
                  </button>
                  <div class="my-1 border-t border-gray-100" />
                </template>

                <!-- Studios section — only rendered when at least one studio exists (flag-OFF = empty = section absent) -->
                <template v-if="studios.length > 0">
                  <div class="px-2 pt-1 pb-0.5">
                    <span class="text-[8px] uppercase tracking-wide text-gray-400 font-semibold leading-none">Agent Studios</span>
                  </div>
                  <button
                    v-for="s in studios"
                    :key="s.id"
                    @click="selectStudio(s.id)"
                    @mouseenter="onStudioHover(s, $event)"
                    @mouseleave="onStudioHoverLeave()"
                    :class="[
                      'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-start transition-colors',
                      selectedStudio?.id === s.id ? 'bg-indigo-50' : 'hover:bg-gray-50'
                    ]"
                  >
                    <span class="w-4 h-4 flex items-center justify-center flex-shrink-0 text-sm leading-none">{{ s.avatar || '🎬' }}</span>
                    <span :class="['text-xs font-medium truncate flex-1', selectedStudio?.id === s.id ? 'text-indigo-700' : 'text-gray-700']">{{ s.name }}</span>
                    <UIcon v-if="selectedStudio?.id === s.id" name="heroicons-check" class="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" />
                  </button>
                  <div class="my-1 border-t border-gray-100" />
                </template>

                <!-- New Studio (Studios-only) — always reachable to create a scope -->
                <NuxtLink
                  v-if="STUDIOS_ONLY"
                  to="/studios"
                  class="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-gray-400 hover:bg-gray-50 hover:text-gray-600 transition-colors"
                >
                  <UIcon name="heroicons-plus" class="w-3.5 h-3.5 flex-shrink-0" />
                  <span class="text-xs">New Agent Studio</span>
                </NuxtLink>

                <!-- Data Agents — selectable directly (parity with the composer
                     picker). Shown in STUDIOS_ONLY too so a connected source
                     (e.g. Power BI) can be picked as the chat context, not only
                     reachable via a Studio. Picking one is exclusive with a
                     Studio (toggleAgent clears the studio). -->
                <template v-if="dataAgents.length > 0">
                  <div class="my-1 border-t border-gray-100" />
                  <div class="px-2 pt-1 pb-0.5">
                    <span class="text-[8px] uppercase tracking-wide text-gray-400 font-semibold leading-none">Data Agents</span>
                  </div>
                  <div class="max-h-52 overflow-y-auto">
                    <button
                      v-for="a in dataAgents"
                      :key="a.id"
                      @click="toggleAgent(a.id)"
                      @mouseenter="onAgentHover(a.id, $event)"
                      @mouseleave="onAgentHoverLeave()"
                      :class="[
                        'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-start transition-colors',
                        isAgentSelected(a.id) ? 'bg-indigo-50' : 'hover:bg-gray-50'
                      ]"
                    >
                      <img
                        v-if="agentLogo(a)"
                        :src="agentLogo(a)"
                        :alt="agentLabel(a)"
                        class="h-4 w-4 flex-shrink-0 object-contain"
                      />
                      <DataSourceIcon
                        v-else-if="a.connections?.[0]?.type"
                        :type="a.connections[0].type"
                        class="h-4 w-4 flex-shrink-0"
                      />
                      <UIcon v-else name="heroicons-circle-stack" class="w-4 h-4 text-gray-400 flex-shrink-0" />
                      <span :class="['text-xs font-medium truncate flex-1', isAgentSelected(a.id) ? 'text-indigo-700' : 'text-gray-700']">{{ agentLabel(a) }}</span>
                      <!-- signed-in user initial (email tooltip) -->
                      <span
                        class="flex-shrink-0 w-4 h-4 rounded-full bg-gray-100 text-[9px] font-semibold text-gray-500 flex items-center justify-center"
                        :title="agentEmail(a)"
                      >{{ agentInitial(a) }}</span>
                      <UIcon v-if="isAgentSelected(a.id)" name="heroicons-check" class="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" />
                    </button>
                  </div>
                </template>

                <!-- Plan A: raw Data Agents hidden from the selector — a connector
                     is only reachable once pinned in a Studio. -->
                <template v-if="!STUDIOS_ONLY">
                <!-- All Agents -->
                <button
                  @click="toggleAgent(null)"
                  @mouseenter="hoveredAgentId = null"
                  @mouseleave="onAgentHoverLeave()"
                  :class="[
                    'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-start transition-colors',
                    isAllAgents ? 'bg-indigo-50' : 'hover:bg-gray-50'
                  ]"
                >
                  <AgentIcon class="w-4 h-4 text-gray-400 flex-shrink-0" />
                  <span :class="['text-xs font-medium flex-1', isAllAgents ? 'text-indigo-700' : 'text-gray-700']">{{ $t('nav.allAgents') }}</span>
                  <UIcon v-if="isAllAgents" name="heroicons-check" class="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" />
                </button>

                <div class="my-1 border-t border-gray-100" />

                <!-- Agent list -->
                <div class="max-h-52 overflow-y-auto">
                  <button
                    v-for="a in agents"
                    :key="a.id"
                    @click="toggleAgent(a.id)"
                    @mouseenter="onAgentHover(a.id, $event)"
                    @mouseleave="onAgentHoverLeave()"
                    :class="[
                      'w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-start transition-colors',
                      isAgentSelected(a.id) ? 'bg-indigo-50' : 'hover:bg-gray-50'
                    ]"
                  >
                    <DataSourceIcon
                      v-if="a.connections?.[0]?.type"
                      :type="a.connections[0].type"
                      class="h-4 w-4 flex-shrink-0"
                    />
                    <UIcon v-else name="heroicons-circle-stack" class="w-4 h-4 text-gray-400 flex-shrink-0" />
                    <span :class="['text-xs font-medium truncate flex-1', isAgentSelected(a.id) ? 'text-indigo-700' : 'text-gray-700']">{{ a.name }}</span>
                    <!-- Connect chip for user_required agents not yet authenticated.
                         Nested as a span (the row is a <button>) to keep markup valid. -->
                    <span
                      v-if="needsUserConnection(a)"
                      role="button"
                      tabindex="0"
                      @click.stop="onConnect(a)"
                      @keydown.enter.stop="onConnect(a)"
                      :class="[
                        'flex-shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded border transition-colors',
                        connectingId === a.id
                          ? 'text-[#C2541E] bg-[#F6EFEA] border-[#E8C9B5] cursor-default'
                          : 'text-[#C2541E] bg-[#F6EFEA] border-[#E8C9B5] hover:bg-[#F4E5DA]'
                      ]"
                    >
                      <Spinner v-if="connectingId === a.id" class="w-3 h-3" />
                      <UIcon v-else name="heroicons-key" class="w-3 h-3" />
                      {{ $t('data.connect') }}
                    </span>
                    <UIcon v-else-if="isAgentSelected(a.id)" name="heroicons-check" class="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" />
                  </button>
                </div>

                <div class="my-1 border-t border-gray-100" />

                <!-- View all -->
                <NuxtLink
                  to="/agents"
                  class="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-gray-400 hover:bg-gray-50 hover:text-gray-600 transition-colors"
                >
                  <AgentIcon class="w-3.5 h-3.5 flex-shrink-0" />
                  <span class="text-xs">{{ $t('nav.viewAllAgents') }}</span>
                </NuxtLink>
                </template>
              </template>
            </div>
          </div>
        </div>
      </template>
    </UPopover>

    <!-- Agent flyout component -->
    <AgentFlyout
      v-if="flyout.visible && hoveredAgentId"
      :agent-id="hoveredAgentId"
      :visible="flyout.visible"
      :position="flyout"
      @mouseenter="onFlyoutEnter"
      @mouseleave="onFlyoutLeave"
      @connect="onConnect"
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

    <!-- User credentials / OAuth modal for connecting user_required agents -->
    <UserDataSourceCredentialsModal
      v-model="showCredsModal"
      :data-source="selectedConnectDs"
      @saved="onCredentialsSaved"
    />
  </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'
import AgentFlyout from '~/components/AgentFlyout.vue'
import StudioFlyout from '~/components/StudioFlyout.vue'
import DataSourceIcon from '~/components/DataSourceIcon.vue'
import AgentIcon from '~/components/icons/AgentIcon.vue'
import UserDataSourceCredentialsModal from '~/components/UserDataSourceCredentialsModal.vue'

const props = withDefaults(defineProps<{
  collapsed?: boolean
  showText?: boolean
  showLabel?: boolean
}>(), {
  collapsed: false,
  showText: true,
  showLabel: true
})

// Agent management
const {
  agents,
  loading,
  isAllAgents,
  currentAgentName,
  selectedAgentObjects,
  toggleAgent,
  isAgentSelected,
  initAgent,
  studios,
  selectedStudio,
  selectStudio,
  initStudios,
} = useAgent()

// Connect (user credentials / OAuth) affordance for user_required agents.
const { connectingId, needsUserConnection, startConnect, asCredentialsModalSource } = useDataSourceConnect()
const showCredsModal = ref(false)
const selectedConnectDs = ref<any>(null)

async function onConnect(agent: any) {
  // OAuth-only (Entra/OBO) redirects straight to the provider; anything else
  // falls back to the credentials modal.
  const openModal = await startConnect(agent)
  if (!openModal) return
  selectedConnectDs.value = asCredentialsModalSource(agent)
  showCredsModal.value = true
}

async function onCredentialsSaved() {
  showCredsModal.value = false
  // Re-fetch so the freshly-connected agent drops its Connect chip.
  await initAgent()
}

// Returns the connection type when exactly one agent is selected (for icon display)
const singleSelectedConnection = computed(() => {
  const selected = selectedAgentObjects.value
  if (selected.length === 1) {
    return selected[0].connections?.[0]?.type || null
  }
  return null
})

// Agent hover preview
const hoveredAgentId = ref<string | null>(null)
const flyout = reactive({ visible: false, top: 0, left: 0, maxHeight: 0 })
let flyoutHideTimer: ReturnType<typeof setTimeout> | null = null

// Plan A — Studios-only selector. Raw Data Agents / "All Agents" hidden; a
// connector activates only when pinned in a Studio. Flip to restore legacy.
const STUDIOS_ONLY = true

// Display label for the trigger: studio name > pinned data-agent name > "Auto".
const contextLabel = computed(() => {
  if (selectedStudio.value) return selectedStudio.value.name
  // a Data Agent is pinned → clean short label ("Power BI") not the raw name
  if (!isAllAgents.value) {
    const objs = selectedAgentObjects.value
    if (objs.length === 1) return agentLabel(objs[0])
    return currentAgentName.value
  }
  return STUDIOS_ONLY ? 'Auto' : currentAgentName.value
})

// Real Data Agents for the picker: drop admin connector TEMPLATES (the
// is_user_template shell isn't a chattable agent) so only usable per-user
// sources (e.g. the Power BI clone) are listed.
const dataAgents = computed(() =>
  (agents.value as any[]).filter(a => !a.is_user_template)
)

// Per-connector short product names — mirrors CONNECTOR_META in the agents
// page. Keeps the row reading "Power BI" instead of the raw stored name
// "Power BI (User Sign-in) · rahulgupta@cityholdings.com.mm".
const CONNECTOR_NAMES: Record<string, string> = {
  powerbi: 'Power BI', powerbi_user: 'Power BI',
  ms_fabric: 'Microsoft Fabric', ms_fabric_user: 'Microsoft Fabric',
  sharepoint: 'SharePoint', onedrive: 'OneDrive',
}
// Product logo PNGs (DataSourceIcon has no powerbi_user/ms_fabric_user glyph →
// it falls back to a generic file icon, so use the real image like the card).
const CONNECTOR_LOGOS: Record<string, string> = {
  powerbi: '/data_sources_icons/powerbi.png', powerbi_user: '/data_sources_icons/powerbi.png',
  ms_fabric: '/data_sources_icons/ms_fabric.png', ms_fabric_user: '/data_sources_icons/ms_fabric.png',
  sharepoint: '/data_sources_icons/sharepoint.png', onedrive: '/data_sources_icons/onedrive.png',
}
function agentType(a: any): string { return a?.connections?.[0]?.type || a?.type || '' }
function agentLogo(a: any): string { return CONNECTOR_LOGOS[agentType(a)] || '' }
// Clean short label: known connector → product name; else strip the
// "(User Sign-in) · email" framing off the raw name.
function agentLabel(a: any): string {
  const t = agentType(a)
  if (CONNECTOR_NAMES[t]) return CONNECTOR_NAMES[t]
  return String(a?.name || '').split('·')[0].replace(/\(user\s*sign-?in\)/i, '').trim() || 'Data Agent'
}
// The signed-in email (stored as "<Product> · email") → initial badge.
function agentEmail(a: any): string {
  const n = String(a?.name || '')
  return n.includes('·') ? n.split('·').pop()!.trim() : (a?.owner_email || '')
}
function agentInitial(a: any): string {
  const src = agentEmail(a) || agentLabel(a)
  return (src.trim()[0] || '?').toUpperCase()
}
// Logo for the trigger when exactly one Data Agent is pinned.
const pinnedAgentLogo = computed(() => {
  const objs = selectedAgentObjects.value
  return objs.length === 1 ? agentLogo(objs[0]) : ''
})

// Auto: clear the pinned studio → agent auto-selects sources/skills per question.
function selectAuto() {
  selectStudio('')
  hideFlyoutNow()
}

// Studio hover preview (shares the same flyout position object; mutually
// exclusive with the agent flyout — only one of hoveredAgentId/hoveredStudioId
// is ever set).
const hoveredStudioId = ref<string | null>(null)
const hoveredStudioName = ref<string | null>(null)
const hoveredStudioAvatar = ref<string | null>(null)

const hideFlyoutNow = () => {
  if (flyoutHideTimer) {
    clearTimeout(flyoutHideTimer)
    flyoutHideTimer = null
  }
  flyout.visible = false
  hoveredAgentId.value = null
  hoveredStudioId.value = null
}

const onStudioHover = (s: any, evt: MouseEvent) => {
  if (flyoutHideTimer) {
    clearTimeout(flyoutHideTimer)
    flyoutHideTimer = null
  }
  hoveredAgentId.value = null
  hoveredStudioId.value = String(s.id)
  hoveredStudioName.value = s.name || null
  hoveredStudioAvatar.value = s.avatar || null
  if (typeof window !== 'undefined') showFlyoutAtEvent(evt)
}

const onStudioHoverLeave = () => {
  if (flyoutHideTimer) clearTimeout(flyoutHideTimer)
  flyoutHideTimer = setTimeout(hideFlyoutNow, 120)
}

const showFlyoutAtEvent = (evt: MouseEvent) => {
  const el = evt.currentTarget as HTMLElement | null
  if (!el) return

  // Anchor off the dropdown panel so a left-placed flyout never overlaps it.
  const panel = el.closest('.rounded-xl') as HTMLElement | null
  const panelRect = panel?.getBoundingClientRect()
  const rect = el.getBoundingClientRect()

  const flyoutWidth = 520 // matches StudioFlyout/AgentFlyout max width
  const gap = 8

  // Prefer right of the panel; flip to the left when it would overflow the
  // viewport (this picker lives at the top-right, so it usually flips left).
  let left = (panelRect?.right ?? rect.right) + gap
  if (left + flyoutWidth > window.innerWidth - 12) {
    left = (panelRect?.left ?? rect.left) - flyoutWidth - gap
  }
  left = Math.max(12, Math.min(left, window.innerWidth - flyoutWidth - 12))

  // Anchor the top to the row; clamp so it never runs off the bottom.
  const top = Math.max(12, rect.top - 8)
  flyout.left = left
  flyout.top = top
  flyout.maxHeight = Math.max(160, window.innerHeight - top - 12)
  flyout.visible = true
}

const onAgentHover = (agentId: string, evt: MouseEvent) => {
  if (flyoutHideTimer) {
    clearTimeout(flyoutHideTimer)
    flyoutHideTimer = null
  }
  if (typeof window !== 'undefined') showFlyoutAtEvent(evt)
  hoveredStudioId.value = null
  hoveredAgentId.value = agentId
}

const onAgentHoverLeave = () => {
  // Give the user time to move cursor from list → flyout
  if (flyoutHideTimer) clearTimeout(flyoutHideTimer)
  flyoutHideTimer = setTimeout(hideFlyoutNow, 120)
}

const onFlyoutEnter = () => {
  if (flyoutHideTimer) {
    clearTimeout(flyoutHideTimer)
    flyoutHideTimer = null
  }
  flyout.visible = true
}

const onFlyoutLeave = () => {
  onAgentHoverLeave()
}

const route = useRoute()
watch(() => route.fullPath, hideFlyoutNow)

onMounted(() => {
  initStudios()
  // Load Data Agents so they appear in this top-nav picker (composer already
  // fetches its own list). Without this the agents[] ref stays empty here.
  initAgent()
})

onBeforeUnmount(hideFlyoutNow)
</script>
