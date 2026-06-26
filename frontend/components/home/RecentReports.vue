<template>
  <div v-if="!isLoading && hasAnyReports" class="mt-12">
    <div class="flex items-center justify-between mb-[18px]">
      <!-- Segmented tab toggle (design): one filled pill for the active scope. -->
      <div class="rr-tabs">
        <button
          v-for="opt in availableOptions"
          :key="opt.value"
          class="rr-tab"
          :class="{ 'rr-tab-active': viewMode === opt.value }"
          @click="viewMode = opt.value"
        >
          {{ opt.label }}
        </button>
      </div>
      <NuxtLink to="/reports" class="rr-viewall">
        View All Reports →
      </NuxtLink>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      <RecentReportCard
        v-for="report in displayedReports"
        :key="report.id"
        :report="report"
        :view-mode="viewMode"
        :is-owner="report.user?.id === (currentUser as any)?.id"
      />
    </div>
  </div>

  <!-- Loading state -->
  <div v-else-if="isLoading" class="mt-12">
    <div class="flex items-center gap-2 mb-4">
      <div class="h-5 w-32 bg-gray-200 rounded animate-pulse"></div>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      <div
        v-for="i in 4"
        :key="i"
        class="bg-gray-100 rounded-xl overflow-hidden"
      >
        <div class="aspect-[4/3] bg-gray-200 animate-pulse"></div>
        <div class="p-3 space-y-2">
          <div class="h-4 bg-gray-200 rounded animate-pulse w-3/4"></div>
          <div class="h-3 bg-gray-200 rounded animate-pulse w-1/2"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import RecentReportCard from './RecentReportCard.vue'

interface RecentReport {
  id: string
  title?: string
  slug: string
  status: string
  user: { id: string; name?: string; email?: string }
  artifact_modes: string[]
  conversation_share_enabled: boolean
  conversation_share_token?: string
  created_at: string
}

const { data: currentUser } = useAuth()
const { organization } = useOrganization()

const orgReports = ref<RecentReport[]>([])
const myReports = ref<RecentReport[]>([])
const isLoading = ref(true)
const viewMode = ref('org')

const orgName = computed(() => organization.value?.name || 'Organization')

const hasAnyReports = computed(() => {
  return orgReports.value.length > 0 || myReports.value.length > 0
})

// Build available options based on what's available
const availableOptions = computed(() => {
  const options = []
  if (orgReports.value.length > 0) {
    options.push({ label: `${orgName.value} Reports`, value: 'org' })
  }
  if (myReports.value.length > 0) {
    options.push({ label: 'My Reports', value: 'my' })
  }
  return options
})

const selectedLabel = computed(() => {
  if (viewMode.value === 'org') return `${orgName.value} Reports`
  return 'My Reports'
})

const displayedReports = computed(() => {
  const list = viewMode.value === 'org' ? orgReports.value : myReports.value
  return list.slice(0, 8)
})

// Auto-select valid mode when data changes
watch([orgReports, myReports], () => {
  if (viewMode.value === 'org' && orgReports.value.length === 0 && myReports.value.length > 0) {
    viewMode.value = 'my'
  } else if (viewMode.value === 'my' && myReports.value.length === 0 && orgReports.value.length > 0) {
    viewMode.value = 'org'
  }
})

const fetchReports = async () => {
  try {
    // Fetch org (published) reports and my reports in parallel
    const [orgResponse, myResponse] = await Promise.all([
      useMyFetch('/reports', {
        method: 'GET',
        query: { filter: 'published', limit: 8 }
      }),
      useMyFetch('/reports', {
        method: 'GET',
        query: { filter: 'my', limit: 8 }
      })
    ])

    if (!orgResponse.error.value && orgResponse.data.value) {
      orgReports.value = (orgResponse.data.value as any).reports || []
    }
    if (!myResponse.error.value && myResponse.data.value) {
      myReports.value = (myResponse.data.value as any).reports || []
    }
  } catch (e) {
    console.error('Failed to fetch recent reports:', e)
    orgReports.value = []
    myReports.value = []
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  fetchReports()
})
</script>

<style scoped>
.rr-tabs {
  display: inline-flex; align-items: center; gap: 6px;
  background: #EFE7DA; border-radius: 11px; padding: 4px;
  font-family: 'Hanken Grotesk', system-ui, sans-serif;
}
.rr-tab {
  border: none; cursor: pointer; background: transparent;
  font-family: inherit; font-size: 14px; font-weight: 600;
  padding: 8px 15px; border-radius: 8px; color: #7A7062; transition: .15s;
}
.rr-tab-active {
  background: #FFFFFF; color: #A8330F;
  box-shadow: 0 2px 6px -2px rgba(60, 40, 20, .2);
}
.rr-viewall {
  font-size: 14px; font-weight: 600; color: #C2541E;
  text-decoration: none; transition: color .15s;
}
.rr-viewall:hover { color: #A8330F; }
</style>
