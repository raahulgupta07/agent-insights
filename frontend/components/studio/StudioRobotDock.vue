<template>
    <!-- Floating robot mascot pinned bottom-right of the studio page. Click = expand a calm,
         Claude-Code-style terminal with TWO TABS: Terminal (live CLI log, newest at bottom) and
         Stages (checklist of train stages). Header (Working… · model) + footer (tokens/spend/
         elapsed/readiness) stay visible in both tabs. Collapsed = just the robot button.
         All live state comes in via props; this component only owns open/tab/auto-scroll. -->
    <div class="srd-dock">
        <!-- expanded CLI panel -->
        <transition name="srd-pop">
            <div v-if="open" class="srd-panel" role="dialog" aria-label="Studio activity terminal" @keydown.esc="close">
                <!-- header: Working… · model <X> -->
                <div class="srd-head">
                    <svg class="srd-bot-sm" viewBox="0 0 64 52" fill="none" aria-hidden="true">
                        <rect x="6" y="21" width="8" height="8" rx="2.5" fill="#C2683F" />
                        <rect x="50" y="21" width="8" height="8" rx="2.5" fill="#C2683F" />
                        <rect x="14" y="9" width="36" height="29" rx="6" fill="#C2683F" />
                        <rect x="23.5" y="18" width="5" height="11" rx="1.4" fill="#211B14" />
                        <rect x="35.5" y="18" width="5" height="11" rx="1.4" fill="#211B14" />
                        <rect x="19" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                        <rect x="26" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                        <rect x="33.5" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                        <rect x="40.5" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                    </svg>
                    <div class="srd-ttl">
                        <div class="t">{{ active ? 'Working…' : 'Idle' }}</div>
                        <div v-if="active" class="s">model <b>{{ model || '—' }}</b></div>
                    </div>
                    <button class="srd-x" @click="close" aria-label="Close">✕</button>
                </div>

                <!-- tab bar -->
                <div class="srd-tabs" role="tablist" aria-label="Activity views">
                    <button
                        class="srd-tab" :class="{ on: tab === 'terminal' }"
                        role="tab" :aria-selected="tab === 'terminal'" type="button"
                        @click="tab = 'terminal'">Terminal</button>
                    <button
                        class="srd-tab" :class="{ on: tab === 'stages' }"
                        role="tab" :aria-selected="tab === 'stages'" type="button"
                        @click="tab = 'stages'">Stages<span v-if="stages.length" class="srd-tab-n">{{ stages.length }}</span></button>
                </div>

                <!-- TERMINAL tab: live CLI log -->
                <div v-show="tab === 'terminal'" class="srd-term" role="tabpanel" aria-label="Terminal">
                    <div class="srd-term-bar">
                        <span class="d" style="background:#ff5f57"></span>
                        <span class="d" style="background:#febc2e"></span>
                        <span class="d" style="background:#28c840"></span>
                        <span class="srd-term-ttl">citybot@insights: <b>~/studios/{{ slug }}</b></span>
                        <span class="srd-clock">{{ elapsed || '0:00' }}</span>
                    </div>
                    <div ref="scrollEl" class="srd-term-body">
                        <div v-if="!lines.length" class="srd-boot">waiting for activity…</div>
                        <template v-for="(row, ri) in renderRows" :key="row.__breaker ? 'brk-' + ri : (row.ln.key != null ? row.ln.key : row.i)">
                            <div v-if="row.__breaker" class="srd-daybreak">{{ row.label }}</div>
                            <div v-else class="srd-ln">
                                <span class="srd-time">{{ lineTime(row.ln, row.i) }}</span>
                                <span class="srd-stage">{{ row.ln.stage }}</span>
                                <span class="srd-msg" :class="lineClass(row.ln)" v-html="renderMsg(row.ln)"></span>
                            </div>
                        </template>
                    </div>
                </div>

                <!-- STAGES tab: checklist -->
                <div v-show="tab === 'stages'" class="srd-stages-panel" role="tabpanel" aria-label="Stages">
                    <div v-if="!stages.length" class="srd-boot srd-stages-empty">no stages yet…</div>
                    <div v-for="st in stages" :key="st.key" class="srd-st" :class="'srd-st-' + st.status">
                        <span class="srd-st-mk">{{ stageGlyph(st.status) }}</span>
                        <span class="srd-st-lbl">{{ st.label }}</span>
                        <span v-if="st.pct != null" class="srd-st-pct">{{ clampPct(st.pct) }}%</span>
                    </div>
                </div>

                <!-- footer: tokens / spend / elapsed / readiness -->
                <div class="srd-foot">
                    <div class="srd-foot-row">
                        <span class="srd-stat">tokens <b>{{ fmt(tokensIn) }}</b> in · <b>{{ fmt(tokensOut) }}</b> out</span>
                        <span class="srd-stat">spend <b>${{ (spend || 0).toFixed(2) }}</b></span>
                        <span class="srd-stat">elapsed <b>{{ elapsed || '0:00' }}</b></span>
                    </div>
                    <div class="srd-ready">
                        <span class="srd-ready-lbl">readiness {{ readyPct }}%</span>
                        <span class="srd-ready-bar"><span class="srd-ready-fill" :style="{ width: readyPct + '%' }"></span></span>
                    </div>
                </div>
            </div>
        </transition>

        <!-- the always-visible robot button -->
        <button class="srd-fab" :class="{ live: active }" @click="open = !open" :aria-label="open ? 'Hide activity terminal' : 'Show activity terminal'">
            <svg viewBox="0 0 64 52" fill="none" aria-hidden="true">
                <rect x="6" y="21" width="8" height="8" rx="2.5" fill="#C2683F" />
                <rect x="50" y="21" width="8" height="8" rx="2.5" fill="#C2683F" />
                <rect x="14" y="9" width="36" height="29" rx="6" fill="#C2683F" />
                <rect x="23.5" y="18" width="5" height="11" rx="1.4" fill="#211B14">
                    <animate v-if="active" attributeName="height" values="11;2;11" dur="3s" repeatCount="indefinite" />
                    <animate v-if="active" attributeName="y" values="18;22.5;18" dur="3s" repeatCount="indefinite" />
                </rect>
                <rect x="35.5" y="18" width="5" height="11" rx="1.4" fill="#211B14">
                    <animate v-if="active" attributeName="height" values="11;2;11" dur="3s" repeatCount="indefinite" />
                    <animate v-if="active" attributeName="y" values="18;22.5;18" dur="3s" repeatCount="indefinite" />
                </rect>
                <rect x="19" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                <rect x="26" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                <rect x="33.5" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                <rect x="40.5" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
            </svg>
            <span v-if="active" class="srd-fab-dot"></span>
        </button>
    </div>
