<template>
    <!-- Only render once a real sync run exists (sync-status returned non-empty). Self-hides otherwise. -->
    <div
        v-if="hasRun && !dismissed"
        class="cai-panel mb-6 rounded-xl overflow-hidden"
        :class="{ 'is-done': phase === 'done', 'is-error': phase === 'error' }"
    >
        <!-- ============ DONE → slim green ribbon ============ -->
        <div v-if="phase === 'done'" class="hero-ribbon">
            <!-- confetti burst (subtle) -->
            <div class="cai-confetti">
                <i
                    v-for="(c, i) in confetti"
                    :key="i"
                    :style="{ background: c.color, '--x': c.x, '--y': c.y, '--r': c.r, animationDelay: c.delay }"
                ></i>
            </div>
            <span class="rchk">✓</span>
            <span class="rmsg">
                Synced
                <span class="rsep">·</span> {{ tablesTotal }} {{ tablesTotal === 1 ? 'table' : 'tables' }}
                <span class="rsep">·</span> {{ rows.toLocaleString() }} rows
            </span>
            <span class="rspacer"></span>
            <button type="button" class="rbtn primary" :disabled="starting" @click="startChat">
                {{ starting ? 'Opening…' : 'Chat' }}
            </button>
            <button type="button" class="rbtn ghost" @click="dismissed = true">Open agent</button>
            <a class="rclose" title="Dismiss" @click="dismissed = true">✕</a>
        </div>

        <!-- ============ COLLAPSED → one-line pill ============ -->
        <div v-else-if="collapsed" class="hero-pill">
            <span class="cai-dot" :class="phase === 'error' ? 'error' : 'syncing'"></span>
            <span class="hpill-msg">
                <template v-if="phase === 'error'">Sync error</template>
                <template v-else>Syncing {{ cappedDone }}/{{ tablesTotal }} tables</template>
                <span class="hpill-clk">· {{ mmss }}</span>
            </span>
            <a class="hpill-show" @click="collapsed = false">Show</a>
        </div>

        <!-- ============ LIVE HERO (connecting · syncing · learning · error) ============ -->
        <div v-else>
            <!-- 1) Stage strip -->
            <div class="hero-stages">
                <template v-for="(s, i) in stageState" :key="s.label">
                    <div class="hstage" :class="'st-' + s.state">
                        <span class="hnode">
                            <span v-if="s.state === 'done'" class="hnode-chk">✓</span>
                        </span>
                        <span class="hlabel">{{ s.label }}</span>
                    </div>
                    <span
                        v-if="i < stageState.length - 1"
                        class="hline"
                        :class="{ filled: stageState[i].state === 'done' }"
                    ></span>
                </template>
            </div>

            <!-- 2) Header: mascot + title + live clock + progress -->
            <div class="hero-body">
                <div class="hero-head">
                    <svg class="cai-bot" viewBox="0 0 44 44" fill="none" aria-hidden="true">
                        <rect x="7" y="12" width="30" height="24" rx="8" fill="#211B14" stroke="#C2541E" stroke-width="1.6" />
                        <circle cx="17" cy="24" r="3.4" fill="#F2C811"><animate attributeName="r" values="3.4;1;3.4" dur="3.2s" repeatCount="indefinite" /></circle>
                        <circle cx="27" cy="24" r="3.4" fill="#33C6D6"><animate attributeName="r" values="3.4;1;3.4" dur="3.2s" begin="0.15s" repeatCount="indefinite" /></circle>
                        <rect x="20.4" y="4" width="3.2" height="7" rx="1.6" fill="#C2541E" /><circle cx="22" cy="3.4" r="2.4" fill="#E89461" />
                        <rect x="16" y="31" width="12" height="2.4" rx="1.2" fill="#3a2e22" />
                    </svg>
                    <div class="hero-titles">
                        <div class="hero-title">Setting up your agent</div>
                        <div class="hero-sub" :class="{ 'is-red': phase === 'error' }">{{ phaseHint }}</div>
                    </div>
                    <span class="hero-clock"><span class="clk-ico">⏱</span> {{ mmss }}</span>
                </div>

                <!-- overall progress bar -->
                <div class="hero-progress">
                    <div class="hero-bar">
                        <div class="hero-fill" :class="{ 'is-error': phase === 'error' }" :style="{ width: progressPct + '%' }"></div>
                    </div>
                    <div class="hero-meta">
                        <span><b>{{ cappedDone }}</b> / {{ tablesTotal }} tables</span>
                        <span v-if="eta" class="hero-eta">{{ eta }}</span>
                    </div>
                </div>

                <!-- 3) Per-table checklist -->
                <div v-if="tableRows.length || queuedCount" class="hero-tables">
                    <div
                        v-for="t in tableRows"
                        :key="t.name"
                        class="trow"
                        :class="'ts-' + t.status"
                    >
                        <span class="tico">
                            <span v-if="t.status === 'done'" class="tchk">✓</span>
                            <span v-else-if="t.status === 'error'" class="terr">⚠</span>
                            <span v-else class="tspin">⟳</span>
                        </span>
                        <span class="tname">{{ shortName(t.name) }}</span>
                        <span class="tmeta">
                            <template v-if="t.status === 'done'">{{ t.rows != null ? t.rows.toLocaleString() + ' rows' : 'ready' }}</template>
                            <template v-else-if="t.status === 'error'">— {{ t.msg || 'failed' }}</template>
                            <template v-else>syncing…</template>
                        </span>
                    </div>
                    <div v-if="queuedCount" class="trow ts-queued">
                        <span class="tico"><span class="tdot">•</span></span>
                        <span class="tname">{{ queuedCount }} {{ queuedCount === 1 ? 'table' : 'tables' }} queued</span>
                    </div>
                    <div v-if="tableRowsMore" class="tmore">…{{ tableRowsMore }} more</div>
                </div>

                <!-- 4a) Footer (running) -->
                <div v-if="phase !== 'error'" class="hero-foot">
                    <span class="foot-note"><span class="foot-ic">↻</span> Syncing in the background — you can leave this page.</span>
                    <span class="foot-spacer"></span>
                    <label class="foot-notify">
                        <input type="checkbox" v-model="notify" />
                        <span>🔔 Notify me when ready</span>
                    </label>
                    <a class="foot-link" @click="collapsed = true">Hide</a>
                    <a class="foot-link" @click="showLog = !showLog">{{ showLog ? 'Hide log' : 'Show log' }}</a>
                </div>

                <!-- 4b) Footer (error / partial) -->
                <div v-else class="hero-foot is-error">
                    <span class="foot-errmsg">
                        <span class="foot-ic">⚠</span>
                        {{ error || 'Sync hit an error.' }}
                        <template v-if="doneCount > 0"> The {{ doneCount }} synced {{ doneCount === 1 ? 'table is' : 'tables are' }} ready to use now.</template>
                    </span>
                    <span class="foot-spacer"></span>
                    <a class="foot-link" @click="showLog = !showLog">{{ showLog ? 'Hide log' : 'Show log' }}</a>
                    <button type="button" class="foot-retry" :disabled="starting" @click="retrySync">
                        {{ starting ? 'Retrying…' : 'Retry' }}
                    </button>
                </div>

                <!-- Optional raw-log terminal (power users) -->
                <div v-if="showLog" ref="termEl" class="cai-term">
                    <div v-if="!log.length" class="cai-boot">Starting sync…</div>
                    <div
                        v-for="(ln, i) in log"
                        :key="i"
                        class="cai-row"
                        :class="['lvl-' + (ln.level || 'step'), { active: ln.level === 'active' && i === lastActiveIdx }]"
                    >
                        <span class="cai-ts">{{ fmtTime(ln.ts) }}</span>
                        <span class="cai-gly" :class="ln.level || 'step'">{{ glyph(ln.level) }}</span>
                        <span class="cai-body">
                            <template v-if="ln.table">
                                <span class="cai-tbl">{{ ln.table }}</span
                                ><span class="cai-sep">  ·  </span><span class="cai-msg">{{ lineMsg(ln) }}</span>
                            </template>
                            <span v-else class="cai-msg">{{ lineMsg(ln) }}</span>
                            <span v-if="ln.level === 'active' && i === lastActiveIdx" class="cai-cursor"></span>
                        </span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script lang="ts" setup>
