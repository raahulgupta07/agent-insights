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

// Whole-timeline collapse. Live runs are EXPANDED; a finished/reloaded run
// starts COLLAPSED (persisted completions mount collapsed).
const collapsed = ref(props.status !== 'in_progress')
// Per-step body (tool code/output) expansion, keyed by step id.
const open = ref<Record<string, boolean>>({})

function toggleStep(id: string) {
  open.value[id] = !open.value[id]
}

// ---- Live elapsed timer (reused 1s tick) ----
const elapsed = ref(0) // seconds since the run started
let tick: ReturnType<typeof setInterval> | null = null
let collapseTimer: ReturnType<typeof setTimeout> | null = null

function stopTick() { if (tick) { clearInterval(tick); tick = null } }
function startTick() {
  stopTick()
  elapsed.value = 0
  tick = setInterval(() => { elapsed.value += 1 }, 1000)
}

// run/stop the elapsed tick with the run
watch(isRunning, (running) => { running ? startTick() : stopTick() }, { immediate: true })

// expand on start; auto-collapse ~0.5s after a LIVE run finishes.
// (Not immediate → a persisted done-on-mount stays collapsed via the ref init.)
watch(isRunning, (running, was) => {
  if (running) {
    collapsed.value = false
  } else if (was) {
    if (collapseTimer) clearTimeout(collapseTimer)
    collapseTimer = setTimeout(() => { collapsed.value = true }, 500)
  }
})

onUnmounted(() => { stopTick(); if (collapseTimer) clearTimeout(collapseTimer) })

const elapsedLabel = computed(() => {
  const m = Math.floor(elapsed.value / 60)
  const s = String(elapsed.value % 60).padStart(2, '0')
  return `${m}:${s}`
})

// Total run seconds for the collapsed "Worked for Ns" line. Prefer the live
// elapsed counter; on a reloaded completion (timer never ran) derive it from
// the real step timestamps/durations — never invented.
const totalSeconds = computed(() => {
  if (elapsed.value > 0) return elapsed.value
  const s = props.steps
  if (!s.length) return 0
  const first = s[0].ts || 0
  const lastStep = s[s.length - 1]
  const last = (lastStep.ts || first) + (lastStep.durationMs || 0)
  const span = Math.round((last - first) / 1000)
  if (span > 0) return span
  const sum = s.reduce((a, x) => a + (x.durationMs || 0), 0)
  return Math.round(sum / 1000)
})

// Collapsed summary — COUNTED from the real steps (tool count + their mapped
// titles + any row counts already present in step output). Nothing fabricated.
const summary = computed(() => {
  const s = props.steps
  if (!s.length) return 'no steps'
  const tools = s.filter(x => x.kind === 'tool')
  const n = tools.length || s.length
  const parts: string[] = [`${n} step${n === 1 ? '' : 's'}`]
  const titles = [...new Set(tools.map(t => t.title).filter(Boolean))]
  if (titles.length) parts.push(titles.slice(0, 3).join(', '))
  let rows = 0
  for (const st of s) {
    const m = (st.body?.output || '').match(/([\d,]+)\s+rows?/i)
    if (m) rows = Math.max(rows, parseInt(m[1].replace(/,/g, ''), 10) || 0)
  }
  if (rows) parts.push(`${rows.toLocaleString()} rows`)
  return parts.join(' · ')
})

