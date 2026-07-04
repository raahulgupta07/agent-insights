<template>
    <!-- Always-on robot mascot, pinned to a screen corner. Click = expand a live
         CLI log of the user's data agents (Power BI + Fabric …). Persistent —
         unlike the connect-modal CLI, this stays on the /agents screen. -->
    <div class="car-dock">
        <!-- expanded CLI panel -->
        <transition name="car-pop">
            <div v-if="open" class="car-panel">
                <div class="car-head">
                    <svg class="car-bot-sm" viewBox="0 0 64 52" fill="none" aria-hidden="true">
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
                    <div class="car-ttl">
                        <div class="t">{{ anyActive ? 'Agents working…' : 'Your data agents' }}</div>
                        <div class="s">{{ agents.length }} agent{{ agents.length === 1 ? '' : 's' }} · {{ anyActive ? 'live' : 'idle' }}</div>
                    </div>
                    <button class="car-x" @click="open = false" aria-label="Close">✕</button>
                </div>

                <div class="car-term">
                    <div class="car-term-bar">
                        <span class="d" style="background:#ff5f57"></span>
                        <span class="d" style="background:#febc2e"></span>
                        <span class="d" style="background:#28c840"></span>
                        <span class="car-term-ttl">citybot@insights: <b>~/agents</b></span>
                    </div>
                    <div ref="scrollEl" class="car-term-body">
                        <div v-if="!lines.length" class="car-boot"><span class="car-spin">◍</span> no agents yet</div>
                        <div v-for="ln in lines" :key="ln.key" class="car-ln">
                            <span class="car-who" :class="'car-who-' + ln.kind">{{ ln.who }}</span>
                            <span class="car-mk" :class="'car-mk-' + ln.level">
                                <span v-if="ln.level === 'active'" class="car-spin">◍</span>
                                <template v-else>{{ glyph(ln.level) }}</template>
                            </span>
                            <span class="car-msg"><template v-if="ln.table"><span class="car-tbl">{{ ln.table }}</span> </template>{{ ln.msg }}</span>
                        </div>
                    </div>
                </div>

                <div class="car-chips">
                    <span v-for="a in agents" :key="a.id" class="car-chip" :class="{ on: phaseOf(a.id) === 'done', err: phaseOf(a.id) === 'error' }">
                        <span class="s"></span>{{ a.label }}<span class="n">{{ tablesLabel(a.id) }}</span>
                    </span>
                </div>
            </div>
        </transition>

        <!-- the always-visible robot button -->
        <button class="car-fab" :class="{ live: anyActive }" @click="open = !open" :aria-label="open ? 'Hide agent log' : 'Show agent log'">
            <svg viewBox="0 0 64 52" fill="none" aria-hidden="true">
                <rect x="6" y="21" width="8" height="8" rx="2.5" fill="#C2683F" />
                <rect x="50" y="21" width="8" height="8" rx="2.5" fill="#C2683F" />
                <rect x="14" y="9" width="36" height="29" rx="6" fill="#C2683F" />
                <rect x="23.5" y="18" width="5" height="11" rx="1.4" fill="#211B14">
                    <animate v-if="anyActive" attributeName="height" values="11;2;11" dur="3s" repeatCount="indefinite" />
                    <animate v-if="anyActive" attributeName="y" values="18;22.5;18" dur="3s" repeatCount="indefinite" />
                </rect>
                <rect x="35.5" y="18" width="5" height="11" rx="1.4" fill="#211B14">
                    <animate v-if="anyActive" attributeName="height" values="11;2;11" dur="3s" repeatCount="indefinite" />
                    <animate v-if="anyActive" attributeName="y" values="18;22.5;18" dur="3s" repeatCount="indefinite" />
                </rect>
                <rect x="19" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                <rect x="26" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                <rect x="33.5" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
                <rect x="40.5" y="38" width="4.5" height="9" rx="1.8" fill="#C2683F" />
            </svg>
            <span v-if="anyActive" class="car-fab-dot"></span>
        </button>
    </div>
</template>

