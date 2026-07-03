<template>
  <div v-if="!isLoading && myReports.length" class="mt-12">
    <div class="flex items-center justify-between mb-[18px]">
      <!-- Output-type tabs: Reports / Dashboards / Presentations / Spreadsheets -->
      <div class="rr-tabs">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="rr-tab"
          :class="{ 'rr-tab-active': activeTab === t.key }"
          @click="activeTab = t.key"
        >
          <Icon :name="t.icon" class="w-3.5 h-3.5" />
          <span>{{ t.label }}</span>
          <span v-if="counts[t.key]" class="rr-count">{{ counts[t.key] }}</span>
        </button>
      </div>
      <NuxtLink :to="activeMeta.to" class="rr-viewall">
        View All {{ activeMeta.label }} →
      </NuxtLink>
    </div>

    <div v-if="displayed.length" class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      <RecentReportCard
        v-for="report in displayed"
        :key="report.id"
        :report="report"
        view-mode="my"
        :is-owner="report.user?.id === (currentUser as any)?.id"
      />
    </div>
    <!-- Empty state for a type with no items yet -->
    <div v-else class="rr-empty">
      No {{ activeMeta.label.toLowerCase() }} yet — ask the agent to build one, or
      <NuxtLink :to="activeMeta.to" class="rr-empty-link">open {{ activeMeta.label }}</NuxtLink>.
    </div>
  </div>

  <!-- Loading state -->
  <div v-else-if="isLoading" class="mt-12">
    <div class="flex items-center gap-2 mb-4">
      <div class="h-5 w-32 bg-gray-200 rounded animate-pulse"></div>
    </div>
    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      <div v-for="i in 4" :key="i" class="bg-gray-100 rounded-xl overflow-hidden">
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

const myReports = ref<RecentReport[]>([])
const isLoading = ref(true)
const activeTab = ref<'reports' | 'dashboards' | 'presentations' | 'spreadsheets'>('reports')

// Each tab = an output type. `mode` filters my reports by their artifact_modes;
// Reports (mode null) shows everything. `to` = the full Workspace page for that type.
const tabs = [
  { key: 'reports',       label: 'Reports',       to: '/reports',       icon: 'heroicons-chat-bubble-left-right',      mode: null },
  { key: 'dashboards',    label: 'Dashboards',    to: '/dashboards',    icon: 'heroicons-chart-bar-square',            mode: 'page' },
  { key: 'presentations', label: 'Presentations', to: '/presentations', icon: 'heroicons-presentation-chart-line',     mode: 'slides' },
  { key: 'spreadsheets',  label: 'Spreadsheets',  to: '/spreadsheets',  icon: 'heroicons-table-cells',                 mode: 'excel' },
] as const

const activeMeta = computed(() => tabs.find(t => t.key === activeTab.value) || tabs[0])

const _forMode = (mode: string | null) =>
  mode === null ? myReports.value : myReports.value.filter(r => r.artifact_modes?.includes(mode))

const counts = computed<Record<string, number>>(() => {
  const c: Record<string, number> = {}
  for (const t of tabs) c[t.key] = _forMode(t.mode).length
  return c
})

const displayed = computed(() => _forMode(activeMeta.value.mode).slice(0, 8))

const fetchReports = async () => {
  try {
    const res = await useMyFetch('/reports', { method: 'GET', query: { filter: 'my', limit: 40 } })
    if (!res.error.value && res.data.value) {
      myReports.value = (res.data.value as any).reports || []
    }
  } catch (e) {
    console.error('Failed to fetch recent reports:', e)
    myReports.value = []
  } finally {
    isLoading.value = false
  }
}

onMounted(() => { fetchReports() })
</script>

<style scoped>
.rr-tabs {
  display: inline-flex; align-items: center; gap: 6px;
  background: #EFE7DA; border-radius: 11px; padding: 4px;
  font-family: 'Hanken Grotesk', system-ui, sans-serif;
}
.rr-tab {
  border: none; cursor: pointer; background: transparent;
  display: inline-flex; align-items: center; gap: 6px;
  font-family: inherit; font-size: 14px; font-weight: 600;
  padding: 8px 14px; border-radius: 8px; color: #7A7062; transition: .15s;
}
.rr-tab-active {
  background: #FFFFFF; color: #A8330F;
  box-shadow: 0 2px 6px -2px rgba(60, 40, 20, .2);
}
.rr-count {
  font-size: 11px; font-weight: 700; line-height: 1;
  padding: 2px 6px; border-radius: 999px;
  background: #EFE7DA; color: #7A7062;
}
.rr-tab-active .rr-count { background: #FBEFE4; color: #C2541E; }
.rr-viewall {
  font-size: 14px; font-weight: 600; color: #C2541E;
  text-decoration: none; transition: color .15s;
}
.rr-viewall:hover { color: #A8330F; }
.rr-empty {
  font-size: 13px; color: #8a8073; padding: 28px 8px;
  border: 1px dashed #E0D6C7; border-radius: 12px; text-align: center;
}
.rr-empty-link { color: #C2541E; text-decoration: none; font-weight: 600; }
.rr-empty-link:hover { color: #A8330F; }
</style>
