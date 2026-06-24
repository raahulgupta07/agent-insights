<template>
  <div>
    <!-- Tab bar + AI-suggest -->
    <div class="flex items-end justify-between gap-3 border-b border-gray-200 mb-6">
      <div class="flex items-center gap-1">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          @click="activeTab = tab.id"
          :class="[
            'px-4 py-2 text-xs font-medium border-b-2 -mb-px transition-colors flex items-center gap-1.5',
            activeTab === tab.id
              ? 'border-blue-500 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
          ]"
        >
          {{ tab.label }}
          <span
            v-if="tab.id === 'review' && pendingCount > 0"
            class="inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-blue-100 text-blue-700 text-[10px] font-semibold"
          >{{ pendingCount }}</span>
        </button>
      </div>

      <!-- AI-suggest (only when a concrete data source is pinned) -->
      <div v-if="dataSourceId" class="pb-1.5">
        <UButton
          size="2xs"
          variant="soft"
          color="gray"
          icon="i-heroicons-sparkles"
          :loading="suggesting"
          @click="aiSuggest"
        >AI-suggest</UButton>
      </div>
    </div>

    <!-- AI-suggest result note -->
    <div
      v-if="suggestNote"
      :class="[
        'mb-4 rounded-md border px-3 py-2 text-xs flex items-start gap-2',
        suggestError
          ? 'border-red-100 bg-red-50 text-red-700'
          : 'border-blue-100 bg-blue-50 text-blue-700'
      ]"
    >
      <Icon
        :name="suggestError ? 'heroicons:exclamation-triangle' : 'heroicons:sparkles'"
        class="w-3.5 h-3.5 shrink-0 mt-0.5"
      />
      <span>{{ suggestNote }}</span>
      <button class="ml-auto text-current opacity-60 hover:opacity-100" @click="suggestNote = ''">
        <Icon name="heroicons:x-mark" class="w-3.5 h-3.5" />
      </button>
    </div>

    <!-- Tabs -->
    <SemanticTab v-if="activeTab === 'semantic'" :dataSourceId="dataSourceId" />
    <MetricsTab v-else-if="activeTab === 'metrics'" :dataSourceId="dataSourceId" />
    <QueriesTab v-else-if="activeTab === 'queries'" :dataSourceId="dataSourceId" />
    <AssetsTab v-else-if="activeTab === 'assets'" :dataSourceId="dataSourceId" />
    <ReviewTab
      v-else-if="activeTab === 'review'"
      :key="reviewRefreshKey"
      :dataSourceId="dataSourceId"
      @count="pendingCount = $event"
    />
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

interface Props { dataSourceId?: string; hideReview?: boolean }
const props = withDefaults(defineProps<Props>(), { dataSourceId: '', hideReview: false })

const ALL_TABS = [
  { id: 'semantic', label: 'Semantic' },
  { id: 'metrics', label: 'Metrics' },
  { id: 'queries', label: 'Queries' },
  { id: 'assets', label: 'Assets' },
  { id: 'review', label: 'Review' },
]

const tabs = computed(() =>
  props.hideReview ? ALL_TABS.filter(t => t.id !== 'review') : ALL_TABS
)

const activeTab = ref('semantic')
const pendingCount = ref(0)

// --- AI-suggest ---
const suggesting = ref(false)
const suggestNote = ref('')
const suggestError = ref(false)
const reviewRefreshKey = ref(0)

async function aiSuggest() {
  if (!props.dataSourceId || suggesting.value) return
  suggesting.value = true
  suggestNote.value = ''
  suggestError.value = false
  try {
    const { data, error } = await useMyFetch<any>(
      `/knowledge/ai-suggest/${props.dataSourceId}`,
      { method: 'POST', body: { focus: 'both' } }
    )
    if (error.value) throw error.value
    const payload = data.value || {}
    if (payload.disabled) {
      suggestError.value = true
      suggestNote.value = 'AI-suggest is disabled (enable HYBRID_SEMANTIC_LAYER / HYBRID_METRICS_CATALOG).'
      return
    }
    const counts = payload.counts || {}
    const sem = counts.semantics ?? 0
    const met = counts.metrics ?? 0
    suggestNote.value = `Proposed ${sem} semantic + ${met} metric suggestions — review in the Review tab.`
    // Force ReviewTab to reload, then surface it (when not hidden).
    reviewRefreshKey.value += 1
    if (!props.hideReview) activeTab.value = 'review'
  } catch (e: any) {
    suggestError.value = true
    suggestNote.value = e?.data?.detail || e?.message || 'AI-suggest failed. Please try again.'
  } finally {
    suggesting.value = false
  }
}
</script>