<script lang="ts" setup>
// Props: the caller's data agents (already owner-scoped). We derive a kind
// (pbi / fabric / city) from the connector type for coloring + a short label.
const props = defineProps<{ agents: any[] }>()

const open = ref(false)
const runs = reactive<Record<string, any>>({})
const scrollEl = ref<HTMLElement | null>(null)
let poll: ReturnType<typeof setTimeout> | null = null
let stopped = false

const NAMES: Record<string, string> = { powerbi: 'Power BI', powerbi_user: 'Power BI', ms_fabric: 'Fabric', ms_fabric_user: 'Fabric', sharepoint: 'SharePoint', onedrive: 'OneDrive' }
function typeOf(a: any) { return a?.connections?.[0]?.type || a?.type || '' }
function kindOf(a: any) { const t = typeOf(a); if (t.includes('fabric')) return 'fabric'; if (t.includes('powerbi')) return 'pbi'; return 'city' }
function labelOf(a: any) { const t = typeOf(a); return NAMES[t] || String(a?.name || '').split('·')[0].trim() || 'Agent' }

// Normalized agent list for rendering + polling.
const agents = computed(() => (props.agents || []).map((a: any) => ({ id: a.id, kind: kindOf(a), label: labelOf(a) })))

function phaseOf(id: string) { return runs[id]?.phase || 'idle' }
function tablesLabel(id: string) {
    const r = runs[id]; if (!r) return ''
    if (r.phase === 'error') return ' · failed'
    const t = r.tables_total || 0
    return t ? ` · ${r.tables_done || 0}/${t}` : ''
}
const anyActive = computed(() => agents.value.some(a => ['connecting', 'syncing', 'learning'].includes(phaseOf(a.id))))

const lines = computed(() => {
    const out: any[] = []
    for (const a of agents.value) {
        const log = (runs[a.id]?.log || []) as any[]
        log.forEach((l, i) => out.push({
            key: a.id + ':' + i, ts: l.ts || '', kind: a.kind,
            who: a.kind === 'fabric' ? 'fabric' : a.kind === 'pbi' ? 'pbi' : 'city',
            level: l.level || 'step', msg: l.msg || '', table: l.table || '',
        }))
    }
    out.sort((x, y) => (x.ts < y.ts ? -1 : x.ts > y.ts ? 1 : 0))
    return out.slice(-120)
})

function glyph(level: string) { return ({ ok: '✓', step: '▸', warn: '!', error: '✕' } as any)[level] || '▸' }

async function pollOnce() {
    if (stopped) return
    await Promise.all(agents.value.map(async (a) => {
        try {
            const { data } = await useMyFetch(`/data_sources/${a.id}/sync-status`, { method: 'GET' })
            const r = (data.value as any) || {}
            if (r && Object.keys(r).length) runs[a.id] = r
        } catch { /* fail-soft */ }
    }))
    if (open.value) { await nextTick(); if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight }
    // Poll faster while a sync is live or the panel is open; slow idle heartbeat otherwise.
    poll = setTimeout(pollOnce, (anyActive.value || open.value) ? 1500 : 8000)
}

onMounted(pollOnce)
onBeforeUnmount(() => { stopped = true; if (poll) clearTimeout(poll) })
</script>

<style scoped>
.car-dock { position: fixed; right: 20px; bottom: 20px; z-index: 60; display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }

