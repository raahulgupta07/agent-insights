<template>
  <div>
    <!-- Data source picker + add button -->
    <div v-if="showPicker || dataSourceId" class="flex items-center gap-3 mb-5">
      <template v-if="showPicker">
        <label class="text-xs font-medium text-gray-500 shrink-0">Data source</label>
        <USelectMenu
          v-model="selectedDataSource"
          :options="dataSources"
          option-attribute="name"
          by="id"
          placeholder="Select a data source"
          size="sm"
          class="w-72"
          :loading="loadingSources"
          :disabled="!dataSources.length"
        />
        <span v-if="!loadingSources && !dataSources.length" class="text-xs text-gray-400">
          No data sources connected.
        </span>
      </template>
      <div class="ml-auto">
        <UButton
          v-if="dataSourceId"
          size="xs"
          icon="i-heroicons-plus"
          @click="openCreate"
        >
          Query
        </UButton>
      </div>
    </div>

    <!-- Stats header -->
    <div v-if="dataSourceId && !loading && !errored && queries.length" class="mb-5">
      <div class="flex items-center gap-2 text-xs text-gray-500">
        <span>
          <span class="font-medium text-gray-700">{{ stats.total }}</span> queries
          &middot;
          <span class="font-medium text-gray-700">{{ stats.approved }}</span> approved
        </span>
        <span class="text-gray-300">&middot;</span>
        <span class="text-gray-400">Approved items are injected into the agent&rsquo;s context.</span>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading && !queries.length" class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center">
      <Icon name="heroicons:arrow-path" class="w-5 h-5 text-gray-400 animate-spin mx-auto mb-2" />
      <p class="text-sm text-gray-500">Loading queries&hellip;</p>
    </div>

    <!-- No data source selected -->
    <div
      v-else-if="!dataSourceId"
      class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center"
    >
      <p class="text-sm text-gray-500">Select a data source to view its query library.</p>
    </div>

    <!-- Unavailable (backend not ready) -->
    <div
      v-else-if="errored"
      class="rounded-lg border border-amber-100 bg-amber-50 px-6 py-10 text-center"
    >
      <Icon name="heroicons:cloud" class="w-6 h-6 text-amber-400 mx-auto mb-2" />
      <p class="text-sm text-amber-700">Query library isn&rsquo;t available yet for this data source.</p>
      <p class="mt-1 text-xs text-amber-600">It will appear here once the knowledge service is ready.</p>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!queries.length"
      class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center"
    >
      <div class="w-12 h-12 rounded-full bg-white border border-gray-100 flex items-center justify-center mx-auto mb-4 shadow-sm">
        <Icon name="heroicons:command-line" class="w-6 h-6 text-gray-400" />
      </div>
      <p class="text-sm text-gray-500">No saved queries yet.</p>
      <UButton size="xs" class="mt-3" icon="i-heroicons-plus" @click="openCreate">
        Add your first query
      </UButton>
    </div>

    <!-- Query cards grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div
        v-for="q in queries"
        :key="q.id"
        class="rounded-lg border border-gray-200 bg-white overflow-hidden flex flex-col"
      >
        <div class="px-4 py-3 flex flex-col gap-3 flex-1">
          <!-- Header -->
          <div class="flex items-start gap-2">
            <Icon name="heroicons:command-line" class="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
            <span class="text-sm font-medium text-gray-900 truncate flex-1">{{ q.name }}</span>
            <span
              :class="[
                'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium shrink-0',
                statusClass(q.status)
              ]"
            >{{ q.status || 'draft' }}</span>
          </div>

          <!-- In-context cue -->
          <div
            v-if="q.status === 'approved'"
            class="flex items-center gap-1 text-[11px] text-green-600"
            title="This query is injected into the agent's context."
          >
            <span class="text-green-500">&bull;</span> in agent context
          </div>

          <!-- Description -->
          <p
            class="text-sm text-gray-700 whitespace-pre-line"
            :class="{ 'text-gray-400 italic': !q.description }"
          >{{ q.description || 'No description yet.' }}</p>

          <!-- Meta: source badge + run count + tags -->
          <div class="flex flex-wrap items-center gap-1.5">
            <span
              :class="[
                'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium',
                sourceClass(q.source)
              ]"
            >{{ q.source || 'manual' }}</span>
            <span class="inline-flex items-center gap-1 text-[11px] text-gray-500">
              <Icon name="heroicons:play" class="w-3 h-3 text-gray-400" />
              {{ q.run_count ?? 0 }} runs
            </span>
            <span
              v-for="(t, ti) in (q.tags || [])"
              :key="ti"
              class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#F6EFEA] text-[#A8542F]"
            >{{ t }}</span>
          </div>

          <!-- SQL block (collapsible) -->
          <div v-if="q.sql_text">
            <div class="flex items-center justify-between mb-1">
              <label class="block text-[11px] font-semibold uppercase tracking-wide text-gray-400">SQL</label>
              <button
                v-if="isLong(q.sql_text)"
                class="text-[11px] text-gray-400 hover:text-gray-600"
                @click="toggleExpand(q.id)"
              >{{ expanded[q.id] ? 'Collapse' : 'Expand' }}</button>
            </div>
            <pre class="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800 overflow-x-auto whitespace-pre-wrap break-words">{{ expanded[q.id] ? q.sql_text : preview(q.sql_text) }}</pre>
          </div>

          <!-- Run result -->
          <div v-if="runState[q.id]" class="mt-1">
            <div
              v-if="runState[q.id].loading"
              class="flex items-center gap-1.5 text-xs text-gray-500"
            >
              <Icon name="heroicons:arrow-path" class="w-3.5 h-3.5 animate-spin" /> Running&hellip;
            </div>
            <div
              v-else-if="runState[q.id].error"
              class="rounded-md border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700 font-mono whitespace-pre-wrap break-words"
            >{{ runState[q.id].error }}</div>
            <div
              v-else
              class="rounded-md border border-green-100 bg-green-50 px-3 py-2 text-xs text-green-800"
            >
              <template v-if="runState[q.id].rows && runState[q.id].rows.length">
                <div class="text-green-600 mb-1">
                  {{ runState[q.id].row_count ?? runState[q.id].rows.length }} row(s)
                </div>
                <div class="overflow-x-auto">
                  <table class="text-[11px] font-mono">
                    <thead v-if="runState[q.id].columns && runState[q.id].columns.length">
                      <tr>
                        <th
                          v-for="(c, ci) in runState[q.id].columns"
                          :key="ci"
                          class="text-left pr-3 pb-0.5 text-green-700 font-medium"
                        >{{ c }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="(row, ri) in runState[q.id].rows.slice(0, 5)"
                        :key="ri"
                      >
                        <td
                          v-for="(cell, vi) in row"
                          :key="vi"
                          class="pr-3 text-gray-800"
                        >{{ cell }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </template>
              <template v-else-if="runState[q.id].row_count !== undefined && runState[q.id].row_count !== null">
                <span class="text-green-600">row count:</span>
                <span class="font-mono font-semibold ml-1">{{ runState[q.id].row_count }}</span>
              </template>
              <template v-else>
                <span class="text-green-600">OK</span>
              </template>
            </div>
          </div>
        </div>

        <!-- Actions -->
        <div class="border-t border-gray-100 px-3 py-2 flex items-center gap-2">
          <UButton
            size="2xs"
            variant="ghost"
            color="gray"
            icon="i-heroicons-pencil-square"
            @click="openEdit(q)"
          >Edit</UButton>
          <UButton
            size="2xs"
            variant="ghost"
            color="gray"
            icon="i-heroicons-play"
            :loading="runState[q.id]?.loading"
            :disabled="!q.sql_text"
            @click="runQuery(q)"
          >Run</UButton>
          <UButton
            v-if="q.status === 'approved'"
            size="2xs"
            variant="ghost"
            color="gray"
            icon="i-heroicons-arrow-uturn-left"
            class="ml-auto"
            :loading="approvingId === q.id"
            @click="setQueryStatus(q, 'draft')"
          >Unapprove</UButton>
          <UButton
            v-else
            size="2xs"
            variant="soft"
            color="green"
            icon="i-heroicons-check"
            class="ml-auto"
            :loading="approvingId === q.id"
            @click="setQueryStatus(q, 'approved')"
          >Approve</UButton>
          <UButton
            size="2xs"
            variant="ghost"
            color="red"
            icon="i-heroicons-trash"
            :loading="deletingId === q.id"
            @click="deleteQuery(q)"
          >Delete</UButton>
        </div>
      </div>
    </div>

    <!-- Create / Edit modal -->
    <UModal v-model="modalOpen" :ui="{ width: 'sm:max-w-lg' }">
      <div class="p-5">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-gray-900">
            {{ editingId ? 'Edit query' : 'New query' }}
          </h3>
          <button @click="modalOpen = false" class="text-gray-400 hover:text-gray-600">
            <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-gray-600 mb-1">Name</label>
            <UInput v-model="form.name" size="sm" placeholder="e.g. Top customers by revenue" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-600 mb-1">Description</label>
            <UTextarea
              v-model="form.description"
              :rows="2"
              autoresize
              placeholder="What does this query return?"
            />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-600 mb-1">SQL</label>
            <UTextarea
              v-model="form.sql_text"
              :rows="5"
              autoresize
              placeholder="SELECT ... FROM ..."
              :ui="{ base: 'font-mono text-xs' }"
            />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-600 mb-1">Tags</label>
            <UInput v-model="form.tags" size="sm" placeholder="comma, separated, tags" />
          </div>
          <div v-if="editingId">
            <label class="block text-xs font-medium text-gray-600 mb-1">Status</label>
            <USelectMenu
              v-model="form.status"
              :options="statusOptions"
              size="sm"
              class="w-40"
            />
          </div>
        </div>

        <div v-if="modalError" class="mt-3 text-xs text-red-600">{{ modalError }}</div>

        <div class="flex justify-end gap-2 mt-5 pt-3 border-t border-gray-100">
          <UButton color="gray" variant="ghost" size="xs" @click="modalOpen = false">Cancel</UButton>
          <UButton
            size="xs"
            :loading="saving"
            :disabled="!form.name.trim()"
            @click="saveQuery"
          >{{ editingId ? 'Save' : 'Create' }}</UButton>
        </div>
      </div>
    </UModal>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

interface DataSource { id: string; name: string }
interface SavedQuery {
  id: string
  name: string
  description?: string
  sql_text?: string
  tags?: string[]
  source?: string
  run_count?: number
  status?: string
}
interface RunResult {
  loading?: boolean
  error?: string
  columns?: string[]
  rows?: any[][]
  row_count?: number
}

const statusOptions = ['draft', 'approved', 'deprecated']

interface Props { dataSourceId?: string }
const props = withDefaults(defineProps<Props>(), { dataSourceId: '' })
const pinnedDs = computed(() => props.dataSourceId || '')
const showPicker = computed(() => !pinnedDs.value)

const dataSources = ref<DataSource[]>([])
const selectedDataSource = ref<DataSource | null>(null)
const loadingSources = ref(false)

const queries = ref<SavedQuery[]>([])
const stats = ref<{ total: number; approved: number }>({ total: 0, approved: 0 })
const loading = ref(false)
const errored = ref(false)

const deletingId = ref<string | null>(null)
const approvingId = ref<string | null>(null)
const runState = ref<Record<string, RunResult>>({})
const expanded = ref<Record<string, boolean>>({})

// `dataSourceId` is the ACTIVE data source: pinned (embedded) takes priority over the picker.
const dataSourceId = computed(() => pinnedDs.value || selectedDataSource.value?.id || '')

function statusClass(status?: string): string {
  switch (status) {
    case 'approved': return 'bg-green-50 text-green-700'
    case 'deprecated': return 'bg-gray-100 text-gray-500'
    default: return 'bg-amber-50 text-amber-700'
  }
}

function sourceClass(source?: string): string {
  switch (source) {
    case 'chat': return 'bg-purple-50 text-purple-700'
    case 'promoted': return 'bg-indigo-50 text-indigo-700'
    default: return 'bg-gray-100 text-gray-600'
  }
}

function isLong(sql?: string): boolean {
  if (!sql) return false
  return sql.length > 160 || sql.split('\n').length > 4
}

function preview(sql: string): string {
  if (!isLong(sql)) return sql
  const lines = sql.split('\n').slice(0, 4)
  let out = lines.join('\n')
  if (out.length > 200) out = out.slice(0, 200)
  return out + '…'
}

function toggleExpand(id: string) {
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] }
}

