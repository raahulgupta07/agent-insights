<template>
  <div>
    <!-- Data source picker + type filter chips -->
    <div v-if="showPicker" class="flex items-center gap-3 mb-4">
      <label class="text-xs font-medium text-gray-500 shrink-0">Data source</label>
      <USelectMenu
        v-model="selectedDataSource"
        :options="dataSourceOptions"
        option-attribute="name"
        by="id"
        placeholder="All sources"
        size="sm"
        class="w-72"
        :loading="loadingSources"
      />
    </div>

    <!-- Type filter chips -->
    <div class="flex items-center gap-1.5 mb-5">
      <button
        v-for="f in typeFilters"
        :key="f.id"
        @click="setFilter(f.id)"
        :class="[
          'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-colors',
          activeFilter === f.id
            ? 'bg-gray-900 text-white border-gray-900'
            : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
        ]"
      >
        {{ f.label }}
        <span
          v-if="f.id !== 'all' && (stats[f.statKey] ?? 0) > 0"
          :class="[
            'inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full text-[10px] font-semibold',
            activeFilter === f.id ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'
          ]"
        >{{ stats[f.statKey] }}</span>
      </button>
    </div>

    <!-- Header: count + helper -->
    <div
      v-if="!loading && !errored && proposals.length"
      class="mb-5"
    >
      <div class="flex items-center gap-2 text-xs text-gray-500">
        <span>
          <span class="font-medium text-gray-700">{{ proposals.length }}</span>
          pending {{ proposals.length === 1 ? 'proposal' : 'proposals' }}
        </span>
        <span class="text-gray-300">&middot;</span>
        <span class="text-gray-400">AI-proposed knowledge from agent feedback. Approve to inject into the agent&rsquo;s context.</span>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading && !proposals.length" class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center">
      <Icon name="heroicons:arrow-path" class="w-5 h-5 text-gray-400 animate-spin mx-auto mb-2" />
      <p class="text-sm text-gray-500">Loading proposals&hellip;</p>
    </div>

    <!-- Unavailable (backend not ready) -->
    <div
      v-else-if="errored"
      class="rounded-lg border border-amber-100 bg-amber-50 px-6 py-10 text-center"
    >
      <Icon name="heroicons:cloud" class="w-6 h-6 text-amber-400 mx-auto mb-2" />
      <p class="text-sm text-amber-700">The review queue isn&rsquo;t available yet.</p>
      <p class="mt-1 text-xs text-amber-600">It will appear here once the knowledge service is ready.</p>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!proposals.length"
      class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center"
    >
      <div class="w-12 h-12 rounded-full bg-white border border-gray-100 flex items-center justify-center mx-auto mb-4 shadow-sm">
        <Icon name="heroicons:inbox" class="w-6 h-6 text-gray-400" />
      </div>
      <p class="text-sm text-gray-500">No pending proposals.</p>
      <p class="mt-1 text-xs text-gray-400">The agent will propose knowledge as it learns from feedback.</p>
    </div>

    <!-- Proposal cards grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div
        v-for="p in proposals"
        :key="`${p.type}-${p.id}`"
        class="rounded-lg border border-gray-200 bg-white overflow-hidden flex flex-col"
      >
        <div class="px-4 py-3 flex flex-col gap-3 flex-1">
          <!-- Header -->
          <div class="flex items-start gap-2">
            <Icon :name="typeIcon(p.type)" class="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
            <span class="text-sm font-medium text-gray-900 truncate flex-1">
              {{ p.name || p.table_name || 'Untitled proposal' }}
            </span>
            <span
              :class="[
                'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium shrink-0',
                typeClass(p.type)
              ]"
            >{{ typeLabel(p.type) }}</span>
          </div>

          <!-- Table ref -->
          <div v-if="p.table_name && p.name" class="text-xs text-gray-500">
            <Icon name="heroicons:table-cells" class="w-3.5 h-3.5 inline -mt-0.5 text-gray-400" />
            <span class="font-mono ml-1">{{ p.table_name }}</span>
          </div>

          <!-- Description / definition -->
          <p
            class="text-sm text-gray-700 whitespace-pre-line"
            :class="{ 'text-gray-400 italic': !(p.description || p.definition) }"
          >{{ p.description || p.definition || 'No description.' }}</p>

          <!-- SQL block -->
          <div v-if="p.sql_calc || p.sql_text">
            <label class="block text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">SQL</label>
            <pre class="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800 overflow-x-auto whitespace-pre-wrap break-words">{{ p.sql_calc || p.sql_text }}</pre>
          </div>

          <!-- Provenance + created at -->
          <div class="flex items-center gap-2 flex-wrap">
            <span
              v-if="p.provenance"
              class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600"
            >{{ p.provenance }}</span>
            <div v-if="p.created_at" class="text-[11px] text-gray-400">
              <Icon name="heroicons:clock" class="w-3 h-3 inline -mt-0.5" />
              <span class="ml-1">proposed {{ relativeTime(p.created_at) }}</span>
            </div>
          </div>
        </div>

        <!-- Actions -->
        <div class="border-t border-gray-100 px-3 py-2 flex items-center gap-2">
          <UButton
            size="2xs"
            variant="soft"
            color="green"
            icon="i-heroicons-check"
            :loading="actingId === proposalKey(p) && actingKind === 'approve'"
            :disabled="actingId === proposalKey(p)"
            @click="approve(p)"
          >Approve</UButton>
          <UButton
            size="2xs"
            variant="ghost"
            color="red"
            icon="i-heroicons-x-mark"
            class="ml-auto"
            :loading="actingId === proposalKey(p) && actingKind === 'reject'"
            :disabled="actingId === proposalKey(p)"
            @click="reject(p)"
          >Reject</UButton>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

