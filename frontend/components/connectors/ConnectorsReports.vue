<template>
    <div>
        <!-- TOTALS strip + controls -->
        <div class="flex flex-wrap items-center gap-3 mb-5">
            <div class="flex flex-wrap items-center gap-2.5">
                <div v-for="s in totals" :key="s.label" class="px-3.5 py-2 rounded-xl border border-[#E9E0D3] bg-white min-w-[92px]">
                    <div class="text-[10px] font-semibold uppercase tracking-wide text-[#9a958c]">{{ s.label }}</div>
                    <div class="text-[17px] font-semibold text-[#1f2328] leading-tight mt-0.5">{{ s.value }}</div>
                </div>
            </div>

            <div class="ms-auto flex items-center gap-2">
                <!-- Days selector -->
                <div class="inline-flex rounded-lg border border-[#E9E0D3] bg-white overflow-hidden">
                    <button
                        v-for="d in [7, 30, 90]"
                        :key="d"
                        @click="setDays(d)"
                        class="px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]/40"
                        :class="days === d ? 'bg-[#C2541E] text-white' : 'text-[#6b6b6b] hover:bg-[#F4EEE5]'"
                    >{{ d }}d</button>
                </div>
                <button
                    @click="load"
                    :disabled="loading"
                    title="Refresh"
                    class="w-8 h-8 grid place-items-center rounded-lg border border-[#E9E0D3] bg-white text-[#6b6b6b] hover:text-[#C2541E] hover:border-[#C2541E]/40 transition-colors cursor-pointer disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]/40"
                >
                    <svg :class="loading ? 'animate-spin' : ''" class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 12a9 9 0 1 1-2.64-6.36" /><path d="M21 3v6h-6" />
                    </svg>
                </button>
            </div>
        </div>

        <!-- Connector pills -->
        <div class="flex flex-wrap gap-2 mb-4">
            <button
                v-for="g in groups"
                :key="g.connector_key"
                @click="activeKey = g.connector_key"
                class="px-3 py-1.5 rounded-full text-xs font-semibold border transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]/40"
                :class="activeKey === g.connector_key
                    ? 'bg-[#C2541E] text-white border-[#C2541E]'
                    : 'bg-white text-[#6b6b6b] border-[#E9E0D3] hover:border-[#C2541E]/40 hover:text-[#1f2328]'"
            >
                {{ g.connector_label }}
                <span
                    class="ms-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold"
                    :class="activeKey === g.connector_key ? 'bg-white/25 text-white' : 'bg-[#F4EEE5] text-[#9a958c]'"
                >{{ g.connected_count }}</span>
            </button>
        </div>

        <!-- Loading skeleton -->
        <div v-if="loading && !groups.length" class="space-y-2">
            <div v-for="i in 4" :key="i" class="h-11 rounded-xl bg-[#F4EEE5] animate-pulse"></div>
        </div>

        <!-- Selected group -->
        <div v-else-if="activeGroup" class="rounded-2xl border border-[#E9E0D3] bg-white overflow-hidden">
            <!-- Header + mini stat strip -->
            <div class="flex flex-wrap items-center gap-4 px-5 py-4 border-b border-[#F0E9DD]">
                <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family:'Spectral',serif">{{ activeGroup.connector_label }}</h3>
                <div class="flex flex-wrap items-center gap-5 ms-auto">
                    <div class="text-center">
                        <div class="text-[10px] uppercase tracking-wide text-[#9a958c] font-semibold">Active 7d</div>
                        <div class="text-sm font-semibold text-[#1f2328]">{{ activeGroup.active_7d }}</div>
                    </div>
                    <div class="text-center">
                        <div class="text-[10px] uppercase tracking-wide text-[#9a958c] font-semibold">Questions</div>
                        <div class="text-sm font-semibold text-[#1f2328]">{{ fmtNum(activeGroup.questions) }}</div>
                    </div>
                    <div class="text-center">
                        <div class="text-[10px] uppercase tracking-wide text-[#9a958c] font-semibold">Tokens</div>
                        <div class="text-sm font-semibold text-[#1f2328]">{{ fmtTokens(activeGroup.tokens) }}</div>
                    </div>
                    <div class="text-center">
                        <div class="text-[10px] uppercase tracking-wide text-[#9a958c] font-semibold">Last used</div>
                        <div class="text-sm font-semibold text-[#1f2328]">{{ relTime(activeGroup.last_used_at) }}</div>
                    </div>
                    <button
                        v-if="activeGroup.users.length"
                        @click="exportCsv"
                        class="text-xs font-semibold px-3 py-1.5 rounded-lg border border-[#E9E0D3] text-[#6b6b6b] hover:text-[#C2541E] hover:border-[#C2541E]/40 transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]/40"
                    >Export CSV</button>
                </div>
            </div>

            <!-- Empty group -->
            <div v-if="!activeGroup.users.length" class="py-14 text-center">
                <div class="text-sm text-[#9a958c]">No one connected yet.</div>
            </div>

            <!-- User table -->
            <div v-else class="overflow-x-auto">
                <table class="w-full text-sm">
                    <thead>
                        <tr class="text-[10.5px] uppercase tracking-wide text-[#9a958c] border-b border-[#F0E9DD]">
                            <th class="text-left font-semibold px-5 py-2.5">User</th>
                            <th class="text-left font-semibold px-3 py-2.5">Status</th>
                            <th class="text-left font-semibold px-3 py-2.5">Connected</th>
                            <th class="text-left font-semibold px-3 py-2.5">Last used</th>
                            <th class="text-right font-semibold px-3 py-2.5">Tables</th>
                            <th class="text-right font-semibold px-3 py-2.5">Q</th>
                            <th class="text-right font-semibold px-3 py-2.5">Tokens</th>
                            <th class="text-right font-semibold px-3 py-2.5">Cost</th>
                            <th class="px-3 py-2.5"></th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr
                            v-for="u in activeGroup.users"
                            :key="u.data_source_id"
                            @click="openDrawer(u)"
                            class="border-b border-[#F6F1EA] hover:bg-[#FCFAF6] transition-colors cursor-pointer"
                        >
                            <td class="px-5 py-3 max-w-[240px]">
                                <div class="text-[#1f2328] font-medium truncate">{{ u.email || u.name || '—' }}</div>
                                <div v-if="u.connector_email && u.connector_email !== u.email" class="text-[11px] text-[#9a8f80] truncate" title="Connector sign-in account">
                                    <span class="inline-block align-middle w-3 h-3 mr-1 rounded-[3px] bg-[#E9E0D3]"></span>{{ u.connector_email }}
                                </div>
                            </td>
                            <td class="px-3 py-3">
                                <span class="inline-flex items-center gap-1.5">
                                    <span class="w-2 h-2 rounded-full" :class="dotClass(u.status)"></span>
                                    <span class="text-xs text-[#6b6b6b] capitalize">{{ u.status }}</span>
                                </span>
                            </td>
                            <td class="px-3 py-3 text-[#6b6b6b] text-xs">{{ relTime(u.connected_at) }}</td>
                            <td class="px-3 py-3 text-[#6b6b6b] text-xs">{{ relTime(u.last_used_at) }}</td>
                            <td class="px-3 py-3 text-right text-[#1f2328]">{{ u.tables }}</td>
                            <td class="px-3 py-3 text-right text-[#1f2328]">{{ fmtNum(u.questions) }}</td>
                            <td class="px-3 py-3 text-right text-[#1f2328]">{{ fmtTokens(u.tokens) }}</td>
                            <td class="px-3 py-3 text-right text-[#1f2328]">{{ fmtCost(u.cost_usd) }}</td>
                            <td class="px-3 py-3 text-right">
                                <button
                                    @click.stop="openDrawer(u)"
                                    title="Details"
                                    class="w-7 h-7 grid place-items-center rounded-lg text-[#9a958c] hover:bg-[#F4EEE5] hover:text-[#C2541E] transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]/40"
                                >
                                    <svg class="w-4 h-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/></svg>
                                </button>
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- ================= DETAIL DRAWER ================= -->
        <Teleport to="body">
            <div v-if="drawerOpen" class="fixed inset-0 z-[80]">
                <div class="absolute inset-0 bg-black/25 transition-opacity" @click="closeDrawer"></div>
                <div class="absolute top-0 right-0 h-full w-full max-w-[440px] bg-[#FBFAF6] shadow-2xl border-l border-[#E9E0D3] flex flex-col animate-[slideIn_220ms_ease-out]">
                    <!-- Drawer header -->
                    <div class="flex items-start gap-3 px-5 py-4 border-b border-[#E9E0D3]">
                        <div class="min-w-0 flex-1">
                            <div class="text-[13.5px] font-semibold text-[#1f2328] truncate">{{ detail?.email || detail?.name || drawerUser?.email || '—' }}</div>
                            <div v-if="(detail?.connector_email || drawerUser?.connector_email) && (detail?.connector_email || drawerUser?.connector_email) !== (detail?.email || drawerUser?.email)" class="text-[11px] text-[#9a8f80] truncate mt-0.5" title="Connector sign-in account">
                                {{ detail?.connector_email || drawerUser?.connector_email }}
                            </div>
                            <div class="text-[11px] text-[#9a958c] mt-0.5">{{ detail?.connector_label || activeGroup?.connector_label }}</div>
                        </div>
                        <button @click="closeDrawer" class="w-7 h-7 grid place-items-center rounded-lg text-[#9a958c] hover:bg-[#F4EEE5] hover:text-[#1f2328] transition-colors cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]/40">
                            <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
                        </button>
                    </div>

                    <div class="flex-1 overflow-y-auto px-5 py-4 space-y-5">
                        <div v-if="detailLoading" class="space-y-2">
                            <div v-for="i in 5" :key="i" class="h-9 rounded-lg bg-[#F4EEE5] animate-pulse"></div>
                        </div>

                        <template v-else-if="detail && !detail.error">
                            <!-- Connection facts -->
                            <div class="grid grid-cols-2 gap-2.5">
                                <div v-for="f in detailFacts" :key="f.label" class="rounded-xl border border-[#E9E0D3] bg-white px-3 py-2">
                                    <div class="text-[10px] uppercase tracking-wide text-[#9a958c] font-semibold">{{ f.label }}</div>
                                    <div class="text-[13px] font-semibold text-[#1f2328] mt-0.5">{{ f.value }}</div>
                                </div>
                            </div>

                            <!-- Daily questions sparkline -->
                            <div>
                                <div class="text-[10px] uppercase tracking-wide text-[#9a958c] font-semibold mb-1.5">Questions · last 14 days</div>
                                <div class="rounded-xl border border-[#E9E0D3] bg-white p-3">
                                    <svg v-if="sparkMax > 0" :viewBox="`0 0 ${spark.length * 12} 40`" class="w-full h-10" preserveAspectRatio="none">
                                        <rect
                                            v-for="(pt, i) in spark"
                                            :key="i"
                                            :x="i * 12 + 1.5"
                                            :y="40 - barH(pt.count)"
                                            width="9"
                                            :height="barH(pt.count)"
                                            rx="1.5"
                                            fill="#C2541E"
                                            :opacity="pt.count ? 0.9 : 0.15"
                                        >
                                            <title>{{ pt.date }} · {{ pt.count }}</title>
                                        </rect>
                                    </svg>
                                    <div v-else class="text-xs text-[#9a958c] text-center py-2">No questions in this window.</div>
                                </div>
                            </div>

                            <!-- Top questions -->
                            <div>
                                <div class="text-[10px] uppercase tracking-wide text-[#9a958c] font-semibold mb-1.5">Top questions</div>
                                <div v-if="detail.top_questions?.length" class="space-y-1.5">
                                    <div
                                        v-for="(q, i) in detail.top_questions"
                                        :key="i"
                                        class="flex items-start gap-2 rounded-lg border border-[#F0E9DD] bg-white px-3 py-2"
                                    >
                                        <span class="text-[13px] text-[#3d3a34] leading-snug flex-1 min-w-0">{{ q.text }}</span>
                                        <span class="text-[10px] font-bold text-[#9a958c] bg-[#F4EEE5] rounded-full px-1.5 py-0.5 shrink-0">×{{ q.count }}</span>
                                    </div>
                                </div>
                                <div v-else class="text-xs text-[#9a958c]">No questions yet.</div>
                            </div>

                            <!-- Sync history -->
                            <div>
                                <div class="text-[10px] uppercase tracking-wide text-[#9a958c] font-semibold mb-1.5">Sync history</div>
                                <div v-if="detail.sync_history?.length" class="rounded-xl border border-[#E9E0D3] bg-[#1b1813] p-3 max-h-64 overflow-y-auto font-mono text-[11px] leading-relaxed">
                                    <div v-for="(h, i) in detail.sync_history" :key="i" class="flex items-start gap-2">
                                        <span class="shrink-0" :class="h.ok ? 'text-[#5fbf8a]' : (h.level === 'error' ? 'text-[#e07a6a]' : 'text-[#8a857c]')">{{ h.ok ? '✓' : (h.level === 'error' ? '✕' : '›') }}</span>
                                        <span class="text-[#c9c2b6] flex-1 min-w-0 break-words">
                                            <span v-if="h.table" class="text-[#d8a26a]">{{ h.table }}</span>
                                            <span v-if="h.table"> · </span>{{ h.phase }}<span v-if="h.rows != null" class="text-[#8a857c]"> · {{ fmtNum(h.rows) }} rows</span>
                                        </span>
                                    </div>
                                </div>
                                <div v-else class="text-xs text-[#9a958c]">No sync history recorded.</div>
                            </div>
                        </template>

                        <div v-else class="text-sm text-[#9a958c] py-8 text-center">Could not load details.</div>
                    </div>
                </div>
            </div>
        </Teleport>
    </div>
