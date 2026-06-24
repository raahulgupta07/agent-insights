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

    <!-- ===== JOINS ===== -->
    <div v-else-if="activeTab === 'joins'" class="mt-6">
      <!-- action bar -->
      <div class="mb-4 flex items-center justify-between gap-3">
        <p class="text-xs text-gray-500">Learned join paths between your tables — inferred from proven SQL and reviewed before grounding the agent.</p>
        <button
          v-if="selectedDs"
          @click="mineJoins"
          :disabled="mining"
          class="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60 disabled:cursor-not-allowed transition"
        >
          <span v-if="mining" class="h-3 w-3 rounded-full border-2 border-gray-300 border-t-gray-600 animate-spin"></span>
          <span v-else class="i-heroicons-sparkles h-3.5 w-3.5"></span>
          {{ mining ? 'Mining…' : 'Mine joins' }}
        </button>
      </div>

      <div v-if="filteredJoins.length" class="rounded-xl border border-gray-200 overflow-hidden divide-y divide-gray-100">
        <div
          v-for="j in filteredJoins"
          :key="j.id"
          class="flex items-center gap-3 px-4 py-3 hover:bg-gray-50/70 transition"
        >
          <div class="flex-1 min-w-0">
            <div class="font-mono text-sm text-gray-800 truncate">
              <span class="text-gray-900">{{ j.left_table }}</span><span class="text-gray-400">.</span><span class="text-indigo-600">{{ j.left_col }}</span>
              <span class="mx-1.5 text-gray-400">=</span>
              <span class="text-gray-900">{{ j.right_table }}</span><span class="text-gray-400">.</span><span class="text-indigo-600">{{ j.right_col }}</span>
            </div>
            <div class="mt-1 flex items-center gap-2 text-[11px] text-gray-400">
              <span v-if="j.source" class="uppercase tracking-wide">{{ j.source }}</span>
              <span v-if="j.confidence">· {{ Math.round((j.confidence || 0) * 100) }}% conf</span>
            </div>
          </div>
          <span class="text-[11px] px-2 py-0.5 rounded bg-gray-100 text-gray-600 shrink-0">seen {{ j.join_count || 0 }}×</span>
          <span :class="['text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded shrink-0', statusClass(j.status)]">{{ j.status || 'pending' }}</span>
          <div v-if="j.status === 'pending'" class="flex items-center gap-1.5 shrink-0">
            <button @click="approveJoin(j.id)" class="rounded-md px-2 py-1 text-[11px] font-medium text-green-700 bg-green-50 hover:bg-green-100 transition">Approve</button>
            <button @click="rejectJoin(j.id)" class="rounded-md px-2 py-1 text-[11px] font-medium text-red-600 bg-red-50 hover:bg-red-100 transition">Reject</button>
          </div>
        </div>
      </div>
      <div v-else class="mt-2 rounded-xl border border-dashed border-gray-200 px-6 py-16 text-center text-sm text-gray-400">
        No joins inferred yet. Run 'Mine joins' or let the daemon learn from query history.
      </div>
    </div>

    <!-- ===== DOCS ===== -->
    <div v-else-if="activeTab === 'docs'" class="mt-6">
      <!-- action bar -->
      <div class="mb-4 flex items-center justify-between gap-3">
        <p class="text-xs text-gray-500">Approved company documents ground the agent on business terms and definitions.</p>
        <button
          @click="showAddDoc = !showAddDoc"
          class="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 cursor-pointer transition"
        >
          <span class="i-heroicons-plus h-3.5 w-3.5"></span>
          {{ showAddDoc ? 'Close' : 'Add doc' }}
        </button>
      </div>

      <!-- inline add-doc form -->
      <div v-if="showAddDoc" class="mb-5 rounded-xl border border-gray-200 bg-gray-50/60 p-4 space-y-3">
        <input
          v-model="docTitle"
          type="text"
          placeholder="Title"
          class="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-gray-400 transition"
        />
        <textarea
          v-model="docBody"
          rows="6"
          placeholder="Paste the document body here…"
          class="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:border-gray-400 transition resize-y"
        ></textarea>
        <div class="flex items-center justify-end gap-2">
          <button
            @click="addDoc"
            :disabled="savingDoc || !docTitle.trim()"
            class="inline-flex items-center gap-1.5 rounded-lg border border-gray-900 bg-gray-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-800 disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer transition"
          >
            <span v-if="savingDoc" class="h-3 w-3 rounded-full border-2 border-gray-400 border-t-white animate-spin"></span>
            {{ savingDoc ? 'Saving…' : 'Save' }}
          </button>
        </div>
      </div>

      <div v-if="docs.length" class="rounded-xl border border-gray-200 overflow-hidden divide-y divide-gray-100">
        <div
          v-for="d in docs"
          :key="d.id"
          class="flex items-center gap-3 px-4 py-3 hover:bg-gray-50/70 transition"
        >
          <div class="flex-1 min-w-0">
            <div class="text-sm font-semibold text-gray-900 truncate">{{ d.title }}</div>
            <div class="mt-1 flex items-center gap-2 text-[11px] text-gray-400">
              <span v-if="d.source" class="uppercase tracking-wide">{{ d.source }}</span>
              <span>· {{ d.chunks || 0 }} chunks</span>
            </div>
          </div>
          <span :class="['text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded shrink-0', statusClass(d.status)]">{{ d.status || 'pending' }}</span>
          <div v-if="d.status === 'pending'" class="flex items-center gap-1.5 shrink-0">
            <button @click="approveDoc(d.id)" class="rounded-md px-2 py-1 text-[11px] font-medium text-green-700 bg-green-50 hover:bg-green-100 cursor-pointer transition">Approve</button>
            <button @click="rejectDoc(d.id)" class="rounded-md px-2 py-1 text-[11px] font-medium text-red-600 bg-red-50 hover:bg-red-100 cursor-pointer transition">Reject</button>
          </div>
        </div>
      </div>
      <div v-else class="mt-2 rounded-xl border border-dashed border-gray-200 px-6 py-16 text-center text-sm text-gray-400">
        No documents yet. Add one to ground the agent on your business terms.
      </div>
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

