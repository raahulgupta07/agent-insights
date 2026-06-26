<template>
    <div class="flex justify-center ps-2 md:ps-4 text-sm bg-[#F6F1EA] min-h-full">
        <div class="w-full max-w-7xl px-4 ps-0 py-2">
            <div>
                <h1
                    class="text-[32px] font-medium text-[#211B14] tracking-tight flex items-center"
                    style="font-family: 'Spectral', ui-serif, Georgia, serif"
                >
                    <GoBackChevron v-if="isExcel" />
                    {{ $t('dashboards.title') }}
                </h1>
                <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">{{ $t('dashboards.subtitle') }}</p>
            </div>

            <div class="mt-6">
                <!-- Main tabs (My / Shared) — directly under header, ABOVE search (canonical) -->
                <div class="border-b border-[#E9E0D3] mb-4">
                    <nav class="-mb-px flex space-x-6">
                        <button
                            class="whitespace-nowrap border-b-2 py-2 px-1 text-sm flex items-center font-medium"
                            :class="activeFilter === 'my'
                                ? 'border-[#C2541E] text-[#1f2328]'
                                : 'border-transparent text-[#6b6b6b] hover:border-[#E9E0D3] hover:text-[#1f2328]'"
                            @click="setActiveFilter('my')"
                        >
                            <span>{{ $t('dashboards.myDashboards') }}</span>
                        </button>
                        <button
                            class="whitespace-nowrap border-b-2 py-2 px-1 text-sm flex items-center font-medium"
                            :class="activeFilter === 'shared'
                                ? 'border-[#C2541E] text-[#1f2328]'
                                : 'border-transparent text-[#6b6b6b] hover:border-[#E9E0D3] hover:text-[#1f2328]'"
                            @click="setActiveFilter('shared')"
                        >
                            <span>{{ $t('dashboards.sharedWithMe') }}</span>
                        </button>
                    </nav>
                </div>

                <!-- Search -->
                <div class="flex flex-col md:flex-row md:items-center gap-3 mb-3">
                    <div class="flex-1 w-full">
                        <div class="relative">
                            <input
                                v-model="searchTerm"
                                type="text"
                                :placeholder="$t('dashboards.searchPlaceholder')"
                                class="w-full ps-10 pe-4 py-2.5 bg-white border border-[#E9E0D3] rounded-xl text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none focus:ring-2 focus:ring-[#C2541E]/30 focus:border-[#C2541E]"
                            />
                            <UIcon
                                name="i-heroicons-magnifying-glass"
                                class="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#9a958c]"
                            />
                        </div>
                    </div>
                </div>

                <!-- Loading state -->
                <div v-if="isLoading" class="mt-4">
                    <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
                        <div
                            v-for="i in 10"
                            :key="i"
                            class="bg-white border border-[#E9E0D3] rounded-2xl overflow-hidden"
                        >
                            <div class="aspect-[4/3] ca-sk !rounded-none"></div>
                            <div class="p-3 space-y-2">
                                <div class="h-4 ca-sk w-3/4"></div>
                                <div class="h-3 ca-sk w-1/2"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Cards grid -->
                <div v-else-if="reports.length > 0">
                    <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6 ca-stagger">
                        <RecentReportCard
                            v-for="report in reports"
                            :key="report.id"
                            :report="report"
                            :view-mode="activeFilter === 'shared' ? 'org' : 'my'"
                            :is-owner="report.user?.id === (currentUser as any)?.id"
                        />
                    </div>

                    <!-- Pagination -->
                    <div
                        v-if="pagination.total_pages > 1"
                        class="mt-6 flex flex-col md:flex-row gap-3 md:items-center justify-between"
                    >
                        <div class="text-xs text-[#9a958c]">
                            {{ $t('dashboards.showingRange', {
                                start: ((currentPage - 1) * pagination.limit) + 1,
                                end: Math.min(currentPage * pagination.limit, pagination.total),
                                total: pagination.total,
                            }) }}
                        </div>
                        <div class="flex items-center gap-2">
                            <button
                                @click="changePage(currentPage - 1)"
                                :disabled="currentPage === 1"
                                :class="[
                                    'px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors',
                                    currentPage === 1
                                        ? 'bg-[#F4EEE5] text-[#9a958c] cursor-not-allowed border-[#E9E0D3]'
                                        : 'bg-white text-[#1f2328] hover:bg-[#F4EEE5] border-[#E9E0D3]'
                                ]"
                            >
                                <Icon name="heroicons:chevron-left" class="w-4 h-4" />
                            </button>
                            <button
                                v-for="page in visiblePages"
                                :key="page"
                                @click="changePage(page)"
                                :class="[
                                    'px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors min-w-[36px]',
                                    page === currentPage
                                        ? 'bg-[#C2541E] text-white border-[#C2541E]'
                                        : 'bg-white text-[#1f2328] hover:bg-[#F4EEE5] border-[#E9E0D3]'
                                ]"
                            >
                                {{ page }}
                            </button>
                            <button
                                @click="changePage(currentPage + 1)"
                                :disabled="currentPage === pagination.total_pages"
                                :class="[
                                    'px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors',
                                    currentPage === pagination.total_pages
                                        ? 'bg-[#F4EEE5] text-[#9a958c] cursor-not-allowed border-[#E9E0D3]'
                                        : 'bg-white text-[#1f2328] hover:bg-[#F4EEE5] border-[#E9E0D3]'
                                ]"
                            >
                                <Icon name="heroicons:chevron-right" class="w-4 h-4" />
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Empty state -->
                <div v-else class="mt-12 flex flex-col items-center text-center">
                    <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3]">
                        <Icon
                            name="heroicons:chart-bar-square"
                            class="h-6 w-6 text-[#C2541E]"
                        />
                    </div>
                    <h3
                        class="mt-3 text-base font-semibold text-[#1f2328]"
                        style="font-family: 'Spectral', ui-serif, Georgia, serif"
                    >
                        {{ $t('dashboards.empty') }}
                    </h3>
                    <p class="mt-1 text-sm text-[#6b6b6b]">
                        {{ $t('dashboards.emptyDescription') }}
                    </p>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import GoBackChevron from '@/components/excel/GoBackChevron.vue'
