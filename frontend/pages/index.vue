<template>
  <!-- Excel compact mode -->
  <div v-if="isExcel" class="flex flex-col h-screen bg-white">
    <div class="flex items-center justify-between p-3 border-b border-[#E9E0D3]">
      <NuxtLink to="/">
        <img :src="orgIconUrl || '/assets/logo-128.png'" alt="Dash" class="h-8 max-w-[120px] object-contain cursor-pointer" />
      </NuxtLink>
      <UDropdown :items="menuItems" :popper="{ placement: 'bottom-end' }">
        <UButton color="white" trailing-icon="i-heroicons-bars-3" />
        <template #queries="{ item }">
          <LibraryIcon class="w-4 h-4 text-[#9a958c]" />
          <span class="truncate">{{ item.label }}</span>
        </template>
        <template #monitoring="{ item }">
          <ActivityIcon class="w-4 h-4 text-[#9a958c]" />
          <span class="truncate">{{ item.label }}</span>
        </template>
        <template #mcp="{ item }">
          <McpIcon class="w-4 h-4 text-[#9a958c]" />
          <span class="truncate">{{ item.label }}</span>
        </template>
      </UDropdown>
    </div>
    <div class="flex-1 flex flex-col justify-center px-3">
      <div class="ps-4">
        <h2 class="text-2xl font-semibold tracking-tight text-[#1f2328] text-start" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ orgAIAnalystName || $t('home.title') }}</h2>
        <p class="text-base text-[#6b6b6b] text-start mt-1">
          {{ $t('home.subtitle') }}
        </p>
      </div>
      <div class="mt-4">
        <PromptBoxV2
          :textareaContent="textareaContent"
          :initialSelectedDataSources="selectedDataSources"
          :initialSelectedStudioId="selectedStudioId"
          :compact="true"
          @update:modelValue="handlePromptUpdate"
        />
      </div>
    </div>
  </div>

  <!-- Normal mode -->
  <div v-else class="home-root flex flex-col h-full overflow-y-auto bg-[#F6F1EA] relative">

    <!-- Add background div with grid -->
    <div class="absolute inset-0 pointer-events-none"
         style="background-image: linear-gradient(to right, rgb(15 23 42 / 0.04) 1px, transparent 1px),
                linear-gradient(to bottom, rgb(15 23 42 / 0.04) 1px, transparent 1px);
                background-size: 24px 24px;
                mask-image: linear-gradient(to bottom, transparent, black);
                -webkit-mask-image: linear-gradient(to bottom, transparent, black);">
    </div>
    <!-- Top bar -->
    <div class="flex justify-between items-center p-3">
        <div class="logo md:hidden">
            <img src="/assets/logo-128.png" alt="Dash" class="h-7" />
        </div>
        <div class="flex items-center gap-4 ms-auto">
            <div class="hamburger md:hidden">
                <UDropdown :items="menuItems" :popper="{ placement: 'bottom-start' }">
                    <UButton color="white" label="" trailing-icon="i-heroicons-bars-3" />
                    <template #queries="{ item }">
                      <LibraryIcon class="w-4 h-4 text-[#9a958c]" />
                      <span class="truncate">{{ item.label }}</span>
                    </template>
                    <template #monitoring="{ item }">
                      <ActivityIcon class="w-4 h-4 text-[#9a958c]" />
                      <span class="truncate">{{ item.label }}</span>
                    </template>
                    <template #mcp="{ item }">
                      <McpIcon class="w-4 h-4 text-[#9a958c]" />
                      <span class="truncate">{{ item.label }}</span>
                    </template>
                </UDropdown>
            </div>
        </div>
    </div>

    <div v-if="isLoading" class="flex flex-col items-center justify-center flex-grow py-20">
      <Spinner class="h-4 w-4 text-[#9a958c]" />
      <p class="text-sm text-[#6b6b6b] mt-2">{{ $t('common.loading') }}</p>
    </div>

    <div v-else class="flex flex-col p-4 flex-grow md:w-2/3 text-center md:mx-auto mt-14">
      <div v-if="showSetupComplete" class="mb-10">
        <div class="mx-auto max-w-xl bg-green-50 border border-green-200 text-green-800 text-sm rounded-lg px-3 py-2 flex items-center justify-center">
          <span class="me-2 flex items-center">
            <Icon name="heroicons-check" />
          </span>
          <span class="flex items-center">{{ $t('home.setupComplete') }}</span>
        </div>
      </div>
      <!-- Design hero: greeting eyebrow + Spectral headline + subtitle (replaces the big logo;
           the nav already carries the wordmark). -->
      <div class="home-hero relative">
        <div class="home-orb" />
        <p class="home-eyebrow">{{ greeting }}{{ userFirstName ? ', ' + userFirstName : '' }}</p>
        <h1 class="home-h1">What should we <span class="home-h1-em">explore</span> today?</h1>
        <p class="home-sub">{{ $t('home.subtitle') }}</p>
        <!-- idle brand wave: same motif as the running "thinking" indicator;
             fills the gap above the composer + signals the agent is ready. -->
        <div class="home-wave" aria-hidden="true">
          <svg viewBox="0 0 220 26" preserveAspectRatio="none">
            <path class="hw hw1" d="M0 13 Q22 4 44 13 T88 13 T132 13 T176 13 T220 13" stroke="#D67037" />
            <path class="hw hw2" d="M0 13 Q22 22 44 13 T88 13 T132 13 T176 13 T220 13" stroke="#C2541E" />
            <path class="hw hw3" d="M0 13 Q22 9 44 13 T88 13 T132 13 T176 13 T220 13" stroke="#A8330F" />
          </svg>
        </div>
        <p class="home-ready">{{ readyCaption }}</p>
      </div>
      <div class="w-full md:w-4/5 mx-auto mt-6 rounded-lg relative z-10">
          <PromptBoxV2
              :textareaContent="textareaContent"
              :initialSelectedDataSources="selectedDataSources"
              :initialSelectedStudioId="selectedStudioId"
              @update:modelValue="handlePromptUpdate"
          />
      </div>
      <div class="w-full mx-auto mt-0 space-x-3 space-y-3" v-if="selectedDataSources">
        <DataSourceQuestionsHome
            :data_sources="selectedDataSources"
            @update-content="updateTextarea"
        />
      </div>

      <div class="w-full mx-auto mt-4">
        <RecentReports />
      </div>

    </div>

    <!-- Existing content -->
    <div v-if="!isLoading" class="flex flex-col p-4 flex-grow md:w-1/3 md:mx-auto relative z-10">

      <div class="flex cursor-pointer flex-col text-sm w-full text-start mt-4 p-2 bg-white rounded-lg border border-[#E9E0D3] hover:shadow-md hover:border-[#E8C9B5]"
        v-if="false"
        @click="router.push('/settings/models')"
      >
        <div class="flex">
          <div class="w-4/5 pe-4">
            <p class="text-sm text-black flex ">
              <LLMProviderIcon provider="openai" class="h-3 inline-block " />
              <LLMProviderIcon provider="anthropic" class="h-2 inline-block ms-2" />
              <span class="inline-block ms-2">{{ $t('home.connectYourLLM') }}</span>
            </p>
          </div>
          <div class="w-1/5 text-end">
            <button class="">
              <UIcon name="i-heroicons-arrow-right" />
            </button>
          </div>
        </div>
      </div>

        <div
        @click="router.push('/agents')"
        class="flex hidden cursor-pointer flex-col text-sm w-full text-start mt-4 p-2 bg-white rounded-lg border border-[#E9E0D3] hover:shadow-md hover:border-[#E8C9B5]">
            <div class="flex">

                <div class="w-4/5 pe-4">
                    <p class="text-sm text-black">
                        <DataSourceIcon type="snowflake" class="h-5 inline me-2" />
                        <DataSourceIcon type="salesforce" class="h-5 inline me-2" />
                        <span v-if="useCan('create_data_source')">
                          {{ $t('home.manageIntegrations') }}
                      </span>
                      <span v-else>
                          {{ $t('home.viewIntegrations') }}
                      </span>
                    </p>
                    <!-- Existing reports list can go here -->
                </div>
                <div class="w-1/5 text-end">
                    <button class="">
                        <UIcon name="i-heroicons-arrow-right" />
                    </button>
                </div>
            </div>
        </div>


    </div>



  </div>

  <McpModal v-model="showMcpModal" />
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';
import { useExcel } from '~/composables/useExcel';
import { onMounted, nextTick } from 'vue';
import Spinner from '@/components/Spinner.vue'
import PromptBoxV2 from '~/components/prompt/PromptBoxV2.vue';
import RecentReports from '~/components/home/RecentReports.vue';
import McpModal from '~/components/McpModal.vue';
import LibraryIcon from '~/components/icons/LibraryIcon.vue';
import ActivityIcon from '~/components/icons/ActivityIcon.vue';
import McpIcon from '~/components/icons/McpIcon.vue';

