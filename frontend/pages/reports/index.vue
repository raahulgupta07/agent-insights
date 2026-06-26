<template>
    <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
        <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto text-[#1f2328]">

            <!-- header: title + subtitle left, readiness ring right -->
            <div class="flex items-start justify-between gap-4 mb-1">
                <div class="flex items-start gap-2">
                    <GoBackChevron v-if="isExcel" />
                    <div>
                        <h2
                            class="text-lg font-semibold text-[#1f2328]"
                            style="font-family: 'Spectral', ui-serif, Georgia, serif"
                        >
                            {{ $t('reports.title') }}
                        </h2>
                        <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[480px]">{{ $t('reports.subtitle') }}</p>
                    </div>
                </div>
                <div class="shrink-0 text-center">
                    <div class="relative w-[54px] h-[54px] mx-auto">
                        <svg width="54" height="54" style="transform:rotate(-90deg)">
                            <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
                            <circle cx="27" cy="27" r="22" stroke="#2F6F4F" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" stroke-dashoffset="20" />
                        </svg>
                        <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#2F6F4F]" style="font-family: ui-serif, Georgia, serif">{{ pagination.total }}</div>
                    </div>
                    <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">reports</div>
                </div>
            </div>

            <!-- Toolbar: search + segmented filter + New report -->
            <div class="flex flex-col md:flex-row md:items-center gap-2 mt-4 mb-4">
                <div class="relative flex-1 w-full md:max-w-[420px]">
                    <input
                        v-model="searchTerm"
                        type="text"
                        :placeholder="$t('reports.searchPlaceholder')"
                        class="w-full ps-9 pe-4 py-2 bg-white text-[#1f2328] border border-[#E9E0D3] rounded-lg text-[13px] focus:outline-none focus:ring-2 focus:ring-[#C2541E]/40 focus:border-[#C2541E]"
                    />
                    <UIcon
                        name="i-heroicons-magnifying-glass"
                        class="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#9a958c]"
                    />
                </div>

                <!-- Segmented scope filter -->
                <div class="inline-flex items-center bg-[#F1ECE3] rounded-lg p-0.5 shrink-0 text-[12px]">
                    <button
                        v-for="opt in scopeOptions"
                        :key="opt.value"
                        type="button"
                        class="px-3 py-1.5 rounded-md transition-colors whitespace-nowrap"
                        :class="activeFilter === opt.value
                            ? 'bg-[#2F6F4F] text-white font-semibold'
                            : 'text-[#6b6b6b] hover:text-[#1f2328]'"
                        @click="setActiveFilter(opt.value)"
                    >
                        {{ opt.label }}
                    </button>
                </div>

                <!-- New report -->
                <button
                    type="button"
                    :disabled="creatingReport"
                    class="md:ms-auto inline-flex items-center gap-1.5 px-3 py-2 text-[13px] font-semibold rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors shrink-0 disabled:opacity-60"
                    @click="createNewReport"
                >
                    <UIcon name="i-heroicons-plus" class="w-4 h-4" />
                    {{ $t('reports.newReport') }}
                </button>
            </div>

            <!-- Loading state -->
            <div v-if="isLoading" class="py-20 flex items-center justify-center text-[#6b6b6b]">
                <Spinner class="w-4 h-4 me-2" />
                <span class="text-sm">{{ $t('common.loading') }}</span>
            </div>

            <template v-else>
                <!-- White section card with band pill -->
                <div class="relative border border-[#E9E0D3] rounded-2xl bg-white p-4">
                    <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">YOUR REPORTS · NEWEST FIRST</span>

                    <!-- Empty state -->
                    <div
                        v-if="visibleReports.length === 0"
                        class="mt-1 py-12 text-center border border-dashed border-[#d8cfc0] bg-gradient-to-b from-white to-[#fdfcf9] rounded-xl"
                    >
                        <span class="inline-flex w-12 h-12 mx-auto mb-3 items-center justify-center rounded-xl bg-[#E7F1EB] text-[#2F6F4F]">
                            <UIcon name="i-heroicons-document-text" class="h-6 w-6" />
                        </span>
                        <h3 class="text-[13px] font-semibold text-[#1f2328]">{{ $t('reports.empty') }}</h3>
                        <p class="mt-1 text-[11px] text-[#9a958c]">{{ $t('reports.emptyHint') }}</p>
                    </div>

                    <!-- Card grid -->
                    <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mt-1">
                        <div
                            v-for="report in visibleReports"
                            :key="report.id"
                            class="group flex flex-col border border-[#E9E0D3] rounded-xl bg-gradient-to-b from-white to-[#fdfcf9] p-3 hover:border-[#2F6F4F]/40 transition-colors"
                        >
                            <!-- Title row: icon chip + title + live/draft badge -->
                            <div class="flex items-center gap-1.5">
                                <span class="w-7 h-7 rounded-lg bg-[#E7F1EB] flex items-center justify-center text-[#2F6F4F] shrink-0">
                                    <UIcon :name="reportTypeIcon(report)" class="w-4 h-4" />
                                </span>
                                <span
                                    class="text-[13px] font-semibold text-[#1f2328] truncate cursor-pointer hover:text-[#2F6F4F]"
                                    @click="goToReport(report)"
                                >
                                    {{ report.title }}
                                </span>
                                <span
                                    class="ms-auto shrink-0 inline-flex items-center text-[9px] font-semibold rounded-full px-1.5 py-0.5"
                                    :class="isReportLive(report)
                                        ? 'text-[#2F6F4F] bg-[#E7F1EB]'
                                        : 'text-[#7a756c] bg-[#F4EEE5]'"
                                >
                                    {{ isReportLive(report) ? $t('reports.statusLive') : $t('reports.statusDraft') }}
                                </span>
                            </div>

                            <!-- Meta row: owner + relative time + star/archive -->
                            <div class="flex items-center gap-1.5 mt-2">
                                <span class="text-[10.5px] text-[#9a958c] truncate">
                                    {{ ownerLabel(report) }}<template v-if="report.created_at"> · {{ relTime(report.created_at) }}</template>
                                </span>
                                <UTooltip
                                    :text="report.is_starred ? $t('reports.tooltips.unstar') : $t('reports.tooltips.star')"
                                    class="ms-auto"
                                >
                                    <button
                                        @click.stop="toggleStar(report)"
                                        class="inline-flex items-center justify-center w-6 h-6 rounded-md hover:bg-[#faf8f3] focus:outline-none"
                                    >
                                        <UIcon
                                            :name="report.is_starred ? 'i-heroicons-star-solid' : 'i-heroicons-star'"
                                            class="h-4 w-4 transition-colors"
                                            :class="report.is_starred ? 'text-yellow-400 hover:text-yellow-500' : 'text-gray-300 hover:text-yellow-400'"
                                        />
                                    </button>
                                </UTooltip>
                                <UTooltip
                                    v-if="canDeleteReport(report)"
                                    :text="$t('reports.archive')"
                                >
                                    <button
                                        @click.stop="confirmDelete(report.id)"
                                        class="inline-flex items-center justify-center w-6 h-6 rounded-md text-[#9a958c] hover:text-red-600 hover:bg-[#faf8f3] opacity-0 group-hover:opacity-100 transition-all focus:outline-none"
                                    >
                                        <UIcon name="i-heroicons-archive-box" class="w-4 h-4" />
                                    </button>
                                </UTooltip>
                            </div>

                            <!-- Actions -->
                            <div class="grid grid-cols-2 gap-2 mt-3">
                                <button
                                    type="button"
                                    class="box-border whitespace-nowrap inline-flex items-center justify-center py-1.5 text-[12px] font-medium rounded-lg border border-[#E9E0D3] bg-white text-[#1f2328] hover:bg-[#faf8f3] transition-colors"
                                    @click.stop="goToReport(report)"
                                >
                                    {{ $t('reports.openButton') }}
                                </button>
                                <button
                                    type="button"
                                    class="box-border whitespace-nowrap inline-flex items-center justify-center py-1.5 text-[12px] font-semibold rounded-lg bg-[#2F6F4F] text-white hover:bg-[#27593f] transition-colors"
                                    @click.stop="goToReportChat(report)"
                                >
                                    {{ $t('reports.openInChatButton') }}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Pagination -->
                <div
                    v-if="visibleReports.length"
                    class="mt-4 pt-4 border-t border-[#E9E0D3] flex items-center justify-between gap-3"
                >
                    <div class="flex items-center gap-2 text-xs text-[#6b6b6b]">
                        <span>{{ $t('reports.pagination.rowsPerPage') }}</span>
                        <USelectMenu
                            :model-value="pagination.limit"
                            @update:model-value="setRowsPerPage"
                            :options="rowsPerPageOptions"
                            class="w-20"
                        />
                    </div>

                    <div class="text-xs text-[#6b6b6b]">
                        {{ $t('reports.pagination.page', { page: currentPage }) }}
                    </div>

                    <div class="flex items-center gap-2">
                        <button
                            @click="changePage(currentPage - 1)"
                            :disabled="currentPage === 1"
                            class="p-1.5 rounded-lg border transition-colors"
                            :class="currentPage === 1
                                ? 'border-[#E9E0D3] text-[#cbc7be] cursor-not-allowed'
                                : 'border-[#E9E0D3] text-[#6b6b6b] hover:bg-[#faf8f3]'"
                        >
                            <Icon name="heroicons:chevron-left" class="w-4 h-4" />
                        </button>
                        <button
                            @click="changePage(currentPage + 1)"
                            :disabled="currentPage >= pagination.total_pages"
                            class="p-1.5 rounded-lg border transition-colors"
                            :class="currentPage >= pagination.total_pages
                                ? 'border-[#E9E0D3] text-[#cbc7be] cursor-not-allowed'
                                : 'border-[#E9E0D3] text-[#6b6b6b] hover:bg-[#faf8f3]'"
                        >
                            <Icon name="heroicons:chevron-right" class="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </template>
        </div>
    </div>
</template>

<script setup lang="ts">
import GoBackChevron from '@/components/excel/GoBackChevron.vue'
import Spinner from '@/components/Spinner.vue'
const creatingReport = ref(false)

const { t } = useI18n()
const { data: currentUser } = useAuth()
const toast = useToast()
const router = useRouter()
const { selectedAgentObjects } = useAgent()

definePageMeta({ auth: true })

const reports = ref<any[]>([])
const activeFilter = ref<'my' | 'shared' | 'published' | 'all'>('my')
const currentPage = ref(1)
const isLoading = ref(true)
const pagination = ref({
    total: 0,
    page: 1,
    limit: 10,
    total_pages: 0,
    has_next: false,
    has_prev: false,
})
const searchTerm = ref('')
const selectedIds = ref<Set<string>>(new Set())
const statusFilter = ref<'all' | 'draft' | 'published'>('all')
const scheduledFilter = ref<boolean | null>(null)
const typeFilter = ref<string>('all')
const dataSourceFilter = ref<string>('all')
const artifactFilter = ref<string>('all')
const dataSources = ref<any[]>([])
const showFilters = ref(false)
const filtersRef = ref<HTMLElement | null>(null)
const rowsPerPageOptions = [10, 25, 50]
const { isExcel } = useExcel()

const visibilityIcon = (v: string) => {
    switch (v) {
        case 'public': return 'heroicons:globe-alt'
        case 'internal': return 'heroicons:building-office'
        case 'shared': return 'heroicons:user-group'
        default: return 'heroicons:lock-closed'
    }
}

const visibilityLabel = (v: string) => {
    switch (v) {
        case 'public': return t('reports.visibility.public')
        case 'internal': return t('reports.visibility.internal')
        case 'shared': return t('reports.visibility.shared')
        default: return t('reports.visibility.private')
    }
}

const reportTypeIcon = (report: any) => {
    if (report.artifact_modes?.includes('page')) return 'heroicons:chart-bar-square'
    if (report.artifact_modes?.includes('slides')) return 'heroicons:presentation-chart-bar'
    return 'heroicons:chat-bubble-left-right'
}

const reportTypeLabel = (report: any) => {
    if (report.artifact_modes?.includes('page')) return t('reports.type.dashboard')
    if (report.artifact_modes?.includes('slides')) return t('reports.type.slides')
    if (report.mode === 'deep') return t('reports.type.deep')
    return t('reports.type.chat')
}

// Resolve where a report row/title should link to.
// "Shared with me" reports belong to another user, so the owner's full
// /reports/:id editing page isn't accessible — open the read-only shared
// conversation view at /c/:token instead. If sharing produced no token
// there's nowhere to link, so return null and skip navigation.
const reportLink = (report: any): string | null => {
    if (activeFilter.value === 'shared') {
        return report.conversation_share_token
            ? `/c/${report.conversation_share_token}`
            : null
    }
    return `/reports/${report.id}`
}

const goToReport = (report: any) => {
    const link = reportLink(report)
    if (link) router.push(link)
}

// "Open in chat" — the report IS the conversation; shared reports open the
// read-only shared view, owned reports open the editing page. Same target as
// the row click, kept as a distinct handler so the two CTAs can diverge later.
const goToReportChat = (report: any) => {
    goToReport(report)
}

// Segmented scope tabs reuse the page's EXISTING filter values.
const scopeOptions = computed(() => [
    { value: 'my' as const, label: t('reports.myReports') },
    { value: 'shared' as const, label: t('reports.sharedWithMe') },
    { value: 'all' as const, label: t('reports.scopeAll') },
])

const ownerLabel = (report: any): string => {
    const u = report?.user
    return u?.name || u?.email || ''
}

// "live" = the report is shared/visible in any way; otherwise "draft" (private).
const isReportLive = (report: any): boolean => {
    return (
        report?.status === 'published' ||
        (report?.conversation_visibility && report.conversation_visibility !== 'none') ||
        (report?.artifact_visibility && report.artifact_visibility !== 'none')
    )
}

function relTime(ts?: string) {
    if (!ts) return ''
    const d = new Date(ts).getTime()
    if (isNaN(d)) return ''
    const s = Math.floor((Date.now() - d) / 1000)
    if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`
    if (s < 604800) return `${Math.floor(s / 86400)}d ago`
    return `${Math.floor(s / 604800)}w ago`
}

const formatDate = (iso: string) => {
    if (!iso) return ''
    const d = new Date(iso)
    if (isNaN(d.getTime())) return iso
    const datePart = new Intl.DateTimeFormat('en-US', {
        month: 'short', day: 'numeric', year: 'numeric',
    }).format(d)
    const timePart = new Intl.DateTimeFormat('en-US', {
        hour: 'numeric', minute: '2-digit', hour12: true,
    }).format(d)
    return `${datePart} • ${timePart}`
}

const statusFilterOptions = computed(() => [
    { value: 'all', label: t('reports.filters.allStatus') },
    { value: 'draft', label: t('reports.filters.private') },
    { value: 'published', label: t('reports.filters.shared') },
])

const scheduleFilterOptions = computed(() => [
    { value: null, label: t('reports.filters.allSchedules') },
    { value: true, label: t('reports.filters.scheduled') },
    { value: false, label: t('reports.filters.notScheduled') },
])

const typeFilterOptions = computed(() => [
    { value: 'all', label: t('reports.filters.allModes') },
    { value: 'chat', label: t('reports.filters.chat') },
    { value: 'deep', label: t('reports.filters.deep') },
    { value: 'training', label: t('reports.filters.training') },
])

const artifactFilterOptions = computed(() => [
    { value: 'all', label: t('reports.filters.allDashboards') },
    { value: 'yes', label: t('reports.filters.withDashboard') },
    { value: 'no', label: t('reports.filters.noDashboard') },
])

const dataSourceFilterOptions = computed(() => {
    const options: { value: string; label: string }[] = [{ value: 'all', label: t('reports.filters.allSources') }]
    for (const ds of dataSources.value) {
        options.push({ value: ds.id, label: ds.name })
    }
    return options
})

const selectedStatusLabel = computed(() => {
    const option = statusFilterOptions.value.find(o => o.value === statusFilter.value)
    return option?.label || t('reports.filters.status')
})

const selectedScheduleLabel = computed(() => {
    const option = scheduleFilterOptions.value.find(o => o.value === scheduledFilter.value)
    return option?.label || t('reports.filters.schedule')
})

const selectedTypeLabel = computed(() => {
    const option = typeFilterOptions.value.find(o => o.value === typeFilter.value)
    return option?.label || t('reports.filters.type')
})

const selectedDataSourceLabel = computed(() => {
    const option = dataSourceFilterOptions.value.find(o => o.value === dataSourceFilter.value)
    return option?.label || t('reports.filters.dataSource')
})

const selectedArtifactLabel = computed(() => {
    const option = artifactFilterOptions.value.find(o => o.value === artifactFilter.value)
    return option?.label || t('reports.filters.artifacts')
})

const activeFilterCount = computed(() => {
    let count = 0
    if (statusFilter.value !== 'all') count++
    if (scheduledFilter.value !== null) count++
    if (typeFilter.value !== 'all') count++
    if (dataSourceFilter.value !== 'all') count++
    if (artifactFilter.value !== 'all') count++
    return count
})

const visibleReports = computed(() => reports.value)

const allVisibleSelected = computed(() => {
    return visibleReports.value.length > 0 && visibleReports.value.every(r => selectedIds.value.has(r.id))
})

const canDeleteReport = (report: any) => {
    return currentUser.value && (report.user.id === currentUser.value.id || report.user.email === currentUser.value.email)
}

const changePage = async (page: number) => {
    if (page === currentPage.value || page < 1 || page > pagination.value.total_pages) {
        return
    }
    currentPage.value = page
    await fetchReports(page, activeFilter.value, searchTerm.value, scheduledFilter.value, statusFilter.value)
}

const setRowsPerPage = async (limit: number) => {
    if (pagination.value.limit === limit) return
    pagination.value.limit = limit
    currentPage.value = 1
    await refreshReports()
}

const setActiveFilter = async (filter: 'my' | 'shared' | 'published' | 'all') => {
    if (activeFilter.value === filter) return
    activeFilter.value = filter
    statusFilter.value = 'all'
    currentPage.value = 1
    scheduledFilter.value = null
    typeFilter.value = 'all'
    dataSourceFilter.value = 'all'
    artifactFilter.value = 'all'
    showFilters.value = false
    await fetchReports(1, filter, searchTerm.value, null, 'all')
}

const setStatusFilter = async (status: 'all' | 'draft' | 'published') => {
    if (statusFilter.value === status) return
    statusFilter.value = status
    currentPage.value = 1
    await fetchReports(1, activeFilter.value, searchTerm.value, scheduledFilter.value, status)
}

const setScheduledFilter = async (scheduled: boolean | null) => {
    if (scheduledFilter.value === scheduled) return
    scheduledFilter.value = scheduled
    currentPage.value = 1
    await refreshReports()
}

const setTypeFilter = async (type: string) => {
    if (typeFilter.value === type) return
    typeFilter.value = type
    currentPage.value = 1
    await refreshReports()
}

const setDataSourceFilter = async (dsId: string) => {
    if (dataSourceFilter.value === dsId) return
    dataSourceFilter.value = dsId
    currentPage.value = 1
    await refreshReports()
}

const setArtifactFilter = async (value: string) => {
    if (artifactFilter.value === value) return
    artifactFilter.value = value
    currentPage.value = 1
    await refreshReports()
}

const clearFilters = async () => {
    statusFilter.value = 'all'
    scheduledFilter.value = null
    typeFilter.value = 'all'
    dataSourceFilter.value = 'all'
    artifactFilter.value = 'all'
    currentPage.value = 1
    await refreshReports()
}

const refreshReports = () => {
    return fetchReports(1, activeFilter.value, searchTerm.value, scheduledFilter.value, statusFilter.value)
}

const fetchReports = async (page: number = 1, filter: 'my' | 'shared' | 'published' | 'all' = 'my', search: string = '', scheduled: boolean | null = null, status: string | null = null) => {
    isLoading.value = true
    try {
        const response = await useMyFetch('/reports', {
            method: 'GET',
            query: {
                page,
                limit: pagination.value.limit,
                filter,
                search: search?.trim() || undefined,
                scheduled: scheduled !== null ? scheduled : undefined,
                status: status && status !== 'all' ? status : undefined,
                data_source_id: dataSourceFilter.value !== 'all' ? dataSourceFilter.value : undefined,
                mode: typeFilter.value !== 'all' ? typeFilter.value : undefined,
                has_artifacts: artifactFilter.value !== 'all' ? artifactFilter.value : undefined,
            },
        })

        if (response.status.value === 'success' && response.data.value) {
            reports.value = response.data.value.reports
            pagination.value = response.data.value.meta
            selectedIds.value = new Set()
        } else {
            throw new Error('Could not fetch reports')
        }
    } catch (error) {
        console.error('Error fetching reports:', error)
        toast.add({
            title: t('common.error'),
            description: t('reports.toasts.failedFetch'),
            color: 'red',
        })
    } finally {
        isLoading.value = false
    }
}

const toggleOne = (id: string) => {
    const s = new Set(selectedIds.value)
    if (s.has(id)) s.delete(id)
    else s.add(id)
    selectedIds.value = s
}

const toggleAllVisible = () => {
    const s = new Set(selectedIds.value)
    const allSelected = visibleReports.value.length > 0 && visibleReports.value.every(r => s.has(r.id))
    if (allSelected) {
        for (const r of visibleReports.value) s.delete(r.id)
    } else {
        for (const r of visibleReports.value) s.add(r.id)
    }
    selectedIds.value = s
}

async function confirmDelete(reportId: string) {
    if (confirm(t('reports.archiveConfirm'))) {
        await deleteReport(reportId)
        await fetchReports(currentPage.value, activeFilter.value, searchTerm.value, scheduledFilter.value, statusFilter.value)
    }
}

async function toggleStar(report: any) {
    const next = !report.is_starred
    // Optimistic update
    report.is_starred = next
    try {
        const response: any = await useMyFetch(`/reports/${report.id}/star`, {
            method: next ? 'POST' : 'DELETE',
        })
        if (response?.error?.value) {
            throw response.error.value
        }
        // Server controls ordering (starred first), so refetch the page
        await fetchReports(currentPage.value, activeFilter.value, searchTerm.value, scheduledFilter.value, statusFilter.value)
    } catch (error: any) {
        // Revert on failure
        report.is_starred = !next
        console.error('Error toggling star', error)
        toast.add({
            title: t('reports.toasts.starFailed'),
            description: String(error?.data?.detail || error?.message || ''),
            color: 'red',
        })
    }
}

async function archiveSelected() {
    if (selectedIds.value.size === 0) return
    const ok = window.confirm(t('reports.archiveConfirmBulk', { count: selectedIds.value.size }))
    if (!ok) return
    try {
        const response: any = await useMyFetch('/reports/bulk/archive', {
            method: 'POST',
            body: Array.from(selectedIds.value),
        })
        if (response?.error?.value) {
            throw response.error.value
        }
        const archived = (response?.data?.value as any)?.archived ?? selectedIds.value.size
        toast.add({
            title: t('reports.toasts.archivedBulk'),
            description: t('reports.toasts.archivedBulkDesc', { count: archived }),
            color: 'green',
        })
        await fetchReports(currentPage.value, activeFilter.value, searchTerm.value, scheduledFilter.value, statusFilter.value)
    } catch (error: any) {
        console.error('Error bulk archiving reports', error)
        const message =
            error?.data?.detail ||
            error?.data?.message ||
            error?.message ||
            t('reports.toasts.archiveBulkFailed')
        toast.add({
            title: t('reports.toasts.archiveBulkFailed'),
            description: String(message),
            color: 'red',
        })
    }
}

async function deleteReport(reportId: string) {
    try {
        const response = await useMyFetch(`/reports/${reportId}`, {
            method: 'DELETE',
        })

        if (response.status.value === 'success') {
            toast.add({
                title: t('reports.toasts.archived'),
                description: t('reports.toasts.archivedDesc'),
                color: 'green',
            })
        } else {
            throw new Error('Failed to archive report')
        }
    } catch (error: any) {
        console.error('Error archiving report', error)
        const message =
            error?.data?.detail ||
            error?.data?.message ||
            error?.message ||
            t('reports.toasts.archiveFailed')
        toast.add({
            title: t('reports.toasts.archiveFailed'),
            description: String(message),
            color: 'red',
        })
    }
}

const actionsDropdownItems = computed(() => {
    return [
        [
            {
                label: t('reports.archiveSelected'),
                icon: 'i-heroicons-archive-box',
                disabled: selectedIds.value.size === 0,
                click: () => archiveSelected(),
            },
        ],
    ]
})

const createNewReport = async () => {
    if (creatingReport.value) return
    creatingReport.value = true
    try {
        const dataSourceIds = selectedAgentObjects.value.map((a: any) => a.id)

        const response: any = await useMyFetch('/reports', {
            method: 'POST',
            body: JSON.stringify({
                title: 'untitled report',
                files: [],
                data_sources: dataSourceIds,
            }),
        })

        if (response?.error?.value) {
            throw new Error('Report creation failed')
        }

        const data: any = response?.data?.value
        if (data?.id) {
            router.push({ path: `/reports/${data.id}` })
        }
    } catch (e: any) {
        console.error('Failed to create report', e)
        const message =
            e?.data?.detail ||
            e?.data?.message ||
            e?.message ||
            t('reports.toasts.createFailed')
        toast.add({
            title: t('reports.toasts.createFailed'),
            description: String(message),
            color: 'red',
        })
    } finally {
        creatingReport.value = false
    }
}

const onClickOutside = (e: MouseEvent) => {
    if (showFilters.value && filtersRef.value && !filtersRef.value.contains(e.target as Node)) {
        showFilters.value = false
    }
}

let _searchTimer: any = null
watch(searchTerm, () => {
    if (_searchTimer) clearTimeout(_searchTimer)
    _searchTimer = setTimeout(() => {
        currentPage.value = 1
        fetchReports(1, activeFilter.value, searchTerm.value, scheduledFilter.value, statusFilter.value)
    }, 300)
})

onMounted(async () => {
    await nextTick()
    document.addEventListener('click', onClickOutside)
    const [_, dsResponse] = await Promise.all([
        fetchReports(1, 'my', ''),
        useMyFetch('/data_sources', { method: 'GET' }),
    ])
    if (dsResponse?.data?.value) {
        dataSources.value = (dsResponse.data.value as any[]) || []
    }
})

onUnmounted(() => {
    document.removeEventListener('click', onClickOutside)
})
</script>
