<template>
    <div class="py-6" style="background:#FAFAF9">
        <div v-if="fetchError" />
        <div v-else class="max-w-[1180px]">
            <!-- Page head -->
            <div class="flex items-start gap-4 mb-5">
                <div class="min-w-0">
                    <h1 class="text-[19px] font-semibold tracking-[-0.01em] text-[#1C1917]">Queries &amp; metrics</h1>
                    <p class="text-[13.5px] text-[#78716C] mt-[3px]">Proven queries the agent has learned. Promote a good one to a named metric so it's computed one consistent way everywhere.</p>
                </div>
                <div class="ms-auto flex items-center gap-2 shrink-0">
                    <!-- Batch C / P6: one-click pre-train (profile columns + optional knowledge) -->
                    <div v-if="isAdmin" class="flex items-center gap-2">
                        <label class="flex items-center gap-1 text-[11px] text-[#78716C] cursor-pointer select-none" title="Auto-approve AI-suggested table/metric knowledge instead of sending it to the review queue">
                            <input type="checkbox" v-model="autoApprove" class="accent-[#C2541E] w-3.5 h-3.5" />
                            Auto-approve
                        </label>
                        <button
                            @click="runPretrain"
                            :disabled="pretraining"
                            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-[#C2541E] hover:bg-[#A8461A] disabled:opacity-60 transition-colors"
                            title="Profile every column (type, role, real values) so the agent is expert before the first question"
                        >
                            <Spinner v-if="pretraining" class="w-3.5 h-3.5" />
                            <Icon v-else name="heroicons:sparkles" class="w-3.5 h-3.5" />
                            {{ pretraining ? 'Training…' : 'Auto-train' }}
                        </button>
                    </div>
                </div>
            </div>

            <!-- Filter tabs + search -->
            <div class="flex items-center justify-between gap-3 mb-4">
                <div class="flex items-center gap-1 border-b border-[#EAE8E4]">
                    <button
                        @click="filterType = 'published'"
                        :class="[
                            'px-3 py-2 text-xs font-medium border-b-2 transition-colors',
                            filterType === 'published'
                                ? 'border-[#C2541E] text-[#C2541E]'
                                : 'border-transparent text-[#78716C] hover:text-[#1C1917]'
                        ]"
                    >
                        {{ $t('queries.published') }}
                    </button>
                    <button
                        @click="filterType = 'suggested'"
                        :class="[
                            'px-3 py-2 text-xs font-medium border-b-2 transition-colors',
                            filterType === 'suggested'
                                ? 'border-[#B45309] text-[#B45309]'
                                : 'border-transparent text-[#78716C] hover:text-[#1C1917]'
                        ]"
                    >
                        {{ isAdmin ? $t('queries.draftSuggested') : $t('queries.myDrafts') }}
                        <span v-if="suggestedCount > 0" class="ms-1.5 px-1.5 py-0.5 rounded-full text-[10px] bg-[#FBF0DD] text-[#B45309]">{{ suggestedCount }}</span>
                    </button>
                </div>
                <input
                    v-model="q"
                    type="text"
                    :placeholder="$t('queries.searchPlaceholder')"
                    class="border border-[#EAE8E4] rounded-lg px-3 py-1.5 text-xs w-52 bg-white text-[#1C1917] focus:outline-none focus:ring-1 focus:ring-[#E8C9B5]"
                />
            </div>

            <!-- Pre-train result card -->
            <div v-if="pretrainResult" class="mb-4 border border-[#E8C9B5] bg-[#FBEDE4] rounded-xl p-4">
                <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                        <div class="text-sm font-medium text-[#8B4427] flex items-center gap-1.5">
                            <Icon name="heroicons:check-badge" class="w-4 h-4" />
                            Trained on {{ formatCount(pretrainResult.row_count) }} rows · {{ pretrainResult.columns_written }} columns
                        </div>
                        <div v-if="pretrainResult.knowledge?.enabled" class="text-[11px] text-[#78716C] mt-0.5">
                            Knowledge: {{ pretrainResult.knowledge.proposed }} suggested<template v-if="pretrainResult.knowledge.approved"> · {{ pretrainResult.knowledge.approved }} auto-approved</template><template v-else-if="pretrainResult.knowledge.proposed"> · pending review</template>
                        </div>
                        <div v-if="pretrainResult.dimensions?.length" class="mt-2 flex flex-wrap gap-1.5">
                            <span
                                v-for="d in pretrainResult.dimensions"
                                :key="d.name"
                                class="text-[10px] px-2 py-0.5 rounded-full border border-[#E8C9B5] bg-white text-[#A8330F]"
                                :title="(d.values || []).join(', ')"
                            >{{ d.name }}: {{ (d.values || []).slice(0, 3).join(', ') }}<template v-if="(d.distinct || 0) > 3"> +{{ d.distinct - 3 }}</template></span>
                        </div>
                    </div>
                    <button @click="pretrainResult = null" class="text-[#A8A29E] hover:text-[#78716C] shrink-0">
                        <Icon name="heroicons:x-mark" class="w-4 h-4" />
                    </button>
                </div>
            </div>

            <!-- Loading -->
            <div v-if="loading" class="text-xs text-[#A8A29E] flex items-center gap-1.5 py-4">
                <Spinner class="w-3.5 h-3.5" />
                {{ $t('queries.loading') }}
            </div>

            <template v-else>
                <!-- Saved metrics card -->
                <div class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)] mb-4">
                    <div class="px-4 py-[13px] border-b border-[#F1EFEC] flex items-center gap-2 text-[13.5px] font-semibold text-[#1C1917]">
                        Saved metrics
                        <span class="ms-auto text-[11.5px] font-medium text-[#A8A29E]">reused across every report</span>
                    </div>
                    <div class="p-4">
                        <template v-if="savedMetrics.length">
                            <div
                                v-for="(m, i) in savedMetrics"
                                :key="m.id"
                                class="flex items-center gap-3 py-[10px] cursor-pointer"
                                :class="i < savedMetrics.length - 1 ? 'border-b border-[#F1EFEC]' : ''"
                                @click="navigateToEntity(m.id)"
                            >
                                <div class="flex-1 min-w-0">
                                    <b class="font-mono font-semibold text-[13.5px] text-[#1C1917]">{{ m.title || m.slug }}</b>
                                    <div class="text-[12px] text-[#78716C] truncate">{{ m.description || $t('queries.noDescription') }}</div>
                                </div>
                                <span
                                    class="text-[10.5px] font-semibold px-[7px] py-[2px] rounded-md whitespace-nowrap"
                                    :class="getEntityType(m) === 'global' ? 'text-[#15803D] bg-[#E7F5EC]' : 'text-[#B45309] bg-[#FBF0DD]'"
                                >{{ getEntityType(m) === 'global' ? 'verified' : 'draft' }}</span>
                            </div>
                        </template>
                        <div v-else class="py-3 text-[13px] text-[#78716C] leading-relaxed">
                            No saved metrics yet — promote a proven query to reuse it consistently.
                        </div>
                    </div>
                </div>

                <!-- Empty state (no queries in this filter) -->
                <div v-if="filteredQueries.length === 0" class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)]">
                    <div class="flex flex-col items-center justify-center py-16">
                        <div class="w-14 h-14 rounded-full bg-[#F1F1F0] flex items-center justify-center mb-3">
                            <Icon
                                :name="filterType === 'suggested' ? 'heroicons:light-bulb' : 'heroicons:cube'"
                                class="w-7 h-7 text-[#A8A29E]"
                            />
                        </div>
                        <p class="text-sm text-[#78716C]">
                            {{ filterType === 'suggested' ? $t('queries.noDrafts') : $t('queries.noPublished') }}
                        </p>
                    </div>
                </div>

                <!-- Recent queries card -->
                <div v-else class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)]">
                    <div class="px-4 py-[13px] border-b border-[#F1EFEC] flex items-center gap-2 text-[13.5px] font-semibold text-[#1C1917]">
                        Recent queries
                        <span class="ms-auto text-[11.5px] font-medium text-[#A8A29E]">↑ hover to promote to a metric</span>
                    </div>
                    <div class="px-4">
                        <div
                            v-for="(item, i) in filteredQueries"
                            :key="item.id"
                            class="py-3 cursor-pointer group"
                            :class="i < filteredQueries.length - 1 ? 'border-b border-[#F1EFEC]' : ''"
                            @click="navigateToEntity(item.id)"
                        >
                            <div class="flex items-center gap-2">
                                <div class="qt font-semibold text-[13.5px] text-[#1C1917] flex-1 min-w-0 group-hover:text-[#C2541E] transition-colors">{{ item.title || item.slug }}</div>
                                <Icon v-if="getEntityType(item) === 'global'" name="heroicons:check-badge" class="w-4 h-4 text-[#15803D]" title="Approved" />
                                <span v-if="getEntityType(item) === 'archived'" class="text-[10.5px] font-semibold px-[7px] py-[2px] rounded-md text-[#B4331A] bg-[#FBEAE6]">{{ $t('queries.archivedBadge') }}</span>
                                <span v-else-if="getEntityType(item) === 'draft'" class="text-[10.5px] font-semibold px-[7px] py-[2px] rounded-md text-[#6B7280] bg-[#F1F1F0]">{{ $t('queries.draftBadge') }}</span>
                                <span v-else-if="getEntityType(item) === 'private'" class="text-[10.5px] font-semibold px-[7px] py-[2px] rounded-md text-[#6B7280] bg-[#F1F1F0]">{{ $t('queries.draftBadge') }}</span>
                                <span v-else-if="getEntityType(item) === 'suggested'" class="text-[10.5px] font-semibold px-[7px] py-[2px] rounded-md text-[#B45309] bg-[#FBF0DD]">{{ $t('queries.suggestedBadge') }}</span>
                            </div>
                            <div v-if="item.description" class="qq font-mono text-[12px] text-[#78716C] mt-1 line-clamp-2">{{ item.description }}</div>
                            <div class="qm flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-[#A8A29E] mt-[6px]">
                                <span class="inline-flex items-center gap-1">
                                    <span
                                        class="text-[10.5px] font-semibold px-[7px] py-[2px] rounded-md"
                                        :class="item.type === 'metric' ? 'text-[#15803D] bg-[#E7F5EC]' : 'text-[#A8330F] bg-[#FBEDE4]'"
                                    >{{ (item.type || '').toUpperCase() }}</span>
                                </span>
                                <span v-if="item.data?.info?.total_rows !== undefined" class="inline-flex items-center gap-1">
                                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" /></svg>
                                    {{ formatCount(item.data.info.total_rows) }}
                                </span>
                                <span v-if="item.data?.info?.total_columns !== undefined" class="inline-flex items-center gap-1">
                                    <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 4v16M15 4v16" /></svg>
                                    {{ formatCount(item.data.info.total_columns) }}
                                </span>
                                <span class="tabular-nums">{{ timeAgo(item.updated_at) }}</span>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Summary -->
                <div v-if="filteredQueries.length > 0" class="mt-4 text-center text-[11px] text-[#A8A29E]">
                    {{ summaryLabel }}
                </div>
            </template>
        </div>
    </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'
