<template>
    <!-- Floating robot mascot pinned bottom-right of the studio page. Click = expand a
         BIG mac-style CLI terminal streaming the studio's live activity one stage at a time
         (model, per-file counts, confidence, train stages, tokens, spend, elapsed, readiness).
         Collapsed = just the robot button (pulses when active). Self-contained toggle. -->
    <div class="srd-dock">
        <!-- expanded CLI panel -->
        <transition name="srd-pop">
            <div v-if="open" class="srd-panel" role="dialog" aria-label="Studio activity terminal" @keydown.esc="close">
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
                        <div class="s">model <b>{{ model || '—' }}</b></div>
                    </div>
                    <button class="srd-x" @click="close" aria-label="Close">✕</button>
                </div>

                <div class="srd-term">
                    <div class="srd-term-bar">
                        <span class="d" style="background:#ff5f57"></span>
                        <span class="d" style="background:#febc2e"></span>
                        <span class="d" style="background:#28c840"></span>
                        <span class="srd-term-ttl">citybot@insights: <b>~/studios/{{ slug }}</b></span>
                        <span class="srd-clock">{{ elapsed || '0:00' }}</span>
                    </div>
                    <div ref="scrollEl" class="srd-term-body">
                        <div v-if="!lines.length" class="srd-boot"><span class="srd-spin">◍</span> waiting for activity…</div>
                        <div v-for="(ln, i) in lines" :key="ln.key != null ? ln.key : i" class="srd-ln">
                            <span class="srd-stage">{{ ln.stage }}</span>
                            <span class="srd-mk" :class="'srd-mk-' + ln.level">
                                <span v-if="ln.level === 'active'" class="srd-spin">◍</span>
                                <template v-else>{{ glyph(ln.level) }}</template>
                            </span>
                            <span class="srd-msg">{{ ln.msg }}</span>
                            <span v-if="ln.meta" class="srd-meta">{{ ln.meta }}</span>
                        </div>
                    </div>
                </div>

                <!-- STAGES strip: one-by-one finishing feel -->
                <div v-if="stages && stages.length" class="srd-stages">
                    <div v-for="st in stages" :key="st.key" class="srd-st" :class="'srd-st-' + st.status">
                        <span class="srd-st-mk">
                            <span v-if="st.status === 'active'" class="srd-spin">◍</span>
                            <template v-else>{{ stageGlyph(st.status) }}</template>
                        </span>
                        <span class="srd-st-lbl">{{ st.label }}</span>
                        <span v-if="st.status === 'active' && st.pct != null" class="srd-st-bar">
                            <span class="srd-st-fill" :style="{ width: clampPct(st.pct) + '%' }"></span>
                        </span>
                        <span v-if="st.status === 'active' && st.pct != null" class="srd-st-pct">{{ clampPct(st.pct) }}%</span>
                    </div>
                </div>

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
// this component only owns the open/closed toggle + auto-scroll.
interface StreamLine { key?: string | number; stage: string; level: 'info' | 'done' | 'active' | 'warn' | 'pending'; msg: string; meta?: string }
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
const scrollEl = ref<HTMLElement | null>(null)

const lines = computed(() => props.lines || [])
const stages = computed(() => props.stages || [])
const slug = computed(() => (props.title || 'studio').toLowerCase().replace(/\s+/g, '-'))
const readyPct = computed(() => clampPct(props.readiness || 0))

function close() { open.value = false; emit('close') }

function glyph(level: string) {
    return ({ done: '✓', warn: '⚠', pending: '·', info: '•' } as Record<string, string>)[level] || '•'
}
function stageGlyph(status: string) {
    return ({ done: '✓', error: '✕', pending: '·' } as Record<string, string>)[status] || '·'
}
function clampPct(n: number) { return Math.max(0, Math.min(100, Math.round(n || 0))) }
function fmt(n?: number) {
    const v = n || 0
    if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M'
    if (v >= 1000) return (v / 1000).toFixed(1) + 'k'
    return String(v)
}

// Auto-scroll the body to the bottom when lines change (only while open).
watch(() => lines.value.length, async () => {
    if (!open.value) return
    await nextTick()
    if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
})
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