// --- load data sources ---
async function loadDataSources() {
  if (!showPicker.value) return
  loadingSources.value = true
  try {
    const { data, error } = await useMyFetch<DataSource[]>('/data_sources', { method: 'GET' })
    if (error.value) throw error.value
    dataSources.value = (data.value as DataSource[]) || []
    if (dataSources.value.length && !selectedDataSource.value) {
      selectedDataSource.value = dataSources.value[0]
    }
  } catch {
    dataSources.value = []
  } finally {
    loadingSources.value = false
  }
}

// --- load queries ---
async function loadQueries() {
  if (!dataSourceId.value) {
    queries.value = []
    return
  }
  loading.value = true
  errored.value = false
  runState.value = {}
  expanded.value = {}
  try {
    const { data, error } = await useMyFetch<any>(
      `/knowledge/queries?data_source_id=${encodeURIComponent(dataSourceId.value)}`,
      { method: 'GET' }
    )
    if (error.value) throw error.value
    const payload = data.value
    if (!payload) throw new Error('empty')
    queries.value = (payload.queries as SavedQuery[]) || []
    stats.value = {
      total: payload.stats?.total ?? queries.value.length,
      approved: payload.stats?.approved ?? 0,
    }
  } catch {
    queries.value = []
    errored.value = true
  } finally {
    loading.value = false
  }
}