</template>

<script lang="ts" setup>
// Studio activity terminal. The parent studio page feeds all live state via props;
// this component only owns the open/closed toggle, the active tab, per-line timestamps
// (captured once when a line first appears), and auto-scroll.
interface StreamLine { key?: string | number; stage: string; level: 'info' | 'done' | 'active' | 'warn' | 'pending'; msg: string; meta?: string; time?: string }
interface StageItem { key: string; label: string; status: 'done' | 'active' | 'pending' | 'error'; pct?: number }

const props = withDefaults(defineProps<{
    active: boolean
    title?: string
    model?: string
    lines?: StreamLine[]
    stages?: StageItem[]
    readiness?: number
    tokensIn?: number
    tokensOut?: number
    spend?: number
    elapsed?: string
}>(), {
    active: false, title: '', model: '', lines: () => [], stages: () => [],
    readiness: 0, tokensIn: 0, tokensOut: 0, spend: 0, elapsed: '',
})

const emit = defineEmits<{ (e: 'close'): void }>()

const open = ref(false)
const tab = ref<'terminal' | 'stages'>('terminal')
const scrollEl = ref<HTMLElement | null>(null)

const lines = computed(() => props.lines || [])
const stages = computed(() => props.stages || [])
const slug = computed(() => (props.title || 'studio').toLowerCase().replace(/\s+/g, '-'))
const readyPct = computed(() => clampPct(props.readiness || 0))

function close() { open.value = false; emit('close') }