const props = defineProps<{ dataSourceId: string; agentName?: string }>()
const emit = defineEmits<{ (e: 'done'): void; (e: 'phase', phase: string): void }>()

const router = useRouter()

const hasRun = ref(false)
const collapsed = ref(false)
const dismissed = ref(false)
const showLog = ref(false)
const notify = ref(false)

const phase = ref<string>('connecting')
const tablesTotal = ref(0)
const tablesDone = ref(0)
const rows = ref(0)
const error = ref('')
const log = ref<{ ts: string; level: string; msg: string; table?: string; status?: string; rows?: number }[]>([])

// Cap the "done" count so the backend can never show e.g. 26/18.
const cappedDone = computed(() => {
    const t = tablesTotal.value
    const d = tablesDone.value
    if (t > 0) return Math.min(d, t)
    return d
})

// ---- elapsed clock (local count-up from first poll) ----
const elapsed = ref(0)
const mmss = computed(() => {
    const m = Math.floor(elapsed.value / 60)
    const s = elapsed.value % 60
    return `${m}:${s.toString().padStart(2, '0')}`
})
let clockTimer: ReturnType<typeof setInterval> | null = null

// ---- stage strip: Sign in · Discover · Import · Learn · Ready ----
const STAGES = ['Sign in', 'Discover', 'Import', 'Learn', 'Ready']
const PHASE_STAGE: Record<string, number> = { connecting: 1, syncing: 2, learning: 3, done: 4 }
// Remember the furthest real stage so an error freezes at the right node (red).
const lastStageIdx = ref(0)
watch(phase, (p) => {
    const idx = PHASE_STAGE[p]
    if (p !== 'error' && idx != null) lastStageIdx.value = idx
})
const stageState = computed(() => {
    const p = phase.value
    if (p === 'done') return STAGES.map((label) => ({ label, state: 'done' }))
    const active = p === 'error' ? lastStageIdx.value : (PHASE_STAGE[p] ?? 0)
    return STAGES.map((label, i) => {
        if (i < active) return { label, state: 'done' }
        if (i === active) return { label, state: p === 'error' ? 'error' : 'active' }
        return { label, state: 'future' }
    })
})

