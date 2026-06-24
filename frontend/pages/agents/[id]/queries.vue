<template>
    <div class="py-6">
        <div v-if="fetchError" />
        <div v-else>
            <!-- Filter tabs + search -->
            <div class="flex items-center justify-between gap-3 mb-4">
                <div class="flex items-center gap-1 border-b border-gray-200">
                    <button
                        @click="filterType = 'published'"
                        :class="[
                            'px-3 py-2 text-xs font-medium border-b-2 transition-colors',
                            filterType === 'published'
                                ? 'border-[#C2683F] text-[#C2683F]'
                                : 'border-transparent text-gray-500 hover:text-gray-700'
                        ]"
                    >
                        {{ $t('queries.published') }}
                    </button>
                    <button
                        @click="filterType = 'suggested'"
                        :class="[
                            'px-3 py-2 text-xs font-medium border-b-2 transition-colors',
                            filterType === 'suggested'
                                ? 'border-amber-500 text-amber-600'
                                : 'border-transparent text-gray-500 hover:text-gray-700'
                        ]"
                    >
                        {{ isAdmin ? $t('queries.draftSuggested') : $t('queries.myDrafts') }}
                        <span v-if="suggestedCount > 0" class="ms-1.5 px-1.5 py-0.5 rounded-full text-[10px] bg-amber-100 text-amber-700">{{ suggestedCount }}</span>
                    </button>
                </div>
                <div class="flex items-center gap-2">
                    <!-- Batch C / P6: one-click pre-train (profile columns + optional knowledge) -->
                    <div v-if="isAdmin" class="flex items-center gap-2">
                        <label class="flex items-center gap-1 text-[11px] text-gray-500 cursor-pointer select-none" title="Auto-approve AI-suggested table/metric knowledge instead of sending it to the review queue">
                            <input type="checkbox" v-model="autoApprove" class="accent-[#C2683F] w-3.5 h-3.5" />
                            Auto-approve
                        </label>
                        <button
                            @click="runPretrain"
                            :disabled="pretraining"
                            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium text-white bg-[#C2683F] hover:bg-[#A8542F] disabled:opacity-60 transition-colors"
                            title="Profile every column (type, role, real values) so the agent is expert before the first question"
                        >
                            <Spinner v-if="pretraining" class="w-3.5 h-3.5" />
                            <Icon v-else name="heroicons:sparkles" class="w-3.5 h-3.5" />
                            {{ pretraining ? 'Training…' : 'Auto-train' }}
                        </button>
                    </div>
                    <input
                        v-model="q"
                        type="text"
                        :placeholder="$t('queries.searchPlaceholder')"
                        class="border border-gray-200 rounded-md px-3 py-1.5 text-xs w-52 focus:outline-none focus:ring-1 focus:ring-[#E8C9B5]"
                    />
                </div>
            </div>

            <!-- Pre-train result card -->
            <div v-if="pretrainResult" class="mb-4 border border-[#E8C9B5] bg-[#FBF6F2] rounded-lg p-4">
                <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                        <div class="text-sm font-medium text-[#8B4427] flex items-center gap-1.5">
                            <Icon name="heroicons:check-badge" class="w-4 h-4" />
                            Trained on {{ formatCount(pretrainResult.row_count) }} rows · {{ pretrainResult.columns_written }} columns
                        </div>
                        <div v-if="pretrainResult.knowledge?.enabled" class="text-[11px] text-gray-500 mt-0.5">
                            Knowledge: {{ pretrainResult.knowledge.proposed }} suggested<template v-if="pretrainResult.knowledge.approved"> · {{ pretrainResult.knowledge.approved }} auto-approved</template><template v-else-if="pretrainResult.knowledge.proposed"> · pending review</template>
                        </div>
                        <div v-if="pretrainResult.dimensions?.length" class="mt-2 flex flex-wrap gap-1.5">
                            <span
                                v-for="d in pretrainResult.dimensions"
                                :key="d.name"
                                class="text-[10px] px-2 py-0.5 rounded-full border border-[#E8C9B5] bg-white text-[#A8542F]"
                                :title="(d.values || []).join(', ')"
                            >{{ d.name }}: {{ (d.values || []).slice(0, 3).join(', ') }}<template v-if="(d.distinct || 0) > 3"> +{{ d.distinct - 3 }}</template></span>
                        </div>
                    </div>
                    <button @click="pretrainResult = null" class="text-gray-400 hover:text-gray-600 shrink-0">
                        <Icon name="heroicons:x-mark" class="w-4 h-4" />
                    </button>
                </div>
            </div>

            <!-- Loading -->
            <div v-if="loading" class="text-xs text-gray-400 flex items-center gap-1.5 py-4">
                <Spinner class="w-3.5 h-3.5" />
                {{ $t('queries.loading') }}
            </div>

            <!-- Empty state -->
            <div v-else-if="filteredItems.length === 0" class="flex flex-col items-center justify-center py-16">
                <div class="w-14 h-14 rounded-full bg-gray-50 flex items-center justify-center mb-3">
                    <Icon
                        :name="filterType === 'suggested' ? 'heroicons:light-bulb' : 'heroicons:cube'"
                        class="w-7 h-7 text-gray-300"
                    />
                </div>
                <p class="text-sm text-gray-500">
                    {{ filterType === 'suggested' ? $t('queries.noDrafts') : $t('queries.noPublished') }}
                </p>
            </div>

            <!-- List -->
            <div v-else class="space-y-2">
                <div
                    v-for="item in filteredItems"
                    :key="item.id"
                    class="border border-gray-100 bg-white rounded-lg p-4 hover:shadow-sm hover:border-gray-200 transition-all cursor-pointer"
                    @click="navigateToEntity(item.id)"
                >
                    <div class="flex items-start gap-3">
                        <div class="min-w-0 flex-1">
                            <div class="flex items-center gap-2 mb-1">
                                <span
                                    class="text-[10px] px-1.5 py-0.5 rounded border"
                                    :class="item.type === 'metric' ? 'text-emerald-700 border-emerald-200 bg-emerald-50' : 'text-[#A8542F] border-[#E8C9B5] bg-[#F6EFEA]'"
                                >{{ (item.type || '').toUpperCase() }}</span>
                                <Icon v-if="getEntityType(item) === 'global'" name="heroicons:check-badge" class="w-4 h-4 text-green-600" title="Approved" />
                                <span v-if="getEntityType(item) === 'archived'" class="text-[10px] px-1.5 py-0.5 rounded border text-red-700 border-red-200 bg-red-50">{{ $t('queries.archivedBadge') }}</span>
                                <span v-else-if="getEntityType(item) === 'draft'" class="text-[10px] px-1.5 py-0.5 rounded border text-gray-700 border-gray-200 bg-gray-50">{{ $t('queries.draftBadge') }}</span>
                                <span v-else-if="getEntityType(item) === 'private'" class="text-[10px] px-1.5 py-0.5 rounded border text-gray-700 border-gray-200 bg-gray-50">{{ $t('queries.draftBadge') }}</span>
                                <span v-else-if="getEntityType(item) === 'suggested'" class="text-[10px] px-1.5 py-0.5 rounded border text-amber-700 border-amber-200 bg-amber-50">{{ $t('queries.suggestedBadge') }}</span>
                                <span class="text-[11px] text-gray-400">{{ timeAgo(item.updated_at) }}</span>
                            </div>
                            <div class="text-sm font-medium text-gray-900 mb-0.5">{{ item.title || item.slug }}</div>
                            <div class="text-xs text-gray-500 line-clamp-2">{{ item.description || $t('queries.noDescription') }}</div>

                            <div class="flex items-center gap-3 mt-2">
                                <div v-if="item.data?.info?.total_rows !== undefined || item.data?.info?.total_columns !== undefined" class="flex items-center gap-3 text-[11px] text-gray-400">
                                    <span v-if="item.data?.info?.total_rows !== undefined" class="flex items-center gap-1">
                                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" /></svg>
                                        {{ formatCount(item.data.info.total_rows) }}
                                    </span>
                                    <span v-if="item.data?.info?.total_columns !== undefined" class="flex items-center gap-1">
                                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 4v16M15 4v16" /></svg>
                                        {{ formatCount(item.data.info.total_columns) }}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Summary -->
            <div v-if="!loading && filteredItems.length > 0" class="mt-4 text-center text-[11px] text-gray-400">
                {{ summaryLabel }}
            </div>
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

const summaryLabel = computed(() => {
    const count = filteredItems.value.length
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
