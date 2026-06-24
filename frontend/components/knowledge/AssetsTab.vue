<template>
  <div>
    <!-- Data source picker -->
    <div v-if="showPicker" class="flex items-center gap-3 mb-5">
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
    </div>

    <!-- Stats header -->
    <div v-if="dataSourceId && !loading && !errored && assets.length" class="mb-5">
      <div class="flex items-center gap-2 text-xs text-gray-500">
        <span>
          <span class="font-medium text-gray-700">{{ stats.total }}</span> assets
          &middot;
          <span class="font-medium text-gray-700">{{ stats.approved }}</span> approved
        </span>
        <span class="text-gray-300">&middot;</span>
        <span class="text-gray-400">
          Reusable <span class="font-mono">analytics.*</span> views the agent built. Approved assets are preferred over raw tables.
        </span>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading && !assets.length" class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center">
      <Icon name="heroicons:arrow-path" class="w-5 h-5 text-gray-400 animate-spin mx-auto mb-2" />
      <p class="text-sm text-gray-500">Loading assets&hellip;</p>
    </div>

    <!-- No data source selected -->
    <div
      v-else-if="!dataSourceId"
      class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center"
    >
      <p class="text-sm text-gray-500">Select a data source to view its engineer assets.</p>
    </div>

    <!-- Unavailable (backend not ready) -->
    <div
      v-else-if="errored"
      class="rounded-lg border border-amber-100 bg-amber-50 px-6 py-10 text-center"
    >
      <Icon name="heroicons:cloud" class="w-6 h-6 text-amber-400 mx-auto mb-2" />
      <p class="text-sm text-amber-700">Engineer assets aren&rsquo;t available yet for this data source.</p>
      <p class="mt-1 text-xs text-amber-600">They will appear here once the knowledge service is ready.</p>
    </div>

    <!-- Empty -->
    <div
      v-else-if="!assets.length"
      class="rounded-lg border border-gray-100 bg-gray-50 px-6 py-12 text-center"
    >
      <div class="w-12 h-12 rounded-full bg-white border border-gray-100 flex items-center justify-center mx-auto mb-4 shadow-sm">
        <Icon name="heroicons:circle-stack" class="w-6 h-6 text-gray-400" />
      </div>
      <p class="text-sm text-gray-500">No engineer assets yet.</p>
      <p class="mt-1 text-xs text-gray-400">
        The agent creates these with the <span class="font-mono">build_data_asset</span> tool when
        <span class="font-mono">HYBRID_ENGINEER_ASSETS</span> is on.
      </p>
    </div>

    <!-- Asset cards grid -->
    <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div
        v-for="a in assets"
        :key="a.id"
        class="rounded-lg border border-gray-200 bg-white overflow-hidden flex flex-col"
      >
        <div class="px-4 py-3 flex flex-col gap-3 flex-1">
          <!-- Header -->
          <div class="flex items-start gap-2">
            <Icon :name="kindIcon(a.kind)" class="w-4 h-4 text-gray-400 shrink-0 mt-0.5" />
            <span class="text-sm font-medium text-gray-900 truncate flex-1">{{ a.name }}</span>
            <span
              :class="[
                'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium shrink-0',
                statusClass(a.status)
              ]"
            >
              <template v-if="a.status === 'approved'">
                <span class="text-green-500 mr-1">&bull;</span> in agent context
              </template>
              <template v-else>draft</template>
            </span>
          </div>

          <!-- Object name chip -->
          <div class="flex flex-wrap items-center gap-1.5">
            <span class="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-mono bg-gray-50 border border-gray-200 text-gray-700">
              {{ a.object_name }}
            </span>
            <span
              :class="[
                'inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium',
                kindClass(a.kind)
              ]"
            >{{ kindLabel(a.kind) }}</span>
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-indigo-50 text-indigo-700">
              engineer
            </span>
          </div>

          <!-- Description -->
          <p
            class="text-sm text-gray-700 line-clamp-3"
            :class="{ 'text-gray-400 italic': !a.description }"
          >{{ a.description || 'No description yet.' }}</p>

          <!-- Created date -->
          <div class="flex items-center gap-1 text-[11px] text-gray-400">
            <Icon name="heroicons:clock" class="w-3 h-3" />
            <span>{{ shortDate(a.created_at) }}</span>
          </div>
        </div>

        <!-- Actions -->
        <div class="border-t border-gray-100 px-3 py-2 flex items-center gap-2">
          <UButton
            v-if="a.status === 'approved'"
            size="2xs"
            variant="ghost"
            color="gray"
            icon="i-heroicons-arrow-uturn-left"
            class="ml-auto"
            :loading="approvingId === a.id"
            @click="setAssetStatus(a, 'reject')"
          >Unapprove</UButton>
          <UButton
            v-else
            size="2xs"
            variant="soft"
            color="green"
            icon="i-heroicons-check"
            class="ml-auto"
            :loading="approvingId === a.id"
            @click="setAssetStatus(a, 'approve')"
          >Approve</UButton>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