// ---- phase → one-line hint ----
const phaseHint = computed(() => ({
    connecting: 'Signing in and discovering your data…',
    syncing: 'Importing your tables…',
    learning: 'Learning column meanings and relationships…',
    done: 'Ready.',
    error: error.value || 'Something went wrong during the sync.',
}[phase.value] || 'Working…'))

// ---- overall progress (guard /0) ----
const progressPct = computed(() => {
    const t = tablesTotal.value
    if (t <= 0) return phase.value === 'done' ? 100 : 0
    return Math.min(100, Math.round((cappedDone.value / t) * 100))
})

// ---- rough ETA: hide until at least 1 table done ----
const eta = computed(() => {
    const d = cappedDone.value
    const t = tablesTotal.value
    if (d < 1 || t <= 0 || d >= t) return ''
    const perTable = elapsed.value / d
    const remainingSec = perTable * (t - d)
    if (!isFinite(remainingSec) || remainingSec <= 0) return ''
    const mins = Math.max(1, Math.ceil(remainingSec / 60))
    return `~${mins} min left`
})

// ---- per-table checklist: group log by table, latest status wins (done>syncing, error sticks) ----
const TABLE_VIS_CAP = 8
type TRow = { name: string; status: 'syncing' | 'done' | 'error'; rows: number | null; msg: string; order: number }
const tableRowsAll = computed<TRow[]>(() => {
    const map = new Map<string, TRow>()
    let order = 0
    for (const ln of log.value) {
        if (!ln.table) continue
        const key = ln.table
        const prev = map.get(key) || { name: key, status: 'syncing' as const, rows: null as number | null, msg: '', order: order++ }
        // derive this entry's status defensively (explicit status → level fallback)
        const st: string = ln.status || (ln.level === 'error' ? 'error' : ln.level === 'ok' ? 'done' : 'syncing')
        if (st === 'error') { prev.status = 'error'; if (ln.msg) prev.msg = ln.msg }
        else if (prev.status !== 'error') {
            if (st === 'done') prev.status = 'done'
            else if (prev.status !== 'done') prev.status = 'syncing'
        }
        if (ln.rows != null) prev.rows = ln.rows
        map.set(key, prev)
    }
    // surface active/error first, done sinks to the bottom
    const weight = { syncing: 0, error: 1, done: 2 }
    return Array.from(map.values()).sort((a, b) => (weight[a.status] - weight[b.status]) || (a.order - b.order))
})
const tableRows = computed(() => tableRowsAll.value.slice(0, TABLE_VIS_CAP))
const tableRowsMore = computed(() => Math.max(0, tableRowsAll.value.length - TABLE_VIS_CAP))
const doneCount = computed(() => tableRowsAll.value.filter((t) => t.status === 'done').length)
// Best-effort "queued": tables counted in total but not yet seen in the log (no names available).
const queuedCount = computed(() => Math.max(0, tablesTotal.value - tableRowsAll.value.length))

