<template>
  <div class="py-6 max-w-[1180px]">
    <!-- page head -->
    <div class="flex items-start justify-between gap-4 mb-5">
      <div>
        <h1 class="text-lg font-semibold text-[#1C1917]">Activity</h1>
        <p class="text-[#78716C] text-sm mt-0.5">Every sync, re-learn and change for this agent — the live log that used to sit on Overview.</p>
      </div>
    </div>

    <!-- segmented filter (visual scope; the live terminal below self-gates) -->
    <div class="mb-4 inline-flex rounded-lg border border-[#EAE8E4] overflow-hidden bg-white">
      <button
        v-for="(f, i) in filters"
        :key="f.key"
        type="button"
        @click="activeFilter = f.key"
        class="px-3 py-1.5 text-xs"
        :class="[
          i < filters.length - 1 ? 'border-r border-[#EAE8E4]' : '',
          activeFilter === f.key ? 'bg-[#F1EFEC] text-[#1C1917] font-semibold' : 'text-[#78716C] hover:bg-[#FAFAF9]'
        ]"
      >{{ f.label }}</button>
    </div>

    <!-- most-recent / live sync run: the terminal. Self-gates on a real run
         existing (its own hasRun/phase polling) — no fabrication. -->
    <div v-show="activeFilter === 'all' || activeFilter === 'syncs'" class="mb-6">
      <AgentSyncLog :data-source-id="(route.params.id as string)" />
    </div>

    <!-- earlier history: honest empty-state (no sync-history endpoint yet) -->
    <div class="bg-white border border-[#EAE8E4] rounded-xl shadow-sm overflow-hidden">
      <div class="px-4 py-3.5 border-b border-[#F1EFEC] text-[13.5px] font-semibold text-[#1C1917]">Earlier</div>
      <div class="p-8 text-center">
        <div class="text-[#A8A29E] text-sm">No earlier activity recorded yet.</div>
        <div class="text-[#A8A29E] text-xs mt-1">Past syncs and re-learns will appear here as they happen.</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Agent Activity tab. Hosts the connector sync terminal (AgentSyncLog) — the
// live/most-recent run feed that previously rendered on the Overview page — plus
// a scope filter and an honest empty history section. No data is fabricated: the
// terminal shows only real runs (it self-gates), and history is an empty-state
// until a sync-history source exists.
import AgentSyncLog from '~/components/agents/AgentSyncLog.vue'

definePageMeta({ auth: true, layout: 'data' })

const route = useRoute()

const activeFilter = ref<'all' | 'syncs' | 'relearns' | 'errors'>('all')
const filters = [
  { key: 'all' as const, label: 'All' },
  { key: 'syncs' as const, label: 'Syncs' },
  { key: 'relearns' as const, label: 'Re-learns' },
  { key: 'errors' as const, label: 'Errors' },
]
</script>