// --- modal state ---
const modalOpen = ref(false)
const editingId = ref<string | null>(null)
const saving = ref(false)
const modalError = ref('')
const form = ref<{ name: string; description: string; sql_text: string; tags: string; status: string }>({
  name: '', description: '', sql_text: '', tags: '', status: 'draft',
})

function resetForm() {
  form.value = { name: '', description: '', sql_text: '', tags: '', status: 'draft' }
  modalError.value = ''
}

function parseTags(raw: string): string[] {
  return raw.split(',').map(t => t.trim()).filter(Boolean)
}

function openCreate() {
  editingId.value = null
  resetForm()
  modalOpen.value = true
}

function openEdit(q: SavedQuery) {
  editingId.value = q.id
  modalError.value = ''
  form.value = {
    name: q.name || '',
    description: q.description || '',
    sql_text: q.sql_text || '',
    tags: (q.tags || []).join(', '),
    status: q.status || 'draft',
  }
  modalOpen.value = true
}

async function saveQuery() {
  if (!form.value.name.trim()) return
  saving.value = true
  modalError.value = ''
  try {
    if (editingId.value) {
      const body = {
        name: form.value.name,
        description: form.value.description,
        sql_text: form.value.sql_text,
        tags: parseTags(form.value.tags),
        status: form.value.status,
      }
      const { error } = await useMyFetch(`/knowledge/queries/${editingId.value}`, {
        method: 'PATCH',
        body,
      })
      if (error.value) throw error.value
      const q = queries.value.find(x => x.id === editingId.value)
      if (q) Object.assign(q, body)
    } else {
      const body = {
        data_source_id: dataSourceId.value,
        name: form.value.name,
        description: form.value.description,
        sql_text: form.value.sql_text,
        tags: parseTags(form.value.tags),
      }
      const { data, error } = await useMyFetch<SavedQuery>('/knowledge/queries', {
        method: 'POST',
        body,
      })
      if (error.value) throw error.value
      const created = data.value as SavedQuery
      if (created && created.id) {
        queries.value.unshift(created)
        stats.value.total += 1
      } else {
        await loadQueries()
      }
    }
    modalOpen.value = false
  } catch (e: any) {
    modalError.value = e?.data?.detail || e?.message || 'Failed to save query.'
  } finally {
    saving.value = false
  }
}