function shortName(name: string): string {
    const slash = name.indexOf('/')
    return slash > 0 ? name.slice(slash + 1) : name
}

const lastActiveIdx = computed(() => {
    for (let i = log.value.length - 1; i >= 0; i--) {
        if (log.value[i].level === 'active') return i
    }
    return -1
})

function fmtTime(ts: string): string {
    if (!ts) return ''
    const d = new Date(ts)
    if (isNaN(d.getTime())) return ''
    const p = (n: number) => n.toString().padStart(2, '0')
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

function glyph(level: string): string {
    return { step: '▶', ok: '✓', active: '⟳', warn: '◦', error: '✕' }[level] || '◦'
}

// Zero-rows label fix: catalogs report no counts → never surface a bare "0 rows".
function lineMsg(ln: { level?: string; msg: string }): string {
    let m = ln.msg || ''
    if (ln.level === 'ok') m = m.replace(/·?\s*\b0\s+rows\b/gi, '· catalog')
    return m
}

// ---- confetti (generated once on done) ----
const confetti = ref<{ color: string; x: string; y: string; r: string; delay: string }[]>([])
function spawnConfetti() {
    const cols = ['#C2541E', '#3f9e6a', '#d9b66a', '#e08a3c', '#A8330F']
    const pieces: { color: string; x: string; y: string; r: string; delay: string }[] = []
    for (let i = 0; i < 22; i++) {
        const ang = Math.random() * Math.PI * 2
        const dist = 50 + Math.random() * 150
        pieces.push({
            color: cols[i % cols.length],
            x: `${(Math.cos(ang) * dist).toFixed(0)}px`,
            y: `${(Math.sin(ang) * dist - 30).toFixed(0)}px`,
            r: `${(Math.random() * 720 - 360).toFixed(0)}deg`,
            delay: `${(Math.random() * 0.15).toFixed(2)}s`,
        })
    }
    confetti.value = pieces
}

// ---- notify toast (fires once, only if enabled) ----
let notifiedDone = false
function fireNotify() {
    if (notifiedDone) return
    notifiedDone = true
    try {
        const t = (useToast as any)?.()
        t?.add?.({ title: `${props.agentName || 'Agent'} synced — ${tablesTotal.value} ${tablesTotal.value === 1 ? 'table' : 'tables'} ready` })
    } catch { /* fail-soft */ }
}

// Trigger completion drama + notify once when phase flips to done.
let firedDone = false
watch(phase, (p) => {
    if (p === 'done' && !firedDone) { firedDone = true; spawnConfetti() }
    if (p === 'done' && notify.value) fireNotify()
})
// If the user ticks the box after we've already finished, still notify.
watch(notify, (on) => {
    if (on && phase.value === 'done') fireNotify()
})

// ---- poll loop ----
let pollTimer: ReturnType<typeof setTimeout> | null = null
let alive = true

const termEl = ref<HTMLElement | null>(null)
function scrollToBottom() {
    nextTick(() => {
        const e = termEl.value
        if (e) e.scrollTop = e.scrollHeight
    })
}

function apply(s: any) {
    const prevPhase = phase.value
    phase.value = s.phase || phase.value
    // Tell the parent about the live phase so it can gate the "ready" strip + drive syncing UI.
    if (phase.value !== prevPhase) emit('phase', phase.value)
    tablesTotal.value = s.tables_total ?? tablesTotal.value
    tablesDone.value = s.tables_done ?? tablesDone.value
    rows.value = s.rows ?? rows.value
    error.value = s.error || ''
    if (Array.isArray(s.log)) {
        const grew = s.log.length > log.value.length
        log.value = s.log
        if (grew && showLog.value) scrollToBottom()
    }
}

async function fetchStatus(): Promise<boolean> {
    try {
        const { data, error: err } = await useMyFetch(`/data_sources/${props.dataSourceId}/sync-status`, { method: 'GET' })
        if (!alive) return false
        if (err.value) return true // transient — keep polling
        const s = (data.value as any) || {}
        // Empty object = no run (old clone opened normally) → stay hidden.
        if (!s || !s.phase) return true
        hasRun.value = true
        apply(s)
        return true
    } catch {
        return true
    }
}

async function poll() {
    if (!alive) return
    await fetchStatus()
    if (!alive) return
    if (phase.value === 'done' || phase.value === 'error') {
        stopClock()
        return // stop polling; the last fetch above is the final one
    }
    pollTimer = setTimeout(poll, 1500)
}

function stopClock() {
    if (clockTimer) { clearInterval(clockTimer); clockTimer = null }
}

// ---- start chat (mirror layouts/data.vue startChat) ----
const starting = ref(false)
async function startChat() {
    if (starting.value) return
    starting.value = true
    try {
        const { data } = await useMyFetch('/reports', {
            method: 'POST',
            body: JSON.stringify({ title: 'untitled report', files: [], data_sources: [props.dataSourceId] }),
        })
        const r = (data.value as any)
        emit('done')
        if (r?.id) await router.push(`/reports/${r.id}`)
    } finally {
        if (alive) starting.value = false
    }
}

// ---- retry a failed sync ----
async function retrySync() {
    if (starting.value) return
    starting.value = true
    try {
        await useMyFetch(`/connectors/${props.dataSourceId}/sync`, { method: 'POST' })
        // reset local state + restart the poll loop
        phase.value = 'connecting'
        error.value = ''
        log.value = []
        tablesDone.value = 0
        elapsed.value = 0
        firedDone = false
        notifiedDone = false
        confetti.value = []
        alive = true
        if (!clockTimer) clockTimer = setInterval(() => { elapsed.value += 1 }, 1000)
        emit('phase', phase.value)
        poll()
    } catch { /* fail-soft */ } finally {
        if (alive) starting.value = false
    }
}

// A manual/auto train started elsewhere (layout header "⚡ Train"). If our poll loop
// had already stopped after a previous done/error run, restart it fresh so this new
// run streams here + the terminal un-hides. If a run is still active we're already
// polling — do nothing.
const trainKick = inject('trainKick', ref(0))
watch(trainKick, () => {
    hasRun.value = true
    dismissed.value = false
    if (phase.value === 'done' || phase.value === 'error') {
        phase.value = 'connecting'
        error.value = ''
        log.value = []
        tablesDone.value = 0
        elapsed.value = 0
        firedDone = false
        notifiedDone = false
        confetti.value = []
        alive = true
        if (!clockTimer) clockTimer = setInterval(() => { elapsed.value += 1 }, 1000)
        emit('phase', phase.value)
        poll()
    }
})

onMounted(() => {
    clockTimer = setInterval(() => { elapsed.value += 1 }, 1000)
    poll()
})

onBeforeUnmount(() => {
    alive = false
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null }
    stopClock()
})
</script>