import { useCan } from '~/composables/usePermissions'
import { useAuth } from '#imports'
import type { Ref } from 'vue'

definePageMeta({ auth: true, layout: 'data' })

const { t } = useI18n()
const router = useRouter()
const { data: authData } = useAuth()

const integration = inject<Ref<any>>('integration', ref(null))
const fetchError = inject<Ref<number | null>>('fetchError', ref(null))
const agentId = computed(() => integration.value?.id || '')

type MinimalDS = { id: string; name?: string; type?: string }
type EntityItem = {
    id: string
    type: string
    title: string
    slug: string
    description?: string | null
    updated_at: string
    data_sources?: MinimalDS[]
    data?: { info?: { total_rows?: number; total_columns?: number } }
    status?: string
    private_status?: string | null
    global_status?: string | null
    owner_id?: string
}

const allItems = ref<EntityItem[]>([])
const loading = ref(false)
const q = ref('')

// Batch C / P6 — one-click pre-train
const toast = useToast()
const activity = useActivity()
const pretraining = ref(false)
const autoApprove = ref(false)
const pretrainResult = ref<any>(null)
const filterType = ref<'published' | 'suggested'>('published')
const isAdmin = computed(() => useCan('update_entities'))
const currentUserId = computed(() => (authData.value as any)?.user?.id)

