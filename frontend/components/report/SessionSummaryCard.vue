<template>
  <!-- Pinned Session Summary: one synthesis rolled up across every turn, sits ABOVE
       the per-turn OutputsFeed. Fail-soft over every missing field. Renders nothing
       (or a slim build prompt) when there is no summary yet. -->

  <!-- Empty / build-prompt state: no summary cached yet. -->
  <div
    v-if="!hasSummary"
    class="rounded-[15px] border border-[#E8C9B5] bg-[#FBF7F0] px-4 py-3"
  >
    <div class="flex items-center gap-2.5">
      <span class="w-6 h-6 rounded-lg flex items-center justify-center text-white text-[12px] flex-none bg-gradient-to-br from-[#C2541E] to-[#A8330F]">✦</span>
      <div class="min-w-0 flex-1">
        <div class="text-[12px] font-extrabold tracking-wide text-[#A8330F]">SESSION SUMMARY</div>
        <div class="text-[11px] text-[#9A8F80] leading-snug">A synthesis across every turn — pinned at the top.</div>
      </div>
      <button
        class="text-[11px] font-bold text-[#C2541E] border border-[#E8C9B5] bg-[#F6EFEA] rounded-lg px-2.5 py-1.5 hover:bg-[#F0E2D2] transition-colors disabled:opacity-50 flex items-center gap-1.5 flex-none"
        :disabled="loading"
        @click="$emit('refresh')"
      >
        <span v-if="loading" class="inline-block w-3 h-3 rounded-full border-2 border-[#E8C9B5] border-t-[#C2541E] animate-spin"></span>
        <span>{{ loading ? 'Generating…' : 'Generate summary' }}</span>
      </button>
    </div>
  </div>

  <!-- Populated card -->
  <div
    v-else
    class="rounded-[15px] border border-[#E8C9B5] overflow-hidden"
    style="background:linear-gradient(#fffdf9,#FBF4EC);box-shadow:0 6px 18px rgba(168,51,15,.06)"
  >
    <!-- HEADER -->
    <div class="flex items-center gap-2.5 px-4 py-3 border-b border-[#F0E2D2]">
      <span class="w-[26px] h-[26px] rounded-lg flex items-center justify-center text-white text-[14px] flex-none bg-gradient-to-br from-[#C2541E] to-[#A8330F]">✦</span>
      <span class="font-extrabold tracking-wide text-[13px] text-[#A8330F]">SESSION SUMMARY</span>
      <span class="text-[9px] font-extrabold tracking-wider text-[#9a6b1a] bg-[#fdf3df] border border-[#f0d6a0] rounded-md px-1.5 py-0.5">PINNED</span>
      <div class="ml-auto flex items-center gap-2">
        <span v-if="stale" class="text-[10px] font-bold text-[#9a6b1a] flex items-center gap-1">
          <span class="w-1.5 h-1.5 rounded-full bg-[#d99a2b]"></span>stale
        </span>
        <button
          class="text-[11px] font-bold text-[#C2541E] border border-[#E8C9B5] bg-[#F6EFEA] rounded-lg px-2.5 py-1 hover:bg-[#F0E2D2] transition-colors disabled:opacity-50 flex items-center gap-1.5"
          :disabled="loading"
          @click="$emit('refresh')"
        >
          <span v-if="loading" class="inline-block w-3 h-3 rounded-full border-2 border-[#E8C9B5] border-t-[#C2541E] animate-spin"></span>
          <span v-else>↻</span>
          <span>{{ loading ? 'Refreshing…' : 'Refresh' }}</span>
        </button>
      </div>
    </div>

    <!-- BODY -->
    <div class="px-4 py-3.5">
      <h3 v-if="summary.headline" class="m-0 mb-1.5 text-[15px] leading-snug font-semibold text-[#211B14]">
        {{ summary.headline }}
      </h3>
      <div v-if="scopeLine" class="text-[11px] text-[#9A8F80] mb-3">{{ scopeLine }}</div>

      <!-- DECISION line -->
      <div
        v-if="decision"
        class="rounded-[9px] bg-white border border-[#f0d6a0] border-l-[3px] border-l-[#C2541E] px-3 py-2.5 text-[12.5px] leading-snug text-[#33373c]"
      >
        <span class="font-extrabold text-[#C2541E]">◆ DECISION{{ decision.verb ? ' · ' + decision.verb : '' }}<span v-if="decision.confidence" class="font-bold"> · {{ decision.confidence }}</span>:</span>
        <span class="ml-1">{{ decision.text }}</span>
      </div>

      <!-- Key findings -->
      <div v-if="keyFindings.length" class="mt-3">
        <div class="text-[9px] font-extrabold tracking-[0.1em] uppercase text-[#9A8F80] mb-1.5">Key findings across the session</div>
        <ul class="m-0 ps-[18px] list-disc">
          <li v-for="(f, i) in keyFindings" :key="i" class="text-[12.5px] leading-relaxed text-[#33373c] my-0.5">{{ f }}</li>
        </ul>
      </div>

      <!-- Produced this session -->
      <div v-if="produced.length" class="mt-3">
        <div class="text-[9px] font-extrabold tracking-[0.1em] uppercase text-[#9A8F80] mb-1.5">Produced this session</div>
        <div class="flex flex-wrap gap-1.5">
          <div
            v-for="(p, i) in produced"
            :key="i"
            class="flex items-center gap-1.5 border border-[#EAE0D2] bg-white rounded-lg px-2.5 py-1.5 text-[11.5px] font-semibold text-[#2A2420]"
          >
            <span class="w-[18px] h-[18px] rounded-[5px] flex items-center justify-center text-white text-[10px] flex-none" :class="chipColor(p.type)">{{ chipGlyph(p.type) }}</span>
            <span class="truncate max-w-[160px]">{{ p.title || chipLabel(p.type) }}</span>
            <span
              v-if="isFailed(p.status)"
              class="text-[8px] font-extrabold rounded px-1 py-0.5 bg-[#fde9e9] text-[#b8403a]"
            >FAILED</span>
            <span
              v-else
              class="text-[8px] font-extrabold rounded px-1 py-0.5 bg-[#eaf6ef] text-[#2f8f5b]"
            >OK</span>
          </div>
        </div>
      </div>

      <!-- Suggested next -->
      <div v-if="nextSteps.length" class="mt-3">
        <div class="text-[9px] font-extrabold tracking-[0.1em] uppercase text-[#9A8F80] mb-1.5">Suggested next</div>
        <ul class="m-0 ps-[18px] list-disc">
          <li v-for="(s, i) in nextSteps" :key="i" class="text-[12.5px] leading-relaxed text-[#33373c] my-0.5">{{ s }}</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  // Backend session-summary object, or null when none has been built yet.
  // Shape: { headline, decision:{verb,confidence,text}|null, key_findings:[],
  //          produced:[{type,title,status}], next_steps:[], generated_from:{} }
  summary?: Record<string, any> | null
  // True when newer turns have landed since the summary was built.
  stale?: boolean
  // True while a (re)build is in flight.
  loading?: boolean
}>()

