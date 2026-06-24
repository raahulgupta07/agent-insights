<template>
  <header
    class="sticky top-0 z-40 w-full bg-white border-b border-gray-200/80"
  >
    <nav class="flex items-center h-12 px-3 gap-2 sm:gap-3">
      <!-- Logo -->
      <button
        @click="router.push('/')"
        class="flex items-center shrink-0 p-1 rounded-md hover:bg-gray-100 transition-colors"
        :aria-label="$t('nav.home') /* falls back to key text if missing */"
      >
        <img
          :src="workspaceIconUrl || '/assets/logo-128.png'"
          alt="CityAgent"
          class="max-h-7 max-w-[120px] object-contain"
        />
      </button>

      <!-- ============ Desktop: grouped dropdown menubar ============ -->
      <div class="hidden sm:flex items-center gap-0.5">
        <UPopover
          v-for="group in visibleGroups"
          :key="group.title"
          :popper="{ placement: 'bottom-start', offsetDistance: 4 }"
          :ui="{ width: 'max-w-none' }"
        >
          <button
            :class="[
              'flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[13px] font-medium transition-colors',
              isGroupActive(group)
                ? 'text-gray-900 bg-gray-100'
                : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
            ]"
          >
            <span>{{ $t(group.title) }}</span>
            <UIcon name="heroicons-chevron-down" class="w-3.5 h-3.5 text-gray-400" />
          </button>

          <template #panel="{ close }">
            <div class="w-56 bg-white rounded-xl shadow-xl border border-gray-200 p-1.5">
              <template v-for="item in group.items" :key="item.key">
                <!-- Action item (e.g. MCP Server modal) -->
                <button
                  v-if="item.action"
                  @click="item.action(); close()"
                  class="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-start text-[13px] text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors"
                >
                  <span class="flex items-center justify-center w-[18px] h-[18px] shrink-0">
                    <UIcon v-if="item.icon" :name="item.icon" />
                    <component v-else-if="item.component" :is="item.component" class="w-[18px] h-[18px]" />
                  </span>
                  <span>{{ $t(item.label) }}</span>
                </button>
                <!-- Route item -->
                <NuxtLink
                  v-else
                  :to="item.href"
                  @click="close()"
                  :class="[
                    'w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-start text-[13px] transition-colors',
                    isRouteActive(item.activePath || item.href!)
                      ? 'text-gray-900 bg-gray-200/70 font-medium'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  ]"
                >
                  <span class="flex items-center justify-center w-[18px] h-[18px] shrink-0">
                    <UIcon v-if="item.icon" :name="item.icon" />
                    <component v-else-if="item.component" :is="item.component" class="w-[18px] h-[18px]" />
                  </span>
                  <span>{{ $t(item.label) }}</span>
                </NuxtLink>
              </template>
            </div>
          </template>
        </UPopover>
      </div>

      <!-- ============ Right cluster ============ -->
      <div class="flex items-center gap-2 sm:gap-3 ms-auto">
        <!-- Agent selector (compact). showLabel off to stay compact in the bar. -->
        <div class="w-44 sm:w-52">
          <AgentSelector :show-text="true" :show-label="false" />
        </div>

        <!-- New Report — desktop primary button -->
        <button
          name="create-report"
          @click="createNewReport"
          :disabled="creatingReport"
          class="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-md text-[13px] font-medium text-white bg-blue-500 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
        >
          <span class="flex items-center justify-center w-[18px] h-[18px]">
            <Spinner v-if="creatingReport" class="animate-spin" />
            <UIcon v-else name="heroicons-plus-circle" />
          </span>
          <span>{{ creatingReport ? $t('common.loading') : $t('nav.newReport') }}</span>
        </button>

        <!-- New Report — mobile icon -->
        <button
          @click="createNewReport"
          :disabled="creatingReport"
          class="sm:hidden flex items-center justify-center w-8 h-8 rounded-md text-white bg-blue-500 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
          :aria-label="$t('nav.newReport')"
        >
          <Spinner v-if="creatingReport" class="animate-spin w-[18px] h-[18px]" />
          <UIcon v-else name="heroicons-plus" class="w-5 h-5" />
        </button>

        <!-- User dropdown — desktop -->
        <UDropdown
          :items="userDropdownItems"
          :popper="{ placement: 'bottom-end' }"
          class="hidden sm:block"
        >
          <button
            class="flex items-center justify-center w-7 h-7 rounded-full bg-blue-500 text-white text-[11px] font-bold hover:bg-blue-600 transition-colors"
            :aria-label="$t('nav.loggedInAs', { name: currentUserName })"
          >
            {{ userInitial }}
          </button>
        </UDropdown>

        <!-- Hamburger — mobile -->
        <button
          @click="mobileOpen = true"
          class="sm:hidden flex items-center justify-center w-8 h-8 rounded-md text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors shrink-0"
          :aria-label="$t('nav.menu')"
        >
          <UIcon name="heroicons-bars-3" class="w-5 h-5" />
        </button>
      </div>
    </nav>

    <!-- ============ Mobile slide-over drawer ============ -->
    <USlideover v-model="mobileOpen" :ui="{ width: 'max-w-xs' }">
      <div class="flex flex-col h-full bg-white">
        <div class="flex items-center justify-between px-4 h-12 border-b border-gray-200/80 shrink-0">
          <img
            :src="workspaceIconUrl || '/assets/logo-128.png'"
            alt="CityAgent"
            class="max-h-7 max-w-[120px] object-contain"
          />
          <button
            @click="mobileOpen = false"
            class="flex items-center justify-center w-8 h-8 rounded-md text-gray-500 hover:text-gray-900 hover:bg-gray-100"
            :aria-label="$t('common.close')"
          >
            <UIcon name="heroicons-x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div class="flex-1 overflow-y-auto px-3 py-3">
          <!-- Groups expanded as vertical lists -->
          <div v-for="group in visibleGroups" :key="group.title" class="mb-4">
            <div class="px-2.5 pb-1">
              <span class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">{{ $t(group.title) }}</span>
            </div>
            <template v-for="item in group.items" :key="item.key">
              <button
                v-if="item.action"
                @click="item.action(); mobileOpen = false"
                class="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-start text-[13px] text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors"
              >
                <span class="flex items-center justify-center w-[18px] h-[18px] shrink-0">
                  <UIcon v-if="item.icon" :name="item.icon" />
                  <component v-else-if="item.component" :is="item.component" class="w-[18px] h-[18px]" />
                </span>
                <span>{{ $t(item.label) }}</span>
              </button>
              <NuxtLink
                v-else
                :to="item.href"
                @click="mobileOpen = false"
                :class="[
                  'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-start text-[13px] transition-colors',
                  isRouteActive(item.activePath || item.href!)
                    ? 'text-gray-900 bg-gray-200/70 font-medium'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                ]"
              >
                <span class="flex items-center justify-center w-[18px] h-[18px] shrink-0">
                  <UIcon v-if="item.icon" :name="item.icon" />
                  <component v-else-if="item.component" :is="item.component" class="w-[18px] h-[18px]" />
                </span>
                <span>{{ $t(item.label) }}</span>
              </NuxtLink>
            </template>
          </div>

          <!-- User actions (org switch + settings + logout) -->
          <div class="mt-2 pt-3 border-t border-gray-200/80">
            <div class="px-2.5 pb-1 flex items-center gap-2">
              <div class="flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-[10px] font-bold shrink-0">
                {{ userInitial }}
              </div>
              <span class="text-[13px] text-gray-700 truncate">{{ currentUserName }}</span>
            </div>
            <template v-for="(grp, gi) in userDropdownItems" :key="gi">
              <button
                v-for="(it, ii) in grp"
                :key="`${gi}-${ii}`"
                @click="it.to ? (router.push(it.to), mobileOpen = false) : (it.click?.(), mobileOpen = false)"
                :disabled="it.disabled"
                class="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-start text-[13px] text-gray-600 hover:text-gray-900 hover:bg-gray-100 disabled:opacity-50 transition-colors"
              >
                <span class="flex items-center justify-center w-[18px] h-[18px] shrink-0">
                  <UIcon v-if="it.icon" :name="it.icon" />
                </span>
                <span class="truncate">{{ it.label }}</span>
              </button>
            </template>
          </div>
        </div>
      </div>
    </USlideover>

    <!-- MCP modal (ported from default.vue) -->
    <McpModal v-if="showMcpModal" v-model="showMcpModal" />
  </header>
