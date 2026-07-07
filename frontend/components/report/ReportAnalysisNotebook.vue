<template>
  <!-- Renders nothing when the feature flag is off, on error, or when there are
       no steps to show — keeps the report page byte-identical in those cases. -->
  <div v-if="loading" class="bg-[#FBFAF6] border border-[#E9E0D3] rounded-xl p-4 mt-3">
    <div class="flex items-center gap-2 text-[12px] text-[#8A4527]">
      <span class="cai-nb-dot" />
      Reading the analysis trail&hellip;
    </div>
  </div>

  <div
    v-else-if="hasSteps"
    class="bg-[#FBFAF6] border border-[#E9E0D3] rounded-xl p-4 mt-3"
  >
    <!-- Header -->
    <div class="flex items-center gap-2 mb-3">
      <div class="w-7 h-7 rounded-[8px] bg-[#F3E3DA] text-[#8A4527] flex items-center justify-center flex-none">
        <Icon name="heroicons:beaker" class="w-4 h-4" />
      </div>
      <div class="min-w-0">
        <div class="text-[13px] font-semibold text-[#211B14] leading-tight">Analysis Notebook</div>
        <div v-if="headline" class="text-[11px] text-[#6b6b6b] leading-tight truncate">{{ headline }}</div>
      </div>
    </div>

    <!-- Steps -->
    <ol class="space-y-2.5">
      <li
        v-for="step in steps"
        :key="step.n"
        class="flex gap-3 bg-white border border-[#f0ddd0] rounded-[10px] px-3 py-2.5"
      >
        <div class="w-5 h-5 rounded-full bg-[#C2541E] text-white text-[11px] font-semibold flex items-center justify-center flex-none mt-0.5">
          {{ step.n }}
        </div>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-[12.5px] font-semibold text-[#211B14]">{{ step.title }}</span>
            <span
              v-if="step.chart"
              class="inline-flex items-center gap-1 text-[9.5px] font-medium px-1.5 py-0.5 rounded bg-[#F3E3DA] text-[#8A4527] border border-[#E8C9B5]"
            >
              <Icon name="heroicons:chart-bar" class="w-2.5 h-2.5 flex-none" />
              {{ chartLabel(step.chart) }}
            </span>
          </div>
          <div v-if="step.did" class="text-[12px] text-[#6b6b6b] mt-0.5 leading-snug">{{ step.did }}</div>
          <div v-if="step.result" class="text-[11px] text-[#8A4527] mt-1 font-mono leading-snug break-words">{{ step.result }}</div>
        </div>
      </li>
    </ol>
  </div>
</template>

<script setup lang="ts">
interface NotebookStep {
  n: number
  title: string
  did?: string
  result?: string
  chart?: string | null
}

const props = defineProps<{
  reportId: string
  completionId?: string
}>()

const loading = ref(false)
const enabled = ref(false)
const headline = ref('')
const steps = ref<NotebookStep[]>([])

const hasSteps = computed(() => enabled.value && steps.value.length > 0)

function chartLabel(chart: string): string {
  return String(chart).replace(/_/g, ' ')
}

async function fetchNotebook() {
  if (!props.reportId) {
    enabled.value = false
    steps.value = []
    return
  }
  loading.value = true
  try {
    const query: Record<string, string> = {}
    if (props.completionId) query.completion_id = props.completionId
    // BARE path — useMyFetch prepends /api and injects auth + org headers.
    const { data, error } = await useMyFetch(`/reports/${props.reportId}/notebook`, {
      method: 'GET',
      query,
    })
    if (error?.value) {
      enabled.value = false
      steps.value = []
      return
    }
    const payload: any = (data as any)?.value || {}
    enabled.value = !!payload.enabled
    headline.value = payload.headline || ''
    steps.value = Array.isArray(payload.steps) ? payload.steps : []
  } catch {
    // Fail-soft: render nothing.
    enabled.value = false
    steps.value = []
  } finally {
    loading.value = false
  }
}

onMounted(fetchNotebook)
watch(() => props.reportId, fetchNotebook)
watch(() => props.completionId, fetchNotebook)
</script>

<style scoped>
.cai-nb-dot {
  width: 7px;
  height: 7px;
  border-radius: 9999px;
  background: #C2541E;
  display: inline-block;
  animation: cai-nb-pulse 1.1s ease-in-out infinite;
}
@keyframes cai-nb-pulse {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1); }
}
</style>