</template>

<script lang="ts" setup>
import { ref, computed, onMounted } from 'vue'

const loading = ref(false)
const groups = ref<any[]>([])
const activeKey = ref<string>('')
const days = ref(30)

const drawerOpen = ref(false)
const drawerUser = ref<any>(null)
const detail = ref<any>(null)
const detailLoading = ref(false)

const activeGroup = computed(() => groups.value.find(g => g.connector_key === activeKey.value) || null)

const totals = computed(() => {
    const connected = groups.value.reduce((a, g) => a + (g.connected_count || 0), 0)
    const active = groups.value.reduce((a, g) => a + (g.active_7d || 0), 0)
    const q = groups.value.reduce((a, g) => a + (g.questions || 0), 0)
    const tok = groups.value.reduce((a, g) => a + (g.tokens || 0), 0)
    const cost = groups.value.reduce((a, g) => a + (g.cost_usd || 0), 0)
    return [
        { label: 'Connected', value: fmtNum(connected) },
        { label: 'Active 7d', value: fmtNum(active) },
        { label: 'Questions', value: fmtNum(q) },
        { label: 'Tokens', value: fmtTokens(tok) },
        { label: 'Cost', value: fmtCost(cost) },
    ]
})

// ---- number / time formatting ----
function fmtNum(n: number) {
    return (n || 0).toLocaleString('en-US')
}
function fmtTokens(n: number) {
    n = n || 0
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(2).replace(/\.00$/, '') + 'M'
    if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, '') + 'K'
    return String(n)
}
function fmtCost(n: number) {
    return '$' + (n || 0).toFixed(2)
}
function relTime(iso: string | null) {
    if (!iso) return '—'
    const t = new Date(iso).getTime()
    if (isNaN(t)) return '—'
    const s = Math.max(0, Math.floor((Date.now() - t) / 1000))
    if (s < 60) return 'just now'
    const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
    const d = Math.floor(h / 24); if (d < 30) return `${d}d ago`
    const mo = Math.floor(d / 30); if (mo < 12) return `${mo}mo ago`
    return `${Math.floor(mo / 12)}y ago`
}
function dotClass(status: string) {
    if (status === 'live') return 'bg-[#3f9e6a]'
    if (status === 'error') return 'bg-[#c0563a]'
    return 'bg-[#c9bfa4]' // idle
}

