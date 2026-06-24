<template>
  <!-- Dashboards-style card-grid Knowledge page: full width, title, search,
       horizontal tabs with counts, responsive card grid. Reads the real
       /knowledge endpoints for the selected data source. The reusable
       <KnowledgePanel> (left-rail / top-tab) is kept for embeds elsewhere. -->
  <div class="px-10 py-7">
    <!-- header -->
    <div class="flex items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-gray-900">Knowledge</h1>
        <p class="mt-1 text-sm text-gray-500">Ground every answer in what your data means.</p>
      </div>
      <USelectMenu
        v-if="dataSources.length"
        v-model="selectedDs"
        :options="dataSources"
        option-attribute="name"
        by="id"
        size="sm"
        class="w-60"
        :loading="loadingSources"
      />
    </div>

    <!-- search -->
    <div class="mt-5 max-w-xl">
      <UInput
        v-model="search"
        icon="i-heroicons-magnifying-glass"
        size="lg"
        placeholder="Search knowledge…"
        :ui="{ rounded: 'rounded-xl' }"
      />
    </div>

    <!-- tabs -->
    <div class="mt-6 border-b border-gray-200 flex items-center gap-6 overflow-x-auto">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        @click="activeTab = tab.id"
        :class="[
          'pb-2 -mb-px text-sm font-medium whitespace-nowrap border-b-2 transition-colors flex items-center gap-1.5',
          activeTab === tab.id
            ? 'border-gray-900 text-gray-900'
            : 'border-transparent text-gray-500 hover:text-gray-700'
        ]"
      >
        {{ tab.label }}
        <span
          v-if="tab.count !== null"
          :class="[
            'text-xs',
            tab.id === 'review' && tab.count > 0 ? 'inline-flex items-center justify-center min-w-[18px] h-4 px-1 rounded-full bg-gray-200 text-gray-600 font-semibold' : 'text-gray-400'
          ]"
        >{{ tab.count }}</span>
      </button>
    </div>

    <!-- loading: shimmer card skeletons matching the grid -->
    <div v-if="loading" class="mt-6">
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5">
        <div v-for="i in 10" :key="i" class="rounded-xl border border-gray-200 overflow-hidden flex flex-col">
          <div class="h-28 ca-sk !rounded-none"></div>
          <div class="p-3 space-y-2">
            <div class="h-4 ca-sk w-2/3"></div>
            <div class="h-3 ca-sk w-full"></div>
            <div class="h-3 ca-sk w-4/5"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== SEMANTIC GRID ===== -->
    <div v-else-if="activeTab === 'semantic'" class="mt-6">
      <!-- Governance summary strip (Kepler Phase 1) -->
      <div v-if="gov && gov.tables > 0" class="mb-4 flex flex-wrap items-center gap-3 text-xs">
        <span class="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5">
          <span class="font-semibold text-emerald-600">{{ gov.tables }}</span><span class="text-gray-500">grounded</span>
        </span>
        <span class="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5">
          <span class="font-semibold" :class="gov.stale ? 'text-amber-600' : 'text-gray-400'">{{ gov.stale }}</span><span class="text-gray-500">stale</span>
        </span>
        <span class="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5">
          <span class="font-semibold" :class="gov.pii ? 'text-red-600' : 'text-gray-400'">{{ gov.pii }}</span><span class="text-gray-500">PII</span>
        </span>
        <span class="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5">
          <span class="font-semibold" :class="gov.unowned ? 'text-gray-700' : 'text-gray-400'">{{ gov.unowned }}</span><span class="text-gray-500">unowned</span>
        </span>
        <span v-if="govAsOf" class="ml-auto text-gray-400">Data as of {{ govAsOf }}</span>
      </div>
      <div v-if="filteredSemantic.length" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5 ca-stagger">
        <div
          v-for="t in filteredSemantic"
          :key="t.id"
          class="group rounded-xl border border-gray-200 hover:border-gray-300 hover:shadow-md hover:-translate-y-1 transition cursor-default overflow-hidden flex flex-col"
        >
          <div class="h-28 bg-gradient-to-br from-gray-50 to-gray-100 border-b border-gray-100 p-3 flex flex-col justify-between">
            <div class="flex items-start justify-between gap-1.5">
              <span :class="['text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded', statusClass(t.status)]">{{ t.status || 'draft' }}</span>
              <span v-if="t.pii" class="text-[9.5px] font-semibold tracking-wide px-1.5 py-0.5 rounded bg-red-50 text-red-600">PII</span>
            </div>
            <div class="font-mono text-[11px] text-gray-400 leading-tight truncate">{{ (t.columns || []).length }} columns</div>
          </div>
          <div class="p-3 flex-1 flex flex-col">
            <div class="text-sm font-semibold text-gray-900 truncate">{{ t.table_name }}</div>
            <p class="mt-1 text-xs text-gray-500 line-clamp-3 flex-1">{{ t.description || 'No description yet.' }}</p>
            <div v-if="(t.use_cases || []).length" class="mt-2 flex flex-wrap gap-1.5">
              <span v-for="(u, i) in (t.use_cases || []).slice(0, 2)" :key="i" class="text-[11px] px-2 py-0.5 rounded bg-gray-100 text-gray-600 truncate max-w-full">{{ u }}</span>
            </div>
            <div v-if="t.owner || t.freshness_sla_hours" class="mt-2 flex items-center gap-2 text-[10.5px] text-gray-400">
              <span v-if="t.owner" class="inline-flex items-center gap-1 truncate"><span class="inline-flex h-4 w-4 items-center justify-center rounded-full bg-gradient-to-br from-[#c2683f] to-[#dd9269] text-[7px] font-bold text-white">{{ ownerInitials(t.owner) }}</span>{{ t.owner }}</span>
              <span v-if="t.freshness_sla_hours" class="inline-flex items-center gap-1"><span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>SLA {{ t.freshness_sla_hours }}h</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="mt-2 rounded-xl border border-dashed border-gray-200 px-6 py-16 text-center text-sm text-gray-400">{{ emptyLabel('semantic') }}</div>
    </div>

    <!-- ===== METRICS GRID ===== -->
    <div v-else-if="activeTab === 'metrics'" class="mt-6">
      <div v-if="filteredMetrics.length" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5 ca-stagger">
        <div
          v-for="m in filteredMetrics"
          :key="m.id"
          class="group rounded-xl border border-gray-200 hover:border-gray-300 hover:shadow-md hover:-translate-y-1 transition overflow-hidden flex flex-col"
        >
          <div class="h-28 bg-gradient-to-br from-indigo-50 to-blue-50 border-b border-gray-100 p-3 flex flex-col justify-between">
            <span :class="['self-start text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded', statusClass(m.status)]">{{ m.status || 'draft' }}</span>
            <div class="font-mono text-[11px] text-indigo-400 leading-tight line-clamp-2">{{ m.sql_calc }}</div>
          </div>
          <div class="p-3 flex-1 flex flex-col">
            <div class="text-sm font-semibold text-gray-900 truncate">{{ m.name }}</div>
            <p class="mt-1 text-xs text-gray-500 line-clamp-3 flex-1">{{ m.definition || 'No definition yet.' }}</p>
            <div v-if="m.table_ref" class="mt-2 flex items-center gap-1.5">
              <span class="text-[11px] px-2 py-0.5 rounded bg-gray-100 text-gray-600">{{ m.table_ref }}</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="mt-2 rounded-xl border border-dashed border-gray-200 px-6 py-16 text-center text-sm text-gray-400">{{ emptyLabel('metrics') }}</div>
    </div>

    <!-- ===== QUERIES GRID ===== -->
    <div v-else-if="activeTab === 'queries'" class="mt-6">
      <div v-if="filteredQueries.length" class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-5 ca-stagger">
        <div
          v-for="q in filteredQueries"
          :key="q.id"
          class="group rounded-xl border border-gray-200 hover:border-gray-300 hover:shadow-md hover:-translate-y-1 transition overflow-hidden flex flex-col"
        >
          <div class="h-28 bg-gradient-to-br from-emerald-50 to-teal-50 border-b border-gray-100 p-3 flex flex-col justify-between">
            <span :class="['self-start text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded', statusClass(q.status)]">{{ q.status || 'draft' }}</span>
            <div class="font-mono text-[11px] text-emerald-500 leading-tight line-clamp-3">{{ q.sql_text }}</div>
          </div>
          <div class="p-3 flex-1 flex flex-col">
            <div class="text-sm font-semibold text-gray-900 truncate">{{ q.name }}</div>
            <p class="mt-1 text-xs text-gray-500 line-clamp-2 flex-1">{{ q.description || '—' }}</p>
            <div class="mt-2 flex items-center justify-between">
              <div class="flex flex-wrap gap-1.5">
                <span v-for="(tg, i) in (q.tags || []).slice(0, 2)" :key="i" class="text-[11px] px-2 py-0.5 rounded bg-gray-100 text-gray-600">{{ tg }}</span>
              </div>
              <span class="text-[11px] text-gray-400 shrink-0">{{ q.run_count || 0 }} runs</span>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="mt-2 rounded-xl border border-dashed border-gray-200 px-6 py-16 text-center text-sm text-gray-400">{{ emptyLabel('queries') }}</div>
    </div>

    <!-- ===== ASSETS / REVIEW: reuse existing tab components ===== -->
    <div v-else-if="activeTab === 'assets'" class="mt-6">
      <AssetsTab :dataSourceId="selectedDs?.id || ''" />
    </div>
    <div v-else-if="activeTab === 'review'" class="mt-6">
      <ReviewTab :dataSourceId="selectedDs?.id || ''" @count="reviewCount = $event" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