import RecentReportCard from '~/components/home/RecentReportCard.vue'

const { data: currentUser } = useAuth()
const { t } = useI18n()
const toast = useToast()

definePageMeta({ auth: true })

const reports = ref<any[]>([])
const activeFilter = ref<'my' | 'shared'>('my')
const currentPage = ref(1)
const isLoading = ref(true)
const pagination = ref({
    total: 0,
    page: 1,
    limit: 15,
    total_pages: 0,
    has_next: false,
    has_prev: false,
})
const searchTerm = ref('')
const { isExcel } = useExcel()

const visiblePages = computed(() => {
    const total = pagination.value.total_pages
    const current = currentPage.value
    const siblingCount = 1

    if (total <= 5) {
        return Array.from({ length: total }, (_, i) => i + 1)
    }

    const leftSibling = Math.max(current - siblingCount, 1)
    const rightSibling = Math.min(current + siblingCount, total)

    const shouldShowLeftDots = leftSibling > 2
    const shouldShowRightDots = rightSibling < total - 1

    if (!shouldShowLeftDots && shouldShowRightDots) {
        return Array.from({ length: 5 }, (_, i) => i + 1)
    }

    if (shouldShowLeftDots && !shouldShowRightDots) {
        return Array.from({ length: 5 }, (_, i) => total - 4 + i)
    }

    if (shouldShowLeftDots && shouldShowRightDots) {
        return Array.from({ length: rightSibling - leftSibling + 1 }, (_, i) => leftSibling + i)
    }

    return Array.from({ length: total }, (_, i) => i + 1)
})

const changePage = async (page: number) => {
    if (page === currentPage.value || page < 1 || page > pagination.value.total_pages) {
        return
    }
    currentPage.value = page
    await fetchDashboards(page, activeFilter.value, searchTerm.value)
}

const setActiveFilter = async (filter: 'my' | 'shared') => {
    if (activeFilter.value === filter) return
    activeFilter.value = filter
    currentPage.value = 1
    await fetchDashboards(1, filter, searchTerm.value)
}

const fetchDashboards = async (page: number = 1, filter: 'my' | 'shared' = 'my', search: string = '') => {
    isLoading.value = true
    try {
        const response = await useMyFetch('/reports', {
            method: 'GET',
            query: {
                page,
                limit: pagination.value.limit,
                filter,
                search: search?.trim() || undefined,
                has_artifacts: 'yes',
            },
        })

        if (response.status.value === 'success' && response.data.value) {
            reports.value = response.data.value.reports
            pagination.value = response.data.value.meta
        } else {
            throw new Error('Could not fetch dashboards')
        }
    } catch (error) {
        console.error('Error fetching dashboards:', error)
        toast.add({
            title: t('common.error'),
            description: t('dashboards.fetchFailed'),
            color: 'red',
        })
    } finally {
        isLoading.value = false
    }
}

let _searchTimer: any = null
watch(searchTerm, () => {
    if (_searchTimer) clearTimeout(_searchTimer)
    _searchTimer = setTimeout(() => {
        currentPage.value = 1
        fetchDashboards(1, activeFilter.value, searchTerm.value)
    }, 300)
})

onMounted(async () => {
    await nextTick()
    await fetchDashboards(1, 'my', '')
})
</script>