// ---- sparkline ----
const spark = computed<any[]>(() => detail.value?.daily_questions || [])
const sparkMax = computed(() => spark.value.reduce((m, p) => Math.max(m, p.count || 0), 0))
function barH(count: number) {
    if (!sparkMax.value) return 0
    return Math.max(count ? 3 : 0, Math.round((count / sparkMax.value) * 36))
}

const detailFacts = computed(() => {
    const d = detail.value || {}
    return [
        { label: 'Status', value: (d.status || '—') },
        { label: 'Connected', value: relTime(d.connected_at) },
        { label: 'Last used', value: relTime(d.last_used_at) },
        { label: 'Tables', value: fmtNum(d.tables || 0) },
        { label: 'Rows', value: fmtNum(d.rows || 0) },
        { label: 'Questions', value: fmtNum(d.questions || 0) },
        { label: 'Tokens in', value: fmtTokens(d.tokens_in || 0) },
        { label: 'Tokens out', value: fmtTokens(d.tokens_out || 0) },
        { label: 'Cost', value: fmtCost(d.cost_usd || 0) },
        { label: 'Avg latency', value: d.avg_latency_ms != null ? `${(d.avg_latency_ms / 1000).toFixed(1)}s` : '—' },
        { label: 'Errors 7d', value: fmtNum(d.errors_7d || 0) },
    ]
})