const activeTab = ref<'semantic' | 'metrics' | 'queries' | 'joins' | 'docs' | 'assets' | 'review'>('semantic')
const search = ref('')
const loading = ref(false)

const semantic = ref<any[]>([])
const metrics = ref<any[]>([])
const queries = ref<any[]>([])
const joins = ref<any[]>([])
const mining = ref(false)
const docs = ref<any[]>([])
const showAddDoc = ref(false)
const docTitle = ref('')
const docBody = ref('')
const savingDoc = ref(false)
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
  { id: 'joins', label: 'Joins', count: joins.value.length },
  { id: 'docs', label: 'Docs', count: docs.value.length },
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
const filteredJoins = computed(() => joins.value.filter(j => matches(j.left_table, j.left_col, j.right_table, j.right_col)))

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
  if (!ds) { semantic.value = []; metrics.value = []; queries.value = []; joins.value = []; loadDocs(); return }
  loading.value = true
  try {
    const [sem, met, qry, jns] = await Promise.all([
      useMyFetch<any>(`/knowledge/semantic?data_source_id=${encodeURIComponent(ds)}`, { method: 'GET' }),
      useMyFetch<any>(`/knowledge/metrics?data_source_id=${encodeURIComponent(ds)}`, { method: 'GET' }),
      useMyFetch<any>(`/knowledge/queries?data_source_id=${encodeURIComponent(ds)}`, { method: 'GET' }),
      useMyFetch<any>(`/knowledge/joins?data_source_id=${encodeURIComponent(ds)}`, { method: 'GET' }),
    ])
    semantic.value = (sem.data.value?.tables as any[]) || []
    metrics.value = (met.data.value?.metrics as any[]) || []
    queries.value = (qry.data.value?.queries as any[]) || []
    joins.value = (jns.data.value?.edges as any[]) || []
  } catch {
    semantic.value = []; metrics.value = []; queries.value = []; joins.value = []
  } finally {
    loading.value = false
  }
  loadGovernance()
  loadDocs()
}

async function loadJoins() {
  const ds = selectedDs.value?.id
  if (!ds) { joins.value = []; return }
  try {
    const { data } = await useMyFetch<any>(`/knowledge/joins?data_source_id=${encodeURIComponent(ds)}`, { method: 'GET' })
    joins.value = (data.value?.edges as any[]) || []
  } catch {
    joins.value = []
  }
}

async function mineJoins() {
  const ds = selectedDs.value?.id
  if (!ds || mining.value) return
  mining.value = true
  try {
    await useMyFetch<any>('/knowledge/joins/mine', { method: 'POST', body: { data_source_id: ds } })
    await loadJoins()
  } finally {
    mining.value = false
  }
}

async function approveJoin(id: string) {
  await useMyFetch<any>(`/knowledge/join/${encodeURIComponent(id)}/approve`, { method: 'POST' })
  await loadJoins()
}

async function rejectJoin(id: string) {
  await useMyFetch<any>(`/knowledge/join/${encodeURIComponent(id)}/reject`, { method: 'POST' })
  await loadJoins()
}

async function loadDocs() {
  const ds = selectedDs.value?.id
  const path = ds ? `/knowledge/docs?data_source_id=${encodeURIComponent(ds)}` : '/knowledge/docs'
  try {
    const { data } = await useMyFetch<any>(path, { method: 'GET' })
    docs.value = (data.value?.docs as any[]) || []
  } catch {
    docs.value = []
  }
}

async function addDoc() {
  if (savingDoc.value) return
  const title = docTitle.value.trim()
  if (!title) return
  savingDoc.value = true
  try {
    await useMyFetch<any>('/knowledge/docs', {
      method: 'POST',
      body: { title, body: docBody.value, source: 'paste', data_source_id: selectedDs.value?.id || null },
    })
    docTitle.value = ''
    docBody.value = ''
    showAddDoc.value = false
    await loadDocs()
  } finally {
    savingDoc.value = false
  }
}

async function approveDoc(id: string) {
  await useMyFetch<any>(`/knowledge/doc/${encodeURIComponent(id)}/approve`, { method: 'POST' })
  await loadDocs()
}

async function rejectDoc(id: string) {
  await useMyFetch<any>(`/knowledge/doc/${encodeURIComponent(id)}/reject`, { method: 'POST' })
  await loadDocs()
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
