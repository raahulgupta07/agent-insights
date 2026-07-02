<template>
    <!-- Only render once a real sync run exists (sync-status returned non-empty). -->
    <div
        v-if="hasRun"
        class="cai-panel mb-6 rounded-2xl overflow-hidden"
        :class="{ 'is-done': phase === 'done', 'is-error': phase === 'error' }"
    >
        <!-- Header row: status dot + label + counters + elapsed + auto-scroll hint -->
        <div class="cai-phead">
            <span class="cai-dot" :class="dotStateClass"></span>
            <span class="cai-plabel" :class="labelClass">{{ phaseLabel }}</span>

            <span class="cai-counter">
                <b>{{ rows.toLocaleString() }}</b> rows ·
                <b class="g">{{ cappedDone }}</b>/<b>{{ tablesTotal }}</b> tables ·
                <span class="clk">{{ mmss }}</span>
            </span>

            <span class="cai-spacer"></span>

            <span class="cai-thint">
                <span class="hidden sm:inline">auto-scroll</span>
                <a @click="collapsed = !collapsed">{{ collapsed ? 'Show' : 'Hide' }}</a>
            </span>
        </div>

        <!-- Body: dramatic warm-dark CLI terminal -->
        <div v-if="!collapsed">
            <div ref="termEl" class="cai-term">
                <!-- completion flash sweep -->
                <div class="cai-flash"></div>
                <!-- confetti burst -->
                <div class="cai-confetti">
                    <i
                        v-for="(c, i) in confetti"
                        :key="i"
                        :style="{
                            background: c.color,
                            '--x': c.x,
                            '--y': c.y,
                            '--r': c.r,
                            animationDelay: c.delay,
                        }"
                    ></i>
                </div>

                <div v-if="!log.length" class="cai-boot">Starting sync…</div>

                <div
                    v-for="(ln, i) in log"
                    :key="i"
                    class="cai-row"
                    :class="[
                        'lvl-' + (ln.level || 'step'),
                        { active: ln.level === 'active' && i === lastActiveIdx },
                    ]"
                >
                    <span class="cai-ts">{{ fmtTime(ln.ts) }}</span>
                    <span class="cai-gly" :class="ln.level || 'step'">{{ glyph(ln.level) }}</span>
                    <span class="cai-body">
                        <template v-if="ln.table">
                            <span class="cai-tbl">{{ ln.table }}</span
                            ><span class="cai-sep">  ·  </span><span class="cai-msg">{{ lineMsg(ln) }}</span>
                        </template>
                        <span v-else class="cai-msg">{{ lineMsg(ln) }}</span>
                        <!-- blinking cursor on the live (active) line -->
                        <span
                            v-if="ln.level === 'active' && i === lastActiveIdx"
                            class="cai-cursor"
                        ></span>
                    </span>
                </div>
            </div>

            <!-- Success footer + Start chat -->
            <div v-if="phase === 'done'" class="cai-pfoot">
                <span class="cai-footmsg">
                    <span class="cai-chk">✓</span>
                    <span>Sync complete — your data agent is ready.</span>
                </span>
                <button
                    type="button"
                    class="cai-startchat"
                    :disabled="starting"
                    @click="startChat"
                >{{ starting ? 'Opening…' : 'Start chat →' }}</button>
            </div>

            <!-- Error footer -->
            <div v-else-if="phase === 'error'" class="cai-pfoot cai-pfoot-error">
                <span class="cai-footmsg-error">{{ error || 'Sync failed. Please try connecting again.' }}</span>
            </div>
        </div>
    </div>
</template>

<script lang="ts" setup>
const props = defineProps<{ dataSourceId: string }>()
const emit = defineEmits<{ (e: 'done'): void }>()

const router = useRouter()

const hasRun = ref(false)
const collapsed = ref(false)

const phase = ref<string>('connecting')
const tablesTotal = ref(0)
const tablesDone = ref(0)
const rows = ref(0)
const error = ref('')
const log = ref<{ ts: string; level: string; msg: string; table?: string }[]>([])

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

// ---- phase → label / colors ----
const phaseLabel = computed(() => ({
    connecting: 'connecting',
    syncing: 'syncing',
    learning: 'learning',
    done: '✓ ready',
    error: 'sync failed',
}[phase.value] || phase.value))

const dotStateClass = computed(() => ({
    connecting: 'syncing',
    syncing: 'syncing',
    learning: 'syncing',
    done: 'done',
    error: 'error',
}[phase.value] || 'idle'))

