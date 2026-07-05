<template>
  <div>
    <!-- Layer header -->
    <div class="flex items-start gap-3 mb-1">
      <div class="w-10 h-10 rounded-[10px] bg-[#F3E3DA] text-[#8A4527] flex items-center justify-center text-lg flex-none">
        <span v-html="M.glyph" />
      </div>
      <div>
        <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ M.title }}</h2>
        <p class="text-xs text-[#6b6b6b] mt-0.5">{{ M.sub }}</p>
      </div>
      <div v-if="!combined" class="ms-auto flex items-center gap-2.5">
        <span class="text-[11px] font-medium text-[#6b6b6b] bg-[#f1efe9] px-2 py-1 rounded-md">{{ M.role }}</span>
        <span
          class="text-[11px] font-bold px-2.5 py-1 rounded-md"
          :class="enabled ? 'bg-[#eaf6f0] text-[#2f9e6f]' : 'bg-[#f0eeec] text-[#9a958c]'"
        >{{ enabled ? 'ENABLED' : 'DISABLED' }}</span>
        <!-- real toggle (org-wide flag override; editors only) -->
        <button
          type="button"
          :disabled="!canEdit || toggling"
          class="relative w-[44px] h-[25px] rounded-full transition-colors flex-none"
          :class="[enabled ? 'bg-[#C2541E]' : 'bg-[#d7d7d7]', (!canEdit || toggling) ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer']"
          :title="canEdit ? 'Toggle org-wide' : 'Editors only'"
          @click="toggle"
        >
          <span class="absolute top-[3px] w-[19px] h-[19px] bg-white rounded-full shadow transition-all" :style="{ left: enabled ? '22px' : '3px' }" />
        </button>
      </div>
    </div>

    <p class="text-[13px] text-[#444] mt-3 mb-1 max-w-[640px]">{{ M.desc }}</p>
    <div class="text-[11px] text-[#9a958c] font-mono mb-1">flag: {{ M.flag }} <span class="ms-1">· org-wide</span></div>
    <div v-if="toggleErr" class="text-[11px] text-[#c0392b] mb-2">{{ toggleErr }}</div>

    <!-- Run actions (live) -->
    <div v-if="acts.length" class="flex flex-wrap items-center gap-2 mt-3">
      <template v-for="a in acts" :key="a.label">
        <input
          v-if="a.kind === 'search'"
          v-model="query"
          type="text"
          placeholder="Search knowledge…"
          class="text-[12px] px-3 py-1.5 rounded-lg border border-[#E9E0D3] bg-white w-56 focus:outline-none focus:border-[#C2541E]"
          @keyup.enter="runAction(a)"
        >
        <button
          type="button"
          :disabled="!!running || (a.kind !== 'refresh' && !enabled && !combined)"
          class="text-[12px] font-semibold px-3.5 py-1.5 rounded-lg transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          :class="a.kind === 'refresh' ? 'bg-[#f1efe9] text-[#6b6b6b] hover:bg-[#e9e6df]' : 'bg-[#C2541E] text-white hover:bg-[#A8330F]'"
          @click="runAction(a)"
        >{{ running === a.label ? 'Working…' : a.label }}</button>
      </template>
    </div>

    <!-- Combined empty state (before anything is run) -->
    <div v-if="combined && !runResult && !loading" class="text-[12px] text-[#555] bg-[#faf8f4] border-l-[3px] border-[#C2541E] rounded-r-lg px-3.5 py-2.5 mt-3">
      Nothing stored yet — click Scan, Forecast or Find patterns to run live.
    </div>

    <!-- Loading -->
    <div v-if="loading" class="rounded-lg border border-[#eee] bg-[#fafafa] px-6 py-10 text-center text-sm text-[#6b6b6b] mt-3">
      Loading…
    </div>

    <template v-else>
      <!-- Stat strip -->
      <div v-if="data?.stats?.length" class="flex gap-3 mb-4 mt-3">
        <div v-for="s in data.stats" :key="s.l" class="flex-1 bg-[#FBF4EF] border border-[#f0ddd0] rounded-[10px] px-3.5 py-2.5">
          <div class="text-xl font-bold text-[#1f2328]">{{ s.n }}</div>
          <div class="text-[10px] text-[#8A4527] uppercase tracking-wide">{{ s.l }}</div>
        </div>
      </div>

      <!-- Data table -->
      <div v-if="data?.table?.rows?.length" class="bg-white border border-[#E9E0D3] rounded-xl p-4 mb-4 mt-3">
        <h3 class="text-[11.5px] font-bold uppercase tracking-wide text-[#6b6b6b] mb-3">{{ data.table.title }}</h3>
        <table class="w-full text-[12px]">
          <thead>
            <tr>
              <th v-for="h in data.table.head" :key="h" class="text-left text-[10px] uppercase tracking-wide text-[#9a958c] font-bold py-1.5 px-2 border-b border-[#E9E0D3]">{{ h }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in data.table.rows" :key="i">
              <td v-for="(cell, j) in row" :key="j" class="py-2 px-2 border-b border-[#f1efe9]" :class="j === 0 ? 'font-mono text-[11.5px]' : ''">{{ cell }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Note / empty state -->
      <div v-if="data?.note && !combined" class="text-[12px] text-[#555] bg-[#faf8f4] border-l-[3px] border-[#C2541E] rounded-r-lg px-3.5 py-2.5 mt-3">
        {{ data.note }}
      </div>
    </template>

    <!-- Run result -->
    <div v-if="runResult" class="mt-4">
      <div v-if="runResult.note" class="text-[12px] text-[#555] bg-[#faf8f4] border-l-[3px] border-[#C2541E] rounded-r-lg px-3.5 py-2.5">
        {{ runResult.note }}
        <span v-if="runResult.disclaimer" class="block text-[10px] text-[#9a958c] mt-1">{{ runResult.disclaimer }}</span>
      </div>
      <template v-else>
        <div v-if="runResult.stats?.length" class="flex gap-3 mb-3">
          <div v-for="s in runResult.stats" :key="s.l" class="flex-1 bg-[#FBF4EF] border border-[#f0ddd0] rounded-[10px] px-3.5 py-2.5">
            <div class="text-lg font-bold text-[#1f2328]">{{ s.n }}</div>
            <div class="text-[10px] text-[#8A4527] uppercase tracking-wide">{{ s.l }}</div>
          </div>
        </div>
        <div v-if="runResult.chips?.length" class="flex flex-wrap gap-2 mb-3">
          <span v-for="(c, i) in runResult.chips" :key="i" class="text-[12px] text-[#1f2328] bg-white border border-[#E9E0D3] rounded-full px-3 py-1">{{ c }}</span>
        </div>
        <div v-if="runResult.table?.rows?.length" class="bg-white border border-[#E9E0D3] rounded-xl p-4 mb-3">
          <h3 class="text-[11.5px] font-bold uppercase tracking-wide text-[#6b6b6b] mb-3">{{ runResult.table.title }}</h3>
          <div class="overflow-x-auto">
            <table class="w-full text-[12px]">
              <thead>
                <tr>
                  <th v-for="h in runResult.table.head" :key="h" class="text-left text-[10px] uppercase tracking-wide text-[#9a958c] font-bold py-1.5 px-2 border-b border-[#E9E0D3]">{{ h }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in runResult.table.rows" :key="i">
                  <td v-for="(cell, j) in row" :key="j" class="py-2 px-2 border-b border-[#f1efe9]">{{ cell }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <div v-if="runResult.text" class="text-[12.5px] text-[#444] italic mb-2 max-w-[640px]">{{ runResult.text }}</div>
        <div v-if="runResult.model" class="text-[10px] text-[#9a958c] font-mono">model: {{ runResult.model }}</div>
        <div v-if="runResult.disclaimer" class="text-[10px] text-[#9a958c] mt-1">{{ runResult.disclaimer }}</div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

interface Props {
  studioId?: string
  sources?: any[]
  canEdit?: boolean
  forceLayer?: string
  // Combined tab: expose Scan / Forecast / Find patterns as one panel (insights + forecast + predictions).
  combined?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  studioId: '', sources: () => [], canEdit: false, forceLayer: 'profiler', combined: false,
})

// Static per-layer metadata (glyph/title/desc/flag). Live status + data are fetched.
const META: Record<string, any> = {
  profiler: { glyph: '&#9638;', title: 'Deep Profiler', role: '🤖 agent', flag: 'HYBRID_PROFILE_V2',
    sub: 'Per-column role catalog + value distribution + variant detection',
    desc: 'Classifies every column into a role (DIMENSION / STATE / MEASURE / IDENTIFIER / TEMPORAL), grabs top-3 values + frequency, and flags near-duplicate variants. Stored as profile_v2 and injected as an 80-char/column catalog.' },
  codeenrich: { glyph: '{ }', title: 'Code Enrich', role: '🤖 agent', flag: 'HYBRID_CODE_ENRICH',
    sub: 'Grain & formulas from source — "meaning lives in code"',
    desc: 'Reads view/table DDL + saved-query SQL, then an LLM extracts grain, derived-column formulas, and included/excluded population into pipeline_logic. File sources derive grain from Deep Profiler.' },
  metrics: { glyph: '&#128274;', title: 'Verified Metrics', role: '✅ review', flag: 'HYBRID_VERIFIED_METRICS',
    sub: 'Locked, executable definitions — one truth, drift-tracked',
    desc: 'A locked metric runs its own read-only sql_calc and returns the value, overriding any formula the agent improvises. Marked AUTHORITATIVE in the prompt; drift computed vs the previous run.' },
  lazy: { glyph: '&#8635;', title: 'Lazy Profile / Drift', role: '🤖 agent', flag: 'HYBRID_PROFILE_V2',
    sub: 'Zero-touch schema drift — auto-profiles new tables at query time',
    desc: 'A table added after training has no catalog. On a cache-miss it profiles the table inline (~1.4s cold, 0.1s warm), caches it, and refreshes the prompt — so the next answer is correct.' },
  insights: { glyph: '&#9672;', title: 'Proactive Insights', role: '👤 user', flag: 'HYBRID_PROACTIVE_INSIGHTS',
    sub: 'Anomaly + trend scan on every result',
    desc: 'After each result, scans numeric columns with z-score + IQR and runs a temporal spike detector. Up to 5 insights rendered as chips under the answer. No LLM, fail-soft.' },
  forecast: { glyph: '&#128200;', title: 'Forecasting', role: '👤 user', flag: 'HYBRID_ADV_METHODS',
    sub: 'LLM reasoning over your real monthly series — no statistical model',
    desc: 'Projects the next periods of this agent’s primary time series by LLM reasoning (LLMTime, pinned to Claude reasoning), sampled several times for a low/high range. Grounded on the real Auto-EDA series; every number is stamped an AI estimate. Click Predict to run it live.' },
  golden: { glyph: '&#9733;', title: 'Golden Queries', role: '✅ review', flag: 'HYBRID_GOLDEN_QUERIES',
    sub: 'Promote proven queries — ranked first for reuse',
    desc: 'A learned query becomes GOLDEN on a thumbs-up or after it succeeds verified_count ≥ 2 times. Golden queries are injected first into the codegen prompt so the agent reuses known-good SQL.' },
  search: { glyph: '&#8853;', title: 'Hybrid Search + Knowledge Graph', role: '🤖 agent', flag: 'HYBRID_SEMANTIC_SEARCH',
    sub: 'pgvector + BM25 RRF search + entity graph',
    desc: 'Indexes tables / metrics / queries / docs into knowledge_search_index, searches via full-text + vector + token-Jaccard fused with Reciprocal Rank Fusion, and links entities into a knowledge graph. Reindex to build the index, then search it live.' },
  predictions: { glyph: '&#129504;', title: 'Predictions', role: '🤖 agent', flag: 'HYBRID_ADV_METHODS',
    sub: 'LLM predictors — classify rows (TabLLM) + discover patterns',
    desc: 'Zero-shot prediction by reasoning over your real data — no trained ML model. Find patterns interprets this agent’s computed correlations, segments and rankings (compute-then-narrate). Row classification (TabLLM) runs on a live chat result via the Predict chip. Every output is an AI estimate.' },
  combined: { glyph: '&#9672;', title: 'Insights & Forecasts', role: '👤 user', flag: 'HYBRID_PROACTIVE_INSIGHTS',
    sub: 'Scan anomalies · project the future · surface patterns — live',
    desc: 'One panel for the three predictive layers. Scan runs the anomaly + trend detector over your latest results, Forecast projects the next periods of your primary time series by LLM reasoning, and Find patterns interprets computed correlations, segments and rankings. Every projected number is an AI estimate.' },
}

const M = computed(() => (props.combined ? META.combined : (META[props.forceLayer] || META.profiler)))

// Per-layer run-buttons. kind: 'run' = POST /run · 'search' = query box + POST ·
// 'refresh' = re-fetch the layer (tabs that already render real data).
const ACTIONS: Record<string, any[]> = {
  forecast:    [{ key: 'run', label: 'Predict', kind: 'run' }],
  insights:    [{ key: 'scan', label: 'Scan now', kind: 'run' },
                { key: 'scan', label: 'Scan + explain', kind: 'run', params: { explain: true } }],
  predictions: [{ key: 'discover', label: 'Find patterns', kind: 'run' }],
  search:      [{ key: 'reindex', label: 'Reindex', kind: 'run' },
                { key: 'search', label: 'Search', kind: 'search' }],
  profiler:    [{ key: '', label: 'Refresh', kind: 'refresh' }],
  codeenrich:  [{ key: '', label: 'Refresh', kind: 'refresh' }],
  metrics:     [{ key: '', label: 'Refresh', kind: 'refresh' }],
  golden:      [{ key: '', label: 'Refresh', kind: 'refresh' }],
  lazy:        [{ key: '', label: 'Refresh', kind: 'refresh' }],
}
// Combined tab: three run buttons, each targets its own layer via `layer`.
const COMBINED_ACTS = [
  { key: 'scan', label: 'Scan', kind: 'run', layer: 'insights' },
  { key: 'run', label: 'Forecast', kind: 'run', layer: 'forecast' },
  { key: 'discover', label: 'Find patterns', kind: 'run', layer: 'predictions' },
]
const acts = computed(() => (props.combined ? COMBINED_ACTS : (ACTIONS[props.forceLayer] || [])))

const data = ref<any>(null)
const loading = ref(false)
const enabled = ref(false)
const toggling = ref(false)
const toggleErr = ref('')
const runResult = ref<any>(null)
const running = ref('')
const query = ref('')

async function runAction(a: any) {
  if (a.kind === 'refresh') { runResult.value = null; return loadLayer() }
  running.value = a.label
  runResult.value = null
  try {
    const params: any = { ...(a.params || {}) }
    if (a.kind === 'search') params.query = query.value
    const layer = a.layer || props.forceLayer
    const { data: d, error } = await useMyFetch<any>(
      `/intelligence/layer/${layer}/run`,
      { method: 'POST', body: { studio_id: props.studioId || '', action: a.key, params } }
    )
    if (error.value) throw error.value
    runResult.value = d.value || { ok: false, note: 'No response.' }
  } catch {
    runResult.value = { ok: false, note: 'Run failed — please retry.' }
  } finally {
    running.value = ''
  }
}

async function loadLayer() {
  loading.value = true
  try {
    const sid = encodeURIComponent(props.studioId || '')
    const { data: d, error } = await useMyFetch<any>(
      `/intelligence/layer/${props.forceLayer}?studio_id=${sid}`, { method: 'GET' }
    )
    if (error.value) throw error.value
    data.value = d.value || null
    enabled.value = !!(d.value && d.value.enabled)
  } catch {
    data.value = { note: 'Data temporarily unavailable.' }
  } finally {
    loading.value = false
  }
}

async function toggle() {
  if (!props.canEdit || toggling.value) return
  toggleErr.value = ''
  toggling.value = true
  const next = !enabled.value
  try {
    const { error } = await useMyFetch(`/organization/hybrid-flags/${M.value.flag}`, {
      method: 'PUT', body: { enabled: next },
    })
    if (error.value) throw error.value
    enabled.value = next
    // refresh data now that the flag changed
    await loadLayer()
  } catch {
    toggleErr.value = 'Could not change the flag (needs manage_settings).'
  } finally {
    toggling.value = false
  }
}

watch(() => props.forceLayer, () => { runResult.value = null; query.value = ''; loadLayer() })
onMounted(loadLayer)
</script>