function fmtDuration(ms?: number): string {
  if (ms == null) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
function fmtPlus(ms?: number): string {
  if (ms == null) return ''
  return `+${(ms / 1000).toFixed(1)}s`
}

const isErr = (s: AgentStep) => s.status === 'err' || s.kind === 'warn' || s.kind === 'retry' || s.status === 'warn'

function stepTitle(s: AgentStep): string {
  return s.kind === 'think' ? 'Thinking' : s.title
}

// node dot treatment: run = pulsing clay ring, done = filled clay,
// warn/err = amber (warn) / clay-deep (err).
function nodeClass(s: AgentStep): string {
  if (s.status === 'err') return 'node-err'
  if (s.kind === 'warn' || s.kind === 'retry' || s.status === 'warn') return 'node-warn'
  if (s.status === 'run') return 'node-run'
  return 'node-done'
}
</script>

<template>
  <!-- Empty + finished: render nothing. -->
  <div v-if="stepCount > 0 || isRunning" class="agent-step-timeline">
    <!-- RUNNING header: ✳ Working… + live M:SS (calm, no weave) -->
    <div
      v-if="isRunning"
      class="cai-head flex items-center gap-2.5 text-[13.5px] mb-3 select-none"
    >
      <span class="clay-spark flex-none" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="15" height="15">
          <path
            d="M12 1.5 L13.6 8.4 L20.5 6.8 L15.4 12 L20.5 17.2 L13.6 15.6 L12 22.5 L10.4 15.6 L3.5 17.2 L8.6 12 L3.5 6.8 L10.4 8.4 Z"
            fill="#C2541E"
          />
        </svg>
      </span>
      <span class="serif font-medium text-[#2A2420]">Working…</span>
      <span class="ml-auto flex-none tabular-nums text-[11.5px] text-[#9A8678]">{{ elapsedLabel }}</span>
    </div>

    <!-- DONE header: ⌄ Worked for Ns · summary (click to re-expand) -->
    <button
      v-else
      type="button"
      class="cai-head flex items-center gap-2 text-[13px] text-[#7A7066] mb-3 select-none w-full text-left"
      @click="collapsed = !collapsed"
    >
      <Icon name="heroicons:check-circle" class="w-4 h-4 text-[#3F8F5B] flex-none" />
      <span class="serif truncate">Worked for {{ totalSeconds }}s · {{ summary }}</span>
      <Icon
        v-if="stepCount > 0"
        name="heroicons:chevron-down"
        class="w-3.5 h-3.5 flex-none text-[#9A8678] transition-transform ml-auto"
        :class="collapsed ? '-rotate-90' : ''"
      />
    </button>

    <!-- TIMELINE (rail grows as steps land) -->
    <div v-if="!collapsed && stepCount > 0" class="cai-rail">
      <div
        v-for="step in steps"
        :key="step.id"
        class="relative pl-5 mb-0.5"
      >
        <!-- node dot -->
        <span class="cai-node" :class="nodeClass(step)" />

        <!-- step row -->
        <button
          type="button"
          class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-[#F6EFEA] text-left"
          @click="toggleStep(step.id)"
        >
          <Icon
            :name="step.icon"
            class="w-4 h-4 flex-none"
            :class="isErr(step) ? 'text-[#A8330F]' : 'text-[#8B4427]'"
          />
          <span
            class="font-medium text-[13.5px] truncate"
            :class="isErr(step) ? 'text-[#A8330F]' : 'text-[#2A2420]'"
          >{{ stepTitle(step) }}</span>

          <!-- recovered pill (kept) -->
          <span
            v-if="step.recovered && step.recoveredLabel"
            class="text-[10.5px] font-semibold px-1.5 py-0.5 rounded-full bg-[#FBF1E0] text-[#B5822F] flex-none"
          >{{ step.recoveredLabel }}</span>

          <span class="ml-auto flex items-center gap-2 flex-none">
            <!-- live spinner on the running step -->
            <Icon
              v-if="step.status === 'run'"
              name="heroicons:arrow-path"
              class="w-3.5 h-3.5 text-[#C2541E] cai-spin"
            />
            <!-- +N.Ns on completed steps -->
            <span
              v-else-if="step.durationMs != null"
              class="text-[11px] text-[#9A8678] tabular-nums"
            >{{ fmtPlus(step.durationMs) }}</span>
            <Icon
              v-if="step.body && (step.body.code || step.body.output)"
              name="heroicons:chevron-right"
              class="w-3 h-3 text-[#9A8678] transition-transform"
              :class="open[step.id] ? 'rotate-90' : ''"
            />
          </span>
        </button>

        <!-- live reasoning / narration line (run step or think step) with caret -->
        <div
          v-if="step.status === 'run' && (step.body?.text || step.why || step.kind === 'think')"
          class="pl-2 pr-2 pb-1.5 text-[12.5px] text-[#7A7066] leading-snug"
        >
          {{ step.body?.text || step.why }}<span class="cai-caret">▍</span>
        </div>
        <div
          v-else-if="step.kind === 'think' && (step.body?.text || step.why)"
          class="pl-2 pr-2 pb-1.5 text-[12.5px] text-[#7A7066] leading-snug"
        >{{ step.body?.text || step.why }}</div>
        <div
          v-else-if="step.why"
          class="pl-2 pr-2 pb-1 text-[12px] text-[#9A8678] leading-snug italic"
        >{{ step.why }}</div>

        <!-- collapsible tool box (code / output) -->
        <div
          v-if="open[step.id] && step.body && (step.body.code || step.body.output)"
          class="cai-toolbox mx-2 mb-2 mt-0.5 rounded-lg overflow-hidden"
        >
          <pre
            v-if="step.body.code"
            class="font-mono text-[12px] px-3 py-2.5 whitespace-pre overflow-auto text-[#2A2420]"
            :class="step.body.output ? 'border-b border-[#E9E0D3]' : ''"
          >{{ step.body.code }}</pre>
          <pre
            v-if="step.body.output"
            class="font-mono text-[12px] px-3 py-2 text-[#7A7066] whitespace-pre overflow-auto max-h-[150px]"
          >{{ step.body.output }}</pre>
        </div>

        <!-- error detail (kept, behind the same body toggle) -->
        <div
          v-if="open[step.id] && step.errorDetail"
          class="mx-2 mb-2 mt-0.5 rounded-lg bg-[#FBEDE7] border border-[#F0C7BB] px-3 py-2 font-mono text-[11.5px] text-[#A8330F] whitespace-pre-wrap overflow-auto max-h-[150px]"
        >{{ step.errorDetail }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.serif {
  font-family: 'Iowan Old Style', 'Palatino Linotype', Georgia, ui-serif, serif;
}

/* faint vertical rail — grows with the number of rows */
.cai-rail {
  border-left: 2px solid #ECE6DE;
  margin-left: 0.375rem;
}

/* timeline node dots */
.cai-node {
  position: absolute;
  left: -6px;
  top: 11px;
  width: 11px;
  height: 11px;
  border-radius: 9999px;
  box-sizing: border-box;
}
.cai-node.node-done { background: #C2541E; border: 2px solid #C2541E; }
.cai-node.node-run {
  background: transparent;
  border: 2px solid #C2541E;
  animation: cai-pulse 1.2s infinite;
}
.cai-node.node-warn { background: #B5822F; border: 2px solid #B5822F; }
.cai-node.node-err { background: #A8330F; border: 2px solid #A8330F; }

/* slow-spinning clay spark in the running header */
.clay-spark { display: inline-flex; line-height: 0; }
.clay-spark svg { animation: cai-slow-spin 3.2s linear infinite; transform-origin: center; }

.cai-spin { animation: cai-slow-spin 1s linear infinite; }

.cai-caret {
  color: #C2541E;
  animation: cai-blink 1s step-start infinite;
}

.cai-toolbox {
  background: #F4EEE4;
  border: 1px solid #E9E0D3;
}

@keyframes cai-slow-spin { to { transform: rotate(360deg); } }
@keyframes cai-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(194, 84, 30, 0.45); }
  50% { box-shadow: 0 0 0 5px rgba(194, 84, 30, 0); }
}
@keyframes cai-blink { 50% { opacity: 0; } }

@media (prefers-reduced-motion: reduce) {
  .clay-spark svg,
  .cai-spin,
  .cai-node.node-run,
  .cai-caret { animation: none; }
}

/* dark mode (opt-in via the app's theme hook; harmless if unused) */
@media (prefers-color-scheme: dark) {
  :root[data-theme='dark'] .cai-rail { border-left-color: #3A342C; }
  :root[data-theme='dark'] .cai-toolbox { background: #201C17; border-color: #3A342C; }
}
</style>
