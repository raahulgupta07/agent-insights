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
          Metric
        </UButton>
      </div>
    </div>

    <!-- Approval helper + stats -->
    <div
      v-if="dataSourceId && !loading && !errored && metrics.length"
      class="mb-5 flex items-center gap-2 text-xs text-gray-400"
    >
      <span>
        <span class="font-medium text-gray-600">{{ approvedCount }}</span> of
        <span class="font-medium text-gray-600">{{ metrics.length }}</span> approved
      </span>
      <span class="text-gray-300">&middot;</span>
      <span>Approved items are injected into the agent&rsquo;s context.</span>
    </div>

    <!-- Loading -->
    <div v-if="loading && !metrics.length" class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center">
      <Icon name="heroicons:arrow-path" class="w-5 h-5 text-gray-400 animate-spin mx-auto mb-2" />
      <p class="text-sm text-gray-500">Loading metrics&hellip;</p>
    </div>

    <!-- No data source selected -->
    <div
      v-else-if="!dataSourceId"
      class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center"
    >
      <p class="text-sm text-gray-500">Select a data source to view its metrics catalog.</p>
    </div>

    <!-- Unavailable (backend not ready) -->
    <div
      v-else-if="errored"
      class="rounded-lg border border-amber-100 bg-amber-50 px-6 py-10 text-center"
    >
      <Icon name="heroicons:cloud" class="w-6 h-6 text-amber-400 mx-auto mb-2" />
      <p class="text-sm text-amber-700">Metrics catalog isn&rsquo;t available yet for this data source.</p>
      <p class="mt-1 text-xs text-amber-600">It will appear here once the knowledge service is ready.</p>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!metrics.length"
      class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center"
    >
      <div class="w-12 h-12 rounded-full bg-white border border-gray-100 flex items-center justify-center mx-auto mb-4 shadow-sm">
        <Icon name="heroicons:calculator" class="w-6 h-6 text-gray-400" />
      </div>
      <p class="text-sm text-gray-500">No metrics defined yet.</p>
      <UButton size="xs" class="mt-3" icon="i-heroicons-plus" @click="openCreate">
        Add your first metric
      </UButton>
    </div>

    <!-- Metric cards grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div
        v-for="m in metrics"
        :key="m.id"
        class="rounded-lg border border-gray-200 bg-white overflow-hidden flex flex-col"
      >
        <div class="px-4 py-3 flex flex-col gap-3 flex-1">
          <!-- Header -->
          <div class="flex items-start gap-2">
            <Icon name="heroicons:calculator" class="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
            <span class="text-sm font-medium text-gray-900 truncate flex-1">{{ m.name }}</span>
            <span
              :class="[
                'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium shrink-0',
                statusClass(m.status)
              ]"
            >{{ m.status || 'draft' }}</span>
          </div>

          <!-- In-context cue -->
          <div
            v-if="m.status === 'approved'"
            class="flex items-center gap-1 text-[11px] text-green-600"
            title="This metric is injected into the agent's context."
          >
            <span class="text-green-500">&bull;</span> in agent context
          </div>

          <!-- Definition -->
          <p
            class="text-sm text-gray-700 whitespace-pre-line"
            :class="{ 'text-gray-400 italic': !m.definition }"
          >{{ m.definition || 'No definition yet.' }}</p>

          <!-- Table ref -->
          <div v-if="m.table_ref" class="text-xs text-gray-500">
            <Icon name="heroicons:table-cells" class="w-3.5 h-3.5 inline -mt-0.5 text-gray-400" />
            <span class="font-mono ml-1">{{ m.table_ref }}</span>
          </div>

          <!-- SQL block -->
          <div v-if="m.sql_calc">
            <label class="block text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">SQL</label>
            <pre class="rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800 overflow-x-auto whitespace-pre-wrap break-words">{{ m.sql_calc }}</pre>
          </div>

          <!-- Test result -->
          <div v-if="testState[m.id]" class="mt-1">
            <div
              v-if="testState[m.id].loading"
              class="flex items-center gap-1.5 text-xs text-gray-500"
            >
              <Icon name="heroicons:arrow-path" class="w-3.5 h-3.5 animate-spin" /> Testing&hellip;
            </div>
            <div
              v-else-if="testState[m.id].error"
              class="rounded-md border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700 font-mono whitespace-pre-wrap break-words"
            >{{ testState[m.id].error }}</div>
            <div
              v-else
              class="rounded-md border border-green-100 bg-green-50 px-3 py-2 text-xs text-green-800"
            >
              <template v-if="testState[m.id].value !== undefined && testState[m.id].value !== null">
                <span class="text-green-600">value:</span>
                <span class="font-mono font-semibold ml-1">{{ testState[m.id].value }}</span>
              </template>
              <template v-else-if="testState[m.id].rows && testState[m.id].rows.length">
                <div class="text-green-600 mb-1">
                  {{ testState[m.id].row_count ?? testState[m.id].rows.length }} row(s)
                </div>
                <div class="overflow-x-auto">
                  <table class="text-[11px] font-mono">
                    <thead v-if="testState[m.id].columns && testState[m.id].columns.length">
                      <tr>
                        <th
                          v-for="(c, ci) in testState[m.id].columns"
                          :key="ci"
                          class="text-left pr-3 pb-0.5 text-green-700 font-medium"
                        >{{ c }}</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td
                          v-for="(cell, vi) in testState[m.id].rows[0]"
                          :key="vi"
                          class="pr-3 text-gray-800"
                        >{{ cell }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
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
            @click="openEdit(m)"
          >Edit</UButton>
          <UButton
            size="2xs"
            variant="ghost"
            color="gray"
            icon="i-heroicons-play"
            :loading="testState[m.id]?.loading"
            :disabled="!m.sql_calc"
            @click="testMetric(m)"
          >Test</UButton>
          <UButton
            v-if="m.status === 'approved'"
            size="2xs"
            variant="ghost"
            color="gray"
            icon="i-heroicons-arrow-uturn-left"
            class="ml-auto"
            :loading="approvingId === m.id"
            @click="setMetricStatus(m, 'draft')"
          >Unapprove</UButton>
          <UButton
            v-else
            size="2xs"
            variant="soft"
            color="green"
            icon="i-heroicons-check"
            class="ml-auto"
            :loading="approvingId === m.id"
            @click="setMetricStatus(m, 'approved')"
          >Approve</UButton>
          <UButton
            size="2xs"
            variant="ghost"
            color="red"
            icon="i-heroicons-trash"
            :loading="deletingId === m.id"
            @click="deleteMetric(m)"
          >Delete</UButton>
        </div>
      </div>
    </div>

    <!-- Create / Edit modal -->
    <UModal v-model="modalOpen" :ui="{ width: 'sm:max-w-lg' }">
      <div class="p-5">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-sm font-semibold text-gray-900">
            {{ editingId ? 'Edit metric' : 'New metric' }}
          </h3>
          <button @click="modalOpen = false" class="text-gray-400 hover:text-gray-600">
            <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-gray-600 mb-1">Name</label>
            <UInput v-model="form.name" size="sm" placeholder="e.g. Monthly Recurring Revenue" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-600 mb-1">Definition</label>
            <UTextarea
              v-model="form.definition"
              :rows="2"
              autoresize
              placeholder="What does this metric measure?"
            />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-600 mb-1">Table ref</label>
            <UInput v-model="form.table_ref" size="sm" placeholder="e.g. public.invoices" />
          </div>
          <div>
            <label class="block text-xs font-medium text-gray-600 mb-1">SQL calculation</label>
            <UTextarea
              v-model="form.sql_calc"
              :rows="4"
              autoresize
              placeholder="SELECT SUM(amount) FROM ..."
              :ui="{ base: 'font-mono text-xs' }"
            />
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
            @click="saveMetric"
          >{{ editingId ? 'Save' : 'Create' }}</UButton>
        </div>
      </div>
    </UModal>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

interface DataSource { id: string; name: string }
interface Metric {
  id: string
  name: string
  definition?: string
  table_ref?: string
  sql_calc?: string
  owner?: string
  status?: string
}
interface TestResult {
  loading?: boolean
  error?: string
  value?: any
  columns?: string[]
  rows?: any[][]
  row_count?: number
}

const statusOptions = ['draft', 'active', 'deprecated']

interface Props { dataSourceId?: string }
const props = withDefaults(defineProps<Props>(), { dataSourceId: '' })
const pinnedDs = computed(() => props.dataSourceId || '')
const showPicker = computed(() => !pinnedDs.value)

const dataSources = ref<DataSource[]>([])
const selectedDataSource = ref<DataSource | null>(null)
const loadingSources = ref(false)

const metrics = ref<Metric[]>([])
const loading = ref(false)
const errored = ref(false)

const deletingId = ref<string | null>(null)
const approvingId = ref<string | null>(null)
const testState = ref<Record<string, TestResult>>({})

// `dataSourceId` is the ACTIVE data source: pinned (embedded) takes priority over the picker.
const dataSourceId = computed(() => pinnedDs.value || selectedDataSource.value?.id || '')
const approvedCount = computed(() => metrics.value.filter(m => m.status === 'approved').length)

function statusClass(status?: string): string {
  switch (status) {
    case 'approved':
    case 'active': return 'bg-green-50 text-green-700'
    case 'deprecated': return 'bg-gray-100 text-gray-500'
    default: return 'bg-amber-50 text-amber-700'
  }
}

// --- approve / unapprove (optimistic, revert on error) ---
async function setMetricStatus(m: Metric, status: string) {
  const prev = m.status
  m.status = status
  approvingId.value = m.id
  try {
    const { error } = await useMyFetch(`/knowledge/metrics/${m.id}`, {
      method: 'PATCH',
      body: { status },
    })
    if (error.value) throw error.value
  } catch {
    m.status = prev
  } finally {
    approvingId.value = null
  }
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

// --- load metrics ---
async function loadMetrics() {
  if (!dataSourceId.value) {
    metrics.value = []
    return
  }
  loading.value = true
  errored.value = false
  testState.value = {}
  try {
    const { data, error } = await useMyFetch<any>(
      `/knowledge/metrics?data_source_id=${encodeURIComponent(dataSourceId.value)}`,
      { method: 'GET' }
    )
    if (error.value) throw error.value
    const payload = data.value
    if (!payload) throw new Error('empty')
    metrics.value = (payload.metrics as Metric[]) || []
  } catch {
    metrics.value = []
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
const form = ref<{ name: string; definition: string; table_ref: string; sql_calc: string; status: string }>({
  name: '', definition: '', table_ref: '', sql_calc: '', status: 'draft',
})

function resetForm() {
  form.value = { name: '', definition: '', table_ref: '', sql_calc: '', status: 'draft' }
  modalError.value = ''
}

function openCreate() {
  editingId.value = null
  resetForm()
  modalOpen.value = true
}

function openEdit(m: Metric) {
  editingId.value = m.id
  modalError.value = ''
  form.value = {
    name: m.name || '',
    definition: m.definition || '',
    table_ref: m.table_ref || '',
    sql_calc: m.sql_calc || '',
    status: m.status || 'draft',
  }
  modalOpen.value = true
}

async function saveMetric() {
  if (!form.value.name.trim()) return
  saving.value = true
  modalError.value = ''
  try {
    if (editingId.value) {
      const body = {
        name: form.value.name,
        definition: form.value.definition,
        table_ref: form.value.table_ref,
        sql_calc: form.value.sql_calc,
        status: form.value.status,
      }
      const { error } = await useMyFetch(`/knowledge/metrics/${editingId.value}`, {
        method: 'PATCH',
        body,
      })
      if (error.value) throw error.value
      const m = metrics.value.find(x => x.id === editingId.value)
      if (m) Object.assign(m, body)
    } else {
      const body = {
        data_source_id: dataSourceId.value,
        name: form.value.name,
        definition: form.value.definition,
        table_ref: form.value.table_ref,
        sql_calc: form.value.sql_calc,
      }
      const { data, error } = await useMyFetch<Metric>('/knowledge/metrics', {
        method: 'POST',
        body,
      })
      if (error.value) throw error.value
      const created = data.value as Metric
      if (created && created.id) {
        metrics.value.unshift(created)
      } else {
        await loadMetrics()
      }
    }
    modalOpen.value = false
  } catch (e: any) {
    modalError.value = e?.data?.detail || e?.message || 'Failed to save metric.'
  } finally {
    saving.value = false
  }
}

async function deleteMetric(m: Metric) {
  if (!confirm(`Delete metric "${m.name}"?`)) return
  deletingId.value = m.id
  try {
    const { error } = await useMyFetch(`/knowledge/metrics/${m.id}`, { method: 'DELETE' })
    if (error.value) throw error.value
    metrics.value = metrics.value.filter(x => x.id !== m.id)
    delete testState.value[m.id]
  } catch {
    // leave the card; surface nothing destructive
  } finally {
    deletingId.value = null
  }
}

async function testMetric(m: Metric) {
  testState.value = { ...testState.value, [m.id]: { loading: true } }
  try {
    const { data, error } = await useMyFetch<TestResult & { ok?: boolean }>(
      `/knowledge/metrics/${m.id}/test`,
      { method: 'POST' }
    )
    if (error.value) throw error.value
    const r = data.value as any
    if (!r || r.ok === false) {
      testState.value = {
        ...testState.value,
        [m.id]: { error: (r && r.error) || 'Test failed.' },
      }
    } else {
      testState.value = {
        ...testState.value,
        [m.id]: {
          value: r.value,
          columns: r.columns || [],
          rows: r.rows || [],
          row_count: r.row_count,
        },
      }
    }
  } catch (e: any) {
    testState.value = {
      ...testState.value,
      [m.id]: { error: e?.data?.detail || e?.data?.error || e?.message || 'Test failed.' },
    }
  }
}

watch([selectedDataSource, () => props.dataSourceId], () => loadMetrics())

onMounted(async () => {
  await loadDataSources()
  await loadMetrics()
})
</script>