import { useCan } from '~/composables/usePermissions'
import { KeyCode } from 'monaco-editor';
const router = useRouter()
const { onboarding, fetchOnboarding } = useOnboarding()
const { selectedAgentObjects, selectedStudioId } = useAgent()
const previous_reports = ref<any[]>([])
const models = ref<any[]>([])
const isLoading = ref(true)
const hasLoadedModels = ref(false)

// Use selected agents from AgentSelector as the data sources
const selectedDataSources = computed(() => selectedAgentObjects.value)
const readyCaption = computed(() => {
  const n = (selectedDataSources.value || []).length
  return n > 0 ? `ready · grounded on ${n} source${n === 1 ? '' : 's'}` : 'ready when you are'
})

const getModels = async () => {
  try {
    const response = await useMyFetch('/llm/models', {
        method: 'GET',
    });

    if (response.error.value) {
        throw new Error(`Could not fetch models: ${response.error.value}`);
    }

    const modelsData = (response.data.value as any[]) || [];
    models.value = modelsData;
    return modelsData;
  } catch (error) {
    console.error('Failed to fetch models:', error);
    models.value = [];
    throw error;
  }
}

const { signIn, signOut, data: currentUser, status, lastRefreshedAt, getSession } = useAuth()
const { organization, ensureOrganization } = useOrganization()
const orgIconUrl = computed(() => {
  const orgId = organization.value?.id
  const orgs = (currentUser.value as any)?.organizations || []
  const org = orgs.find((o: any) => o.id === orgId) || orgs[0]
  return org?.icon_url || null
})