.car-fab { position: relative; width: 56px; height: 56px; border-radius: 16px; border: 1px solid #E9E0D3; background: #FBFAF6; box-shadow: 0 10px 26px -10px rgba(40,25,10,.42); cursor: pointer; display: grid; place-items: center; transition: transform .15s, box-shadow .15s; padding: 9px 7px; }
.car-fab:hover { transform: translateY(-2px); box-shadow: 0 16px 34px -12px rgba(40,25,10,.5); }
.car-fab svg { width: 100%; height: 100%; }
.car-fab.live { border-color: #C2541E66; }
.car-fab-dot { position: absolute; top: 6px; right: 6px; width: 9px; height: 9px; border-radius: 50%; background: #3FA86B; box-shadow: 0 0 0 3px #FBFAF6; animation: car-pulse 1.6s ease-in-out infinite; }
@keyframes car-pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }

.car-panel { width: 380px; max-width: calc(100vw - 40px); background: #fff; border: 1px solid #E9E0D3; border-radius: 16px; box-shadow: 0 30px 70px -24px rgba(40,25,10,.5); overflow: hidden; }
.car-head { display: flex; align-items: center; gap: 10px; padding: 12px 13px; border-bottom: 1px solid #EFE7DA; }
.car-bot-sm { width: 36px; height: 29px; flex: none; }
.car-ttl { flex: 1; min-width: 0; }
.car-ttl .t { font-family: 'Spectral', ui-serif, Georgia, serif; font-size: 14.5px; font-weight: 600; color: #211B14; }
.car-ttl .s { font-size: 10.5px; color: #8A7F70; margin-top: 1px; }
.car-x { border: none; background: none; color: #b7ac9c; cursor: pointer; font-size: 14px; padding: 4px; border-radius: 8px; }
.car-x:hover { background: #F4EEE5; color: #C2541E; }

.car-term { margin: 11px; border-radius: 12px; background: linear-gradient(180deg, #17120D, #1F1811); border: 1px solid #0d0a07; overflow: hidden; }
.car-term-bar { display: flex; align-items: center; gap: 6px; padding: 7px 10px; border-bottom: 1px solid #2b2119; }
.car-term-bar .d { width: 8px; height: 8px; border-radius: 50%; }
.car-term-ttl { margin-left: 6px; font-family: ui-monospace, Menlo, monospace; font-size: 10px; color: #c9bdaa; }
.car-term-ttl b { color: #fff; }
.car-term-body { padding: 9px 11px; height: 220px; overflow-y: auto; font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; line-height: 1.65; }
.car-term-body::-webkit-scrollbar { width: 6px; }
.car-term-body::-webkit-scrollbar-thumb { background: #3a2e22; border-radius: 8px; }
.car-boot { color: #8b7d6b; }
.car-ln { display: flex; gap: 7px; align-items: baseline; white-space: pre-wrap; animation: car-in .18s ease; }
@keyframes car-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
.car-who { flex: none; width: 44px; text-align: right; font-weight: 700; font-size: 9px; padding-top: 1px; }
.car-who-pbi { color: #F2C811; } .car-who-fabric { color: #33C6D6; } .car-who-city { color: #8b7d6b; }
.car-mk { flex: none; width: 12px; text-align: center; }
.car-mk-ok { color: #5FCE93; } .car-mk-step { color: #C2541E; } .car-mk-warn { color: #E0A44B; } .car-mk-error { color: #E77; }
.car-msg { color: #e7ddcd; flex: 1; }
.car-tbl { color: #fff; font-weight: 600; }
.car-spin { display: inline-block; color: #C2541E; animation: car-sp .8s linear infinite; }
@keyframes car-sp { to { transform: rotate(360deg); } }

.car-chips { display: flex; gap: 6px; flex-wrap: wrap; padding: 0 12px 12px; }
.car-chip { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600; padding: 4px 9px; border-radius: 9px; border: 1px solid #E9E0D3; background: #FBFAF6; color: #6b6156; }
.car-chip .s { width: 6px; height: 6px; border-radius: 50%; background: #D8CFC0; }
.car-chip .n { font-weight: 500; color: #9a958c; font-family: ui-monospace, Menlo, monospace; font-size: 10px; }
.car-chip.on { border-color: #cfe6d7; background: #F0F7F2; color: #2F7E50; } .car-chip.on .s { background: #3FA86B; }
.car-chip.err { border-color: #ecd2cc; background: #F9EDEA; color: #B4432B; } .car-chip.err .s { background: #C2541E; }

.car-pop-enter-active, .car-pop-leave-active { transition: opacity .18s, transform .18s; }
.car-pop-enter-from, .car-pop-leave-to { opacity: 0; transform: translateY(8px) scale(.98); }
@media (prefers-reduced-motion: reduce) { .car-ln, .car-spin, .car-fab-dot { animation: none; } }
</style>
