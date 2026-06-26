<template>
  <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
    <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto">

      <!-- header: serif title + subtitle + readiness ring -->
      <div class="flex items-start justify-between gap-4 mb-1">
        <div>
          <h1 class="text-2xl font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Workflows</h1>
          <p class="text-[#7c7368] mt-0.5 max-w-2xl leading-relaxed">
            Multi-step agent pipelines. You trigger; the agent runs each stage; a judge gate scores every step before it lands.
          </p>
        </div>
        <div v-if="workflows.length" class="shrink-0 text-center">
          <div class="relative w-[54px] h-[54px] mx-auto">
            <svg width="54" height="54" style="transform:rotate(-90deg)">
              <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
              <circle cx="27" cy="27" r="22" stroke="#5A4FCF" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" stroke-dashoffset="0" style="transition:stroke-dashoffset .5s" />
            </svg>
            <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#5A4FCF]" style="font-family: ui-serif, Georgia, serif">{{ workflows.length }}</div>
          </div>
          <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">pipelines</div>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center py-20 text-[#9a958c]">
        <Icon name="heroicons:arrow-path" class="w-5 h-5 animate-spin me-2" />
        <span class="text-sm">Loading workflows…</span>
      </div>

      <!-- Error -->
      <div v-else-if="error" class="mt-4 rounded-2xl border border-[#E9E0D3] bg-[#FBEFE4] p-4 text-sm text-[#A8330F]">
        {{ error }}
        <button
          type="button"
          class="ms-2 rounded-lg px-2 py-0.5 text-xs font-medium text-[#C2541E] hover:bg-white/60"
          @click="fetchWorkflows"
        >
          Retry
        </button>
      </div>

      <template v-else>
        <!-- PIPELINES section card -->
        <div class="relative mt-4 border border-[#E9E0D3] rounded-2xl bg-white p-4">
          <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">PIPELINES</span>

          <!-- Empty state (flag off / none) -->
          <div v-if="workflows.length === 0" class="flex flex-col items-center justify-center py-16 text-center">
            <span class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#ECEAFB] border border-[#E9E0D3] text-[#5A4FCF]">
              <UIcon name="i-heroicons-squares-plus" class="w-6 h-6" />
            </span>
            <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">No workflows available</h3>
            <p class="mt-1 text-sm text-[#9a958c] max-w-md leading-relaxed">
              Enable Workflows in Feature Flags to run multi-step agent pipelines. Each
              pipeline runs a stage per item and a judge gate scores it before it lands.
            </p>
          </div>

          <!-- Workflow card grid -->
          <div v-else class="mt-1.5 grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            <div
              v-for="wf in workflows"
              :key="wf.name"
              class="flex flex-col gap-3 rounded-xl border border-[#E9E0D3] bg-gradient-to-b from-white to-[#fdfcf9] p-4 transition hover:-translate-y-0.5 hover:border-[#5A4FCF] hover:shadow-md h-full"
            >
              <!-- Title row -->
              <div class="flex items-start justify-between gap-2">
                <div class="flex items-center gap-2 text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                  <span class="w-7 h-7 rounded-lg bg-[#ECEAFB] flex items-center justify-center shrink-0"><Icon name="heroicons:squares-2x2" class="w-[15px] h-[15px] text-[#5A4FCF]" /></span>
                  {{ wf.label || wf.name }}
                </div>
                <span
                  v-if="wf.max_concurrency"
                  class="inline-flex items-center gap-1 rounded-full border border-[#E9E0D3] bg-[#ECEAFB] px-2 py-0.5 text-[11px] font-medium text-[#6f67b0] shrink-0"
                >
                  <Icon name="heroicons:bolt" class="w-3 h-3 text-[#5A4FCF]" />
                  {{ wf.max_concurrency }}x
                </span>
              </div>

                        <!-- Description -->
                        <p class="text-xs text-[#6b6b6b] leading-relaxed line-clamp-3">
                            {{ wf.description || '—' }}
                        </p>

                        <!-- Controls -->
                        <div class="flex flex-col gap-2.5 pt-2 border-t border-[#E9E0D3]">
                            <!-- Data source picker -->
                            <label class="flex flex-col gap-1">
                                <span class="text-[11px] font-medium text-[#9a958c]">Data source</span>
                                <USelect
                                    v-model="runState[wf.name].dataSourceId"
                                    :options="dataSourceOptions"
                                    option-attribute="label"
                                    value-attribute="value"
                                    :placeholder="dataSources.length ? 'Select a data source…' : 'No data sources found'"
                                    :disabled="!dataSources.length || isRunning(wf.name)"
                                    size="sm"
                                />
                            </label>

                            <!-- Options row -->
                            <div class="flex items-end gap-3">
                                <label class="flex flex-col gap-1">
                                    <span class="text-[11px] font-medium text-[#9a958c]">Max tables</span>
                                    <UInput
                                        v-model.number="runState[wf.name].maxTables"
                                        type="number"
                                        :min="1"
                                        size="sm"
                                        class="w-24"
                                        :disabled="isRunning(wf.name)"
                                    />
                                </label>
                                <label class="flex items-center gap-2 pb-1.5">
                                    <UToggle
                                        v-model="runState[wf.name].useLlmJudge"
                                        :disabled="isRunning(wf.name)"
                                    />
                                    <span class="text-[11px] font-medium text-[#6b6b6b]">LLM judge</span>
                                </label>
                            </div>

                            <!-- Run button -->
                            <button
                                type="button"
                                class="inline-flex items-center justify-center gap-1.5 rounded-lg bg-[#5A4FCF] px-3 py-2 font-medium text-white transition hover:bg-[#4940b0] disabled:opacity-50 disabled:cursor-not-allowed"
                                :disabled="isRunning(wf.name) || !runState[wf.name].dataSourceId"
                                @click="runWorkflow(wf)"
                            >
                                <Icon
                                    :name="isRunning(wf.name) ? 'heroicons:arrow-path' : 'heroicons:play'"
                                    class="w-4 h-4"
                                    :class="{ 'animate-spin': isRunning(wf.name) }"
                                />
                                {{ isRunning(wf.name) ? 'Running…' : 'Run' }}
                            </button>
                        </div>

                        <!-- Summary (inline result) -->
                        <div
                            v-if="runState[wf.name].summary"
                            class="mt-1 rounded-xl border border-[#E9E0D3] bg-[#F4EEE5] p-3 text-xs"
                        >
                            <div class="flex flex-wrap items-center gap-2 mb-2">
                                <span class="inline-flex items-center gap-1 rounded-full border border-[#d7ebde] bg-[#eef6f0] px-2 py-0.5 font-medium text-[#3f9e6a]">
                                    {{ runState[wf.name].summary.passed ?? 0 }} passed
                                </span>
                                <span
                                    v-if="(runState[wf.name].summary.failed ?? 0) > 0"
                                    class="inline-flex items-center gap-1 rounded-full border border-[#ecd8cb] bg-[#FBEFE4] px-2 py-0.5 font-medium text-[#C2541E]"
                                >
                                    {{ runState[wf.name].summary.failed }} failed
                                </span>
                                <span
                                    v-if="(runState[wf.name].summary.skipped ?? 0) > 0"
                                    class="inline-flex items-center gap-1 rounded-full border border-[#E9E0D3] bg-white px-2 py-0.5 font-medium text-[#6b6b6b]"
                                >
                                    {{ runState[wf.name].summary.skipped }} skipped
                                </span>
                                <span class="ms-auto text-[#9a958c]">
                                    {{ runState[wf.name].summary.processed ?? 0 }} processed
                                </span>
                            </div>
                            <p v-if="runState[wf.name].summary.note" class="text-[#6b6b6b] leading-relaxed">
                                {{ runState[wf.name].summary.note }}
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </template>
      </div>
    </div>
</template>

<script setup lang="ts">
definePageMeta({
    auth: true,
    layout: 'default'
})

interface Workflow {
    name: string
    label?: string
    description?: string
    max_concurrency?: number | null
}

interface WorkflowSummary {
    label?: string
    processed?: number
    passed?: number
    skipped?: number
    failed?: number
    log?: any
    results?: any
    note?: string
}

interface DataSource {
    id: string
    name: string
}

interface RunState {
    dataSourceId: string | null
    maxTables: number
    useLlmJudge: boolean
    running: boolean
    summary: WorkflowSummary | null
}

const toast = useToast()

const workflows = ref<Workflow[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const dataSources = ref<DataSource[]>([])
const dataSourceOptions = computed(() =>
    dataSources.value.map(ds => ({ label: ds.name, value: ds.id }))
)

// Per-workflow run state, keyed by workflow name.
const runState = reactive<Record<string, RunState>>({})

const defaultDsId = computed(() => dataSources.value[0]?.id ?? null)

function ensureState(name: string) {
    if (!runState[name]) {
        runState[name] = {
            dataSourceId: defaultDsId.value,
            maxTables: 25,
            useLlmJudge: false,
            running: false,
            summary: null,
        }
    }
}

function isRunning(name: string) {
    return runState[name]?.running ?? false
}

const fetchWorkflows = async () => {
    loading.value = true
    error.value = null
    try {
        const { data, error: fetchErr } = await useMyFetch<Workflow[]>('/api/workflows', { method: 'GET' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        workflows.value = data.value || []
        for (const wf of workflows.value) {
            ensureState(wf.name)
        }
    } catch (e: any) {
        console.error('Failed to fetch workflows:', e)
        error.value = 'Failed to load workflows.'
    } finally {
        loading.value = false
    }
}

const fetchDataSources = async () => {
    try {
        const { data } = await useMyFetch<DataSource[]>('/api/data_sources', { method: 'GET' })
        dataSources.value = (data.value as DataSource[]) || []
        // Backfill default selection on any state created before sources loaded.
        for (const name of Object.keys(runState)) {
            if (!runState[name].dataSourceId) runState[name].dataSourceId = defaultDsId.value
        }
    } catch (e: any) {
        console.error('Failed to fetch data sources:', e)
    }
}

const runWorkflow = async (wf: Workflow) => {
    const state = runState[wf.name]
    if (!state || !state.dataSourceId || state.running) return

    state.running = true
    state.summary = null
    try {
        const { data, error: fetchErr } = await useMyFetch<WorkflowSummary>(
            `/api/workflows/${wf.name}/run`,
            {
                method: 'POST',
                body: {
                    data_source_id: state.dataSourceId,
                    max_tables: state.maxTables || 25,
                    use_llm_judge: state.useLlmJudge,
                },
            }
        )
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        state.summary = (data.value as WorkflowSummary) || null
        toast.add({
            title: `${wf.label || wf.name} finished`,
            description: state.summary
                ? `${state.summary.passed ?? 0} passed · ${state.summary.failed ?? 0} failed · ${state.summary.skipped ?? 0} skipped`
                : undefined,
            color: 'green',
        })
    } catch (e: any) {
        console.error('Failed to run workflow:', e)
        toast.add({
            title: `${wf.label || wf.name} failed to run`,
            description: 'Check the data source and try again.',
            color: 'red',
        })
    } finally {
        state.running = false
    }
}

onMounted(() => {
    fetchWorkflows()
    fetchDataSources()
})
</script>