const orgAIAnalystName = computed(() => {
  const orgId = organization.value?.id
  const orgs = (currentUser.value as any)?.organizations || []
  const org = orgs.find((o: any) => o.id === orgId) || orgs[0]
  return org?.ai_analyst_name || "City Agent Insights"
})

definePageMeta({ 
  layout: 'default',
  auth: true,
  permissions: ['view_reports']
})

// Design fonts (Spectral serif heading + Hanken Grotesk body).
useHead({
  link: [
    { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
    { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Hanken+Grotesk:wght@400;500;600;700&display=swap' },
  ],
})

// Time-of-day greeting (matches the design's eyebrow line).
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 5) return 'Working late'
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  if (h < 22) return 'Good evening'
  return 'Working late'
})
const userFirstName = computed(() => {
  const n = ((currentUser.value as any)?.name || '').trim()
  return n ? n.split(/\s+/)[0] : ''
})

const textContent = ref('')
const showOnboardingBanner = computed(() => {
  // If onboarding info not yet fetched, fallback to model/data heuristics below
  const steps = (onboarding.value as any)?.steps || {}
  const llmStatus = steps.llm_configured?.status
  const dataStatus = steps.data_source_created?.status
  // Show when not both done: (no llm and no data) OR (llm yes but data not done)
  if (llmStatus || dataStatus) {
    const llmDone = llmStatus === 'done'
    const dataDone = dataStatus === 'done'
    return !(llmDone && dataDone)
  }
  // Heuristic fallback: if no enabled models → prompt onboarding
  if (hasLoadedModels.value && models.value.filter(m => m.is_enabled).length === 0) return true
  return false
})


