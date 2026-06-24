<template>
    <div>
        <!-- Action row -->
        <div class="flex items-center justify-between mb-5">
            <p class="text-sm text-[#6b6b6b] leading-relaxed max-w-2xl">
                How Domain Packs (Skills) are bound, firing, and performing across every studio in this org.
            </p>
            <button
                type="button"
                :disabled="loading"
                class="inline-flex items-center gap-1.5 text-xs text-[#6b6b6b] hover:text-[#1f2328] border border-[#E7E5DD] rounded-lg px-2.5 py-1.5 transition-colors disabled:opacity-50"
                @click="load"
            >
                <Spinner v-if="loading" class="h-3.5 w-3.5" />
                <UIcon v-else name="i-heroicons-arrow-path" class="w-3.5 h-3.5" />
                Refresh
            </button>
        </div>

        <!-- Loading (first load) -->
        <div v-if="loading && !loaded" class="py-12 flex justify-center">
            <Spinner class="h-6 w-6 text-[#C2683F]" />
        </div>

        <!-- Error -->
        <div v-else-if="errorMsg" class="flex items-start gap-2 rounded-xl border border-[#EAD4D4] bg-[#FBF2F2] px-4 py-3">
            <UIcon name="i-heroicons-exclamation-triangle" class="w-5 h-5 text-[#A83F3F] mt-0.5 flex-shrink-0" />
            <p class="text-sm text-[#A83F3F]">{{ errorMsg }}</p>
        </div>

        <template v-else>
            <!-- Totals strip -->
            <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-7">
                <div
                    v-for="card in totalCards"
                    :key="card.label"
                    class="rounded-2xl border border-[#E7E5DD] bg-white px-4 py-3.5"
                >
                    <div class="text-2xl font-semibold text-[#1f2328]" style="font-family: ui-serif, Georgia, 'Times New Roman', serif">
                        {{ card.value }}
                    </div>
                    <div class="text-xs text-[#6b6b6b] mt-0.5">{{ card.label }}</div>
                </div>
            </div>

            <!-- Empty -->
            <div v-if="!packs.length" class="py-10 text-center border border-dashed border-[#E7E5DD] rounded-2xl">
                <UIcon name="i-heroicons-puzzle-piece" class="w-7 h-7 mx-auto text-[#9a958c] mb-1.5" />
                <p class="text-xs text-[#6b6b6b]">No Domain Packs are bound in any studio yet. Bind a pack in a studio's Skills tab, or run Auto-train.</p>
            </div>

            <!-- Packs table -->
            <div v-else class="mb-8">
                <h2 class="text-[15px] font-semibold text-[#1f2328] mb-3" style="font-family: ui-serif, Georgia, 'Times New Roman', serif">
                    Packs
                </h2>
                <div class="border border-[#E7E5DD] rounded-2xl overflow-hidden">
                    <div class="overflow-x-auto">
                        <table class="min-w-full text-sm">
                            <thead class="bg-[#F4F1EA] text-[#6b6b6b]">
                                <tr>
                                    <th class="text-start font-medium px-4 py-2.5 whitespace-nowrap">Pack</th>
                                    <th class="text-center font-medium px-3 py-2.5 whitespace-nowrap">Studios</th>
                                    <th class="text-start font-medium px-3 py-2.5 whitespace-nowrap">Status mix</th>
                                    <th class="text-center font-medium px-3 py-2.5 whitespace-nowrap">Fires</th>
                                    <th class="text-center font-medium px-4 py-2.5 whitespace-nowrap">Win rate</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-[#E7E5DD]">
                                <tr v-for="p in packs" :key="p.pack_id" class="bg-white">
                                    <!-- Name + source -->
                                    <td class="px-4 py-3 align-top">
                                        <div class="flex items-center gap-2 flex-wrap">
                                            <span class="font-medium text-[#1f2328]">{{ p.name }}</span>
                                            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-[#F4F1EA] border border-[#E7E5DD] text-[#6b6b6b]">
                                                {{ sourceLabel(p.source) }}
                                            </span>
                                        </div>
                                        <p class="text-[11px] font-mono text-[#9a958c] mt-0.5 truncate max-w-[220px]">{{ p.pack_id }}</p>
                                    </td>

                                    <!-- Studios bound -->
                                    <td class="px-3 py-3 text-center align-top tabular-nums text-[#1f2328]">{{ p.studios }}</td>

                                    <!-- Status mix -->
                                    <td class="px-3 py-3 align-top">
                                        <div class="flex items-center gap-1 flex-wrap">
                                            <span
                                                v-for="b in statusBadges(p)"
                                                :key="b.key"
                                                class="inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full border"
                                                :class="b.cls"
                                                :title="b.title"
                                            >{{ b.count }} {{ b.short }}</span>
                                            <span v-if="!statusBadges(p).length" class="text-[11px] text-[#9a958c]">—</span>
                                        </div>
                                    </td>

                                    <!-- Fires -->
                                    <td class="px-3 py-3 text-center align-top tabular-nums text-[#1f2328]">{{ p.fires }}</td>

                                    <!-- Win rate -->
                                    <td class="px-4 py-3 text-center align-top">
                                        <span
                                            class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full"
                                            :class="winrateClass(p)"
                                            :title="`${p.wins} win(s) · ${p.losses} loss(es)`"
                                        >
                                            {{ winrateLabel(p) }}
                                        </span>
                                        <div class="text-[10px] text-[#9a958c] mt-0.5">{{ p.samples }} sample{{ p.samples === 1 ? '' : 's' }}</div>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- Dormant backlog -->
            <div v-if="dormant.length">
                <h2 class="text-[15px] font-semibold text-[#1f2328] mb-1" style="font-family: ui-serif, Georgia, 'Times New Roman', serif">
                    Dormant backlog
                </h2>
                <p class="text-xs text-[#6b6b6b] mb-3 max-w-2xl">
                    These packs are bound but missing a column in their studio — add the column and re-train to activate.
                </p>
                <div class="space-y-2.5">
                    <div
                        v-for="(d, i) in dormant"
                        :key="`${d.pack_id}-${d.studio_id}-${i}`"
                        class="rounded-2xl border border-[#E7E5DD] bg-white px-4 py-3"
                    >
                        <div class="flex items-center gap-2 flex-wrap mb-1.5">
                            <span class="text-sm font-medium text-[#1f2328]">{{ d.name }}</span>
                            <span class="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border border-[#E7E5DD] bg-[#F4F1EA] text-[#6b6b6b]">
                                <UIcon name="i-heroicons-moon" class="w-3 h-3" /> Dormant
                            </span>
                            <span class="text-[11px] text-[#9a958c]" :title="d.studio_id">studio {{ shortId(d.studio_id) }}</span>
                        </div>
                        <div class="text-[11px] text-[#A8542F] flex items-center gap-1.5 flex-wrap">
                            <UIcon name="i-heroicons-exclamation-triangle" class="w-3.5 h-3.5 shrink-0" />
                            <span class="text-[#6b6b6b]">needs a column for:</span>
                            <code
                                v-for="m in (d.missing || [])"
                                :key="m"
                                class="bg-[#F6EFEA] border border-[#E8C9B5] text-[#A8542F] rounded px-1.5 py-0.5"
                            >{{ m }}</code>
                            <span v-if="!(d.missing || []).length" class="text-[#9a958c]">unspecified</span>
                        </div>
                    </div>
                </div>
            </div>
        </template>
    </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

definePageMeta({ auth: true, permissions: ['manage_settings'], layout: 'settings' })

interface PackRow {
    pack_id: string
    name: string
    source: string
    studios: number
    active: number
    pending: number
    dormant: number
    rejected: number
    fires: number
    wins: number
    losses: number
    win_rate: number | null
    samples: number
}
interface DormantRow {
    pack_id: string
    name: string
    studio_id: string
    missing: string[]
}

const loading = ref(false)
const loaded = ref(false)
const errorMsg = ref('')

const totals = ref<Record<string, number>>({})
const packs = ref<PackRow[]>([])
const dormant = ref<DormantRow[]>([])

const totalCards = computed(() => [
    { label: 'Packs', value: totals.value.packs ?? 0 },
    { label: 'Active', value: totals.value.active ?? 0 },
    { label: 'Dormant', value: totals.value.dormant ?? 0 },
    { label: 'Total fires', value: totals.value.fires ?? 0 },
    { label: 'Studios with packs', value: totals.value.studios_with_packs ?? 0 },
])

function sourceLabel(src: string): string {
    return src === 'user' ? 'authored' : src === 'org' ? 'org-shared' : 'library'
}

function shortId(id: string): string {
    return id ? String(id).slice(0, 8) : '—'
}

const _statusMeta: { key: 'active' | 'pending' | 'dormant' | 'rejected'; short: string; cls: string }[] = [
    { key: 'active', short: 'active', cls: 'border-[#CFE0CF] bg-[#EEF5EE] text-[#2f7d53]' },
    { key: 'pending', short: 'pending', cls: 'border-[#E8C9B5] bg-[#F6EFEA] text-[#A8542F]' },
    { key: 'dormant', short: 'dormant', cls: 'border-[#E7E5DD] bg-[#F4F1EA] text-[#6b6b6b]' },
    { key: 'rejected', short: 'rejected', cls: 'border-[#EAD4D4] bg-[#FBF2F2] text-[#A83F3F]' },
]

function statusBadges(p: PackRow) {
    return _statusMeta
        .filter(m => (p[m.key] || 0) > 0)
        .map(m => ({ key: m.key, short: m.short, cls: m.cls, count: p[m.key], title: `${p[m.key]} ${m.short}` }))
}

function winrateClass(p: PackRow): string {
    if (!p.samples || p.win_rate === null) return 'bg-[#F4F1EA] text-[#6b6b6b]'
    return p.win_rate >= 0.5 ? 'bg-[#E4F1EA] text-[#2f7d53]' : 'bg-[#FBE4E4] text-[#A83F3F]'
}

function winrateLabel(p: PackRow): string {
    if (!p.samples || p.win_rate === null) return 'no data'
    return `${Math.round(p.win_rate * 100)}%`
}

async function load() {
    if (loading.value) return
    loading.value = true
    errorMsg.value = ''
    try {
        const { data, error } = await useMyFetch<any>('/api/organization/pack-analytics')
        if (error.value) throw error.value
        const res = (data.value as any) || {}
        totals.value = res.totals || {}
        packs.value = Array.isArray(res.packs) ? res.packs : []
        dormant.value = Array.isArray(res.dormant) ? res.dormant : []
    } catch (e: any) {
        errorMsg.value = String(e?.data?.detail || e?.data?.message || e?.message || 'Could not load pack analytics.')
    } finally {
        loading.value = false
        loaded.value = true
    }
}

onMounted(load)
</script>
