<!--
  SmartWorkbookSheet — Smart Excel Build (HYBRID_SMART_WORKBOOK).
  Auto-import name: <DashboardSmartWorkbookSheet> (dir `dashboard` + file `SmartWorkbookSheet`).
  If a bare tag renders blank, explicit-import it (Nuxt <DirX> landmine) + restart dev.

  Opens from the Outputs "Excel" button when the flag is ON. On open it loads the
  workbook context (sheet names + prefill from the last chat turn). The user types
  a transform intent ("pivot revenue by region × month, drop raw ids"), picks which
  sheets to include, and hits Build. The backend converts the intent to a strict
  whitelist transform spec (select/rename/filter/aggregate/pivot/sort) applied in
  pure-Python — no SQL re-run. The result is a download-ready workbook.

  Additive + flag-gated: backend returns {disabled:true} when off → emits `skip`
  and the host falls back to the existing raw workbook dump (setPanelView('excel')).
-->
<template>
  <div v-if="open" class="swb-overlay" @click.self="close">
    <div class="swb-sheet">
      <header class="swb-head">
        <h2>📊 Smart Excel
          <span class="swb-badge">⚡ Auto</span>
        </h2>
        <button class="swb-x" @click="close">✕</button>
      </header>

      <!-- loading context -->
      <div v-if="phase === 'loading'" class="swb-body swb-center">
        <div class="swb-spin"></div>
        <p>Loading workbook context…</p>
      </div>

      <!-- needs data: no grids yet -->
      <div v-else-if="phase === 'needsData'" class="swb-body">
        <div class="swb-warn">{{ message }}</div>
      </div>

      <!-- setup: normal path -->
      <div v-else-if="phase === 'setup'" class="swb-body">
        <label class="swb-lbl">
          Describe how to transform the data
          <span class="swb-sub">— e.g. pivot revenue by region × month, drop raw ids</span>
        </label>
        <textarea v-model="prompt" class="swb-ta" rows="3"
          placeholder="pivot revenue by region × month, drop raw ids, sort by total desc"></textarea>

        <div v-if="sheetOptions.length > 1" class="swb-sheets">
          <div class="swb-slbl">Sheets to include</div>
          <label v-for="s in sheetOptions" :key="s.name" class="swb-srow">
            <input type="checkbox" v-model="s.checked" class="swb-chk" />
            <span class="swb-sname">{{ s.name }}</span>
            <span class="swb-smeta">{{ s.cols }} cols · {{ s.rows }} rows</span>
          </label>
        </div>
      </div>

      <!-- building -->
      <div v-else-if="phase === 'building'" class="swb-body swb-center">
        <div class="swb-spin"></div>
        <div class="swb-wave">⚡ Auto · transforming…</div>
        <p class="swb-step">{{ buildStep }}</p>
      </div>

      <!-- done -->
      <div v-else-if="phase === 'done'" class="swb-body">
        <div class="swb-tick-row">
          <div class="swb-tick">✓</div>
          <p>Workbook transformed. {{ resultSheets.length }} sheet{{ resultSheets.length !== 1 ? 's' : '' }}.</p>
        </div>
        <div class="swb-result">
          <div v-for="s in resultSheets" :key="s.name" class="swb-srow swb-sdone">
            <span class="swb-sname">{{ s.name }}</span>
            <span class="swb-smeta">{{ s.columns.length }} cols · {{ s.rows.length }} rows</span>
          </div>
        </div>
        <p v-if="specNote" class="swb-note-inline">{{ specNote }}</p>
      </div>

      <!-- error -->
      <div v-else-if="phase === 'error'" class="swb-body">
        <div class="swb-warn">{{ error }}</div>
      </div>

      <footer class="swb-foot">
        <div class="swb-fn">{{ footNote }}</div>
        <div class="swb-fbtns">
          <button class="swb-ghost" @click="close">Close</button>
          <button v-if="phase === 'setup'" class="swb-primary" :disabled="!prompt.trim() || building" @click="build">
            Build →
          </button>
          <button v-else-if="phase === 'done'" class="swb-primary" @click="openRaw">
            View in Excel tab
          </button>
          <button v-else-if="phase === 'needsData' || phase === 'error'" class="swb-ghost" @click="phase = 'setup'">
            Back
          </button>
        </div>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  reportId: { type: String, required: true },
  open:     { type: Boolean, default: false },
})
const emit = defineEmits(['close', 'built', 'skip'])

const phase      = ref('loading')   // loading|setup|building|done|needsData|error
const prompt     = ref('')
const sheetOptions = ref([])        // [{name, rows, cols, checked}]
const resultSheets = ref([])
const specNote   = ref('')
const message    = ref('')
const error      = ref('')
const building   = ref(false)
const buildStep  = ref('Analysing schema…')

const footNote = computed(() => ({
  loading:  'Reading sheet structure…',
  setup:    'Transforms run on existing data — no re-query.',
  building: 'Applying transform spec…',
  done:     'Open the Excel tab to download the workbook.',
  needsData:'No data yet — ask the agent a data question first.',
  error:    'Something went wrong.',
}[phase.value] || ''))

watch(() => props.open, async (v) => { if (v) await loadContext() })