// Per-line timestamps: prefer a time the entry already carries; otherwise stamp it once when
// the line first appears (captured in the watcher below → stable, never re-derived on re-render).
// Each stamp stores a full {date, time} so day-breakers know which calendar day a line belongs to.
interface LineStamp { date: string; time: string }
const lineStamps = reactive<Record<string | number, LineStamp>>({})
function lineKey(ln: StreamLine, i: number) { return ln.key != null ? ln.key : i }
function lineTime(ln: StreamLine, i: number) {
    const s = lineStamps[lineKey(ln, i)]
    return ln.time || (s ? s.time : '') || ''
}
function nowStamp(): LineStamp {
    const d = new Date()
    const p = (n: number) => String(n).padStart(2, '0')
    return {
        date: `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`,
        time: `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`,
    }
}

// Day-breaker formatting: YYYY-MM-DD → "Mon D, YYYY" (no external lib).
const MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function formatDay(iso: string) {
    const [y, m, d] = iso.split('-').map(Number)
    return `${MONTHS_SHORT[m - 1]} ${d}, ${y}`
}

// Walk lines in order; emit a breaker marker whenever the captured date changes between
// consecutive rendered lines (including the first). Lines without a captured date yet are skipped.
type RenderRow = { __breaker: true; label: string } | { __breaker: false; ln: StreamLine; i: number }
const renderRows = computed<RenderRow[]>(() => {
    const out: RenderRow[] = []
    let prevDate: string | null = null
    lines.value.forEach((ln, i) => {
        const stamp = lineStamps[lineKey(ln, i)]
        const date = stamp ? stamp.date : null
        if (date && date !== prevDate) {
            out.push({ __breaker: true, label: formatDay(date) })
            prevDate = date
        }
        out.push({ __breaker: false, ln, i })
    })
    return out
})

function stageGlyph(status: string) {
    return ({ done: '✓', active: '◐', pending: '·', error: '✕' } as Record<string, string>)[status] || '·'
}

// Semantic class per log line, by level + content. Priority: error > held > success > stage > model > default
// (so a failed stage reads red, not clay). Returns a `.srd-msg` modifier class.
function lineClass(ln: StreamLine) {
    const msg = ln && ln.msg != null ? String(ln.msg) : ''
    const m = msg.toLowerCase()
    const isStage = !!(ln && ln.stage) || /^\s*▸/.test(msg)
    if ((ln && ln.level === 'error') || /(failed|error|exception|does not exist)/.test(m)) return 'lvl-err'
    if (/(⏸|held|skip|paused)/.test(m)) return 'lvl-held'
    if (/(✓|all stages complete| done|complete|ready|\bok\b|passed|persisted)/.test(m)) return 'lvl-ok'
    if (isStage) return 'lvl-stage'
    if (/model:/.test(m)) return 'lvl-model'
    return 'lvl-info'
}

// Safe-HTML message: escape first (& < >), THEN inline-highlight count numbers (cyan) and id/org/path
// tokens (dim grey). Ordered alternation so each char is wrapped at most once (id tokens win over numbers).
const COUNT_WORDS = 'files?|agents?|rows?|tables?|docs?|chunks?|columns?|sources?|periods?|months?|records?'
const HL_RE = new RegExp(
    '(org=[\\w.-]+|\\b(?:t|staging)_\\w+|[A-Za-z0-9_]+=\\d+|=\\d+|\\b\\d+(?=\\s+(?:' + COUNT_WORDS + ')\\b))',
    'g',
)
function renderMsg(ln: StreamLine) {
    const raw = ln && ln.msg != null ? String(ln.msg) : ''
    const esc = raw.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    return esc.replace(HL_RE, (tok) => {
        if (/^org=|^t_|^staging_/.test(tok)) return `<span class="hl-id">${tok}</span>`
        const eq = tok.indexOf('=')
        if (eq >= 0) return `${tok.slice(0, eq + 1)}<span class="hl-num">${tok.slice(eq + 1)}</span>`
        return `<span class="hl-num">${tok}</span>`
    })
}
function clampPct(n: number) { return Math.max(0, Math.min(100, Math.round(n || 0))) }
function fmt(n?: number) {
    const v = n || 0
    if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M'
    if (v >= 1000) return (v / 1000).toFixed(1) + 'k'
    return String(v)
}