<style scoped>
/* ---------- SYNC HERO ---------- */
.cai-panel {
    position: relative;
    border-radius: 12px;
    border: 1px solid #E9E0D3;
    background: #FFFFFF;
    box-shadow: 0 1px 2px rgba(28, 25, 23, .04), 0 1px 3px rgba(28, 25, 23, .06);
}

/* ===== Stage strip ===== */
.hero-stages {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 13px 18px;
    background: linear-gradient(180deg, #FBFAF6, #F7F2EA);
    border-bottom: 1px solid #F1EFEC;
    overflow-x: auto;
}
.hstage {
    display: flex;
    align-items: center;
    gap: 7px;
    flex: none;
}
.hnode {
    width: 15px;
    height: 15px;
    border-radius: 50%;
    border: 2px solid #D9CFC2;
    background: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
    transition: all .3s;
}
.hnode-chk { font-size: 8px; color: #fff; font-weight: 700; line-height: 1; }
.hlabel {
    font-size: 12px;
    color: #A8A29E;
    font-weight: 600;
    white-space: nowrap;
}
.hstage.st-done .hnode { background: #C2541E; border-color: #C2541E; }
.hstage.st-done .hlabel { color: #78716C; }
.hstage.st-active .hnode {
    border-color: #C2541E;
    background: #fff;
    box-shadow: 0 0 0 0 rgba(194, 84, 30, .5);
    animation: cai-pulse 1.4s infinite;
}
.hstage.st-active .hlabel { color: #1C1917; font-weight: 700; }
.hstage.st-error .hnode { background: #B4432B; border-color: #B4432B; }
.hstage.st-error .hlabel { color: #B4432B; }
.hline {
    flex: 1;
    min-width: 14px;
    height: 2px;
    border-radius: 2px;
    background: #E9E0D3;
    transition: background .3s;
}
.hline.filled { background: #C2541E; }
@keyframes cai-pulse {
    0% { box-shadow: 0 0 0 0 rgba(194, 84, 30, .45) }
    70% { box-shadow: 0 0 0 7px rgba(194, 84, 30, 0) }
    100% { box-shadow: 0 0 0 0 rgba(194, 84, 30, 0) }
}

/* ===== Body / header ===== */
.hero-body { padding: 16px 18px 6px; }
.hero-head {
    display: flex;
    align-items: center;
    gap: 12px;
}
.cai-bot { width: 34px; height: 34px; flex: none; }
.hero-titles { flex: 1; min-width: 0; }
.hero-title {
    font-family: 'Spectral', ui-serif, Georgia, serif;
    font-size: 18px;
    font-weight: 600;
    color: #211B14;
    line-height: 1.15;
}
.hero-sub {
    font-size: 12.5px;
    color: #78716C;
    margin-top: 2px;
}
.hero-sub.is-red { color: #B4432B; }
.hero-clock {
    font-family: 'SF Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 15px;
    font-weight: 600;
    color: #44403C;
    font-variant-numeric: tabular-nums;
    flex: none;
}
.clk-ico { font-size: 13px; }

/* ===== Progress bar ===== */
.hero-progress { margin-top: 12px; }
.hero-bar {
    height: 9px;
    border-radius: 6px;
    background: #F1EFEC;
    overflow: hidden;
}
.hero-fill {
    height: 100%;
    border-radius: 6px;
    background: linear-gradient(90deg, #C2541E, #E08A3C);
    transition: width .5s cubic-bezier(.4, 0, .2, 1);
}
.hero-fill.is-error { background: #B4432B; }
.hero-meta {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 6px;
    font-size: 12px;
    color: #78716C;
    font-variant-numeric: tabular-nums;
}
.hero-meta b { color: #1C1917; font-weight: 700; }
.hero-eta {
    font-weight: 600;
    color: #C2541E;
}

/* ===== Per-table checklist ===== */
.hero-tables {
    margin-top: 14px;
    border-top: 1px solid #F1EFEC;
    padding-top: 4px;
}
.trow {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 2px;
    font-size: 13px;
    border-bottom: 1px solid #F6F3EE;
}
.trow:last-child { border-bottom: 0; }
.tico { width: 16px; text-align: center; flex: none; }
.tchk {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: #E7F5EC;
    color: #15803D;
    font-size: 10px;
    font-weight: 700;
}
.terr { color: #B4432B; font-size: 13px; }
.tspin {
    display: inline-block;
    color: #C2541E;
    animation: cai-spin 1s linear infinite;
}
.tdot { color: #C9BCA9; }
@keyframes cai-spin { to { transform: rotate(360deg) } }
.tname {
    flex: 1;
    min-width: 0;
    font-family: 'SF Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12.5px;
    color: #1C1917;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.tmeta {
    flex: none;
    font-size: 12px;
    color: #78716C;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.ts-done .tname { color: #44403C; }
.ts-syncing .tname { color: #1C1917; font-weight: 600; }
.ts-syncing { animation: cai-rowpulse 1.6s ease-in-out infinite; }
.ts-error .tname { color: #B4432B; }
.ts-error .tmeta { color: #B4432B; }
.ts-queued .tname { color: #A8A29E; font-family: inherit; }
@keyframes cai-rowpulse {
    0%, 100% { background: transparent }
    50% { background: rgba(224, 138, 60, .07) }
}
.tmore {
    text-align: center;
    padding: 6px 0 2px;
    font-size: 11.5px;
    color: #A8A29E;
}

/* ===== Footer ===== */
.hero-foot {
    display: flex;
    align-items: center;
    gap: 14px;
    margin: 10px -18px 0;
    padding: 11px 18px;
    background: #FBFAF6;
    border-top: 1px solid #E9E0D3;
    flex-wrap: wrap;
}
.foot-note {
    font-size: 12.5px;
    color: #78716C;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.foot-ic { color: #C2541E; }
.foot-spacer { flex: 1; }
.foot-notify {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12.5px;
    color: #44403C;
    cursor: pointer;
    user-select: none;
}
.foot-notify input { accent-color: #C2541E; cursor: pointer; }
.foot-link {
    font-size: 12.5px;
    color: #9a958c;
    cursor: pointer;
    text-decoration: none;
    transition: color .15s;
}
.foot-link:hover { color: #C2541E; }
.hero-foot.is-error {
    background: #F7E7E2;
    border-top-color: #EDD6CE;
}
.foot-errmsg {
    font-size: 12.5px;
    color: #B4432B;
    display: inline-flex;
    align-items: center;
    gap: 6px;
}
.hero-foot.is-error .foot-ic { color: #B4432B; }
.foot-retry {
    flex: none;
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
    background: #C2541E;
    color: #fff;
    transition: background .15s;
}
.foot-retry:hover { background: #A8330F; }
.foot-retry:disabled { opacity: .6; cursor: default; }

/* ===== Collapsed pill ===== */
.hero-pill {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 11px 16px;
}
.cai-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex: none;
    background: #C2541E;
}
.cai-dot.syncing {
    box-shadow: 0 0 0 0 rgba(194, 84, 30, .5);
    animation: cai-pulse 1.4s infinite;
}
.cai-dot.error { background: #B4432B; }
.hpill-msg { font-size: 13px; color: #1C1917; font-weight: 600; }
.hpill-clk { color: #78716C; font-weight: 400; font-variant-numeric: tabular-nums; }
.hpill-show {
    margin-left: auto;
    font-size: 12.5px;
    color: #C2541E;
    cursor: pointer;
    font-weight: 600;
}

/* ===== Done ribbon ===== */
.hero-ribbon {
    position: relative;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    background: linear-gradient(0deg, #eef6f0, #f4faf5);
    overflow: hidden;
}
.rchk {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: #15803D;
    color: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 12px;
    font-weight: 700;
    flex: none;
    transform: scale(0);
    animation: cai-pop .5s cubic-bezier(.2, 1.4, .4, 1) forwards;
    z-index: 2;
}
@keyframes cai-pop { to { transform: scale(1) } }
.rmsg {
    font-size: 14px;
    font-weight: 600;
    color: #15803D;
    z-index: 2;
}
.rsep { color: #9dc4ac; font-weight: 400; margin: 0 2px; }
.rspacer { flex: 1; }
.rbtn {
    z-index: 2;
    border: none;
    border-radius: 9px;
    padding: 7px 15px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    transition: all .15s;
}
.rbtn.primary { background: #C2541E; color: #fff; }
.rbtn.primary:hover { background: #A8330F; }
.rbtn.primary:disabled { opacity: .6; cursor: default; }
.rbtn.ghost {
    background: #fff;
    color: #15803D;
    border: 1px solid #CDE9D6;
}
.rbtn.ghost:hover { background: #EAF6EE; }
.rclose {
    z-index: 2;
    color: #8AAE97;
    cursor: pointer;
    font-size: 13px;
    padding: 4px 2px 4px 4px;
}
.rclose:hover { color: #15803D; }

/* confetti */
.cai-confetti {
    position: absolute;
    top: 50%;
    left: 22px;
    width: 0;
    height: 0;
    pointer-events: none;
    z-index: 1;
}
.cai-confetti i {
    position: absolute;
    width: 6px;
    height: 10px;
    border-radius: 2px;
    opacity: 0;
}
.cai-panel.is-done .cai-confetti i {
    animation: cai-burst .9s ease-out forwards;
}
@keyframes cai-burst {
    0% { opacity: 1; transform: translate(0, 0) rotate(0) }
    100% { opacity: 0; transform: translate(var(--x), var(--y)) rotate(var(--r)) }
}

/* ===== Raw-log terminal (behind "Show log") ===== */
.cai-term {
    position: relative;
    margin: 12px -18px 0;
    background: radial-gradient(120% 80% at 50% -10%, #23201a 0%, #1b1813 45%, #14110d 100%);
    padding: 14px 18px 16px;
    max-height: 300px;
    overflow: auto;
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    line-height: 1.85;
    border-top: 1px solid #E9E0D3;
}
.cai-term::-webkit-scrollbar { width: 8px }
.cai-term::-webkit-scrollbar-thumb { background: #332c22; border-radius: 8px }
.cai-boot { color: #6d6455; }
.cai-row {
    display: flex;
    gap: 10px;
    white-space: pre-wrap;
    word-break: break-word;
    position: relative;
}
.cai-ts { color: #6d6455; flex: none; user-select: none; font-variant-numeric: tabular-nums; }
.cai-gly { flex: none; width: 12px; text-align: center; user-select: none; }
.cai-gly.step { color: #a89e8c }
.cai-gly.ok { color: #5fbf86 }
.cai-gly.active { color: #e08a3c; display: inline-block; animation: cai-spin 1s linear infinite; }
.cai-gly.error { color: #e06a55 }
.cai-body { flex: 1; min-width: 0 }
.cai-tbl { color: #e0b872 }
.cai-sep { color: #6d6455 }
.cai-msg { color: #cfc6b6 }
.cai-row.active .cai-msg { color: #f0dcc0 }
.cai-cursor {
    display: inline-block;
    width: 7px;
    height: 14px;
    background: #e08a3c;
    margin-left: 2px;
    vertical-align: -2px;
    animation: cai-blink 1s steps(1) infinite;
}
@keyframes cai-blink { 50% { opacity: 0 } }
</style>
