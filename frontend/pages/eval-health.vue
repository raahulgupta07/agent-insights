<template>
  <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
    <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto text-[#1f2328]">

      <!-- Header -->
      <div class="flex items-start justify-between gap-4 mb-5">
        <div>
          <h1
            class="text-2xl font-semibold text-[#1f2328] tracking-tight"
            style="font-family: 'Spectral', ui-serif, Georgia, serif"
          >Eval Canary Health</h1>
          <p class="mt-1.5 text-[#7c7368] leading-relaxed max-w-2xl">
            Continuous health of the nightly result-set goldens: per-golden pass-rate,
            last run, and drift alerts when a golden that used to pass starts failing.
          </p>
        </div>
        <button
          class="shrink-0 px-3 py-1.5 rounded-lg border border-[#E9E0D3] bg-white hover:bg-[#F6F1EA] text-[#3f3a33]"
          :disabled="loading"
          @click="loadAll"
        >{{ loading ? 'Refreshing…' : 'Refresh' }}</button>
      </div>

      <!-- Disabled state -->
      <div v-if="disabled" class="rounded-xl border border-[#E9E0D3] bg-[#F6F1EA] px-4 py-6 text-[#7c7368]">
        Eval canary is off. Enable <b>HYBRID_EVAL_CANARY</b> to surface golden health here.
      </div>

      <template v-else>
        <!-- Drift alerts -->
        <div v-if="drift.length" class="mb-6">
          <h2 class="text-[13px] font-semibold uppercase tracking-wide text-[#a8330f] mb-2">
            Drift alerts ({{ drift.length }})
          </h2>
          <div
            v-for="d in drift"
            :key="d.case_id"
            class="mb-2 rounded-xl border border-[#e6b8a3] bg-[#FBEFE4] px-4 py-3"
          >
            <div class="font-medium text-[#1f2328]">{{ d.case_name || d.case_id }}</div>
            <div class="text-[#7c7368] mt-0.5">
              Regressed
              <span class="font-medium text-[#3f9e6a]">{{ d.prev_status }}</span>
              &rarr;
              <span class="font-medium text-[#a8330f]">{{ d.now_status }}</span>
              vs last green run.
            </div>
          </div>
        </div>

        <!-- Health table -->
        <h2 class="text-[13px] font-semibold uppercase tracking-wide text-[#7c7368] mb-2">
          Goldens ({{ tables.length }})
        </h2>

        <div v-if="!tables.length && !loading" class="rounded-xl border border-[#E9E0D3] bg-[#F6F1EA] px-4 py-6 text-[#7c7368]">
          No result-set goldens yet. Bless a good answer (thumbs-up) to create one.
        </div>

        <div v-else class="overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="text-[12px] uppercase tracking-wide text-[#a89a88]">
                <th class="py-2 pr-4 font-medium">Golden</th>
                <th class="py-2 px-3 font-medium">Pass rate</th>
                <th class="py-2 px-3 font-medium">Last run</th>
                <th class="py-2 px-3 font-medium">Runs</th>
                <th class="py-2 px-3 font-medium">Trend</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="t in tables"
                :key="t.case_id"
                class="border-t border-[#EFE7DB]"
              >
                <td class="py-2.5 pr-4 max-w-[360px]">
                  <div class="truncate text-[#1f2328]" :title="t.name">{{ t.name }}</div>
                </td>
                <td class="py-2.5 px-3">
                  <span
                    class="inline-flex items-center px-2 py-0.5 rounded-full text-[12px] font-medium"
                    :class="rateClass(t)"
                  >{{ ratePct(t) }}</span>
                </td>
                <td class="py-2.5 px-3">
                  <span
                    class="inline-flex items-center px-2 py-0.5 rounded-full text-[12px] font-medium"
                    :class="statusClass(t.last_status)"
                  >{{ t.last_status || 'never' }}</span>
                  <span class="ml-2 text-[12px] text-[#a89a88]">{{ fmtDate(t.last_run_at) }}</span>
                </td>
                <td class="py-2.5 px-3 text-[#7c7368]">{{ t.runs }}</td>
                <td class="py-2.5 px-3">{{ trendIcon(t.trend) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ auth: true, layout: 'default' })

interface HealthRow {
  case_id: string
  name: string
  data_source_ids: string[]
  runs: number
  passes: number
  pass_rate: number
  last_status: string | null
  last_run_at: string | null
  trend: string
}
interface DriftRow {
  case_id: string
  case_name: string | null
  prev_status: string
  now_status: string
}

const tables = ref<HealthRow[]>([])
const drift = ref<DriftRow[]>([])
const disabled = ref(false)
const loading = ref(false)

async function loadAll() {
  loading.value = true
  try {
    const [h, d] = await Promise.all([
      useMyFetch<any>('/eval/canary/health', { method: 'GET' }),
      useMyFetch<any>('/eval/canary/drift', { method: 'GET' }),
    ])
    const hd = (h as any).data?.value ?? (h as any).data
    const dd = (d as any).data?.value ?? (d as any).data
    disabled.value = hd && hd.enabled === false
    tables.value = (hd && hd.tables) || []
    drift.value = (dd && dd.drift) || []
  } catch (e) {
    // fail-soft: leave whatever we have
  } finally {
    loading.value = false
  }
}

function ratePct(t: HealthRow): string {
  if (!t.runs) return '—'
  return Math.round((t.pass_rate || 0) * 100) + '%'
}
function rateClass(t: HealthRow): string {
  if (!t.runs) return 'bg-[#EFE7DB] text-[#7c7368]'
  const r = t.pass_rate || 0
  if (r >= 0.9) return 'bg-[#e3f2e9] text-[#2f7d52]'
  if (r >= 0.6) return 'bg-[#fbeecf] text-[#8a6d1f]'
  return 'bg-[#fbe0d6] text-[#a8330f]'
}
function statusClass(s: string | null): string {
  if (s === 'pass') return 'bg-[#e3f2e9] text-[#2f7d52]'
  if (s === 'fail' || s === 'error') return 'bg-[#fbe0d6] text-[#a8330f]'
  return 'bg-[#EFE7DB] text-[#7c7368]'
}
function trendIcon(t: string): string {
  if (t === 'up') return '▲ up'
  if (t === 'down') return '▼ down'
  if (t === 'new') return '• new'
  return '— flat'
}
function fmtDate(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return ''
  }
}

onMounted(loadAll)
</script>