const labelClass = computed(() => ({
    done: 'is-green',
    error: 'is-red',
}[phase.value] || ''))

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
    return { step: '▸', ok: '✓', active: '⟳', error: '✕' }[level] || '·'
}

// Zero-rows label fix: Power BI catalogs report no counts and the backend emits
// "0 rows" / "· 0 rows". Never surface a bare "0 rows" in a per-line message —
// rewrite it to the dim "catalog" label instead.
function lineMsg(ln: { level?: string; msg: string }): string {
    let m = ln.msg || ''
    if (ln.level === 'ok') {
        m = m.replace(/·?\s*\b0\s+rows\b/gi, '· catalog')
    }
    return m
}

// ---- confetti (generated once on done) ----
const confetti = ref<{ color: string; x: string; y: string; r: string; delay: string }[]>([])
function spawnConfetti() {
    const cols = ['#C2541E', '#3f9e6a', '#d9b66a', '#e08a3c', '#A8330F']
    const pieces: { color: string; x: string; y: string; r: string; delay: string }[] = []
    for (let i = 0; i < 26; i++) {
        const ang = Math.random() * Math.PI * 2
        const dist = 60 + Math.random() * 180
        pieces.push({
            color: cols[i % cols.length],
            x: `${(Math.cos(ang) * dist).toFixed(0)}px`,
            y: `${(Math.sin(ang) * dist - 40).toFixed(0)}px`,
            r: `${(Math.random() * 720 - 360).toFixed(0)}deg`,
            delay: `${(Math.random() * 0.15).toFixed(2)}s`,
        })
    }
    confetti.value = pieces
}