async function deleteQuery(q: SavedQuery) {
  if (!confirm(`Delete query "${q.name}"?`)) return
  deletingId.value = q.id
  try {
    const { error } = await useMyFetch(`/knowledge/queries/${q.id}`, { method: 'DELETE' })
    if (error.value) throw error.value
    queries.value = queries.value.filter(x => x.id !== q.id)
    delete runState.value[q.id]
    stats.value.total = Math.max(0, stats.value.total - 1)
  } catch {
    // leave the card; surface nothing destructive
  } finally {
    deletingId.value = null
  }
}

async function runQuery(q: SavedQuery) {
  runState.value = { ...runState.value, [q.id]: { loading: true } }
  try {
    const { data, error } = await useMyFetch<RunResult & { ok?: boolean }>(
      `/knowledge/queries/${q.id}/run`,
      { method: 'POST' }
    )
    if (error.value) throw error.value
    const r = data.value as any
    if (!r || r.ok === false) {
      runState.value = {
        ...runState.value,
        [q.id]: { error: (r && r.error) || 'Run failed.' },
      }
    } else {
      runState.value = {
        ...runState.value,
        [q.id]: {
          columns: r.columns || [],
          rows: r.rows || [],
          row_count: r.row_count,
        },
      }
      // optimistic run_count bump
      const target = queries.value.find(x => x.id === q.id)
      if (target) target.run_count = (target.run_count ?? 0) + 1
    }
  } catch (e: any) {
    runState.value = {
      ...runState.value,
      [q.id]: { error: e?.data?.detail || e?.data?.error || e?.message || 'Run failed.' },
    }
  }
}

// --- approve / unapprove (optimistic, revert on error) ---
async function setQueryStatus(q: SavedQuery, status: string) {
  const prev = q.status
  q.status = status
  if (status === 'approved' && prev !== 'approved') stats.value.approved += 1
  else if (status !== 'approved' && prev === 'approved') {
    stats.value.approved = Math.max(0, stats.value.approved - 1)
  }
  approvingId.value = q.id
  try {
    const { error } = await useMyFetch(`/knowledge/queries/${q.id}`, {
      method: 'PATCH',
      body: { status },
    })
    if (error.value) throw error.value
  } catch {
    q.status = prev
    if (status === 'approved' && prev !== 'approved') {
      stats.value.approved = Math.max(0, stats.value.approved - 1)
    } else if (status !== 'approved' && prev === 'approved') {
      stats.value.approved += 1
    }
  } finally {
    approvingId.value = null
  }
}

watch([selectedDataSource, () => props.dataSourceId], () => loadQueries())

onMounted(async () => {
  await loadDataSources()
  await loadQueries()
})
</script>