definePageMeta({ auth: true, layout: 'default' })

interface DataSource { id: string; name: string }

const dataSources = ref<DataSource[]>([])
const selectedDs = ref<DataSource | null>(null)
const loadingSources = ref(false)

const activeTab = ref<'semantic' | 'metrics' | 'queries' | 'assets' | 'review'>('semantic')
const search = ref('')
const loading = ref(false)

const semantic = ref<any[]>([])
const metrics = ref<any[]>([])
const queries = ref<any[]>([])
const reviewCount = ref(0)

// Governance rollup (Kepler Phase 1)
const gov = ref<{ tables: number; stale: number; pii: number; unowned: number } | null>(null)
const govAsOf = ref('')
function ownerInitials(name?: string) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
  if (!parts.length) return '?'
  return (parts[0][0] + (parts[1]?.[0] || '')).toUpperCase()
}

const tabs = computed(() => [
  { id: 'semantic', label: 'Semantic', count: semantic.value.length },
  { id: 'metrics', label: 'Metrics', count: metrics.value.length },
  { id: 'queries', label: 'Queries', count: queries.value.length },
  { id: 'assets', label: 'Assets', count: null },
  { id: 'review', label: 'Review', count: reviewCount.value },
])

function statusClass(s?: string) {
  if (s === 'approved') return 'bg-green-100 text-green-700'
  if (s === 'pending') return 'bg-yellow-100 text-yellow-700'
  if (s === 'rejected') return 'bg-red-100 text-red-600'
  return 'bg-gray-100 text-gray-500'
}