const { t } = useI18n()
const { isMcpEnabled } = useOrgSettings()
const isAdmin = computed<boolean>(() => useCan('full_admin_access'))

const menuItems = computed(() => {
  const main: any[] = [
    { label: t('nav.reports'), icon: 'i-heroicons-chat-bubble-left-right', to: '/reports' },
    { label: t('nav.dashboards'), icon: 'i-heroicons-chart-bar-square', to: '/dashboards' },
    { label: t('nav.scheduled'), icon: 'i-heroicons-clock', to: '/scheduled-tasks' },
    { label: t('nav.instructions'), icon: 'i-heroicons-cube', to: '/instructions' },
    { label: t('nav.queries'), slot: 'queries', to: '/queries' },
  ]
  if (isAdmin.value) {
    main.push({ label: t('nav.monitoring'), slot: 'monitoring', to: '/monitoring' })
  }
  if (useCan('manage_evals')) {
    main.push({ label: t('nav.evals'), icon: 'i-heroicons-check-circle', to: '/evals' })
  }

  const bottom: any[] = [
    { label: t('nav.dataAgents'), icon: 'i-heroicons-circle-stack', to: '/agents' },
    { label: t('nav.settings'), icon: 'i-heroicons-cog-6-tooth', to: '/settings' },
  ]
  if (isMcpEnabled.value && useCan('manage_settings')) {
    bottom.push({ label: t('nav.mcpServer'), slot: 'mcp', click: () => { showMcpModal.value = true } })
  }

  const identity: any[] = [
    { label: (currentUser.value as any)?.name, icon: 'i-heroicons-user' },
    { label: organization.value?.name, icon: 'i-heroicons-building-office' },
  ]

  return [
    main,
    bottom,
    identity,
    [{ label: t('auth.logout'), icon: 'i-heroicons-arrow-right-on-rectangle', click: () => { signOff() } }],
  ]
})

const showMcpModal = ref(false)

const { isExcel } = useExcel()

const textareaContent = ref('')

const updateTextarea = (content: string) => {
    textareaContent.value = content
}

const handlePromptUpdate = (value: string) => {
    textareaContent.value = value
}

const route = useRoute()
const showSetupComplete = computed(() => route.query.setup === 'done')

function withTimeout<T>(promise: Promise<T>, ms = 6000, label = 'request'): Promise<T | 'timeout'> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      console.warn(`${label} timed out after ${ms}ms`)
      resolve('timeout')
    }, ms)
    promise
      .then((v) => { clearTimeout(timer); resolve(v) })
      .catch((e) => { console.warn(`${label} failed:`, e); clearTimeout(timer); resolve('timeout') })
  })
}

onMounted(async () => {
  try {
    // Ensure organization is loaded first before making any API calls
    await withTimeout(ensureOrganization(), 6000, 'ensureOrganization')
    // Fetch onboarding state early for banner visibility
    try { await withTimeout(fetchOnboarding(), 6000, 'fetchOnboarding') } catch {}
    // If onboarding already started and not completed, redirect to correct step
    const ob = onboarding.value as any
    if (ob && !ob.completed && !ob.dismissed) {
      const step = ob.current_step
      if (step === 'llm_configured') router.replace('/onboarding/llm')
      else if (step === 'data_source_created') router.replace('/onboarding/data')
      else if (step === 'schema_selected') router.replace('/onboarding/data/schema')
      else if (step === 'instructions_added') router.replace('/onboarding/context')
      else router.replace('/onboarding')
      return
    }
    
    // Only proceed with API calls if organization is available
    // Note: agents are already loaded by the layout via initAgent()
    if (organization.value?.id) {
      await Promise.allSettled([
        withTimeout(getModels(), 6000, 'getModels'),
        withTimeout(getReports(), 6000, 'getReports')
      ])
    } else {
      console.warn('Organization not available, skipping API calls')
    }
  } catch (error) {
    console.error('Error during page initialization:', error)
  } finally {
    isLoading.value = false
    hasLoadedModels.value = true
  }
})