interface DataSource { id: string; name: string }
type ProposalType = 'semantic' | 'metric' | 'query'
interface Proposal {
  id: string
  type: ProposalType
  name?: string
  table_name?: string
  description?: string
  definition?: string
  sql_calc?: string
  sql_text?: string
  data_source_id?: string
  created_at?: string
  source?: string | null
  owner?: string | null
  provenance?: string | null
}
interface Stats { semantic: number; metric: number; query: number; total: number }

const emit = defineEmits<{ (e: 'count', n: number): void }>()

interface Props { dataSourceId?: string }
const props = withDefaults(defineProps<Props>(), { dataSourceId: '' })
const pinnedDs = computed(() => props.dataSourceId || '')
const showPicker = computed(() => !pinnedDs.value)

const typeFilters = [
  { id: 'all', label: 'All', statKey: 'total' as keyof Stats },
  { id: 'semantic', label: 'Semantic', statKey: 'semantic' as keyof Stats },
  { id: 'metric', label: 'Metrics', statKey: 'metric' as keyof Stats },
  { id: 'query', label: 'Queries', statKey: 'query' as keyof Stats },
]

const dataSources = ref<DataSource[]>([])
const selectedDataSource = ref<DataSource | null>(null)
const loadingSources = ref(false)

const proposals = ref<Proposal[]>([])
const stats = ref<Stats>({ semantic: 0, metric: 0, query: 0, total: 0 })
const loading = ref(false)
const errored = ref(false)
const activeFilter = ref<'all' | ProposalType>('all')

const actingId = ref<string | null>(null)
const actingKind = ref<'approve' | 'reject' | null>(null)

const ALL_SOURCES: DataSource = { id: '', name: 'All sources' }
const dataSourceOptions = computed<DataSource[]>(() => [ALL_SOURCES, ...dataSources.value])
// `dataSourceId` is the ACTIVE data source: pinned (embedded) filters to that ds; otherwise the picker.
const dataSourceId = computed(() => pinnedDs.value || selectedDataSource.value?.id || '')

function proposalKey(p: Proposal): string {
  return `${p.type}-${p.id}`
}

function typeLabel(t: ProposalType): string {
  switch (t) {
    case 'semantic': return 'semantic'
    case 'metric': return 'metric'
    case 'query': return 'query'
    default: return t
  }
}