function matches(...fields: (string | undefined)[]) {
  const q = search.value.trim().toLowerCase()
  if (!q) return true
  return fields.some(f => (f || '').toLowerCase().includes(q))
}

const filteredSemantic = computed(() => semantic.value.filter(t => matches(t.table_name, t.description)))
const filteredMetrics = computed(() => metrics.value.filter(m => matches(m.name, m.definition, m.table_ref)))
const filteredQueries = computed(() => queries.value.filter(q => matches(q.name, q.description, (q.tags || []).join(' '))))

function emptyLabel(tab: string) {
  if (!selectedDs.value) return 'Connect a data source to build knowledge.'
  if (search.value.trim()) return `No ${tab} match “${search.value.trim()}”.`
  return `No ${tab} yet for ${selectedDs.value.name}.`
}

async function loadSources() {
  loadingSources.value = true
  try {
    const { data } = await useMyFetch<DataSource[]>('/data_sources', { method: 'GET' })
    dataSources.value = (data.value as DataSource[]) || []
    if (dataSources.value.length && !selectedDs.value) selectedDs.value = dataSources.value[0]
  } finally {
    loadingSources.value = false
  }
}

async function loadAll() {
  const ds = selectedDs.value?.id
  if (!ds) { semantic.value = []; metrics.value = []; queries.value = []; return }
  loading.value = true
  try {
    const [sem, met, qry] = await Promise.all([
      useMyFetch<any>(`/knowledge/semantic?data_source_id=${encodeURIComponent(ds)}`, { method: 'GET' }),
      useMyFetch<any>(`/knowledge/metrics?data_source_id=${encodeURIComponent(ds)}`, { method: 'GET' }),
      useMyFetch<any>(`/knowledge/queries?data_source_id=${encodeURIComponent(ds)}`, { method: 'GET' }),
    ])
    semantic.value = (sem.data.value?.tables as any[]) || []
    metrics.value = (met.data.value?.metrics as any[]) || []
    queries.value = (qry.data.value?.queries as any[]) || []
  } catch {
    semantic.value = []; metrics.value = []; queries.value = []
  } finally {
    loading.value = false
  }
  loadGovernance()
}

async function loadGovernance() {
  const ds = selectedDs.value?.id
  if (!ds) { gov.value = null; govAsOf.value = ''; return }
  try {
    const { data } = await useMyFetch<any>(`/knowledge/governance/${encodeURIComponent(ds)}`, { method: 'GET' })
    const g = data.value || {}
    gov.value = { tables: g.tables || 0, stale: g.stale || 0, pii: g.pii || 0, unowned: g.unowned || 0 }
    govAsOf.value = g.data_as_of ? String(g.data_as_of).slice(0, 10) : ''
  } catch {
    gov.value = null; govAsOf.value = ''
  }
}

watch(selectedDs, () => loadAll())

onMounted(async () => {
  await loadSources()
  await loadAll()
})
</script>