// Trigger the completion drama once when phase flips to done.
let firedDone = false
watch(phase, (p) => {
    if (p === 'done' && !firedDone) {
        firedDone = true
        spawnConfetti()
    }
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
    phase.value = s.phase || phase.value
    tablesTotal.value = s.tables_total ?? tablesTotal.value
    tablesDone.value = s.tables_done ?? tablesDone.value
    rows.value = s.rows ?? rows.value
    error.value = s.error || ''
    if (Array.isArray(s.log)) {
        const grew = s.log.length > log.value.length
        log.value = s.log
        if (grew) scrollToBottom()
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
/* ---------- SYNC PANEL ---------- */
.cai-panel {
    position: relative;
    border: 1px solid #E9E0D3;
    background: #FBFAF6;
    box-shadow: 0 1px 0 rgba(0, 0, 0, .02), 0 18px 44px -28px rgba(33, 27, 20, .5);
}

/* header */
.cai-phead {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    background: #FBFAF6;
    border-bottom: 1px solid #E9E0D3;
}
.cai-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex: none;
    position: relative;
    background: #C9BCA9;
}
.cai-dot.syncing {
    background: #C2541E;
    box-shadow: 0 0 0 0 rgba(194, 84, 30, .5);
    animation: cai-pulse 1.4s infinite;
}
.cai-dot.done {
    background: #3f9e6a;
    box-shadow: 0 0 0 4px rgba(63, 158, 106, .15);
}
.cai-dot.error {
    background: #B4432B;
}
@keyframes cai-pulse {
    0% { box-shadow: 0 0 0 0 rgba(194, 84, 30, .45) }
    70% { box-shadow: 0 0 0 8px rgba(194, 84, 30, 0) }
    100% { box-shadow: 0 0 0 0 rgba(194, 84, 30, 0) }
}
.cai-plabel {
    font-weight: 700;
    font-size: 14px;
    letter-spacing: .2px;
    color: #211B14;
}
.cai-plabel.is-green { color: #3f9e6a }
.cai-plabel.is-red { color: #B4432B }
.cai-counter {
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 11.5px;
    color: #6b6b6b;
    font-variant-numeric: tabular-nums;
}
.cai-counter b { color: #211B14; font-weight: 700 }
.cai-counter b.g { color: #3f9e6a }
.cai-spacer { flex: 1 }
.cai-thint {
    font-size: 11px;
    color: #b3ac9f;
    display: flex;
    align-items: center;
    gap: 10px;
}
.cai-thint a {
    color: #9a958c;
    cursor: pointer;
    text-decoration: none;
    transition: color .15s;
}
.cai-thint a:hover { color: #211B14 }

/* terminal body */
.cai-term {
    position: relative;
    background: radial-gradient(120% 80% at 50% -10%, #23201a 0%, #1b1813 45%, #14110d 100%);
    padding: 14px 16px 16px;
    max-height: 340px;
    overflow: auto;
    font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    line-height: 1.85;
}
/* faint grid + top glow */
.cai-term::before {
    content: "";
    position: absolute;
    inset: 0;
    pointer-events: none;
    background:
        linear-gradient(rgba(255, 255, 255, .015) 1px, transparent 1px) 0 0 / 100% 22px,
        radial-gradient(60% 40% at 50% 0%, rgba(224, 138, 60, .10), transparent 70%);
}
.cai-term::-webkit-scrollbar { width: 8px }
.cai-term::-webkit-scrollbar-thumb { background: #332c22; border-radius: 8px }

.cai-boot { color: #6d6455; position: relative }

.cai-row {
    display: flex;
    gap: 10px;
    white-space: pre-wrap;
    word-break: break-word;
    position: relative;
    opacity: 0;
    transform: translateY(3px);
    animation: cai-reveal .18s ease forwards;
}
@keyframes cai-reveal {
    to { opacity: 1; transform: none }
}
.cai-ts {
    color: #6d6455;
    flex: none;
    user-select: none;
    font-variant-numeric: tabular-nums;
}
.cai-gly {
    flex: none;
    width: 12px;
    text-align: center;
    user-select: none;
}
.cai-gly.step { color: #a89e8c }
.cai-gly.ok { color: #5fbf86 }
.cai-gly.active {
    color: #e08a3c;
    display: inline-block;
    animation: cai-spin 1s linear infinite;
}
.cai-gly.error { color: #e06a55 }
@keyframes cai-spin {
    to { transform: rotate(360deg) }
}
.cai-body { flex: 1; min-width: 0 }
.cai-tbl { color: #e0b872 }
.cai-sep { color: #6d6455 }
.cai-msg { color: #cfc6b6 }
.cai-num { color: #d9b66a }
.cai-dur { color: #6d6455 }
.cai-row.active .cai-msg { color: #f0dcc0 }

/* typing cursor on the active (last) line */
.cai-cursor {
    display: inline-block;
    width: 7px;
    height: 14px;
    background: #e08a3c;
    margin-left: 2px;
    vertical-align: -2px;
    animation: cai-blink 1s steps(1) infinite;
}
@keyframes cai-blink {
    50% { opacity: 0 }
}

/* footer */
.cai-pfoot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 16px;
    background: #FBFAF6;
    border-top: 1px solid #E9E0D3;
    transition: background .5s;
}
.cai-footmsg {
    font-size: 13px;
    color: #6b6b6b;
    display: flex;
    align-items: center;
    gap: 8px;
}
.cai-panel.is-done .cai-pfoot {
    background: linear-gradient(0deg, #eef6f0, #f4faf5);
}
.cai-panel.is-done .cai-footmsg {
    color: #3f9e6a;
    font-weight: 600;
}
.cai-chk {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: #3f9e6a;
    color: #fff;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 11px;
    transform: scale(0);
    flex: none;
}
.cai-panel.is-done .cai-chk {
    animation: cai-pop .5s cubic-bezier(.2, 1.4, .4, 1) forwards;
}
@keyframes cai-pop {
    to { transform: scale(1) }
}

/* error footer */
.cai-pfoot-error {
    background: #F7E7E2;
    border-top: 1px solid #EDE6DA;
}
.cai-footmsg-error {
    font-size: 13px;
    color: #B4432B;
}

/* start chat button — slides in on done */
.cai-startchat {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    border: none;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    background: #C2541E;
    color: #fff;
    transition: background .15s;
    animation: cai-reveal .4s .2s both;
}
.cai-startchat:hover { background: #A8330F }
.cai-startchat:disabled { opacity: .6; cursor: default }

/* completion flash sweep over the terminal */
.cai-flash {
    position: absolute;
    inset: 0;
    pointer-events: none;
    opacity: 0;
    z-index: 2;
    background: radial-gradient(60% 60% at 50% 55%, rgba(63, 158, 106, .35), transparent 70%);
}
.cai-panel.is-done .cai-flash {
    animation: cai-flash 1.1s ease-out;
}
@keyframes cai-flash {
    0% { opacity: 0 }
    18% { opacity: 1 }
    100% { opacity: 0 }
}

/* confetti */
.cai-confetti {
    position: absolute;
    top: 40%;
    left: 50%;
    width: 0;
    height: 0;
    pointer-events: none;
    z-index: 3;
}
.cai-confetti i {
    position: absolute;
    width: 7px;
    height: 11px;
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
</style>
