<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AgentStep } from '~/utils/stepMap'

const props = withDefaults(
  defineProps<{
    steps?: AgentStep[]
    status?: string
  }>(),
  {
    steps: () => [],
    status: 'in_progress',
  },
)

const isRunning = computed(() => props.status === 'in_progress')
const stepCount = computed(() => props.steps.length)

// Collapse state for the whole timeline (toggled via the thinking pill).
const collapsed = ref(false)
// Per-step body expansion, keyed by step id.
const open = ref<Record<string, boolean>>({})

function toggleStep(id: string) {
  open.value[id] = !open.value[id]
}

const pillLabel = computed(() => {
  const n = stepCount.value
  if (isRunning.value) {
    return n > 0 ? `Working… · ${n} step${n === 1 ? '' : 's'}` : 'Thinking…'
  }
  return `Thought process · ${n} step${n === 1 ? '' : 's'} · Done`
})

function fmtDuration(ms?: number): string {
  if (ms == null) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function nodeClass(s: AgentStep): string {
  if (s.status === 'done') return 'bg-[#3F7A4F] border-[#3F7A4F]'
  if (s.status === 'warn') return 'bg-[#B5822F] border-[#B5822F]'
  // run
  return 'bg-[#C2541E] border-[#C2541E] step-pulse'
}

function badgeClass(s: AgentStep): string {
  if (s.kind === 'think') return 'bg-[#f3eefb] text-[#7c3aed]'
  if (s.kind === 'retry' || s.kind === 'warn') return 'bg-[#FBF1E0] text-[#B5822F]'
  if (s.kind === 'subagent') return 'bg-[#f3eefb] text-[#7c3aed]'
  // tool
  return 'bg-[#F4E5DA] text-[#8B4427]'
}
</script>

<template>
  <!-- Empty + running: just the bare thinking pill. -->
  <!-- Empty + finished: render nothing. -->
  <div v-if="stepCount > 0 || isRunning" class="agent-step-timeline">
    <!-- THINKING PILL -->
    <button
      type="button"
      class="flex items-center gap-2 text-[13px] text-[#7A7066] mb-3 select-none"
      @click="collapsed = !collapsed"
    >
      <span
        v-if="isRunning"
        class="w-3.5 h-3.5 rounded-full border-2 border-[#E8C9B5] border-t-[#C2541E] animate-spin flex-none"
      />
      <Icon v-else name="heroicons:check-circle" class="w-4 h-4 text-[#3F7A4F] flex-none" />
      <span class="serif">{{ pillLabel }}</span>
      <Icon
        v-if="stepCount > 0"
        name="heroicons:chevron-down"
        class="w-3.5 h-3.5 transition-transform"
        :class="collapsed ? '-rotate-90' : ''"
      />
    </button>

    <!-- TIMELINE -->
    <div v-if="!collapsed && stepCount > 0" class="border-l-2 border-[#ECE6DE] ml-1.5">
      <div
        v-for="step in steps"
        :key="step.id"
        class="relative pl-5 mb-0.5"
      >
        <!-- node dot -->
        <span
          class="absolute -left-[6px] top-[11px] w-[11px] h-[11px] rounded-full border-2"
          :class="nodeClass(step)"
        />

        <!-- step row -->
        <button
          type="button"
          class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-[#F6EFEA] text-left"
          @click="toggleStep(step.id)"
        >
          <Icon
            :name="step.icon"
            class="w-4 h-4 flex-none text-[#8B4427]"
          />
          <span class="font-medium text-[13.5px] text-[#2A2420] truncate">{{ step.title }}</span>
          <span class="ml-auto flex items-center gap-2 flex-none">
            <span
              class="text-[10.5px] font-semibold px-2 py-0.5 rounded-full"
              :class="badgeClass(step)"
            >{{ step.badge }}</span>
            <span
              v-if="step.durationMs != null"
              class="text-[11px] text-[#7A7066]"
            >{{ fmtDuration(step.durationMs) }}</span>
            <Icon
              name="heroicons:chevron-right"
              class="w-3 h-3 text-[#7A7066] transition-transform"
              :class="open[step.id] ? 'rotate-90' : ''"
            />
          </span>
        </button>

        <!-- collapsible body -->
        <div
          v-if="open[step.id] && step.body"
          class="mx-2 mb-2 mt-0.5 border border-[#ECE6DE] rounded-lg overflow-hidden"
        >
          <pre
            v-if="step.body.code"
            class="bg-[#FAF7F2] font-mono text-[12px] px-3 py-2.5 whitespace-pre overflow-auto border-b border-[#ECE6DE] text-[#2A2420]"
          >{{ step.body.code }}</pre>
          <pre
            v-if="step.body.output"
            class="font-mono text-[12px] px-3 py-2 text-[#7A7066] whitespace-pre overflow-auto max-h-[150px]"
          >{{ step.body.output }}</pre>
          <div
            v-if="step.body.text"
            class="px-3 py-2 text-[13px] text-[#7A7066]"
          >{{ step.body.text }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.serif {
  font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, ui-serif, serif;
}
.step-pulse {
  animation: step-pulse 1.2s infinite;
}
@keyframes step-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(194, 104, 63, 0.4);
  }
  50% {
    box-shadow: 0 0 0 5px rgba(194, 104, 63, 0);
  }
}
</style>