defineEmits(['refresh'])

const hasSummary = computed(() => !!(props.summary && typeof props.summary === 'object'))

const summary = computed<Record<string, any>>(() => (props.summary && typeof props.summary === 'object') ? props.summary : {})

const decision = computed<Record<string, any> | null>(() => {
  const d = summary.value.decision
  if (!d || typeof d !== 'object') return null
  if (!d.text || !String(d.text).trim()) return null
  return d
})

const keyFindings = computed<string[]>(() => {
  const f = summary.value.key_findings
  return Array.isArray(f) ? f.filter((x: any) => x && String(x).trim()) : []
})

const produced = computed<any[]>(() => {
  const p = summary.value.produced
  return Array.isArray(p) ? p.filter((x: any) => x && typeof x === 'object') : []
})

const nextSteps = computed<string[]>(() => {
  const n = summary.value.next_steps
  return Array.isArray(n) ? n.filter((x: any) => x && String(x).trim()) : []
})

// Optional one-line scope ("Synthesised from N turns · …"). Built from
// generated_from when present, fail-soft to nothing.
const scopeLine = computed<string>(() => {
  const g = summary.value.generated_from
  if (!g || typeof g !== 'object') return ''
  const parts: string[] = []
  if (g.turn_count) parts.push(`Synthesised from ${g.turn_count} turn${g.turn_count === 1 ? '' : 's'}`)
  if (g.time_range) parts.push(String(g.time_range))
  if (g.sources) parts.push(String(g.sources))
  if (g.scope) parts.push(String(g.scope))
  return parts.join(' · ')
})

function isFailed(status?: string): boolean {
  return String(status || '').toLowerCase() === 'failed'
}

function chipType(type?: string): string {
  return String(type || '').toLowerCase()
}
function chipColor(type?: string): string {
  switch (chipType(type)) {
    case 'slides': return 'bg-gradient-to-br from-[#d35400] to-[#c0392b]'
    case 'excel': return 'bg-gradient-to-br from-[#27ae60] to-[#1e8449]'
    case 'answer': return 'bg-gradient-to-br from-[#3b82f6] to-[#1d4ed8]'
    default: return 'bg-gradient-to-br from-[#e0a32e] to-[#C2541E]' // dashboard
  }
}
function chipGlyph(type?: string): string {
  switch (chipType(type)) {
    case 'slides': return '▤'
    case 'excel': return '⊞'
    case 'answer': return '✓'
    default: return '▦'
  }
}
function chipLabel(type?: string): string {
  switch (chipType(type)) {
    case 'slides': return 'Slide deck'
    case 'excel': return 'Workbook'
    case 'answer': return 'Answer'
    default: return 'Dashboard'
  }
}
</script>
