<template>
  <div>
    <!-- Fixed global onboarding banner shown above everything -->
    <div v-if="showGlobalOnboardingBanner" class="fixed top-0 start-0 end-0 z-[1000]">
      <div
        @click="router.push(showGlobalOnboardingBannerLink)"
        class="text-center cursor-pointer text-white text-sm bg-blue-500/95 hover:bg-blue-600/90 py-2 flex items-center justify-center shadow-md"
      >
        <UIcon name="i-heroicons-rocket-launch" class="h-5 me-2" />
        <span>{{ showGlobalOnboardingBannerText }}</span>
      </div>
    </div>

    <!-- License expiry countdown banner (shown in the last 30 days, and after expiry) -->
    <div v-if="showLicenseBanner" class="fixed top-0 start-0 end-0 z-[1000]">
      <div
        :class="[
          'text-center text-sm py-2 px-4 flex items-center justify-center gap-2 shadow-md',
          licenseExpired
            ? 'bg-red-600/95 text-white'
            : 'bg-amber-500/95 text-white',
          canModifySettings ? 'cursor-pointer hover:opacity-95' : ''
        ]"
        @click="canModifySettings ? router.push('/settings/license') : null"
      >
        <UIcon :name="licenseExpired ? 'i-heroicons-exclamation-circle' : 'i-heroicons-exclamation-triangle'" class="h-5 shrink-0" />
        <span>{{ licenseBannerText }}</span>
        <span v-if="canModifySettings" class="underline underline-offset-2 font-medium ms-1">
          {{ $t('settings.licensePage.banner.viewLicense') }}
        </span>
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
          <ChatHistoryRail />
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
  const { t } = useI18n()

  const { fetchOnboarding, onboarding } = useOnboarding()
  const { initAgent } = useAgent()

  const canModifySettings = computed(() => useCan('manage_settings'))
  const showGlobalOnboardingBanner = computed(() => {
    if (!canModifySettings.value) return false
    const ob = onboarding.value as any

    if (!ob) return false
    //if (ob.dismissed) return false
    const steps = ob.steps || {}
    const llmDone = steps.llm_configured?.status === 'done'
    const dataDone = steps.data_source_created?.status === 'done'
    return !(llmDone && dataDone)
  })

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

  // License expiry countdown banner. Shown to everyone (an expired license affects the
  // whole org), but only admins get the clickable link to the license settings page.
  const { isExpired: licenseExpired, isExpiringSoon, daysUntilExpiry } = useEnterprise()
  const showLicenseBanner = computed<boolean>(() => {
    // Never stack on top of the onboarding banner — they share the same fixed slot,
    // and a brand-new org won't have a near-expiry enterprise license anyway.
    if (showGlobalOnboardingBanner.value) return false
    return licenseExpired.value || isExpiringSoon.value
  })
  // Either fixed top banner pushes the content down by the same amount.
  const showTopBanner = computed<boolean>(() => showGlobalOnboardingBanner.value || showLicenseBanner.value)
  const licenseBannerText = computed<string>(() => {
    if (licenseExpired.value) return t('settings.licensePage.banner.expired')
    return t('settings.licensePage.banner.expiring', { days: daysUntilExpiry.value ?? 0 })
  })

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
    // the user's personal choice (stored under `bow.locale`) always
    // wins; we only apply the org override when they haven't picked
    // anything. Executes here rather than in the i18n plugin because
    // useMyFetch needs the session + org state that are only ready
    // after mount.
    try {
      const stored = typeof localStorage !== 'undefined' ? localStorage.getItem('bow.locale') : null
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
