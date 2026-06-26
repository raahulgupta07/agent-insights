<template>
  <div>
    <!-- Header -->
    <div class="mb-4">
      <h2 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ headerMeta.title }}</h2>
      <p class="text-xs text-[#6b6b6b] mt-0.5">
        {{ headerMeta.subtitle }}
      </p>
    </div>

    <!-- No pinned sources -->
    <div
      v-if="!sources || sources.length === 0"
      class="py-10 text-center border border-dashed border-gray-200 rounded-lg"
    >
      <UIcon name="i-heroicons-code-bracket-square" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
      <p class="text-xs text-gray-500">
        Pin a Data Agent in the Sources tab to manage its saved queries here.
      </p>
    </div>

    <template v-else>
      <!-- Source switcher (only when more than one source is pinned) -->
      <div v-if="sources.length > 1" class="flex items-center gap-1 flex-wrap mb-5">
        <button
          v-for="s in sources"
          :key="s.id"
          @click="activeSourceId = String(s.agent_id)"
          :class="[
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border transition-colors',
            String(s.agent_id) === activeSourceId
              ? 'border-[#E8C9B5] bg-[#F6EFEA] text-[#A8330F]'
              : 'border-gray-200 bg-white text-gray-600 hover:text-gray-800 hover:border-gray-300'
          ]"
        >
          <DataSourceIcon v-if="s.type" class="h-3.5 shrink-0" :type="s.type" />
          <UIcon v-else name="i-heroicons-circle-stack" class="w-3.5 h-3.5 shrink-0" />
          <span class="truncate max-w-[12rem]">{{ s.name || s.agent_id }}</span>
        </button>
      </div>

      <!-- Knowledge library for the active source, scoped to its data-source id.
           Reuses the Data Agent Knowledge panel (Semantic / Metrics / Queries /
           Assets / Review). Review is the approval / mutation surface, so it is
           hidden for non-editors (viewers). :key forces a clean remount when the
           active source changes so each panel reloads its own data. -->
      <KnowledgePanel
        v-if="activeSourceId"
        :key="activeSourceId"
        :forceTab="forceTab"
        :hideNav="!!forceTab"
        :dataSourceId="activeSourceId"
        :hideReview="!canEdit"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
// Data Agent parity tab. Props contract (shared by all parity tabs):
//   studioId: string         -> the studio id
//   sources:  Source[]       -> pinned data agents [{ id, agent_id, name, type }]
//   canEdit:  boolean        -> caller may mutate
const props = withDefaults(
  defineProps<{ studioId: string; sources: any[]; canEdit: boolean; forceTab?: string }>(),
  { forceTab: '' }
)

const { t } = useI18n()

// When this tab is surfaced as its OWN rail destination, forceTab pins a single
// KnowledgePanel sub-tab and the header reflects that sub-tab's name.
const TAB_HEADERS: Record<string, { title: string; subtitle: string }> = {
  semantic: { title: 'Semantic', subtitle: "Table & column meaning for this studio's pinned sources." },
  metrics: { title: 'Metrics', subtitle: "Named KPI definitions for this studio's pinned sources." },
  queries: { title: 'Queries', subtitle: "Saved SQL & knowledge library for this studio's pinned sources." },
  assets: { title: 'Assets', subtitle: "Engineer-built data assets for this studio's pinned sources." },
  review: { title: 'Review', subtitle: "Approve or reject pending knowledge for this studio's pinned sources." },
}

const headerMeta = computed(() => {
  if (props.forceTab && TAB_HEADERS[props.forceTab]) return TAB_HEADERS[props.forceTab]
  return { title: t('studio.tabQueries') || 'Queries', subtitle: "Saved SQL & knowledge library for this studio's pinned sources." }
})

// The active pinned source whose knowledge library is shown. agent_id is the
// underlying data-source id consumed by KnowledgePanel and the /knowledge routes.
const activeSourceId = ref<string>('')

function firstSourceId(): string {
  const first = props.sources?.[0]
  return first?.agent_id != null ? String(first.agent_id) : ''
}

// Keep the active source valid as the pinned set changes (initial load + unpins).
watch(
  () => props.sources,
  (list) => {
    const ids = (list || []).map((s) => String(s?.agent_id))
    if (!activeSourceId.value || !ids.includes(activeSourceId.value)) {
      activeSourceId.value = firstSourceId()
    }
  },
  { immediate: true, deep: true }
)
</script>