.srd-panel { width: 420px; max-width: calc(100vw - 40px); background: #fff; border: 1px solid #E9E0D3; border-radius: 16px; box-shadow: 0 30px 70px -24px rgba(40,25,10,.5); overflow: hidden; }
.srd-head { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid #EFE7DA; }
.srd-bot-sm { width: 38px; height: 30px; flex: none; }
.srd-ttl { flex: 1; min-width: 0; }
.srd-ttl .t { font-family: 'Spectral', ui-serif, Georgia, serif; font-size: 15px; font-weight: 600; color: #211B14; }
.srd-ttl .s { font-size: 11px; color: #8A7F70; margin-top: 1px; font-family: ui-monospace, Menlo, monospace; }
.srd-ttl .s b { color: #C2541E; font-weight: 600; }
.srd-x { border: none; background: none; color: #b7ac9c; cursor: pointer; font-size: 15px; padding: 4px; border-radius: 8px; }
.srd-x:hover { background: #F4EEE5; color: #C2541E; }

.srd-term { margin: 12px; border-radius: 12px; background: linear-gradient(180deg, #17120D, #1F1811); border: 1px solid #0d0a07; overflow: hidden; }
.srd-term-bar { display: flex; align-items: center; gap: 6px; padding: 8px 11px; border-bottom: 1px solid #2b2119; }
.srd-term-bar .d { width: 9px; height: 9px; border-radius: 50%; }
.srd-term-ttl { margin-left: 6px; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; color: #c9bdaa; }
.srd-term-ttl b { color: #fff; }
.srd-clock { margin-left: auto; font-family: ui-monospace, Menlo, monospace; font-size: 10.5px; color: #E0A44B; }
.srd-term-body { padding: 11px 13px; max-height: 380px; overflow-y: auto; font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; line-height: 1.7; }
.srd-term-body::-webkit-scrollbar { width: 7px; }
.srd-term-body::-webkit-scrollbar-thumb { background: #3a2e22; border-radius: 8px; }
.srd-boot { color: #8b7d6b; }
.srd-ln { display: flex; gap: 8px; align-items: baseline; white-space: pre-wrap; animation: srd-in .18s ease; }
@keyframes srd-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
.srd-stage { flex: none; width: 62px; text-align: right; font-weight: 700; font-size: 9.5px; color: #8b7d6b; text-transform: uppercase; letter-spacing: .3px; padding-top: 2px; overflow: hidden; text-overflow: ellipsis; }
.srd-mk { flex: none; width: 13px; text-align: center; }
.srd-mk-done { color: #5FCE93; } .srd-mk-active { color: #C2541E; } .srd-mk-warn { color: #E0A44B; } .srd-mk-pending { color: #6b6156; } .srd-mk-info { color: #C2683F; }
.srd-msg { color: #e7ddcd; flex: 1; min-width: 0; }
.srd-meta { flex: none; color: #8b7d6b; font-size: 10.5px; margin-left: auto; padding-left: 8px; }
.srd-spin { display: inline-block; color: #C2541E; animation: srd-sp .8s linear infinite; }
@keyframes srd-sp { to { transform: rotate(360deg); } }

.srd-stages { display: flex; flex-direction: column; gap: 5px; padding: 0 14px 4px; }
.srd-st { display: flex; align-items: center; gap: 8px; font-size: 11.5px; }
.srd-st-mk { flex: none; width: 14px; text-align: center; }
.srd-st-lbl { flex: none; min-width: 84px; font-weight: 600; color: #4a4238; }
.srd-st-done .srd-st-mk { color: #3FA86B; } .srd-st-done .srd-st-lbl { color: #2F7E50; }
.srd-st-active .srd-st-mk { color: #C2541E; } .srd-st-active .srd-st-lbl { color: #C2541E; }
.srd-st-error .srd-st-mk { color: #C2541E; } .srd-st-error .srd-st-lbl { color: #B4432B; }
.srd-st-pending { opacity: .5; } .srd-st-pending .srd-st-mk, .srd-st-pending .srd-st-lbl { color: #9a958c; }
.srd-st-bar { flex: 1; height: 5px; border-radius: 4px; background: #EFE7DA; overflow: hidden; }
.srd-st-fill { display: block; height: 100%; background: linear-gradient(90deg, #C2683F, #C2541E); border-radius: 4px; transition: width .3s ease; }
.srd-st-pct { flex: none; font-family: ui-monospace, Menlo, monospace; font-size: 10px; color: #8A7F70; width: 30px; text-align: right; }

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
@media (prefers-reduced-motion: reduce) { .srd-ln, .srd-spin, .srd-fab-dot, .srd-fab, .srd-st-fill, .srd-ready-fill { animation: none; transition: none; } }
</style>