const suggestedCount = computed(() =>
    allItems.value.filter(item => {
        const type = getEntityType(item)
        return (type === 'private' || type === 'suggested' || type === 'draft') && !isArchived(item)
    }).length
)

const filteredItems = computed(() => {
    let filtered = allItems.value.filter(item => !isArchived(item))
    if (filterType.value === 'published') {
        filtered = filtered.filter(item => getEntityType(item) === 'global')
    } else {
        filtered = filtered.filter(item => {
            const type = getEntityType(item)
            return type === 'private' || type === 'suggested' || type === 'draft'
        })
        if (!isAdmin.value) {
            filtered = filtered.filter(item => item.owner_id === currentUserId.value)
        }
    }
    if (q.value) {
        const s = q.value.toLowerCase()
        filtered = filtered.filter(item =>
            item.title?.toLowerCase().includes(s) ||
            item.slug?.toLowerCase().includes(s) ||
            item.description?.toLowerCase().includes(s)
        )
    }
    return filtered
})

// Saved metrics = promoted/verified metric entities (real data; empty-state when none).
// Approved (global) metrics surface as "verified"; unapproved metric entities as "draft".
const savedMetrics = computed(() =>
    filteredItems.value.filter(item => item.type === 'metric')
)

// Recent queries = everything in the current filter that isn't a saved metric.
const filteredQueries = computed(() =>
    filteredItems.value.filter(item => item.type !== 'metric')
)