// Stamp new lines + auto-scroll the terminal to the newest line when lines change (only while open).
watch(() => lines.value.length, async () => {
    const stamp = nowStamp()
    lines.value.forEach((ln, i) => {
        const k = lineKey(ln, i)
        if (lineStamps[k] == null) lineStamps[k] = { date: stamp.date, time: ln.time || stamp.time }
    })
    if (!open.value) return
    await nextTick()
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}, { immediate: true })
watch(open, async (o) => {
    if (!o) return
    await nextTick()
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
})
</script>

<style scoped>
.srd-dock { position: fixed; right: 20px; bottom: 20px; z-index: 80; display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }

.srd-fab { position: relative; width: 58px; height: 58px; border-radius: 16px; border: 1px solid #E9E0D3; background: #FBFAF6; box-shadow: 0 10px 26px -10px rgba(40,25,10,.42); cursor: pointer; display: grid; place-items: center; transition: transform .15s, box-shadow .15s; padding: 9px 7px; }
.srd-fab:hover { transform: translateY(-2px); box-shadow: 0 16px 34px -12px rgba(40,25,10,.5); }
.srd-fab:focus-visible { outline: 2px solid #C2541E; outline-offset: 2px; }
.srd-fab svg { width: 100%; height: 100%; }
.srd-fab.live { border-color: #C2541E66; }
.srd-fab-dot { position: absolute; top: 6px; right: 6px; width: 9px; height: 9px; border-radius: 50%; background: #3FA86B; box-shadow: 0 0 0 3px #FBFAF6; animation: srd-pulse 1.6s ease-in-out infinite; }
@keyframes srd-pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }

.srd-panel { width: min(92vw, 620px); max-width: calc(100vw - 40px); background: #fff; border: 1px solid #E9E0D3; border-radius: 16px; box-shadow: 0 30px 70px -24px rgba(40,25,10,.5); overflow: hidden; }
.srd-head { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid #EFE7DA; }
.srd-bot-sm { width: 38px; height: 30px; flex: none; }
.srd-ttl { flex: 1; min-width: 0; }
.srd-ttl .t { font-family: 'Spectral', ui-serif, Georgia, serif; font-size: 15px; font-weight: 600; color: #211B14; }
.srd-ttl .s { font-size: 11px; color: #8A7F70; margin-top: 1px; font-family: ui-monospace, Menlo, monospace; }
.srd-ttl .s b { color: #C2541E; font-weight: 600; }
.srd-x { border: none; background: none; color: #b7ac9c; cursor: pointer; font-size: 15px; padding: 4px; border-radius: 8px; }
.srd-x:hover { background: #F4EEE5; color: #C2541E; }

/* tab bar */
.srd-tabs { display: flex; gap: 2px; padding: 8px 12px 0; border-bottom: 1px solid #EFE7DA; }
.srd-tab { position: relative; border: none; background: none; cursor: pointer; padding: 7px 12px 9px; font-size: 12px; font-weight: 600; color: #8A7F70; font-family: ui-monospace, Menlo, monospace; border-bottom: 2px solid transparent; margin-bottom: -1px; border-radius: 6px 6px 0 0; }
.srd-tab:hover { color: #4a4238; }
.srd-tab:focus-visible { outline: 2px solid #C2541E; outline-offset: -2px; }
.srd-tab.on { color: #C2541E; border-bottom-color: #C2541E; }
.srd-tab-n { margin-left: 6px; font-size: 10px; background: #F1E7D9; color: #8A7F70; border-radius: 8px; padding: 1px 6px; }
.srd-tab.on .srd-tab-n { background: #F6E3D6; color: #C2541E; }

.srd-term { margin: 12px; border-radius: 12px; background: #1b1813; border: 1px solid #0d0a07; overflow: hidden; }
.srd-term-bar { display: flex; align-items: center; gap: 6px; padding: 8px 11px; border-bottom: 1px solid #2b2119; }
.srd-term-bar .d { width: 9px; height: 9px; border-radius: 50%; }
.srd-term-ttl { margin-left: 6px; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; color: #c9bdaa; }
.srd-term-ttl b { color: #fff; }
.srd-clock { margin-left: auto; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; color: #E0A44B; }
.srd-term-body { padding: 11px 13px; max-height: 380px; overflow-y: auto; font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; line-height: 1.7; }
.srd-term-body::-webkit-scrollbar { width: 7px; }
.srd-term-body::-webkit-scrollbar-thumb { background: #3a2e22; border-radius: 8px; }
.srd-boot { color: #8b7d6b; }
.srd-ln { display: flex; gap: 8px; align-items: baseline; white-space: pre-wrap; }
.srd-time { flex: none; color: #6b6156; font-size: 10.5px; font-variant-numeric: tabular-nums; }
.srd-stage { flex: none; width: 62px; text-align: right; font-weight: 700; font-size: 9.5px; color: #8b7d6b; text-transform: uppercase; letter-spacing: .3px; overflow: hidden; text-overflow: ellipsis; }
.srd-msg { color: #cfc4b3; flex: 1; min-width: 0; }
.srd-msg.lvl-stage { color: #e08a52; }
.srd-msg.lvl-ok { color: #6bd18f; }
.srd-msg.lvl-err { color: #e88a7a; }
.srd-msg.lvl-held { color: #e0b64f; }
.srd-msg.lvl-model { color: #b79ae8; }
.srd-msg.lvl-info { color: #d8cdbb; }
.hl-num { color: #5fc8d8; }
.hl-id { color: #8a8073; font-variant-numeric: tabular-nums; }
.srd-daybreak { display: flex; align-items: center; gap: 10px; padding: 5px 0; color: #b59a6f; font-size: 9.5px; text-transform: uppercase; letter-spacing: 1px; font-variant-numeric: tabular-nums; }
.srd-daybreak::before, .srd-daybreak::after { content: ''; flex: 1; height: 1px; background: #2b2119; }

/* stages checklist */
.srd-stages-panel { padding: 12px 14px; max-height: 380px; overflow-y: auto; display: flex; flex-direction: column; gap: 7px; }
.srd-stages-empty { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: #9a958c; }
.srd-st { display: flex; align-items: center; gap: 10px; font-size: 12.5px; }
.srd-st-mk { flex: none; width: 16px; text-align: center; font-size: 13px; }
.srd-st-lbl { flex: 1; min-width: 0; font-weight: 600; color: #4a4238; }
.srd-st-pct { flex: none; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; color: #8A7F70; }
.srd-st-done .srd-st-mk { color: #2f7a52; } .srd-st-done .srd-st-lbl { color: #2F7E50; }
.srd-st-active .srd-st-mk { color: #C2541E; } .srd-st-active .srd-st-lbl { color: #C2541E; }
.srd-st-error .srd-st-mk { color: #C2541E; } .srd-st-error .srd-st-lbl { color: #B4432B; }
.srd-st-pending { opacity: .55; } .srd-st-pending .srd-st-mk, .srd-st-pending .srd-st-lbl { color: #9a958c; }

.srd-foot { padding: 8px 14px 13px; border-top: 1px solid #EFE7DA; }
.srd-foot-row { display: flex; flex-wrap: wrap; gap: 4px 14px; }
.srd-stat { font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; color: #8A7F70; }
.srd-stat b { color: #4a4238; font-weight: 600; }
.srd-ready { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.srd-ready-lbl { flex: none; font-size: 11px; font-weight: 600; color: #4a4238; }
.srd-ready-bar { flex: 1; height: 6px; border-radius: 4px; background: #EFE7DA; overflow: hidden; }
.srd-ready-fill { display: block; height: 100%; background: linear-gradient(90deg, #3FA86B, #5FCE93); border-radius: 4px; transition: width .4s ease; }

.srd-pop-enter-active, .srd-pop-leave-active { transition: opacity .18s, transform .18s; }
.srd-pop-enter-from, .srd-pop-leave-to { opacity: 0; transform: translateY(8px) scale(.98); }
@media (prefers-reduced-motion: reduce) { .srd-fab-dot, .srd-fab, .srd-ready-fill, .srd-pop-enter-active, .srd-pop-leave-active { animation: none; transition: none; } }
</style>
