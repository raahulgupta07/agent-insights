<template>
  <div class="cai-cli">
    <!-- header: robot mascot + title -->
    <div class="cai-cli-head">
      <svg class="cai-bot" viewBox="0 0 44 44" fill="none" aria-hidden="true">
        <rect x="7" y="12" width="30" height="24" rx="8" fill="#211B14" stroke="#C2541E" stroke-width="1.6" />
        <circle cx="17" cy="24" r="3.4" fill="#F2C811"><animate attributeName="r" values="3.4;1;3.4" dur="3.2s" repeatCount="indefinite" /></circle>
        <circle cx="27" cy="24" r="3.4" fill="#33C6D6"><animate attributeName="r" values="3.4;1;3.4" dur="3.2s" begin="0.15s" repeatCount="indefinite" /></circle>
        <rect x="20.4" y="4" width="3.2" height="7" rx="1.6" fill="#C2541E" /><circle cx="22" cy="3.4" r="2.4" fill="#E89461" />
        <rect x="16" y="31" width="12" height="2.4" rx="1.2" fill="#3a2e22" />
      </svg>
      <div class="cai-cli-ttl">
        <div class="t">{{ allDone ? 'Your agents are ready' : 'Connecting your Microsoft agents' }}</div>
        <div class="s">One sign-in · Power BI + Fabric · private to you</div>
      </div>
    </div>

    <!-- terminal -->
    <div class="cai-term">
      <div class="cai-term-bar">
        <span class="d" style="background:#ff5f57"></span>
        <span class="d" style="background:#febc2e"></span>
        <span class="d" style="background:#28c840"></span>
        <span class="cai-term-ttl">citybot@insights: <b>~/connect</b></span>
        <span class="cai-pipe">
          <span v-for="a in agents" :key="a.id" class="cai-tag" :class="'cai-tag-' + a.kind">{{ a.label }}</span>
        </span>
      </div>
      <div ref="scrollEl" class="cai-term-body">
        <div v-if="!lines.length" class="cai-boot"><span class="cai-spin">◍</span> starting…</div>
        <div v-for="ln in lines" :key="ln.key" class="cai-ln">
          <span class="cai-who" :class="'cai-who-' + ln.kind">{{ ln.who }}</span>
          <span class="cai-mk" :class="'cai-mk-' + ln.level">
            <span v-if="ln.level === 'active'" class="cai-spin">◍</span>
            <template v-else>{{ glyph(ln.level) }}</template>
          </span>
          <span class="cai-msg">
            <template v-if="ln.table"><span class="cai-tbl">{{ ln.table }}</span> </template>{{ ln.msg }}
          </span>
        </div>
      </div>
    </div>

    <!-- footer: per-agent chips + progress -->
    <div class="cai-cli-foot">
      <div class="cai-chips">
        <span v-for="a in agents" :key="a.id" class="cai-chip" :class="{ on: phaseOf(a.id) === 'done', err: phaseOf(a.id) === 'error' }">
          <span class="s"></span>{{ a.label }}
          <span class="n">{{ tablesLabel(a.id) }}</span>
        </span>
      </div>
      <div class="cai-prog"><i :style="{ width: pct + '%' }"></i></div>
      <button v-if="allDone" class="cai-go" @click="$emit('done')">Done →</button>
    </div>
  </div>
</template>

<script lang="ts" setup>
const props = defineProps<{ agents: { id: string; kind: string; label: string }[] }>()
const emit = defineEmits<{ (e: 'done'): void }>()

// Per-agent live run state, keyed by data_source_id.
const runs = reactive<Record<string, any>>({})
const scrollEl = ref<HTMLElement | null>(null)
let poll: ReturnType<typeof setTimeout> | null = null
let stopped = false
let ticks = 0

function phaseOf(id: string) { return runs[id]?.phase || 'pending' }
function tablesLabel(id: string) {
  const r = runs[id]
  if (!r) return ''
  if (r.phase === 'error') return 'failed'
  const t = r.tables_total || 0
  return t ? `${r.tables_done || 0}/${t} tables` : ''
}

// A short who-tag per agent line: pbi / fabric / city (system steps).
function whoTag(kind: string, level: string) {
  if (level === 'error') return 'city'
  return kind === 'fabric' ? 'fabric' : (kind === 'pbi' ? 'pbi' : 'city')
}

// Merge both agents' logs into one time-sorted stream, tagged by agent.
const lines = computed(() => {
  const out: any[] = []
  for (const a of props.agents) {
    const r = runs[a.id]
    const log = (r?.log || []) as any[]
    log.forEach((l, i) => {
      out.push({
        key: a.id + ':' + i,
        ts: l.ts || '',
        kind: a.kind,
        who: a.kind === 'fabric' ? 'fabric' : a.kind === 'pbi' ? 'pbi' : 'city',
        level: l.level || 'step',
        msg: l.msg || '',
        table: l.table || '',
      })
    })
  }
  out.sort((x, y) => (x.ts < y.ts ? -1 : x.ts > y.ts ? 1 : 0))
  return out
})

const pct = computed(() => {
  if (!props.agents.length) return 0
  let s = 0
  for (const a of props.agents) {
    const r = runs[a.id]
    if (!r) continue
    if (r.phase === 'done' || r.phase === 'error') { s += 100; continue }
    const t = r.tables_total || 0
    const base = { connecting: 10, syncing: 35, learning: 80 }[r.phase] || 5
    const frac = t ? Math.min(1, (r.tables_done || 0) / t) * 40 : 0
    s += Math.min(95, base + frac)
  }
  return Math.round(s / props.agents.length)
})