// ---- data ----
async function load() {
    loading.value = true
    try {
        const { data } = await useMyFetch(`/connectors/report?days=${days.value}`, { method: 'GET' })
        const list = (data.value as any[]) || []
        groups.value = list
        if (!activeKey.value || !list.find(g => g.connector_key === activeKey.value)) {
            // Prefer the first group that has users, else the first group.
            const withUsers = list.find(g => (g.connected_count || 0) > 0)
            activeKey.value = (withUsers || list[0])?.connector_key || ''
        }
    } catch {
        groups.value = []
    } finally {
        loading.value = false
    }
}

function setDays(d: number) {
    if (days.value === d) return
    days.value = d
    load()
    if (drawerOpen.value && drawerUser.value) openDrawer(drawerUser.value)
}

async function openDrawer(u: any) {
    drawerUser.value = u
    drawerOpen.value = true
    detail.value = null
    detailLoading.value = true
    try {
        const { data } = await useMyFetch(`/connectors/report/${u.data_source_id}?days=${days.value}`, { method: 'GET' })
        detail.value = (data.value as any) || null
    } catch {
        detail.value = { error: true }
    } finally {
        detailLoading.value = false
    }
}
function closeDrawer() {
    drawerOpen.value = false
    drawerUser.value = null
    detail.value = null
}

function exportCsv() {
    const g = activeGroup.value
    if (!g) return
    const cols = ['email', 'connector_email', 'status', 'connected_at', 'last_used_at', 'tables', 'questions', 'tokens', 'cost_usd']
    const head = ['User', 'Connector account', 'Status', 'Connected', 'Last used', 'Tables', 'Questions', 'Tokens', 'Cost (USD)']
    const esc = (v: any) => {
        const s = v == null ? '' : String(v)
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
    }
    const lines = [head.join(',')]
    for (const u of g.users) lines.push(cols.map(c => esc(u[c])).join(','))
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `connector-report-${g.connector_key}-${days.value}d.csv`
    a.click()
    URL.revokeObjectURL(url)
}

onMounted(load)
</script>

<style scoped>
@keyframes slideIn {
    from { transform: translateX(24px); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}
</style>
