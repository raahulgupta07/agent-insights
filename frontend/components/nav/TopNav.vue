<template>
  <header
    class="cag-nav sticky top-0 z-40 w-full"
  >
    <nav class="flex items-center h-14 px-4 sm:px-6 gap-3 sm:gap-5 w-full">
      <!-- Logo — design gradient mark + wordmark -->
      <button
        @click="router.push('/')"
        class="flex items-center gap-[11px] shrink-0 pe-1"
        :aria-label="$t('nav.home') /* falls back to key text if missing */"
      >
        <span class="cag-mark">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="#fff" stroke-width="2" opacity=".55"/><path d="M12 3a9 9 0 0 1 0 18" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/><circle cx="12" cy="12" r="2.6" fill="#fff"/></svg>
        </span>
        <span class="cag-word">City Agent <span class="cag-word-em">Insights</span></span>
      </button>

      <!-- ============ Desktop: group tabs (no dropdowns) ============
           Each group is a single link. Clicking it routes to the group's first
           page; the contextual left rail (AppRail) then lists that group's items.
           Agent Studios is a direct standalone tab (no rail). -->
      <div class="hidden sm:flex items-center gap-[18px] ms-1">
        <template v-for="group in visibleGroups" :key="group.title">
          <NuxtLink
            :to="group.direct || firstHref(group) || '/'"
            :class="[
              'flex items-center gap-1 text-[14px] transition-colors whitespace-nowrap',
              isGroupActive(group)
                ? 'text-[#A8330F] font-semibold'
                : 'text-[#574E44] font-medium hover:text-[#A8330F]'
            ]"
          >
            <span>{{ $t(group.title) }}</span>
          </NuxtLink>
        </template>
      </div>

      <!-- ============ Right cluster ============ -->
      <div class="flex items-center gap-2 sm:gap-3 ms-auto">
        <!-- Agent selector (compact). showLabel off to stay compact in the bar. -->
        <div class="w-44 sm:w-52">
          <AgentSelector :show-text="true" :show-label="false" />
        </div>

        <!-- New Report — desktop primary button -->
        <button
          v-if="!isReportPage"
          name="create-report"
          @click="createNewReport"
          :disabled="creatingReport"
          class="hidden sm:flex items-center gap-2 px-[15px] py-2 rounded-[10px] text-[13.5px] font-semibold text-[#A8330F] bg-[#FCFAF6] border border-[#E4C9B6] hover:bg-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
        >
          <span class="flex items-center justify-center w-[18px] h-[18px]">
            <Spinner v-if="creatingReport" class="animate-spin" />
            <UIcon v-else name="heroicons-plus-circle" />
          </span>
          <span>{{ creatingReport ? $t('common.loading') : $t('nav.newReport') }}</span>
        </button>

        <!-- New Report — mobile icon -->
        <button
          v-if="!isReportPage"
          @click="createNewReport"
          :disabled="creatingReport"
          class="sm:hidden flex items-center justify-center w-8 h-8 rounded-md text-white bg-[#C2541E] hover:bg-[#A8330F] disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
          :aria-label="$t('nav.newReport')"
        >
          <Spinner v-if="creatingReport" class="animate-spin w-[18px] h-[18px]" />
          <UIcon v-else name="heroicons-plus" class="w-5 h-5" />
        </button>

        <!-- Install as desktop app (PWA) — only shows when installable -->
        <InstallApp />

        <!-- What's new (changelog) — bell before profile -->
        <WhatsNew class="hidden sm:block" />

        <!-- User dropdown — desktop -->
        <UDropdown
          :items="userDropdownItems"
          :popper="{ placement: 'bottom-end' }"
          class="hidden sm:block"
        >
          <button
            class="cag-avatar flex items-center justify-center w-[38px] h-[38px] rounded-full text-white text-[14px] font-semibold transition-transform hover:scale-105"
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
              <!-- Expandable item (Settings → sub-tabs) -->
              <template v-if="item.children">
                <button
                  @click="toggleExpand(item.key)"
                  class="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-start text-[13px] text-gray-600 hover:text-gray-900 hover:bg-gray-100 transition-colors"
                >
                  <span class="flex items-center justify-center w-[18px] h-[18px] shrink-0">
                    <UIcon v-if="item.icon" :name="item.icon" />
                  </span>
                  <span class="flex-1">{{ $t(item.label) }}</span>
                  <UIcon
                    name="heroicons-chevron-right"
                    :class="['w-3.5 h-3.5 text-gray-400 transition-transform', expandedKey === item.key ? 'rotate-90' : '']"
                  />
                </button>
                <div v-if="expandedKey === item.key" class="ms-3.5 ps-2 border-s border-gray-100 mt-0.5 mb-1 space-y-0.5">
                  <NuxtLink
                    v-for="child in item.children"
                    :key="child.key"
                    :to="child.href"
                    @click="mobileOpen = false"
                    :class="[
                      'w-full flex items-center px-2.5 py-2 rounded-md text-start text-[13px] transition-colors',
                      isRouteActive(child.href!)
                        ? 'text-gray-900 bg-gray-200/70 font-medium'
                        : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                    ]"
                  >
                    <span>{{ $t(child.label) }}</span>
                  </NuxtLink>
                </div>
              </template>
              <button
                v-else-if="item.action"
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
              <div class="flex items-center justify-center w-6 h-6 rounded-full bg-[#5B6470] text-white text-[10px] font-bold shrink-0">
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
  import McpModal from '~/components/McpModal.vue'
  import AgentSelector from '~/components/AgentSelector.vue'
  import WhatsNew from '~/components/nav/WhatsNew.vue'
  import InstallApp from '~/components/nav/InstallApp.vue'
  import { useCan } from '~/composables/usePermissions'

  // ---- Composables (self-contained: TopNav reads its own state, no props) ----
  // Design fonts (Spectral serif + Hanken Grotesk) — loaded here so they're
  // available app-wide (TopNav mounts on every authed page).
  useHead({
    link: [
      { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
      { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
      { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Hanken+Grotesk:wght@400;500;600;700&display=swap' },
    ],
  })

  const route = useRoute()
  // Hide "New Report" on a report route — that page's ChatHistoryRail already
  // owns a "+ New chat" button, so the top-bar button is redundant there.
  const isReportPage = computed(() => /^\/reports\/[^/]+/.test(route.path))
  const router = useRouter()
  const { t } = useI18n()
  const { signOut, data: currentUser } = useAuth()
  const { organization, setOrganization } = useOrganization()
  // New report uses the live AgentSelector context (selected agents + studio).
  const { initAgent, selectedAgentObjects, selectedStudioId } = useAgent()

  // Nav model (groups, active-state helpers, MCP modal) — shared with AppRail.
  const {
    visibleGroups,
    isRouteActive,
    isGroupActive,
    firstHref,
    showMcpModal,
    loadDomainPacksFlag,
  } = useAppNav()

  const mobileOpen = ref(false)
  const creatingReport = ref(false)

  // Close transient UI on navigation.
  watch(() => route.fullPath, () => {
    showMcpModal.value = false
    mobileOpen.value = false
  })

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
  ]
  const firstAccessibleSettingsTab = computed(() =>
    settingsTabPermissions.find(tab => useCan(tab.permission)) || null
  )

  // Mobile drawer: which group is expanded (one at a time). Desktop has no
  // dropdowns anymore — groups route directly and AppRail shows the items.
  const expandedKey = ref<string | null>(null)
  const toggleExpand = (key: string) => {
    expandedKey.value = expandedKey.value === key ? null : key
  }

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

  // ---- New report (LAZY creation) --------------------------------------------
  // Do NOT create a DB row here. Navigate to the blank composer at /reports/new;
  // the report is created on first message submit. creatingReport stays false.
  const createNewReport = async () => {
    await router.push('/reports/new')
  }

  async function signOff() {
    await signOut({ callbackUrl: '/' })
    window.location.href = '/'
  }

  // The AgentSelector itself inits studios; the New Report flow needs agents
  // hydrated too. Cheap + idempotent if default.vue (or another mount) already ran it.
  onMounted(() => {
    initAgent().catch(() => {})
    loadDomainPacksFlag()
  })
</script>

<style scoped>
.cag-nav {
  background: rgba(246, 241, 234, .82);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  border-bottom: 1px solid #E9E0D3;
  font-family: 'Hanken Grotesk', system-ui, sans-serif;
}
.cag-mark {
  width: 34px; height: 34px; border-radius: 9px;
  background: linear-gradient(150deg, #D67037, #A8330F);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 5px 14px -5px rgba(168, 51, 15, .6);
  flex-shrink: 0;
}
.cag-word {
  font-size: 15.5px; font-weight: 600; letter-spacing: -.01em;
  color: #1A1611; white-space: nowrap;
}
.cag-word-em { color: #C2541E; }
.cag-avatar { background: linear-gradient(150deg, #3A332B, #1A1611); }
</style>
