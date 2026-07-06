<template>
  <!-- ALWAYS-VISIBLE training process-flow strip for the Data Agent Overview.
       Same node grammar as the Studio auto-pilot BPMN flow (teal tiles + ✓/⟳/○ badges,
       top progress bar + status text, legend, RESULT lanes below). Remapped to the
       Data Agent's 9 stages. Self-polls sync-status; fail-soft on every field. -->
  <div id="agent-training-flow" class="atf">
    <!-- thin clay progress bar + right-aligned status text -->
    <div class="atf-bar-row">
      <div class="atf-bar"><div class="atf-bar-fill" :style="{ width: pct + '%' }"></div></div>
      <span v-if="isWorking" class="atf-status atf-status-run">training · {{ pct }}%<template v-if="tablesTotal"> · {{ Math.min(tablesDone, tablesTotal) }}/{{ tablesTotal }}</template></span>
      <span v-else-if="everTrained" class="atf-status atf-status-done">agent ready · 100%</span>
      <span v-else class="atf-status">not trained yet</span>
    </div>

    <!-- horizontal 9-node strip (scrolls-x on narrow screens) -->
    <div class="atf-canvas">
      <div class="atf-spine">
        <template v-for="(n, i) in nodes" :key="n.key">
          <div v-if="i > 0" class="atf-arrow" :class="{ done: nodes[i - 1].state === 'done' }" aria-hidden="true">
            <svg viewBox="0 0 34 16"><path d="M1 8h28M24 3l6 5-6 5" /></svg>
          </div>
          <div class="atf-node" :class="'st-' + n.state">
            <div class="atf-box">
              <UIcon :name="n.icon" class="atf-ico" />
              <svg class="ring" viewBox="0 0 70 70"><circle class="track" cx="35" cy="35" r="32" /><circle class="fill" cx="35" cy="35" r="32" stroke-dasharray="201" stroke-dashoffset="110" /></svg>
              <span class="atf-badge">{{ n.state === 'done' ? '✓' : n.state === 'skipped' ? '⊘' : n.state === 'queued' ? '○' : '' }}</span>
            </div>
            <span class="atf-lbl">{{ n.label }}</span>
          </div>
        </template>
      </div>

      <div class="atf-legend">
        <span><i class="dot d" />done</span>
        <span><i class="dot r" />working</span>
        <span><i class="dot q" />queued</span>
        <span><i class="dot s" />skipped</span>
      </div>
    </div>

    <!-- live CLI terminal — streams the training log (stage-tagged) -->
    <div v-if="logLines.length" class="atf-term">
      <div class="atf-term-head">
        <span class="atf-term-dot" /><span class="atf-term-dot" /><span class="atf-term-dot" />
        <span class="atf-term-title">training log</span>
        <span v-if="isWorking" class="atf-term-live">● live</span>
        <button class="atf-term-toggle" @click="showLog = !showLog">{{ showLog ? 'hide' : 'show' }}</button>
      </div>
      <div v-show="showLog" ref="termBody" class="atf-term-body">
        <div v-for="(l, i) in logLines" :key="i" class="atf-term-line" :class="'lg-' + l.level">
          <span class="atf-term-prompt">$</span>
          <span v-if="l.stage" class="atf-term-stage">[{{ l.stage }}]</span>
          <span class="atf-term-msg">{{ l.text }}</span>
        </div>
      </div>
    </div>

    <!-- WHAT GOT LEARNED — 5 result lanes (hidden when `learned` absent) -->
    <div v-if="hasLearned" class="atf-lanes">
      <p class="atf-lanes-cap"><span class="ln" />what got learned<span class="ln" /></p>
      <div class="atf-lane-grid">
        <div v-for="lane in lanes" :key="lane.key" class="atf-lane" :class="'lane-' + lane.key">
          <span class="atf-lane-dot" />
          <div class="atf-lane-body">
            <div class="atf-lane-n">{{ lane.count }}</div>
            <div class="atf-lane-t">{{ lane.label }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
// Props: only the data-source id. We self-poll (simplest, paused when tab hidden).
const props = defineProps<{ dataSourceId: string }>()

// ─── the 9 Data-Agent stages (fixed order + icon per stage) ──────────────────
const STAGES: { key: string; label: string; icon: string }[] = [
  { key: 'discover',   label: 'discover',   icon: 'i-heroicons-magnifying-glass' },
  { key: 'introspect', label: 'introspect', icon: 'i-heroicons-table-cells' },
  { key: 'profile',    label: 'profile',    icon: 'i-heroicons-chart-bar' },
  { key: 'values',     label: 'values',     icon: 'i-heroicons-list-bullet' },
  { key: 'meanings',   label: 'meanings',   icon: 'i-heroicons-book-open' },
  { key: 'metrics',    label: 'metrics',    icon: 'i-heroicons-calculator' },
  { key: 'queries',    label: 'queries',    icon: 'i-heroicons-command-line' },
  { key: 'rules',      label: 'rules',      icon: 'i-heroicons-scale' },
  { key: 'ready',      label: 'ready',      icon: 'i-heroicons-check-badge' },
]
const VALID_STATES = new Set(['done', 'working', 'queued', 'skipped'])

// ─── raw sync-status (self-poll, fail-soft) ──────────────────────────────────
const status = ref<any>(null)
const everRun = ref(false)   // a sync-status with real content has been seen at least once

const phase = computed(() => String(status.value?.phase || '').toLowerCase())
const pct = computed(() => {
  const p = Number(status.value?.pct)
  if (isFinite(p) && p >= 0) return Math.min(100, Math.round(p))
  // no pct → derive from phase / node completion
  if (phase.value === 'done') return 100
  if (isWorking.value) return Math.round(100 * derivedIndex.value / STAGES.length)
  return everTrained.value ? 100 : 0
})
const tablesDone = computed(() => Number(status.value?.tables_done || 0))
const tablesTotal = computed(() => Number(status.value?.tables_total || 0))

// "working" = a run is actively in progress
const isWorking = computed(() => ['connecting', 'syncing', 'learning', 'working', 'training', 'running'].includes(phase.value))
// "everTrained" = a run has finished at some point (this session or a past one)
const everTrained = computed(() => phase.value === 'done' || (everRun.value && !isWorking.value && phase.value !== 'error'))

// When `stages` is absent, best-effort node index from pct (0..9).
const derivedIndex = computed(() => {
  const p = Number(status.value?.pct)
  const frac = isFinite(p) && p >= 0 ? Math.min(100, p) / 100 : (phase.value === 'done' ? 1 : 0)
  return Math.round(frac * STAGES.length)
})

// ─── node states ─────────────────────────────────────────────────────────────
// Prefer the backend `stages` map; else derive from phase/pct (graceful fallback).
const nodes = computed(() => {
  const raw = status.value?.stages
  const stageMap: Record<string, string> = (raw && typeof raw === 'object') ? raw : {}
  const haveStages = Object.keys(stageMap).length > 0

  return STAGES.map((s, i) => {
    let state = 'queued'
    if (haveStages) {
      const v = String(stageMap[s.key] || '').toLowerCase()
      state = VALID_STATES.has(v) ? v : 'queued'
    } else if (isWorking.value) {
      const idx = derivedIndex.value
      state = i < idx ? 'done' : i === idx ? 'working' : 'queued'
    } else if (everTrained.value) {
      state = 'done'                       // finished past run → all ✓
    } else {
      state = 'queued'                      // never trained → neutral/greyed
    }
    return { ...s, state }
  })
})

// ─── learned lanes ───────────────────────────────────────────────────────────
const learned = computed<any>(() => {
  const l = status.value?.learned
  return (l && typeof l === 'object') ? l : null
})
const hasLearned = computed(() => !!learned.value)
const lanes = computed(() => {
  const l = learned.value || {}
  const num = (v: any) => { const n = Number(v); return isFinite(n) ? n : 0 }
  return [
    { key: 'tables',      label: 'Tables',      count: num(l.tables) },
    { key: 'definitions', label: 'Definitions', count: num(l.definitions) },
    { key: 'metrics',     label: 'Metrics',     count: num(l.metrics) },
    { key: 'values',      label: 'Values',      count: num(l.values) },
    { key: 'rules',       label: 'Rules',       count: num(l.rules) },
  ]
})

// ─── live CLI terminal (stage-tagged log lines from sync-status) ─────────────
const showLog = ref(true)
const termBody = ref<HTMLElement | null>(null)
const logLines = computed(() => {
  const raw = status.value?.log
  if (!Array.isArray(raw)) return []
  return raw
    .slice(-80)
    .map((e: any) => ({
      stage: String(e?.stage || ''),
      text: String(e?.message ?? e?.msg ?? e?.text ?? e?.line ?? '').slice(0, 220),
      level: String(e?.status ?? e?.level ?? '').toLowerCase(),
    }))
    .filter((l) => l.text)
})
// auto-scroll to newest line
watch(() => logLines.value.length, () => {
  nextTick(() => { if (termBody.value) termBody.value.scrollTop = termBody.value.scrollHeight })
})

// ─── poll loop (1.5s while training / recently, slower idle; pause when hidden) ─
let timer: ReturnType<typeof setTimeout> | null = null
let alive = true

async function fetchStatus() {
  if (!props.dataSourceId) return
  try {
    const { data, error } = await useMyFetch<any>(`/data_sources/${props.dataSourceId}/sync-status`, { method: 'GET' })
    if (!alive || error?.value) return
    const s = (data.value as any) || {}
    if (s && Object.keys(s).length && s.phase) { status.value = s; everRun.value = true }
    else if (s && Object.keys(s).length) { status.value = s }
  } catch { /* fail-soft */ }
}

function schedule() {
  if (!alive) return
  const fast = isWorking.value
  timer = setTimeout(async () => {
    if (typeof document === 'undefined' || document.visibilityState !== 'hidden') await fetchStatus()
    schedule()
  }, fast ? 1500 : 8000)
}

onMounted(() => { fetchStatus().then(schedule) })
onBeforeUnmount(() => { alive = false; if (timer) clearTimeout(timer) })
</script>

<style scoped>
/* warm clay / cream — matches Studio BPMN flow + the app palette */
.atf { }
.atf-bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.atf-bar { flex: 1; height: 5px; border-radius: 999px; background: #EDE5D8; overflow: hidden; }
.atf-bar-fill { height: 100%; background: #C2541E; border-radius: 999px; transition: width .4s ease; }
.atf-status { font-size: 10.5px; font-weight: 600; color: #9a958c; white-space: nowrap; }
.atf-status-run { color: #C2541E; }
.atf-status-done { color: #3f9e6a; }

/* spine — all 9 nodes FIT (equal flex), never scrolls left-right */
.atf-canvas { border: 1px solid #ECE3D6; border-radius: 14px; background: #FBF8F3; padding: 16px 10px 12px; overflow: hidden; }
.atf-spine { display: flex; align-items: flex-start; gap: 0; width: 100%; }

/* icon box — each node shares the row width equally */
.atf-node { flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; text-align: center; }
.atf-box { width: 48px; height: 48px; border-radius: 13px; display: grid; place-items: center; position: relative; background: #F3EFE8; border: 1.5px solid #eae3d7; color: #b7b0a4; transition: .3s; flex: none; }
.atf-ico { width: 22px; height: 22px; }
.atf-lbl { font-size: 9px; margin-top: 6px; line-height: 1.2; color: #9a958c; font-weight: 600; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* states */
.atf-node.st-done .atf-box { background: #e4f6f3; color: #1f8878; border-color: #bde9e2; }
.atf-node.st-done .atf-lbl { color: #1f8878; }
.atf-node.st-working .atf-box { background: #fbeedd; color: #e0912f; border-color: #e0912f; animation: atf-pulse 1.2s ease-in-out infinite; }
.atf-node.st-working .atf-lbl { color: #c98a2e; font-weight: 700; }
.atf-node.st-queued .atf-box { background: #f3efe8; color: #cfc8bb; border-color: #eae3d7; }
.atf-node.st-skipped .atf-box { background: #eef2ef; color: #9db3a9; border-color: #cdddd4; }
.atf-node.st-skipped .atf-lbl { color: #9db3a9; }

/* running progress ring (only on the working node) */
.ring { position: absolute; top: -5px; left: -5px; width: 62px; height: 62px; pointer-events: none; display: none; }
.atf-node.st-working .ring { display: block; }
.ring circle { fill: none; stroke-width: 3; }
.ring .track { stroke: #f0dcc0; }
.ring .fill { stroke: #e0912f; stroke-linecap: round; transform-origin: 50% 50%; transform: rotate(-90deg); animation: atf-ring 1.1s linear infinite; }

/* badge */
.atf-badge { position: absolute; right: -4px; bottom: -4px; min-width: 17px; height: 17px; padding: 0 2px; border-radius: 50%; display: grid; place-items: center; font-size: 10px; color: #fff; background: #2fb8a6; border: 2px solid #FBF8F3; line-height: 1; }
.atf-badge:empty { display: none; }
.atf-node.st-queued .atf-badge { background: #cfc8bb; color: #FBF8F3; }
.atf-node.st-skipped .atf-badge { background: #b6c7bf; color: #f7faf8; }

/* connector arrow — shrinks so the row fits without scrolling */
.atf-arrow { flex: 0 1 24px; min-width: 8px; height: 48px; display: flex; align-items: center; justify-content: center; }
.atf-arrow svg { width: 100%; max-width: 24px; height: 13px; stroke: #cbbda0; stroke-width: 1.6; fill: none; }
.atf-arrow.done svg { stroke: #2fb8a6; }

/* legend */
.atf-legend { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 12px; font-size: 10px; color: #9a958c; }
.atf-legend span { display: inline-flex; align-items: center; gap: 5px; }
.atf-legend .dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.atf-legend .dot.d { background: #2fb8a6; }
.atf-legend .dot.r { background: #e0912f; }
.atf-legend .dot.q { background: #d8cfc0; }
.atf-legend .dot.s { background: #b6c7bf; }

/* learned lanes */
.atf-lanes { margin-top: 14px; }
.atf-lanes-cap { display: flex; align-items: center; gap: 8px; font-size: 10px; text-transform: uppercase; letter-spacing: .05em; color: #9a958c; margin-bottom: 8px; }
.atf-lanes-cap .ln { flex: 1; height: 1px; background: #EFEDE6; }
.atf-lane-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; }
.atf-lane { display: flex; align-items: center; gap: 9px; border: 1px solid #E9E0D3; border-radius: 12px; background: #fff; padding: 10px 12px; }
.atf-lane-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; }
.atf-lane-n { font-size: 18px; font-weight: 700; color: #1C1917; line-height: 1; font-variant-numeric: tabular-nums; }
.atf-lane-t { font-size: 10.5px; color: #78716C; margin-top: 2px; }
.lane-tables .atf-lane-dot { background: #2F6F4F; }
.lane-tables { background: #F1F8F3; }
.lane-definitions .atf-lane-dot { background: #1F6F8B; }
.lane-definitions { background: #EFF6F8; }
.lane-metrics .atf-lane-dot { background: #C2541E; }
.lane-metrics { background: #FBF1EA; }
.lane-values .atf-lane-dot { background: #5A4FCF; }
.lane-values { background: #F2F1FB; }
.lane-rules .atf-lane-dot { background: #9A6A12; }
.lane-rules { background: #FBF5E8; }

/* live CLI terminal */
.atf-term { margin-top: 12px; border-radius: 12px; overflow: hidden; border: 1px solid #241f1b; background: #1b1813; }
.atf-term-head { display: flex; align-items: center; gap: 6px; padding: 7px 12px; background: #231e19; border-bottom: 1px solid #322b24; }
.atf-term-dot { width: 9px; height: 9px; border-radius: 50%; background: #4a423a; flex: none; }
.atf-term-dot:nth-child(1) { background: #e0725c; } .atf-term-dot:nth-child(2) { background: #e0b23c; } .atf-term-dot:nth-child(3) { background: #57b06a; }
.atf-term-title { margin-left: 6px; font-size: 10.5px; font-weight: 600; color: #b8ad9e; letter-spacing: .04em; }
.atf-term-live { margin-left: auto; font-size: 9.5px; color: #e0912f; font-weight: 700; }
.atf-term-toggle { margin-left: auto; background: none; border: none; color: #8a8175; font-size: 10px; cursor: pointer; padding: 2px 4px; }
.atf-term-live + .atf-term-toggle { margin-left: 10px; }
.atf-term-body { max-height: 190px; overflow-y: auto; padding: 10px 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; line-height: 1.7; }
.atf-term-line { display: flex; gap: 7px; white-space: pre-wrap; word-break: break-word; }
.atf-term-prompt { color: #5b6f52; flex: none; }
.atf-term-stage { color: #5aa9c4; flex: none; }
.atf-term-msg { color: #cfc6b8; }
.lg-ok .atf-term-msg, .lg-done .atf-term-msg { color: #8fd6a0; }
.lg-error .atf-term-msg { color: #e88b7d; }
.lg-warn .atf-term-msg { color: #e0b23c; }

@keyframes atf-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(224, 145, 47, .35); } 50% { box-shadow: 0 0 0 6px rgba(224, 145, 47, 0); } }
@keyframes atf-ring { to { transform: rotate(270deg); } }
@media (prefers-reduced-motion: reduce) {
  .atf-node.st-working .atf-box { animation: none; }
  .ring .fill { animation: none; }
}
</style>