const summaryLabel = computed(() => {
    const count = filteredQueries.value.length
    if (filterType.value === 'suggested') {
        return t(count === 1 ? 'queries.showingDraftsOne' : 'queries.showingDraftsMany', { count })
    }
    return t(count === 1 ? 'queries.showingPublishedOne' : 'queries.showingPublishedMany', { count })
})

function isArchived(item: EntityItem) {
    return item.status === 'archived' || item.private_status === 'archived'
}

function getEntityType(item: EntityItem): string {
    if (isArchived(item)) return 'archived'
    if (item.private_status && !item.global_status) return 'private'
    if (item.private_status && item.global_status === 'suggested') return 'suggested'
    if (!item.private_status && item.global_status === 'approved') {
        if (item.status === 'published') return 'global'
        if (item.status === 'draft') return 'draft'
    }
    return 'unknown'
}

function navigateToEntity(id: string) {
    router.push(`/queries/${id}`)
}

function timeAgo(iso: string | Date | null | undefined) {
    if (!iso) return '—'
    const d = typeof iso === 'string' ? new Date(iso) : iso
    const diff = Math.max(0, Date.now() - (d?.getTime?.() || 0))
    const mins = Math.floor(diff / 60000)
    if (mins < 60) return t('queries.timeMinutesAgo', { n: mins })
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return t('queries.timeHoursAgo', { n: hrs })
    return t('queries.timeDaysAgo', { n: Math.floor(hrs / 24) })
}

function formatCount(num?: number): string {
    if (num == null) return '—'
    if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`
    if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`
    return String(num)
}

async function loadEntities() {
    if (!agentId.value) return
    loading.value = true
    try {
        const { data, error } = await useMyFetch(`/api/entities?data_source_ids=${agentId.value}`, { method: 'GET' })
        if (error.value) throw error.value
        allItems.value = (data.value as any) || []
    } catch {
        allItems.value = []
    } finally {
        loading.value = false
    }
}

async function runPretrain() {
    if (!agentId.value || pretraining.value) return
    pretraining.value = true
    pretrainResult.value = null
    // P7 — robot pre-train activity stream (agent studio only; route-scoped in RobotAssistant)
    activity.start('Pre-training agent')
    activity.openPanel()
    activity.setState('processing')
    activity.log('Profiling columns — types, roles, real values…')
    try {
        const { data, error } = await useMyFetch(`/api/data_sources/${agentId.value}/pretrain`, {
            method: 'POST',
            body: { suggest_knowledge: true, auto_approve: autoApprove.value },
        })
        if (error.value) throw error.value
        const res = data.value as any
        if (res?.disabled) {
            activity.fail('Column intelligence is disabled (Feature Flags)')
            toast.add({ title: 'Pre-train disabled', description: 'Enable Column Intelligence in Settings → Feature Flags.', color: 'orange' })
            return
        }
        if (!res?.ok) {
            activity.fail(res?.error || 'Pre-train failed')
            toast.add({ title: 'Pre-train failed', description: res?.error || 'Unknown error', color: 'red' })
            return
        }
        pretrainResult.value = res
        for (const d of (res.dimensions || []).slice(0, 8)) {
            activity.log(`${d.name}: ${(d.values || []).slice(0, 4).join(', ')}${(d.distinct || 0) > 4 ? ` +${d.distinct - 4}` : ''}`, 'ok')
        }
        if (res.knowledge?.enabled) {
            activity.log(`Knowledge: ${res.knowledge.proposed} suggested${res.knowledge.approved ? `, ${res.knowledge.approved} approved` : (res.knowledge.proposed ? ', pending review' : '')}`, 'info')
        }
        activity.done(`Trained on ${res.row_count?.toLocaleString?.() || res.row_count} rows · ${res.columns_written} columns`)
        toast.add({ title: 'Agent trained', description: `${res.columns_written} columns profiled on ${res.row_count?.toLocaleString?.() || res.row_count} rows.`, color: 'green' })
    } catch (e: any) {
        activity.fail('Pre-train failed')
        toast.add({ title: 'Pre-train failed', description: e?.data?.detail || e?.message || 'Unknown error', color: 'red' })
    } finally {
        pretraining.value = false
    }
}

watch(agentId, (id) => { if (id) loadEntities() }, { immediate: true })
</script>

<style scoped>
.line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
</style>