const getReports = async () => {
  try {
    const response = await useMyFetch('/reports', {
        method: 'GET',
    });

    if (response.error.value) {
        throw new Error(`Could not fetch reports: ${response.error.value}`);
    }

    const reportsData = (response.data.value as any[]) || [];
    previous_reports.value = reportsData;
    return reportsData;
  } catch (error) {
    console.error('Failed to fetch reports:', error);
    previous_reports.value = [];
    throw error;
  }
}


const subscription = computed(() => (currentUser.value as any)?.organizations?.find((org: any) => org.id === organization.value.id)?.subscription)


async function signOff() {
await signOut({ 
  callbackUrl: '/' 
})
}
</script>

<style scoped>
.home-root { font-family: 'Hanken Grotesk', system-ui, sans-serif; }
.home-hero { text-align: center; padding: 8px 0 6px; }
.home-orb {
  position: absolute; top: -28px; left: 50%; transform: translateX(-50%);
  width: 520px; max-width: 90%; height: 260px; border-radius: 50%;
  background: radial-gradient(circle, rgba(214, 112, 55, .16), transparent 68%);
  filter: blur(26px); pointer-events: none; animation: home-orb 9s ease-in-out infinite;
}
.home-eyebrow {
  position: relative; margin: 0 0 12px;
  font-size: 13px; font-weight: 600; letter-spacing: .12em;
  color: #B07A4E; text-transform: uppercase;
}
.home-h1 {
  position: relative; margin: 0 0 14px;
  font-family: 'Spectral', 'Spectral', ui-serif, Georgia, serif; font-weight: 500;
  font-size: 46px; line-height: 1.1; letter-spacing: -.02em; color: #211B14;
}
.home-h1-em { font-style: italic; color: #A8330F; }
.home-sub {
  position: relative; margin: 0 auto;
  font-size: 16.5px; color: #6E6356; max-width: 480px;
}
/* idle brand wave + readiness caption (gap-filler above the composer) */
.home-wave {
  position: relative; width: 220px; max-width: 62%; height: 24px; margin: 20px auto 0; opacity: .92;
}
.home-wave svg { width: 100%; height: 100%; display: block; overflow: visible; }
.home-wave .hw { fill: none; stroke-width: 2; stroke-linecap: round; transform-origin: center; }
.home-wave .hw1 { animation: home-wob 2.6s ease-in-out infinite; opacity: .8; }
.home-wave .hw2 { animation: home-wob 2.6s ease-in-out infinite .35s; opacity: .5; }
.home-wave .hw3 { animation: home-wob 2.6s ease-in-out infinite .7s; opacity: .32; }
@keyframes home-wob { 0%, 100% { transform: scaleY(.5); } 50% { transform: scaleY(1); } }
.home-ready {
  position: relative; margin: 9px 0 0; font-size: 12px; letter-spacing: .04em;
  color: #9A8678; text-transform: lowercase;
}
@media (prefers-reduced-motion: reduce) { .home-wave .hw { animation: none; } }
@keyframes home-orb {
  0%, 100% { transform: translateX(-50%) translateY(0) scale(1); opacity: .55; }
  50% { transform: translateX(-50%) translateY(-22px) scale(1.15); opacity: .8; }
}
@media (prefers-reduced-motion: reduce) { .home-orb { animation: none !important; } }
.gradient-glow {
    background-image: linear-gradient(45deg, #BE93C5, #7BC6CC, #DBE6F6);
    border-radius: 9999px;
    filter: blur(60px);
    height: 160px;
    left: 50%;
    pointer-events: none;
    position: absolute;
    bottom:-180px;
    transform: translate(-50%, -50%);
    transition: all 1s ease;
    width: 160px;
    z-index: 1;
    pointer-events: none;
    position: fixed;
}

@keyframes pulse {
  0% {
    transform: translate(-50%, -50%) scale(0.8);
    opacity: 0.1;
  }
  50% {
    transform: translate(-50%, -50%) scale(1);
    opacity: 0.15;
  }
  100% {
    transform: translate(-50%, -50%) scale(0.8);
    opacity: 0.1;
  }
}
</style>