function typeClass(t: ProposalType): string {
  switch (t) {
    case 'semantic': return 'bg-[#F6EFEA] text-[#A8542F]'
    case 'metric': return 'bg-purple-50 text-purple-700'
    case 'query': return 'bg-indigo-50 text-indigo-700'
    default: return 'bg-gray-100 text-gray-600'
  }
}

function typeIcon(t: ProposalType): string {
  switch (t) {
    case 'semantic': return 'heroicons:book-open'
    case 'metric': return 'heroicons:calculator'
    case 'query': return 'heroicons:command-line'
    default: return 'heroicons:sparkles'
  }
}

function relativeTime(iso?: string): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (isNaN(then)) return ''
  const diff = Date.now() - then
  const min = Math.floor(diff / 60000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day}d ago`
  return new Date(iso).toLocaleDateString()
}

function setFilter(id: 'all' | ProposalType) {
  if (activeFilter.value === id) return
  activeFilter.value = id
  loadProposals()
}

// --- load data sources ---
async function loadDataSources() {
  if (!showPicker.value) return
  loadingSources.value = true
  try {
    const { data, error } = await useMyFetch<DataSource[]>('/data_sources', { method: 'GET' })
    if (error.value) throw error.value
    dataSources.value = (data.value as DataSource[]) || []
  } catch {
    dataSources.value = []
  } finally {
    loadingSources.value = false
  }
}

// --- load pending proposals ---
async function loadProposals() {
  loading.value = true
  errored.value = false
  try {
    const params = new URLSearchParams()
    if (activeFilter.value !== 'all') params.set('type', activeFilter.value)
    if (dataSourceId.value) params.set('data_source_id', dataSourceId.value)
    const qs = params.toString()
    const { data, error } = await useMyFetch<any>(
      `/knowledge/pending${qs ? `?${qs}` : ''}`,
      { method: 'GET' }
    )
    if (error.value) throw error.value
    const payload = data.value
    if (!payload) throw new Error('empty')
    proposals.value = (payload.proposals as Proposal[]) || []
    stats.value = {
      semantic: payload.stats?.semantic ?? 0,
      metric: payload.stats?.metric ?? 0,
      query: payload.stats?.query ?? 0,
      total: payload.stats?.total ?? proposals.value.length,
    }
    emit('count', stats.value.total)
  } catch {
    proposals.value = []
    errored.value = true
  } finally {
    loading.value = false
  }
}

function decStat(t: ProposalType) {
  if (stats.value[t] > 0) stats.value[t] -= 1
  if (stats.value.total > 0) stats.value.total -= 1
  emit('count', stats.value.total)
}

function incStat(t: ProposalType) {
  stats.value[t] += 1
  stats.value.total += 1
  emit('count', stats.value.total)
}

// --- approve / reject (optimistic, revert on error) ---
async function act(p: Proposal, kind: 'approve' | 'reject') {
  const key = proposalKey(p)
  const idx = proposals.value.findIndex(x => proposalKey(x) === key)
  if (idx === -1) return
  const removed = proposals.value[idx]

  actingId.value = key
  actingKind.value = kind
  // optimistic remove
  proposals.value.splice(idx, 1)
  decStat(removed.type)

  try {
    const { error } = await useMyFetch(`/knowledge/${p.type}/${p.id}/${kind}`, {
      method: 'POST',
    })
    if (error.value) throw error.value
  } catch {
    // revert
    proposals.value.splice(Math.min(idx, proposals.value.length), 0, removed)
    incStat(removed.type)
  } finally {
    actingId.value = null
    actingKind.value = null
  }
}

function approve(p: Proposal) {
  act(p, 'approve')
}

function reject(p: Proposal) {
  if (!confirm(`Reject this proposed ${typeLabel(p.type)}? It will not be added to the agent's context.`)) return
  act(p, 'reject')
}

watch([selectedDataSource, () => props.dataSourceId], () => loadProposals())

onMounted(async () => {
  await loadDataSources()
  await loadProposals()
})
</script>