interface DataSource { id: string; name: string }
interface EngineerAsset {
  id: string
  name: string
  object_name: string
  kind: string
  description?: string
  status?: string
  source?: string
  created_at?: string
  updated_at?: string
}

const emit = defineEmits<{ count: [number] }>()

interface Props { dataSourceId?: string }
const props = withDefaults(defineProps<Props>(), { dataSourceId: '' })
const pinnedDs = computed(() => props.dataSourceId || '')
const showPicker = computed(() => !pinnedDs.value)

const dataSources = ref<DataSource[]>([])
const selectedDataSource = ref<DataSource | null>(null)
const loadingSources = ref(false)

const assets = ref<EngineerAsset[]>([])
const stats = ref<{ total: number; approved: number }>({ total: 0, approved: 0 })
const loading = ref(false)
const errored = ref(false)

const approvingId = ref<string | null>(null)

// `dataSourceId` is the ACTIVE data source: pinned (embedded) takes priority over the picker.
const dataSourceId = computed(() => pinnedDs.value || selectedDataSource.value?.id || '')

function statusClass(status?: string): string {
  switch (status) {
    case 'approved': return 'bg-green-50 text-green-700'
    default: return 'bg-gray-100 text-gray-500'
  }
}

function kindClass(kind?: string): string {
  switch (kind) {
    case 'view': return 'bg-[#F6EFEA] text-[#A8542F]'
    case 'materialized_view': return 'bg-purple-50 text-purple-700'
    case 'table': return 'bg-gray-100 text-gray-600'
    default: return 'bg-gray-100 text-gray-600'
  }
}

function kindLabel(kind?: string): string {
  switch (kind) {
    case 'view': return 'view'
    case 'materialized_view': return 'materialized view'
    case 'table': return 'table'
    case 'data_asset': return 'data asset'
    default: return kind || 'asset'
  }
}

function kindIcon(kind?: string): string {
  switch (kind) {
    case 'view': return 'heroicons:eye'
    case 'materialized_view': return 'heroicons:circle-stack'
    case 'table': return 'heroicons:table-cells'
    default: return 'heroicons:circle-stack'
  }
}

function shortDate(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
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

// --- load assets ---
async function loadAssets() {
  if (!dataSourceId.value) {
    assets.value = []
    return
  }
  loading.value = true
  errored.value = false
  try {
    const { data, error } = await useMyFetch<any>(
      `/knowledge/assets?data_source_id=${encodeURIComponent(dataSourceId.value)}`,
      { method: 'GET' }
    )
    if (error.value) throw error.value
    const payload = data.value
    if (!payload) throw new Error('empty')
    assets.value = (payload.assets as EngineerAsset[]) || []
    stats.value = {
      total: payload.stats?.total ?? assets.value.length,
      approved: payload.stats?.approved ?? 0,
    }
    emit('count', stats.value.total)
  } catch {
    assets.value = []
    errored.value = true
  } finally {
    loading.value = false
  }
}

// --- approve / unapprove (optimistic, revert on error) ---
async function setAssetStatus(a: EngineerAsset, action: 'approve' | 'reject') {
  const prev = a.status
  const next = action === 'approve' ? 'approved' : 'draft'
  a.status = next
  if (next === 'approved' && prev !== 'approved') stats.value.approved += 1
  else if (next !== 'approved' && prev === 'approved') {
    stats.value.approved = Math.max(0, stats.value.approved - 1)
  }
  approvingId.value = a.id
  try {
    const { error } = await useMyFetch(`/knowledge/assets/${a.id}/${action}`, {
      method: 'POST',
    })
    if (error.value) throw error.value
  } catch {
    a.status = prev
    if (next === 'approved' && prev !== 'approved') {
      stats.value.approved = Math.max(0, stats.value.approved - 1)
    } else if (next !== 'approved' && prev === 'approved') {
      stats.value.approved += 1
    }
  } finally {
    approvingId.value = null
  }
}

watch([selectedDataSource, () => props.dataSourceId], () => loadAssets())

onMounted(async () => {
  await loadDataSources()
  await loadAssets()
})
</script>