async function loadContext() {
  phase.value = 'loading'
  prompt.value = ''
  sheetOptions.value = []
  resultSheets.value = []
  error.value = ''
  specNote.value = ''
  try {
    const res = await useMyFetch(`/reports/${props.reportId}/workbook/context`)
    const d = res?.data?.value ?? res
    if (d?.disabled) { emit('skip'); return }
    if (!d?.ok) { error.value = d?.error || 'could not load context'; phase.value = 'error'; return }
    sheetOptions.value = (d.sheets || []).map(s => ({ ...s, checked: true }))
    prompt.value = d.prefill || ''
    if (sheetOptions.value.length === 0) {
      message.value = 'Ask the agent a data question first so it builds the result tables, then smart-build the workbook from them.'
      phase.value = 'needsData'
      return
    }
    phase.value = 'setup'
  } catch (e) {
    error.value = (e && e.message) || 'could not load context'
    phase.value = 'error'
  }
}

async function build() {
  if (!prompt.value.trim()) return
  building.value = true
  phase.value = 'building'
  cycleSteps()
  try {
    const selectedSheets = sheetOptions.value.filter(s => s.checked).map(s => s.name)
    const res = await useMyFetch(`/reports/${props.reportId}/workbook/smart-build`, {
      method: 'POST',
      body: {
        prompt: prompt.value,
        sheets: selectedSheets.length ? selectedSheets : null,
      },
    })
    const d = res?.data?.value ?? res
    if (d?.disabled) { emit('skip'); return }
    if (d?.needs_data) { message.value = d.message; phase.value = 'needsData'; return }
    if (!d?.ok) { error.value = d?.error || 'build failed'; phase.value = 'error'; return }
    resultSheets.value = d.sheets || []
    specNote.value = d.note || ''
    phase.value = 'done'
    emit('built', { sheets: resultSheets.value })
  } catch (e) {
    error.value = (e && e.message) || 'build failed'
    phase.value = 'error'
  } finally {
    building.value = false
  }
}

function cycleSteps() {
  const steps = ['Analysing schema…', 'Planning transforms…', 'Applying spec…', 'Finalising…']
  let i = 0
  const iv = setInterval(() => {
    if (phase.value !== 'building') { clearInterval(iv); return }
    i = (i + 1) % steps.length
    buildStep.value = steps[i]
  }, 900)
}

function openRaw() {
  emit('built', { sheets: resultSheets.value })
  close()
}

function close() { emit('close') }
</script>

<style scoped>
.swb-overlay{position:fixed;inset:0;background:rgba(20,16,12,.55);display:flex;align-items:center;justify-content:center;z-index:120;padding:24px}
.swb-sheet{background:#FFFDF9;color:#211B14;width:min(620px,96vw);max-height:88vh;display:flex;flex-direction:column;border-radius:18px;box-shadow:0 18px 60px rgba(0,0,0,.3);overflow:hidden}
.swb-head{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:16px 20px;border-bottom:1px solid #E2D6C5}
.swb-head h2{font-family:'Spectral',Georgia,serif;font-size:18px;margin:0;display:flex;align-items:center;gap:8px}
.swb-badge{background:#C2541E;color:#fff;font-weight:700;font-size:11px;padding:2px 9px;border-radius:20px}
.swb-x{border:none;background:transparent;font-size:17px;cursor:pointer;color:#6b5f50}
.swb-body{padding:18px 20px;overflow-y:auto;flex:1}
.swb-center{text-align:center;color:#6b5f50}
.swb-lbl{display:block;font-size:13px;font-weight:600;margin-bottom:4px}
.swb-sub{color:#8a7a5f;font-weight:400}
.swb-ta{width:100%;min-height:72px;border:1px solid #E2D6C5;border-radius:10px;padding:10px 12px;font-family:inherit;font-size:14px;resize:vertical;box-sizing:border-box;margin-bottom:14px}
.swb-sheets{border:1px solid #E2D6C5;border-radius:10px;padding:10px 12px}
.swb-slbl{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#6b5f50;margin-bottom:8px}
.swb-srow{display:flex;align-items:center;gap:8px;padding:4px 0}
.swb-sdone{border-top:1px solid #F0E9DC;padding-top:6px;margin-top:2px}
.swb-chk{accent-color:#C2541E}
.swb-sname{font-size:13px;font-weight:600;flex:1}
.swb-smeta{font-size:11px;color:#8a7a5f}
.swb-warn{background:#FBEFE4;border:1px solid #E7C9A8;color:#8a4b1e;border-radius:10px;padding:12px 14px;font-size:14px}
.swb-spin{width:32px;height:32px;border:3px solid #E2D6C5;border-top-color:#C2541E;border-radius:50%;margin:8px auto 12px;animation:swbsp .8s linear infinite}
@keyframes swbsp{to{transform:rotate(360deg)}}
.swb-wave{font-size:13px;color:#3a3127;font-weight:600}
.swb-step{font-size:12px;color:#8a7a5f}
.swb-tick-row{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.swb-tick{width:36px;height:36px;flex-shrink:0;border-radius:50%;background:#2E7D52;color:#fff;font-size:20px;display:flex;align-items:center;justify-content:center}
.swb-result{border:1px solid #E2D6C5;border-radius:10px;padding:8px 12px;margin-top:8px}
.swb-note-inline{font-size:12px;color:#8a7a5f;margin-top:8px}
.swb-foot{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:13px 20px;border-top:1px solid #E2D6C5;flex-shrink:0}
.swb-fn{font-size:12px;color:#8a7a5f}
.swb-fbtns{display:flex;gap:8px}
.swb-ghost{background:transparent;border:1px solid #D8CBB8;border-radius:9px;padding:8px 15px;cursor:pointer;color:#3a3127;font-size:13px}
.swb-primary{background:#C2541E;border:none;color:#fff;border-radius:9px;padding:8px 17px;font-weight:600;cursor:pointer;font-size:13px}
.swb-primary:disabled{opacity:.55;cursor:default}
</style>