</template>

<script setup lang="ts">
  import Spinner from '~/components/Spinner.vue'
  import McpIcon from '~/components/icons/McpIcon.vue'
  import LibraryIcon from '~/components/icons/LibraryIcon.vue'
  import ActivityIcon from '~/components/icons/ActivityIcon.vue'
  import AgentIcon from '~/components/icons/AgentIcon.vue'
  import McpModal from '~/components/McpModal.vue'
  import AgentSelector from '~/components/AgentSelector.vue'
  import { useCan } from '~/composables/usePermissions'

  // ---- Composables (self-contained: TopNav reads its own state, no props) ----
  const route = useRoute()
  const router = useRouter()
  const { t } = useI18n()
  const { isMcpEnabled } = useOrgSettings()
  const { signOut, data: currentUser } = useAuth()
  const { organization, setOrganization } = useOrganization()
  // New report uses the live AgentSelector context (selected agents + studio).
  const { initAgent, selectedAgentObjects, selectedStudioId } = useAgent()

  const showMcpModal = ref(false)
  const mobileOpen = ref(false)
  const creatingReport = ref(false)

  // Close transient UI on navigation.
  watch(() => route.fullPath, () => {
    showMcpModal.value = false
    mobileOpen.value = false
  })

  const isAdmin = computed<boolean>(() => useCan('full_admin_access'))

  // ---- Active-state helpers ----
  const isRouteActive = (path: string) => {
    if (path === '/') return route.path === '/'
    return route.path === path || route.path.startsWith(path + '/')
  }

  // ---- Nav model -------------------------------------------------------------
  interface NavItem {
    key: string
    label: string
    href?: string
    activePath?: string
    icon?: string
    component?: any
    adminOnly?: boolean
    permission?: string
    action?: () => void
  }
  interface NavGroup {
    title: string
    items: NavItem[]
  }

  // Settings tabs + the permission each requires — mirror of layouts/settings.vue.
  // Used to deep-link the user-menu Settings entry at the first reachable tab and
  // to hide it entirely when none is reachable (matches default.vue behaviour).
  const settingsTabPermissions: { name: string; permission: string }[] = [
    { name: 'members', permission: 'view_members' },
    { name: 'models', permission: 'manage_llm' },
    { name: 'ai_settings', permission: 'manage_settings' },
    { name: 'general', permission: 'manage_settings' },
    { name: 'integrations', permission: 'manage_settings' },
    { name: 'audit', permission: 'view_audit_logs' },
    { name: 'identity-provider', permission: 'manage_identity_providers' },
    { name: 'license', permission: 'manage_settings' },
  ]
  const firstAccessibleSettingsTab = computed(() =>
    settingsTabPermissions.find(tab => useCan(tab.permission)) || null
  )

  // Full group model — hrefs/icons/labels/gating ported verbatim from default.vue.
  const allGroups = computed<NavGroup[]>(() => [
    {
      title: 'nav.workspace',
      items: [
        { key: 'studios', href: '/studios', icon: 'heroicons-film', label: 'nav.studios' },
        { key: 'reports', href: '/reports', icon: 'heroicons-chat-bubble-left-right', label: 'nav.reports' },
        { key: 'dashboards', href: '/dashboards', icon: 'heroicons-chart-bar-square', label: 'nav.dashboards' },
        { key: 'scheduled', href: '/scheduled-tasks', icon: 'heroicons-clock', label: 'nav.scheduled' },
      ],
    },
    {
      title: 'nav.build',
      items: [
        { key: 'instructions', href: '/instructions', icon: 'heroicons-cube', label: 'nav.instructions' },
        { key: 'queries', href: '/queries', component: LibraryIcon, label: 'nav.queries' },
        { key: 'knowledge', href: '/knowledge', icon: 'heroicons-academic-cap', label: 'nav.knowledge' },
      ],
    },
    {
      title: 'nav.manage',
      items: [
        { key: 'monitoring', href: '/monitoring', component: ActivityIcon, label: 'nav.monitoring', adminOnly: true },
        { key: 'evals', href: '/evals', icon: 'heroicons-check-circle', label: 'nav.evals', permission: 'manage_evals' },
        { key: 'agents', href: '/agents', component: AgentIcon, label: 'nav.dataAgents' },
        // MCP Server opens a modal rather than navigating. Shown only when the MCP
        // feature is enabled AND the user can manage settings (ported from default.vue).
        {
          key: 'mcp',
          label: 'nav.mcpServer',
          component: McpIcon,
          permission: 'manage_settings',
          action: () => { if (isMcpEnabled.value) showMcpModal.value = true },
        },
      ],
    },
  ])

  // An item shows when its permission/admin gate passes. MCP additionally requires
  // the feature to be enabled (its permission gate is checked here too).
  const itemVisible = (item: NavItem) => {
    if (item.key === 'mcp' && !isMcpEnabled.value) return false
    if (item.permission && !useCan(item.permission)) return false
    if (item.adminOnly && !isAdmin.value) return false
    return true
  }

  // Filter items per group; drop a group entirely if it has zero visible items.
  const visibleGroups = computed<NavGroup[]>(() =>
    allGroups.value
      .map(g => ({ title: g.title, items: g.items.filter(itemVisible) }))
      .filter(g => g.items.length > 0)
  )

  // A group's trigger is active when the current route matches any of its children.
  const isGroupActive = (group: NavGroup) =>
    group.items.some(it => it.href && isRouteActive(it.activePath || it.href))

  // ---- User dropdown (org switcher + settings + logout) ----------------------
  const currentUserName = computed<string>(() => {
    const user = currentUser.value as any
    return user?.name || user?.email || 'User'
  })
  const userInitial = computed<string>(() => currentUserName.value.charAt(0).toUpperCase())

  const userOrganizations = computed<any[]>(() =>
    ((currentUser.value as any)?.organizations || []) as any[]
  )

  const workspaceIconUrl = computed<string | null>(() => {
    const orgId = organization.value?.id
    const orgs = (currentUser.value as any)?.organizations || []
    const org = orgs.find((o: any) => o.id === orgId) || orgs[0]
    return org?.icon_url || null
  })

  const userDropdownItems = computed(() => {
    const groups: any[] = []
    const orgs = userOrganizations.value
    if (orgs.length > 1) {
      groups.push(
        orgs.map((org: any) => ({
          label: org.name,
          icon: org.id === organization.value?.id ? 'heroicons-check' : undefined,
          disabled: org.id === organization.value?.id,
          click: () => setOrganization(org.id),
        }))
      )
    }
    // Settings entry — only when a settings tab is reachable, deep-linked to the
    // first one the user can open (so it never bounces them to '/').
    const tab = firstAccessibleSettingsTab.value
    if (tab) {
      groups.push([{
        label: t('nav.settings'),
        icon: 'heroicons-cog-6-tooth',
        to: `/settings/${tab.name}`,
        click: () => router.push(`/settings/${tab.name}`),
      }])
    }
    groups.push([{
      label: t('auth.logout'),
      icon: 'heroicons-arrow-left',
      click: signOff,
    }])
    return groups
  })

  // ---- New report (ported verbatim from default.vue) -------------------------
  const createNewReport = async () => {
    if (creatingReport.value) return
    creatingReport.value = true

    try {
      // Use selected agents from AgentSelector, or all agents if none selected
      const dataSourceIds = selectedAgentObjects.value.map((a: any) => a.id)

      const reportBody: Record<string, any> = {
        title: 'untitled report',
        files: [],
        data_sources: dataSourceIds
      }
      // Studios: bind the new report to the active studio when one is selected so
      // the chat inherits its pinned sources + persona/instructions.
      if (selectedStudioId.value) {
        reportBody.studio_id = selectedStudioId.value
      }
      const response = await useMyFetch('/reports', {
        method: 'POST',
        body: JSON.stringify(reportBody)
      })

      if ((response as any).error?.value) {
        throw new Error('Report creation failed')
      }

      const data = ((response as any).data?.value) as any
      await router.push({ path: `/reports/${data.id}` })
    } finally {
      creatingReport.value = false
    }
  }

  async function signOff() {
    await signOut({ callbackUrl: '/' })
    window.location.href = '/'
  }

  // The AgentSelector itself inits studios; the New Report flow needs agents
  // hydrated too. Cheap + idempotent if default.vue (or another mount) already ran it.
  onMounted(() => {
    initAgent().catch(() => {})
  })
</script>
