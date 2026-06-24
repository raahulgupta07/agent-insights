<template>
  <div>
    <!-- Fixed global onboarding banner shown above everything -->
    <div v-if="showGlobalOnboardingBanner" class="fixed top-0 start-0 end-0 z-[1000]">
      <div
        @click="router.push(showGlobalOnboardingBannerLink)"
        class="text-center cursor-pointer text-white text-sm bg-[#C2683F] hover:bg-[#A8542F] py-2 flex items-center justify-center shadow-md"
      >
        <UIcon name="i-heroicons-rocket-launch" class="h-5 me-2" />
        <span>{{ showGlobalOnboardingBannerText }}</span>
      </div>
    </div>

    <!-- Fixed app shell: the window itself never scrolls. The top bar is pinned
         (shrink-0) and a single scroll zone lives BELOW it, so content scrolls
         under the bar instead of the whole document scrolling past a sticky bar. -->
    <div class="h-screen overflow-hidden flex flex-col" :class="[showTopBanner ? 'pt-10' : '']">
      <TopNav class="shrink-0" />
      <div class="flex-1 min-h-0">
        <UNotifications />

        <!-- Report detail pages: chat-history rail + a self-bounding page that
             owns its own internal scroll → this zone must NOT scroll. -->
        <div v-if="showChatRail" class="flex h-full overflow-hidden">
          <!-- Dashboard-first mode (?focus=dashboard) hides the report-history rail
               so the board gets full width. "Switch to chat-first" drops the query
               param → this reappears. -->
          <ChatHistoryRail v-if="!dashboardFocus" />
          <div class="flex-1 min-w-0 h-full overflow-hidden">
            <slot />
          </div>
        </div>
        <!-- Every other page: one scroll container under the bar. -->
        <div v-else class="h-full overflow-y-auto">
          <slot />
        </div>
      </div>
    </div>

    <!-- Global ⌘K / Ctrl+K command palette -->
    <CommandPalette />
  </div>
</template>

<script setup lang="ts">
  import TopNav from '~/components/nav/TopNav.vue'
  import ChatHistoryRail from '~/components/nav/ChatHistoryRail.vue'
  import { useCan } from '~/composables/usePermissions'

  const route = useRoute()
  const router = useRouter()

  // Show the chat-history rail only on report detail pages (/reports/:id),
  // never on the bare /reports library list.
  const showChatRail = computed(() => /^\/reports\/[^/]+/.test(route.path))
  // Hide the report-history rail in dashboard-first mode for a full-width board.
  const dashboardFocus = computed(() => route.query.focus === 'dashboard')
  const { t } = useI18n()

  const { fetchOnboarding, onboarding } = useOnboarding()
  const { initAgent } = useAgent()

  const canModifySettings = computed(() => useCan('manage_settings'))
  // Onboarding nudge banner disabled (no "Configure your LLM" / "Connect your
  // first data source" bar). Re-enable by restoring the steps-based logic below.
  const showGlobalOnboardingBanner = computed(() => false)

  const showGlobalOnboardingBannerText = computed(() => {
    const ob = onboarding.value as any
    if (!ob) return 'Continue onboarding'
    return ob.current_step === 'llm_configured' ? 'Configure your LLM' : 'Connect your first data source'
  })

  const showGlobalOnboardingBannerLink = computed(() => {
    const ob = onboarding.value as any
    if (!ob) return '/onboarding'
    return ob.current_step === 'llm_configured' ? '/onboarding/llm' : '/onboarding/data'
  })

  // License surface removed from this fork — only the onboarding banner remains.
  const showTopBanner = computed<boolean>(() => showGlobalOnboardingBanner.value)

  onMounted(async () => {
    try {
      const inOnboarding = route.path.startsWith('/onboarding')
      if (!inOnboarding) {
        // Fetch onboarding and agents in parallel for faster load
        await Promise.all([
          fetchOnboarding({ in_onboarding: false }),
          initAgent()
        ])
      }
    } catch {}

    // Hydrate locale from org config. Runs once per full page load —
    // the user's personal choice (stored under `dash.locale`) always
    // wins; we only apply the org override when they haven't picked
    // anything. Executes here rather than in the i18n plugin because
    // useMyFetch needs the session + org state that are only ready
    // after mount.
    try {
      const stored = typeof localStorage !== 'undefined' ? localStorage.getItem('dash.locale') : null
      if (!stored) {
        const resp = await useMyFetch('/api/organization/locale')
        const body = resp.data?.value as any
        const effective = body?.effective_locale
        const setLocale = (useNuxtApp() as any).$setLocale as ((c: string) => void) | undefined
        if (effective && typeof setLocale === 'function') setLocale(effective)
      }
    } catch {
      // non-fatal; user can still pick manually via the settings picker
    }
  })
  </script>
