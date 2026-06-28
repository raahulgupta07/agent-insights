<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
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

// ---- Live "wave · what's happening · wave" running indicator ----
// Friendly fallback verbs cycled while the run hasn't emitted a concrete step
// yet (so the line is never blank). Once real steps arrive, we show the live
// step title instead — driven entirely by the run stream, not faked.
const FALLBACK = [
  'Understanding your question…',
  'Reading your data…',
  'Writing the query…',
  'Running the query…',
  'Composing the answer…',
]
const fallbackIdx = ref(0)
const elapsed = ref(0) // seconds since the run started
let tick: ReturnType<typeof setInterval> | null = null

function stopTick() { if (tick) { clearInterval(tick); tick = null } }
function startTick() {
  stopTick()
  elapsed.value = 0
  fallbackIdx.value = 0
  tick = setInterval(() => {
    elapsed.value += 1
    // advance the fallback verb every ~2s, only while no real step is live
    if (stepCount.value === 0 && elapsed.value % 2 === 0) {
      fallbackIdx.value = (fallbackIdx.value + 1) % FALLBACK.length
    }
  }, 1000)
}

watch(isRunning, (running) => { running ? startTick() : stopTick() }, { immediate: true })
onUnmounted(stopTick)

// Current live stage text: the running step's title, else the last step's
// title, else a cycling friendly fallback verb.
const currentStage = computed(() => {
  const steps = props.steps
  if (steps.length) {
    const live = [...steps].reverse().find(s => s.status === 'run')
    return (live || steps[steps.length - 1])?.title || FALLBACK[fallbackIdx.value]
  }
  return FALLBACK[fallbackIdx.value]
})

const elapsedLabel = computed(() => {
  const m = Math.floor(elapsed.value / 60)
  const s = String(elapsed.value % 60).padStart(2, '0')
  return `${m}:${s}`
})

const pillLabel = computed(() => {
  const n = stepCount.value
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
    <!-- RUNNING: wave · live stage · wave · elapsed -->
    <button
      v-if="isRunning"
      type="button"
      class="flex items-center gap-2.5 w-full text-[13.5px] mb-3 select-none"
      @click="collapsed = !collapsed"
    >
      <span class="cai-wave flex-none" aria-hidden="true">
        <svg viewBox="0 0 40 18" preserveAspectRatio="none">
          <path class="wv wv1" d="M0 9 Q10 1 20 9 T40 9" stroke="#D67037" />
          <path class="wv wv2" d="M0 9 Q10 17 20 9 T40 9" stroke="#C2541E" style="opacity:.55" />
        </svg>
      </span>
      <span class="serif font-medium text-[#2A2420] truncate">{{ currentStage }}</span>
      <span class="cai-wave cai-flip flex-none" aria-hidden="true">
        <svg viewBox="0 0 40 18" preserveAspectRatio="none">
          <path class="wv wv1" d="M0 9 Q10 1 20 9 T40 9" stroke="#D67037" />
          <path class="wv wv2" d="M0 9 Q10 17 20 9 T40 9" stroke="#C2541E" style="opacity:.55" />
        </svg>
      </span>
      <span class="ml-auto flex-none tabular-nums text-[11.5px] text-[#9A8678]">{{ elapsedLabel }}</span>
      <Icon
        v-if="stepCount > 0"
        name="heroicons:chevron-down"
        class="w-3.5 h-3.5 flex-none text-[#9A8678] transition-transform"
        :class="collapsed ? '-rotate-90' : ''"
      />
    </button>

    <!-- DONE: collapsed "thought process" pill -->
    <button
      v-else
      type="button"
      class="flex items-center gap-2 text-[13px] text-[#7A7066] mb-3 select-none"
      @click="collapsed = !collapsed"
    >
      <Icon name="heroicons:check-circle" class="w-4 h-4 text-[#3F7A4F] flex-none" />
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
/* running "wave · stage · wave" indicator */
.cai-wave {
  width: 30px;
  height: 16px;
  display: inline-block;
}
.cai-wave svg {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}
.cai-wave.cai-flip {
  transform: scaleX(-1);
}
.cai-wave .wv {
  fill: none;
  stroke-width: 2.2;
  stroke-linecap: round;
  transform-origin: center;
}
.cai-wave .wv1 {
  animation: cai-wob 1.5s ease-in-out infinite;
}
.cai-wave .wv2 {
  animation: cai-wob 1.5s ease-in-out infinite 0.25s;
}
@keyframes cai-wob {
  0%, 100% { transform: scaleY(0.3); }
  50% { transform: scaleY(1); }
}
@media (prefers-reduced-motion: reduce) {
  .cai-wave .wv { animation: none; }
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
