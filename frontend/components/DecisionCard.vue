<template>
  <!-- Sense-Making "Decision" card — renders ONLY when a sense_making object is present.
       Leads the answer with a triage-ready headline + findings (what / so-what / now-what)
       + alerts. Absent data -> renders nothing (defensive optional chaining everywhere).
       `compact` -> a condensed variant for narrow side panels (Outputs). The `sense` data
       contract is FROZEN — this component is read-only over it. -->
  <div
    v-if="hasData"
    class="decision-card mb-4 rounded-xl border overflow-hidden"
    :class="frameClass"
  >
    <!-- =========================== COMPACT VARIANT =========================== -->
    <template v-if="compact">
      <div class="px-3 py-3">
        <!-- header: eyebrow + severity + confidence -->
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-[10px] font-bold uppercase tracking-[0.12em] text-[#C2541E]">&#9670; Decision</span>
          <span
            v-if="headline?.severity"
            class="px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide rounded-full border"
            :class="severityPill(headline?.severity)"
          >
            {{ headline?.severity }}
          </span>
          <span v-if="headline?.confidence" class="text-[10px] text-gray-500">
            conf: <b class="text-gray-600">{{ headline?.confidence }}</b>
          </span>
        </div>

        <!-- headline -->
        <h3 v-if="headline?.text" class="mt-1.5 text-[13px] font-semibold text-[#211B14] leading-snug">
          {{ headline?.text }}
        </h3>

        <!-- top-2 moves: only now_what.action -->
        <ul v-if="compactMoves.length" class="mt-2 space-y-1">
          <li
            v-for="(mv, i) in compactMoves"
            :key="i"
            class="flex items-start gap-1.5 text-[11.5px] text-gray-700 leading-snug"
          >
            <span class="flex-none mt-[3px] w-1.5 h-1.5 rounded-full bg-[#0e8a5f]" />
            <span>{{ mv }}</span>
          </li>
        </ul>

        <!-- alerts count -->
        <div v-if="alerts.length" class="mt-2 inline-flex items-center gap-1 text-[10.5px] text-amber-700">
          <Icon name="heroicons-bell-alert" class="w-3 h-3" />
          {{ alerts.length }} alert{{ alerts.length === 1 ? '' : 's' }}
        </div>
      </div>
    </template>

    <!-- ============================ FULL VARIANT ============================ -->
    <template v-else>
      <!-- HEADER -->
      <div class="px-4 pt-3 pb-3">
        <div class="flex items-start gap-2">
          <!-- DECISION label + collapse toggle -->
          <button
            type="button"
            class="flex-none mt-0.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-[#C2541E] hover:text-[#A8330F] select-none"
            @click="collapsed = !collapsed"
            :title="collapsed ? 'Expand' : 'Collapse'"
          >
            <Icon
              :name="collapsed ? 'heroicons-chevron-right' : 'heroicons-chevron-down'"
              class="w-3.5 h-3.5 rtl-flip"
            />
            <span>&#9670; Decision</span>
          </button>

          <!-- severity pill -->
          <span
            v-if="headline?.severity"
            class="flex-none px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide rounded-full border"
            :class="severityPill(headline?.severity)"
          >
            {{ headline?.severity }}
          </span>

          <div class="flex-1" />
        </div>

        <!-- generated_by / model provenance -->
        <div
          v-if="!collapsed && (sense?.generated_by || sense?.model)"
          class="mt-1.5 text-[10px] text-gray-400"
        >
          <span v-if="sense?.generated_by">{{ sense?.generated_by }}</span>
          <template v-if="sense?.generated_by && sense?.model"> &middot; </template>
          <span v-if="sense?.model" class="font-mono">{{ sense?.model }}</span>
        </div>

        <div v-if="!collapsed">
          <!-- headline text -->
          <h3 v-if="headline?.text" class="mt-2 text-[15px] font-semibold text-[#211B14] leading-snug">
            {{ headline?.text }}
          </h3>

          <!-- confidence bar line: confidence · basis · primary metric -->
          <div
            v-if="headline?.confidence || findings.length || headline?.metric"
            class="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11px] text-gray-500"
          >
            <span
              v-if="headline?.confidence"
              class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full border"
              :class="confidencePill(headline?.confidence)"
            >
              <Icon name="heroicons-signal" class="w-3 h-3" />
              confidence <b class="ms-0.5">{{ headline?.confidence }}</b>
            </span>
            <span v-if="findings.length" class="inline-flex items-center gap-1">
              <Icon name="heroicons-light-bulb" class="w-3 h-3 opacity-70" />
              basis <b class="text-gray-600">{{ findings.length }} finding{{ findings.length === 1 ? '' : 's' }}</b>
            </span>
            <span v-if="headline?.metric" class="inline-flex items-center gap-1">
              <Icon name="heroicons-chart-bar" class="w-3 h-3 opacity-70" />
              <span class="text-gray-600">{{ headline?.metric }}</span>
            </span>
          </div>
        </div>
      </div>

      <div v-if="!collapsed">
        <!-- FINDINGS -->
        <div v-if="findings.length" class="px-4 pb-1 space-y-3">
          <div
            v-for="(f, idx) in findings"
            :key="idx"
            class="rounded-lg border bg-white/60 p-3"
            :style="{ borderColor: '#EAE0D2' }"
          >
            <!-- finding head: kind badge + rank + what -->
            <div class="flex items-start gap-2">
              <span
                v-if="f?.kind"
                class="flex-none px-2 py-0.5 text-[10px] font-medium rounded-full border"
                :class="kindClass(f?.kind)"
              >
                {{ kindLabel(f?.kind) }}
              </span>
              <span
                v-if="f?.now_what?.impact_rank != null"
                class="flex-none text-[11px] font-bold text-[#C2541E]"
              >
                #{{ f?.now_what?.impact_rank }}
              </span>
              <span class="text-[13px] font-semibold text-[#211B14] leading-snug">
                {{ f?.what }}
              </span>
            </div>

            <!-- SO WHAT / NOW WHAT — 2-col grid -->
            <div
              v-if="f?.so_what || f?.now_what?.action"
              class="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2"
            >
              <!-- SO WHAT box -->
              <div
                v-if="f?.so_what"
                class="rounded-md bg-[#FAF8F3] border border-[#EAE0D2] px-2.5 py-2"
              >
                <div class="text-[10px] font-bold uppercase tracking-wide text-gray-400 mb-0.5">So what</div>
                <div class="text-[12px] text-gray-700 leading-snug">{{ f?.so_what }}</div>
              </div>
              <!-- NOW WHAT box (green) -->
              <div
                v-if="f?.now_what?.action"
                class="rounded-md bg-[#EAF6F0] border border-[#BFE5D4] px-2.5 py-2"
              >
                <div class="text-[10px] font-bold uppercase tracking-wide text-[#0e8a5f] mb-0.5">Now what</div>
                <div class="text-[12px] text-gray-800 font-medium leading-snug">{{ f?.now_what?.action }}</div>
              </div>
            </div>

            <!-- EVIDENCE chips -->
            <div
              v-if="f?.now_what?.evidence && f?.now_what?.evidence.length"
              class="mt-2 flex flex-wrap items-center gap-1"
            >
              <span class="text-[10px] font-bold uppercase tracking-wide text-gray-400 me-0.5">Evidence</span>
              <span
                v-for="(ev, ei) in f?.now_what?.evidence"
                :key="ei"
                class="px-1.5 py-0.5 text-[10px] font-mono rounded bg-white border border-gray-200 text-gray-600 max-w-[280px] truncate"
                :title="String(ev)"
              >
                {{ ev }}
              </span>
            </div>

            <!-- per-finding confidence pill + cause -->
            <div class="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
              <span
                v-if="f?.now_what?.confidence"
                class="inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] rounded-full border"
                :class="confidencePill(f?.now_what?.confidence)"
              >
                confidence <b>{{ f?.now_what?.confidence }}</b>
              </span>
              <span v-if="f?.cause_hypothesis" class="text-[11px] text-gray-500">
                <span class="font-semibold text-gray-400">cause:</span> {{ f?.cause_hypothesis }}
              </span>
            </div>

            <!-- plain language -->
            <div v-if="f?.plain_language" class="mt-1.5 text-[12px] italic text-gray-500 leading-snug">
              {{ f?.plain_language }}
            </div>
          </div>
        </div>

        <!-- ALERTS table -->
        <div v-if="alerts.length" class="px-4 pb-3 pt-1">
          <div class="text-[10px] font-bold uppercase tracking-wide text-gray-400 mb-1.5">Alerts</div>
          <div class="overflow-x-auto rounded-lg border border-[#EAE0D2] bg-white/60">
            <table class="w-full text-[11px] border-collapse">
              <thead>
                <tr class="text-left text-gray-400 border-b border-[#EAE0D2]">
                  <th class="font-medium px-2 py-1.5">Rule</th>
                  <th class="font-medium px-2 py-1.5">Metric</th>
                  <th class="font-medium px-2 py-1.5">Value</th>
                  <th class="font-medium px-2 py-1.5">Threshold</th>
                  <th class="font-medium px-2 py-1.5">Severity</th>
                  <th class="font-medium px-2 py-1.5">Action</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="(a, idx) in alerts"
                  :key="idx"
                  class="border-b border-[#F0E9DD] last:border-0 align-top"
                >
                  <td class="px-2 py-1.5 text-gray-700">{{ a?.rule ?? '—' }}</td>
                  <td class="px-2 py-1.5 text-gray-700">{{ a?.metric ?? '—' }}</td>
                  <td class="px-2 py-1.5 font-mono text-gray-700">{{ a?.value ?? '—' }}</td>
                  <td class="px-2 py-1.5 font-mono text-gray-500">{{ a?.threshold ?? '—' }}</td>
                  <td class="px-2 py-1.5">
                    <span
                      v-if="a?.severity"
                      class="px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide rounded-full border"
                      :class="severityPill(a?.severity)"
                    >{{ a?.severity }}</span>
                    <span v-else class="text-gray-400">—</span>
                  </td>
                  <td class="px-2 py-1.5 text-gray-600">{{ a?.action ?? '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- FOOTER note -->
        <div class="px-4 pb-3 pt-0.5 text-[10px] text-gray-400">
          Grounded on real result data &middot; one cheap LLM pass &middot; flag-gated.
        </div>
      </div>
    </template>
  </div>
</template>

<script lang="ts" setup>
import { computed, ref } from 'vue'

const props = withDefaults(defineProps<{
  /** Backend-attached sense_making object on completion.completion.sense_making. FROZEN contract. */
  sense?: Record<string, any> | null
  /** Condensed variant for narrow side panels (Outputs). Default false = full detail. */
  compact?: boolean
}>(), {
  sense: null,
  compact: false,
})

const collapsed = ref(false)

const headline = computed(() => props.sense?.headline ?? null)

const hasData = computed(() =>
  !!(props.sense && (props.sense.headline || (Array.isArray(props.sense.findings) && props.sense.findings.length)))
)

const findings = computed<any[]>(() => {
  const raw = props.sense?.findings
  if (!Array.isArray(raw)) return []
  // Sort ascending by impact_rank defensively (already ordered backend-side).
  return [...raw].sort((a, b) => {
    const ra = a?.now_what?.impact_rank ?? 999
    const rb = b?.now_what?.impact_rank ?? 999
    return ra - rb
  })
})

const alerts = computed<any[]>(() => {
  const raw = props.sense?.alerts
  return Array.isArray(raw) ? raw : []
})

// Compact: top-2 findings' actions only (bullet moves).
const compactMoves = computed<string[]>(() =>
  findings.value
    .slice(0, 2)
    .map(f => f?.now_what?.action)
    .filter(a => a && String(a).trim())
    .map(a => String(a))
)

// Optimization #11 — only the strong red/amber frame for critical/watch; calm for the rest.
const frameClass = computed(() => {
  const sev = String(headline.value?.severity || 'neutral').toLowerCase()
  if (sev === 'critical') return 'border-red-200 bg-red-50/40'
  if (sev === 'watch') return 'border-amber-200 bg-amber-50/40'
  if (sev === 'positive') return 'border-green-200 bg-green-50/30'
  return 'border-[#EAE0D2] bg-[#FAF8F3]'
})

function severityPill(sev?: string): string {
  const s = String(sev || '').toLowerCase()
  if (s === 'critical') return 'border-red-200 bg-red-100 text-red-700'
  if (s === 'watch' || s === 'warning') return 'border-amber-200 bg-amber-100 text-amber-700'
  if (s === 'positive') return 'border-green-200 bg-green-100 text-green-700'
  return 'border-gray-200 bg-gray-100 text-gray-600'
}

function confidencePill(conf?: string): string {
  const c = String(conf || '').toLowerCase()
  if (c === 'high') return 'border-green-200 bg-green-50 text-green-700'
  if (c === 'med' || c === 'medium') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (c === 'low') return 'border-gray-200 bg-gray-50 text-gray-500'
  return 'border-gray-200 bg-gray-50 text-gray-500'
}

function kindClass(kind?: string): string {
  const k = String(kind || '').toLowerCase()
  if (k === 'risk' || k === 'anomaly') return 'border-red-200 bg-red-50 text-red-600'
  if (k === 'threshold' || k === 'trend_change') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (k === 'opportunity') return 'border-green-200 bg-green-50 text-green-700'
  return 'border-gray-200 bg-gray-50 text-gray-600'
}

function kindLabel(kind?: string): string {
  return String(kind || '').replace(/_/g, ' ')
}
</script>

<style scoped>
.decision-card {
  /* warm app theme; matches #FAF8F3 surfaces + coral #C2541E accent used app-wide */
  font-size: 13px;
}
.rtl-flip {
  /* mirror chevrons under RTL, matching the rest of the app's icon convention */
}
</style>
