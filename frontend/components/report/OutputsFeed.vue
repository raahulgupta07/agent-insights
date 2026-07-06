<template>
  <!-- Per-turn Outputs feed: every chat turn rendered as Question + Answer + Decision
       + artifact chips, newest on top. Latest turn expanded, older collapsed to the
       one-line header (click header to toggle). Fail-soft over missing data. -->
  <div class="space-y-4">

    <!-- Empty state -->
    <div v-if="!turns.length" class="flex flex-col items-center justify-center h-56 text-gray-400">
      <Icon name="heroicons-document-text" class="w-8 h-8 mb-2" />
      <span class="text-sm">No items yet</span>
    </div>

    <!-- Turn blocks (newest first) -->
    <div
      v-for="(turn, idx) in turns"
      :key="turn.id"
      class="border border-[#EAE0D2] rounded-2xl bg-white overflow-hidden"
    >
      <!-- HEADER (click to toggle) -->
      <div
        class="flex items-center gap-2.5 px-3.5 py-3 cursor-pointer bg-[#FCFAF6] select-none"
        :class="isOpen(turn, idx) ? 'border-b border-[#EAE0D2]' : ''"
        @click="toggle(turn.id)"
      >
        <Icon
          name="heroicons-chevron-down"
          class="w-3.5 h-3.5 text-[#9A8F80] flex-none transition-transform"
          :class="isOpen(turn, idx) ? '' : '-rotate-90'"
        />
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-1.5 text-[13px] font-semibold text-[#2A2420] truncate">
            <span class="flex-none text-[9px] font-extrabold tracking-wide text-[#1d4ed8] bg-[#eaf1fe] rounded px-1.5 py-0.5">ASKED</span>
            <span class="truncate">{{ turn.question || 'Untitled turn' }}</span>
          </div>
          <div class="mt-0.5 flex items-center gap-1.5 text-[11px] text-[#9A8F80]">
            <Icon name="heroicons-clock" class="w-3 h-3 flex-none" />
            <span>{{ relTime(turn.ts) }}</span>
            <span v-if="clockTime(turn.ts)">· {{ clockTime(turn.ts) }}</span>
            <span v-if="turn.autoModel?.model" class="truncate">· routed to {{ turn.autoModel.model }}</span>
          </div>
        </div>
        <!-- type badges -->
        <div class="flex items-center gap-1 flex-none">
          <span v-if="turn.hasDecision" class="text-[9px] font-extrabold uppercase tracking-wide rounded px-1.5 py-0.5 bg-[#F6EFEA] text-[#C2541E]">Decision</span>
          <span v-if="turn.hasAnswer" class="text-[9px] font-extrabold uppercase tracking-wide rounded px-1.5 py-0.5 bg-[#eaf1fe] text-[#1d4ed8]">Answer</span>
          <span v-if="turn.hasDashboard" class="text-[9px] font-extrabold uppercase tracking-wide rounded px-1.5 py-0.5 bg-[#fdf3df] text-[#9a6b1a]">Dashboard</span>
          <span v-if="turn.hasSlides" class="text-[9px] font-extrabold uppercase tracking-wide rounded px-1.5 py-0.5 bg-[#fdeae6] text-[#b8403a]">Slides</span>
        </div>
      </div>

      <!-- BODY -->
      <div v-if="isOpen(turn, idx)" class="p-3.5 space-y-3">
        <!-- in-progress note -->
        <div v-if="turn.inProgress && !turn.answer && !turn.senseMaking" class="flex items-center gap-2 text-[12px] text-[#9A8F80]">
          <span class="inline-block w-3 h-3 rounded-full border-2 border-[#E8C9B5] border-t-[#C2541E] animate-spin"></span>
          Working…
        </div>

        <!-- DECISION card (reused as-is) -->
        <DecisionCard v-if="turn.senseMaking" :sense="turn.senseMaking" :compact="false" />

        <!-- ANSWER card -->
        <section v-if="turn.answer">
          <div class="rounded-xl border border-[#E9E0D3] bg-white shadow-sm px-4 py-3.5">
            <div class="flex items-center gap-2 mb-2">
              <span class="inline-flex items-center text-[10px] font-semibold uppercase tracking-wide text-[#A8330F] bg-[#F6EFEA] px-2 py-0.5 rounded">Answer</span>
            </div>
            <div class="markdown-content text-[13px] text-[#33373c] leading-relaxed">
              <MarkdownRender :content="turn.answer || ''" :final="true" :render-code-blocks-as-pre="true" />
            </div>
          </div>
        </section>

        <!-- ARTIFACT chips -->
        <div v-if="turn.artifacts.length" class="flex flex-wrap gap-2">
          <div
            v-for="art in turn.artifacts"
            :key="art.id"
            class="flex items-center gap-2 border border-[#EAE0D2] rounded-[10px] bg-white px-2.5 py-2 text-[12.5px] font-medium hover:border-[#E8C9B5] transition-colors"
          >
            <span
              class="w-6 h-6 rounded-[7px] flex items-center justify-center text-white text-[12px] flex-none"
              :class="art.mode === 'slides' ? 'bg-gradient-to-br from-[#d35400] to-[#c0392b]' : 'bg-gradient-to-br from-[#e0a32e] to-[#C2541E]'"
            >
              <Icon :name="art.mode === 'slides' ? 'heroicons-presentation-chart-bar' : 'heroicons-squares-2x2'" class="w-3.5 h-3.5" />
            </span>
            <span class="truncate max-w-[180px] text-[#2A2420]">{{ art.title || (art.mode === 'slides' ? 'Slide deck' : 'Dashboard') }}</span>
            <span
              v-if="art.status === 'failed'"
              class="text-[9px] font-extrabold rounded px-1.5 py-0.5 bg-[#fde9e9] text-[#b8403a]"
            >FAILED</span>
            <span
              v-else
              class="text-[9px] font-extrabold rounded px-1.5 py-0.5 bg-[#eaf6ef] text-[#2f8f5b]"
            >OK</span>
            <button
              v-if="art.status === 'failed'"
              class="ml-1 text-[11px] font-semibold text-[#C2541E] hover:text-[#A8330F] flex items-center gap-0.5"
              @click="emit('retryArtifact', { mode: art.mode === 'slides' ? 'slides' : 'page', artifactId: art.id })"
            >
              <Icon name="heroicons-arrow-path-rounded-square" class="w-3 h-3" /> Retry
            </button>
            <button
              v-else
              class="ml-1 text-[11px] font-semibold text-[#C2541E] hover:text-[#A8330F] flex items-center gap-0.5"
              @click="emit('openArtifact', { artifactId: art.id })"
            >
              Open
              <Icon name="heroicons-arrow-top-right-on-square" class="w-3 h-3" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { MarkdownRender } from 'markstream-vue'
import DecisionCard from '~/components/DecisionCard.vue'

const props = defineProps<{
  // The report's chat messages (flat list of user + system completion rows).
  messages?: any[]
  // All report artifacts (from /artifacts/report/{id}) — mode/status/title/created_at/id.
  artifacts?: any[]
}>()

const emit = defineEmits(['openArtifact', 'retryArtifact'])

// ---- per-turn pairing ----
// Walk messages in order: a user row opens a turn, the following system row attaches
// its answer/decision. System-only rows (scheduled/webhook) form their own turn.
const turnsAsc = computed<any[]>(() => {
  const msgs = Array.isArray(props.messages) ? props.messages : []
  const out: any[] = []
  let cur: any = null
  for (const m of msgs) {
    if (!m) continue
    if (m.role === 'user') {
      cur = { id: m.id, question: m?.prompt?.content || '', ts: m.created_at, system: null }
      out.push(cur)
    } else if (m.role === 'system') {
      if (cur && !cur.system) {
        cur.system = m
        if (!cur.ts) cur.ts = m.created_at
      } else {
        out.push({ id: m.id, question: m?.prompt?.content || '', ts: m.created_at, system: m })
        cur = null
      }
    }
  }
  return out
})

// Map artifacts to turns: each artifact → the latest turn created at-or-before it.
// Recency-based, best-effort (exact turn↔artifact links aren't tracked backend-side).
const artifactsByTurn = computed<Record<string, any[]>>(() => {
  const map: Record<string, any[]> = {}
  const arts = Array.isArray(props.artifacts) ? props.artifacts : []
  const ascTurns = turnsAsc.value
  if (!ascTurns.length) return map
  for (const art of arts) {
    if (!art) continue
    const at = new Date(art.created_at || 0).getTime()
    let best: any = null
    for (const t of ascTurns) {
      const tt = new Date(t.ts || 0).getTime()
      if (tt <= at) best = t
    }
    if (!best) best = ascTurns[ascTurns.length - 1]
    if (!map[best.id]) map[best.id] = []
    map[best.id].push(art)
  }
  return map
})

function answerOf(system: any): string {
  try {
    if (!system) return ''
    const blocks = (system.completion_blocks || []).filter((b: any) => b && b.phase !== 'knowledge_harness')
    for (let i = blocks.length - 1; i >= 0; i--) {
      const b = blocks[i]
      if (String(b?.status || '').toLowerCase() === 'error') continue
      if (b?.tool_execution?.tool_name === 'clarify') continue
      if (b?.source_type === 'plan') continue
      const text = b?.content || b?.plan_decision?.final_answer || b?.plan_decision?.assistant
      if (/^\s*\{[\s\S]*"tasks"\s*:/.test(String(text || ''))) continue
      if (text && String(text).trim()) return String(text)
    }
    if (system?.completion?.content && String(system.completion.content).trim()) {
      return String(system.completion.content)
    }
  } catch { /* fail-soft */ }
  return ''
}

// Newest-first, enriched turns.
const turns = computed<any[]>(() => {
  const enriched = turnsAsc.value.map((t) => {
    const sys = t.system
    const answer = answerOf(sys)
    const senseMaking = sys?.sense_making ?? sys?.completion?.sense_making ?? null
    const autoModel = sys?.auto_model ?? null
    const arts = artifactsByTurn.value[t.id] || []
    const hasSlides = arts.some((a: any) => a?.mode === 'slides')
    const hasDashboard = arts.some((a: any) => a && a.mode !== 'slides')
    return {
      id: t.id,
      question: t.question,
      ts: t.ts,
      answer,
      senseMaking,
      autoModel,
      artifacts: arts,
      inProgress: String(sys?.status || '') === 'in_progress',
      hasAnswer: !!(answer && answer.trim()),
      hasDecision: !!(senseMaking && (senseMaking.headline || (Array.isArray(senseMaking.findings) && senseMaking.findings.length))),
      hasDashboard,
      hasSlides,
    }
  })
  return enriched.reverse()
})

// ---- expand / collapse (newest open by default) ----
const userToggled = ref<Record<string, boolean>>({})
function isOpen(turn: any, idx: number): boolean {
  if (turn.id in userToggled.value) return userToggled.value[turn.id]
  return idx === 0
}
function toggle(id: string) {
  const cur = (id in userToggled.value) ? userToggled.value[id] : (turns.value[0]?.id === id)
  userToggled.value = { ...userToggled.value, [id]: !cur }
}

// ---- time helpers ----
function relTime(ts?: string): string {
  if (!ts) return ''
  const diff = Date.now() - new Date(ts).getTime()
  if (Number.isNaN(diff)) return ''
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} h ago`
  const d = Math.floor(h / 24)
  return `${d} d ago`
}
function clockTime(ts?: string): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  } catch { return '' }
}
</script>
