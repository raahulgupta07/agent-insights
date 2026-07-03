<template>
  <div class="wf-picker">
    <div v-if="loading" class="wf-muted">Loading workflows…</div>

    <div v-else-if="!items.length" class="wf-muted">
      No saved workflows yet. Finish an analysis and choose
      <span class="wf-strong">Save as workflow</span> to reuse it here.
    </div>

    <div v-else class="wf-list">
      <!-- List of workflows -->
      <div v-if="!selected">
        <button
          v-for="w in items"
          :key="w.id"
          class="wf-row"
          type="button"
          @click="select(w)"
        >
          <div class="wf-row-main">
            <span class="wf-name">{{ w.name }}</span>
            <span class="wf-chip">{{ w.scope === 'org' ? 'Shared' : 'Private' }}</span>
          </div>
          <div class="wf-row-sub">
            {{ w.step_count }} step{{ w.step_count === 1 ? '' : 's' }}
            <template v-if="w.params && w.params.length">
              · {{ w.params.length }} param{{ w.params.length === 1 ? '' : 's' }}
            </template>
            <template v-if="w.run_count"> · run {{ w.run_count }}×</template>
          </div>
        </button>
      </div>

      <!-- Param form + run -->
      <div v-else class="wf-run">
        <button class="wf-back" type="button" @click="clearSelection">← Back</button>
        <div class="wf-run-title">{{ selected.name }}</div>

        <div v-if="paramList.length" class="wf-fields">
          <label v-for="p in paramList" :key="p.name" class="wf-field">
            <span class="wf-field-label">{{ p.label || p.name }}</span>
            <input
              v-model="paramValues[p.name]"
              class="wf-input"
              type="text"
              :placeholder="p.name"
            />
          </label>
        </div>
        <div v-else class="wf-muted wf-noparams">This workflow takes no parameters.</div>

        <button class="wf-run-btn" type="button" :disabled="running" @click="run">
          {{ running ? 'Running…' : 'Run workflow' }}
        </button>

        <div v-if="error" class="wf-error">{{ error }}</div>
        <div v-if="result && result.ok" class="wf-result">
          <template v-if="result.background">Running in the background…</template>
          <template v-else>Ran {{ result.steps_run }} step{{ result.steps_run === 1 ? '' : 's' }}.</template>
          <a v-if="result.report_id" class="wf-link" :href="`/reports/${result.report_id}`">
            Open result →
          </a>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'

const emit = defineEmits(['ran', 'close'])

const items = ref([])
const loading = ref(true)
const selected = ref(null)
const paramValues = reactive({})
const running = ref(false)
const error = ref('')
const result = ref(null)

const paramList = computed(() => (selected.value && selected.value.params) || [])

async function load() {
  loading.value = true
  try {
    const { data } = await useMyFetch('/workflows-v2')
    const body = data.value || {}
    items.value = body.enabled ? (body.items || []) : []
  } catch (e) {
    items.value = []
  } finally {
    loading.value = false
  }
}

function select(w) {
  selected.value = w
  error.value = ''
  result.value = null
  for (const k of Object.keys(paramValues)) delete paramValues[k]
  for (const p of w.params || []) paramValues[p.name] = ''
}

function clearSelection() {
  selected.value = null
  error.value = ''
  result.value = null
}

async function run() {
  if (!selected.value) return
  running.value = true
  error.value = ''
  result.value = null
  try {
    const { data, error: fErr } = await useMyFetch(`/workflows-v2/${selected.value.id}/run`, {
      method: 'POST',
      body: { params: { ...paramValues } },
    })
    if (fErr && fErr.value) {
      error.value = fErr.value?.data?.detail || 'Workflow run failed.'
      return
    }
    result.value = data.value || null
    if (result.value && result.value.ok) emit('ran', result.value)
  } catch (e) {
    error.value = 'Workflow run failed.'
  } finally {
    running.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.wf-picker { font-size: 14px; color: #211B14; }
.wf-muted { color: #8a8378; padding: 8px 2px; }
.wf-strong, .wf-name { font-weight: 600; }
.wf-list { display: flex; flex-direction: column; gap: 8px; }
.wf-row {
  width: 100%; text-align: left; background: #FBFAF6; border: 1px solid #E9E0D3;
  border-radius: 12px; padding: 10px 12px; cursor: pointer; transition: border-color .12s;
}
.wf-row:hover { border-color: #C2541E; }
.wf-row-main { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.wf-row-sub { color: #8a8378; font-size: 12px; margin-top: 2px; }
.wf-chip {
  font-size: 11px; color: #A8330F; background: #FBEFE4; border-radius: 999px;
  padding: 1px 8px; white-space: nowrap;
}
.wf-back { background: none; border: none; color: #8a8378; cursor: pointer; padding: 0 0 6px; font-size: 13px; }
.wf-run-title { font-weight: 600; margin-bottom: 10px; }
.wf-fields { display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px; }
.wf-field { display: flex; flex-direction: column; gap: 4px; }
.wf-field-label { font-size: 12px; color: #6b655b; }
.wf-input {
  border: 1px solid #E9E0D3; border-radius: 10px; padding: 8px 10px; font-size: 14px;
  background: #fff; outline: none;
}
.wf-input:focus { border-color: #C2541E; }
.wf-noparams { padding: 0 0 12px; }
.wf-run-btn {
  background: #C2541E; color: #fff; border: none; border-radius: 10px;
  padding: 9px 16px; font-weight: 600; cursor: pointer;
}
.wf-run-btn:disabled { opacity: .6; cursor: default; }
.wf-error { color: #b0341a; margin-top: 10px; font-size: 13px; }
.wf-result { margin-top: 12px; font-size: 13px; }
.wf-link, .wf-link:visited { color: #C2541E; margin-left: 6px; font-weight: 600; text-decoration: none; }
</style>