const allDone = computed(() =>
  props.agents.length > 0 && props.agents.every(a => ['done', 'error'].includes(phaseOf(a.id)))
)

function glyph(level: string) {
  return { ok: '✓', step: '▸', warn: '!', error: '✕' }[level] || '▸'
}

async function pollOnce() {
  if (stopped) return
  ticks++
  await Promise.all(props.agents.map(async (a) => {
    try {
      const { data } = await useMyFetch(`/data_sources/${a.id}/sync-status`, { method: 'GET' })
      const r = (data.value as any) || {}
      if (r && Object.keys(r).length) runs[a.id] = r
    } catch { /* fail-soft; keep last */ }
  }))
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
  if (allDone.value) { stopped = true; return }
  if (ticks > 300) { stopped = true; return }  // ~6min safety
  poll = setTimeout(pollOnce, 1200)
}

onMounted(pollOnce)
onBeforeUnmount(() => { stopped = true; if (poll) clearTimeout(poll) })
</script>

<style scoped>
.cai-cli { display: flex; flex-direction: column; }
.cai-cli-head { display: flex; align-items: center; gap: 11px; padding: 4px 2px 12px; }
.cai-bot { width: 38px; height: 38px; flex: none; }
.cai-cli-ttl .t { font-family: 'Spectral', ui-serif, Georgia, serif; font-size: 16px; font-weight: 600; color: #211B14; }
.cai-cli-ttl .s { font-size: 11px; color: #8A7F70; margin-top: 1px; }

.cai-term { border-radius: 13px; background: linear-gradient(180deg, #17120D, #1F1811); border: 1px solid #0d0a07; overflow: hidden; }
.cai-term-bar { display: flex; align-items: center; gap: 7px; padding: 8px 11px; border-bottom: 1px solid #2b2119; }
.cai-term-bar .d { width: 9px; height: 9px; border-radius: 50%; }
.cai-term-ttl { margin-left: 7px; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; color: #c9bdaa; }
.cai-term-ttl b { color: #fff; }
.cai-pipe { margin-left: auto; display: flex; gap: 5px; }
.cai-tag { font-family: ui-monospace, Menlo, monospace; font-size: 9px; font-weight: 700; padding: 2px 6px; border-radius: 5px; }
.cai-tag-pbi { color: #1a1206; background: rgba(242,200,17,.9); }
.cai-tag-fabric { color: #04211f; background: rgba(51,198,214,.9); }
.cai-term-body { padding: 10px 12px; height: 250px; overflow-y: auto; font-family: ui-monospace, Menlo, monospace; font-size: 12px; line-height: 1.7; }
.cai-term-body::-webkit-scrollbar { width: 7px; }
.cai-term-body::-webkit-scrollbar-thumb { background: #3a2e22; border-radius: 8px; }
.cai-boot { color: #8b7d6b; }
.cai-ln { display: flex; gap: 8px; align-items: baseline; white-space: pre-wrap; animation: cai-in .18s ease; }
@keyframes cai-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
.cai-who { flex: none; width: 50px; text-align: right; font-weight: 700; font-size: 9.5px; padding-top: 1px; }
.cai-who-pbi { color: #F2C811; } .cai-who-fabric { color: #33C6D6; } .cai-who-city { color: #8b7d6b; }
.cai-mk { flex: none; width: 13px; text-align: center; }
.cai-mk-ok { color: #5FCE93; } .cai-mk-step { color: #C2541E; } .cai-mk-warn { color: #E0A44B; } .cai-mk-error { color: #E77; }
.cai-msg { color: #e7ddcd; flex: 1; }
.cai-tbl { color: #fff; font-weight: 600; }
.cai-spin { display: inline-block; color: #C2541E; animation: cai-sp .8s linear infinite; }
@keyframes cai-sp { to { transform: rotate(360deg); } }

.cai-cli-foot { display: flex; align-items: center; gap: 10px; padding: 12px 2px 2px; }
.cai-chips { display: flex; gap: 7px; flex-wrap: wrap; }
.cai-chip { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 600; padding: 5px 10px; border-radius: 9px; border: 1px solid #E9E0D3; background: #FBFAF6; color: #6b6156; }
.cai-chip .s { width: 7px; height: 7px; border-radius: 50%; background: #D8CFC0; }
.cai-chip .n { font-weight: 500; color: #9a958c; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; }
.cai-chip.on { border-color: #cfe6d7; background: #F0F7F2; color: #2F7E50; } .cai-chip.on .s { background: #3FA86B; }
.cai-chip.err { border-color: #ecd2cc; background: #F9EDEA; color: #B4432B; } .cai-chip.err .s { background: #C2541E; }
.cai-prog { flex: 1; height: 6px; border-radius: 99px; background: #EDE7DC; overflow: hidden; }
.cai-prog i { display: block; height: 100%; border-radius: 99px; background: linear-gradient(90deg, #D67037, #A8330F); transition: width .35s; }
.cai-go { border: none; border-radius: 9px; padding: 8px 14px; font-size: 13px; font-weight: 600; background: #C2541E; color: #fff; cursor: pointer; }
.cai-go:hover { background: #A8330F; }
@media (prefers-reduced-motion: reduce) { .cai-ln, .cai-spin { animation: none; } }
</style>
