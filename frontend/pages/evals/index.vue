<template>
    <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
        <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto text-[#1f2328]">

            <!-- Header: serif title + subtitle + readiness ring -->
            <div class="flex items-start justify-between gap-4 mb-1">
                <div>
                    <h1
                        class="text-2xl font-semibold text-[#1f2328]"
                        style="font-family: 'Spectral', ui-serif, Georgia, serif"
                    >
                        {{ $t('evals.title') }}
                    </h1>
                    <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[520px]">{{ $t('evals.subtitle') }}</p>
                </div>
                <div class="shrink-0 text-center">
                    <div class="relative w-[54px] h-[54px] mx-auto">
                        <svg width="54" height="54" style="transform:rotate(-90deg)">
                            <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
                            <circle cx="27" cy="27" r="22" stroke="#2F6F4F" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" :stroke-dashoffset="(metrics?.total_test_runs ?? 0) > 0 ? 0 : 138" style="transition:stroke-dashoffset .5s" />
                        </svg>
                        <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#2F6F4F]" style="font-family: ui-serif, Georgia, serif">{{ metrics?.total_test_runs ?? 0 }}</div>
                    </div>
                    <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">runs</div>
                </div>
            </div>

            <!-- OVERVIEW · top metrics -->
            <div class="relative mt-4 border border-[#E9E0D3] rounded-2xl bg-white p-4">
                <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">OVERVIEW</span>
                <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mt-1">
                    <div class="border border-[#E9E0D3] rounded-xl p-3 bg-gradient-to-b from-white to-[#fdfcf9]">
                        <div class="text-[11px] uppercase tracking-wide text-[#7c7368]">{{ $t('evals.totalTestCases') }}</div>
                        <div class="text-2xl font-semibold text-[#1f2328] mt-1">{{ metrics?.total_test_cases ?? 0 }}</div>
                    </div>
                    <div class="border border-[#E9E0D3] rounded-xl p-3 bg-gradient-to-b from-white to-[#fdfcf9]">
                        <div class="text-[11px] uppercase tracking-wide text-[#7c7368]">{{ $t('evals.totalTestRuns') }}</div>
                        <div class="text-2xl font-semibold text-[#1f2328] mt-1">{{ metrics?.total_test_runs ?? 0 }}</div>
                    </div>
                    <div class="border border-[#E9E0D3] rounded-xl p-3 bg-gradient-to-b from-white to-[#fdfcf9]">
                        <div class="text-[11px] uppercase tracking-wide text-[#7c7368]">{{ $t('evals.lastTestResult') }}</div>
                        <div class="mt-1.5">
                            <span v-if="metrics?.last_result_status" :class="['inline-flex items-center px-2 py-1 rounded-full text-xs font-medium', statusClass(derivedStatus(metrics?.last_result_status))]">
                                {{ localizedStatus(derivedStatus(metrics?.last_result_status)) }}
                            </span>
                            <span v-else class="text-[#9a958c] text-sm">—</span>
                        </div>
                        <div class="text-xs text-[#9a958c] mt-1" v-if="metrics?.last_result_at">
                            {{ formatDate(metrics?.last_result_at) }}
                        </div>
                    </div>
                </div>
            </div>

            <!-- Tabs (segmented pill group) -->
            <div class="mt-5 inline-flex items-center gap-1 bg-[#F4EEE5] border border-[#E9E0D3] rounded-full p-1">
                <button
                    type="button"
                    @click="activeTab = 'tests'"
                    :class="tabClass('tests')"
                >
                    {{ $t('evals.tabs.tests') }}
                </button>
                <button
                    type="button"
                    @click="activeTab = 'runs'"
                    :class="tabClass('runs')"
                >
                    {{ $t('evals.tabs.runs') }}
                </button>
            </div>

            <!-- Tests tab -->
            <div v-if="activeTab === 'tests'">
                <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4 mb-6">
                    <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">TEST CASES</span>
                    <div class="pt-1 pb-3 border-b border-[#E9E0D3]">
                            <div class="flex flex-col md:flex-row md:items-center gap-3">
                                <div class="text-sm font-medium text-[#1f2328] me-auto">{{ $t('evals.tests.title') }}</div>
                                <div class="flex items-center gap-2 w-full md:w-auto">
                                    <!-- Suite filter -->
                                    <USelectMenu
                                        v-model="suiteFilter"
                                        :options="suiteFilterOptions"
                                        option-attribute="label"
                                        value-attribute="value"
                                        size="xs"
                                        class="text-xs w-full md:w-56"
                                        :ui="{ option: { base: 'text-xs py-1.5' } }"
                                    >
                                        <template #option="{ option }">
                                            <div v-if="option.value === '__manage__'" class="flex items-center gap-1.5 text-xs text-[#6b6b6b] border-t border-[#E9E0D3] -mx-2 px-2 pt-2 -mb-0.5">
                                                <Icon name="heroicons:cog-6-tooth" class="w-3.5 h-3.5" />
                                                {{ option.label }}
                                            </div>
                                            <span v-else class="text-xs truncate">{{ option.label }}</span>
                                        </template>
                                    </USelectMenu>
                                    <!-- Search -->
                                    <div class="relative w-full md:w-56">
                                        <input
                                            v-model="searchTerm"
                                            type="text"
                                            :placeholder="$t('evals.tests.search')"
                                            class="w-full ps-10 pe-4 py-2.5 bg-white border border-[#E9E0D3] rounded-xl text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none focus:ring-2 focus:ring-[#C2541E]/40 focus:border-[#C2541E]"
                                        />
                                        <UIcon
                                            name="i-heroicons-magnifying-glass"
                                            class="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#9a958c]"
                                        />
                                    </div>
                                    <!-- Actions -->
                                    <UButton :disabled="selectedIds.size === 0" color="primary" size="xs" icon="i-heroicons-play" @click="runSelected">{{ $t('evals.tests.runSelected') }}</UButton>
                                    <UButton color="primary" size="xs" variant="soft" icon="i-heroicons-plus" @click="addNewTest">{{ $t('evals.tests.addNew') }}</UButton>
                                </div>
                            </div>
                        </div>
                        <div class="overflow-x-auto mt-3">
                            <table class="min-w-full">
                                <thead>
                                    <tr class="border-b border-[#E9E0D3]">
                                        <th class="px-4 py-3 w-10 text-center">
                                            <input type="checkbox" :checked="allVisibleSelected" @change="toggleAllVisible" />
                                        </th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.tests.colPrompt') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.tests.colRules') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.tests.colSuite') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.tests.colOptions') }}</th>
                                    </tr>
                                </thead>
                                <tbody class="text-xs">
                                    <tr v-for="c in filteredTests" :key="c.id" class="border-b border-[#F0EAE0] hover:bg-[#FBF8F2]">
                                        <td class="px-4 py-3 w-10 text-center">
                                            <div class="flex items-center justify-center">
                                                <input type="checkbox" :checked="selectedIds.has(c.id)" @change="toggleOne(c.id)" />
                                            </div>
                                        </td>
                                        <td class="px-6 py-3">
                                            <div class="flex items-center gap-2 max-w-[620px]">
                                                <span v-if="c.status === 'draft'" class="inline-flex items-center rounded-full bg-amber-100 text-amber-800 text-[10px] font-medium px-2 py-0.5 shrink-0" title="Draft — promote to active to include in default suite runs">Draft</span>
                                                <span v-else-if="c.status === 'archived'" class="inline-flex items-center rounded-full bg-[#F4EEE5] text-[#9a958c] border border-[#E9E0D3] text-[10px] font-medium px-2 py-0.5 shrink-0">Archived</span>
                                                <span v-if="c.auto_generated" class="inline-flex items-center rounded-full bg-purple-100 text-purple-800 text-[10px] font-medium px-2 py-0.5 shrink-0" title="Auto-drafted by the knowledge harness">Auto</span>
                                                <span class="block flex-1 truncate" :title="c.prompt_json?.content || ''">{{ c.prompt_json?.content || '—' }}</span>
                                            </div>
                                        </td>
                                        <td class="px-6 py-3 text-[#1f2328]">
                                            <div class="flex flex-wrap gap-1 max-w-[620px]">
                                                <span
                                                  v-for="cat in categoriesForCase(c)"
                                                  :key="cat.key"
                                                  :class="['inline-flex items-center rounded-full border text-[11px] px-2 py-0.5', badgeClassesFor(cat.key)]"
                                                  :title="cat.label"
                                                >{{ cat.label }}</span>
                                            </div>
                                        </td>
                                        <td class="px-6 py-3">{{ c.suite_name }}</td>
                                        <td class="px-6 py-3">
                                            <div class="flex items-center gap-2">
                                                <UButton v-if="c.status === 'draft'" color="green" size="xs" variant="soft" icon="i-heroicons-check-badge" @click="promoteCase(c)">Promote</UButton>
                                                <UButton color="gray" size="xs" variant="soft" icon="i-heroicons-pencil-square" @click="editCase(c)">{{ $t('evals.tests.actionEdit') }}</UButton>
                                                <UButton color="primary" size="xs" variant="soft" icon="i-heroicons-play" @click="runCase(c)">{{ $t('evals.tests.actionRunTest') }}</UButton>
                                                <UButton color="red" size="xs" variant="soft" icon="i-heroicons-trash" @click="deleteCase(c)">{{ $t('evals.tests.actionDelete') }}</UButton>
                                            </div>
                                        </td>
                                    </tr>
                                    <tr v-if="filteredTests.length === 0">
                                        <td colspan="5" class="px-6 py-10 text-center">
                                            <div class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] text-[#C2541E]">
                                                <Icon name="heroicons:beaker" class="w-6 h-6" />
                                            </div>
                                            <h3 class="text-[15px] font-semibold text-[#1f2328]">{{ $t('evals.tests.empty') }}</h3>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <div class="pt-3 mt-3 border-t border-[#E9E0D3] flex flex-col md:flex-row gap-3 md:items-center justify-between">
                            <div class="text-xs text-[#9a958c]">{{ $t('evals.pagination.showing', { page: testsPage, n: filteredTests.length }) }}</div>
                            <div class="flex items-center gap-2">
                                <USelectMenu
                                  v-model="testsLimit"
                                  :options="pageSizeOptions"
                                  option-attribute="label"
                                  value-attribute="value"
                                  size="xs"
                                  class="text-xs w-24"
                                />
                                <UButton size="xs" variant="soft" :disabled="testsPage <= 1" @click="prevTestsPage">{{ $t('evals.pagination.prev') }}</UButton>
                                <UButton size="xs" variant="soft" :disabled="!testsHasNext" @click="nextTestsPage">{{ $t('evals.pagination.next') }}</UButton>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Runs tab -->
                <div v-else>
                    <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4 mb-6">
                        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">TEST RUNS</span>
                        <div class="pt-1 pb-3 border-b border-[#E9E0D3]">
                            <div class="flex flex-col md:flex-row md:items-center gap-3">
                                <div class="text-sm font-medium text-[#1f2328] me-auto">{{ $t('evals.runs.title') }}</div>
                                <div class="flex items-center gap-2 w-full md:w-auto">
                                    <USelectMenu
                                      v-model="runSuiteFilter"
                                      :options="suiteFilterOptions"
                                      option-attribute="label"
                                      value-attribute="value"
                                      size="xs"
                                      class="text-xs w-full md:w-48"
                                      :ui="{ option: { base: 'text-xs py-1.5' } }"
                                    >
                                        <template #option="{ option }">
                                            <div v-if="option.value === '__manage__'" class="flex items-center gap-1.5 text-xs text-[#6b6b6b] border-t border-[#E9E0D3] -mx-2 px-2 pt-2 -mb-0.5">
                                                <Icon name="heroicons:cog-6-tooth" class="w-3.5 h-3.5" />
                                                {{ option.label }}
                                            </div>
                                            <span v-else class="text-xs truncate">{{ option.label }}</span>
                                        </template>
                                    </USelectMenu>
                                    <USelectMenu
                                      v-model="runCaseFilter"
                                      :options="runCaseOptions"
                                      option-attribute="label"
                                      value-attribute="value"
                                      size="xs"
                                      class="text-xs w-full md:w-56"
                                    />
                                    <div class="relative w-full md:w-56">
                                        <input
                                          v-model="runSearchTerm"
                                          type="text"
                                          :placeholder="$t('evals.filter.searchRuns')"
                                          class="w-full ps-10 pe-4 py-2.5 bg-white border border-[#E9E0D3] rounded-xl text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none focus:ring-2 focus:ring-[#C2541E]/40 focus:border-[#C2541E]"
                                        />
                                        <UIcon
                                            name="i-heroicons-magnifying-glass"
                                            class="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#9a958c]"
                                        />
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="overflow-x-auto mt-3">
                            <table class="min-w-full">
                                <thead>
                                    <tr class="border-b border-[#E9E0D3]">
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.runs.colTitle') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.runs.colStarted') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.runs.colTrigger') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.runs.colBuild') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.runs.colStatus') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.runs.colResults') }}</th>
                                        <th class="px-6 py-3 text-start text-[11px] font-medium text-[#7c7368] uppercase tracking-wide">{{ $t('evals.runs.colDuration') }}</th>
                                    </tr>
                                </thead>
                                <tbody class="text-xs">
                                    <tr v-for="r in filteredRuns" :key="r.id" class="border-b border-[#F0EAE0] hover:bg-[#FBF8F2]">
                                        <td class="px-6 py-3 text-[#1f2328]">
                                            <NuxtLink :to="`/evals/runs/${r.id}`" class="text-[#C2541E] hover:underline">
                                                {{ r.title || $t('evals.runs.fallbackTitle') }}
                                            </NuxtLink>
                                        </td>
                                        <td class="px-6 py-3">{{ formatDate(r.started_at) }}</td>
                                        <td class="px-6 py-3 capitalize">{{ r.trigger_reason || $t('evals.run.triggerManually') }}</td>
                                        <td class="px-6 py-3">
                                            <span v-if="r.build_number" class="inline-flex items-center gap-1 text-[#6b6b6b]">
                                                <Icon name="heroicons:cube" class="w-3 h-3" />
                                                #{{ r.build_number }}
                                            </span>
                                            <span v-else class="text-[#9a958c]">—</span>
                                        </td>
                                        <td class="px-6 py-3">
                                            <span class="inline-flex px-2 py-1 text-xs font-medium rounded-full" :class="runStatusClass(r)">
                                                {{ localizedStatus(derivedRunStatus(r)) || '—' }}
                                            </span>
                                        </td>
                                        <td class="px-6 py-3">
                                            <span :class="resultBadgeClassByStatus(derivedRunStatus(r))">{{ resultSummaryReal(r) }}</span>
                                        </td>
                                        <td class="px-6 py-3">{{ formatDuration(r.started_at, r.finished_at) }}</td>
                                    </tr>
                                    <tr v-if="filteredRuns.length === 0">
                                        <td colspan="7" class="px-6 py-10 text-center">
                                            <div class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] text-[#C2541E]">
                                                <Icon name="heroicons:play-circle" class="w-6 h-6" />
                                            </div>
                                            <h3 class="text-[15px] font-semibold text-[#1f2328]">{{ $t('evals.runs.empty') }}</h3>
                                        </td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <div class="pt-3 mt-3 border-t border-[#E9E0D3] flex flex-col md:flex-row gap-3 md:items-center justify-between">
                            <div class="text-xs text-[#9a958c]">{{ $t('evals.pagination.showing', { page: runsPage, n: filteredRuns.length }) }}</div>
                            <div class="flex items-center gap-2">
                                <USelectMenu
                                  v-model="runsLimit"
                                  :options="pageSizeOptions"
                                  option-attribute="label"
                                  value-attribute="value"
                                  size="xs"
                                  class="text-xs w-24"
                                />
                                <UButton size="xs" variant="soft" :disabled="runsPage <= 1" @click="prevRunsPage">{{ $t('evals.pagination.prev') }}</UButton>
                                <UButton size="xs" variant="soft" :disabled="!runsHasNext" @click="nextRunsPage">{{ $t('evals.pagination.next') }}</UButton>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        <AddTestCaseModal
            v-if="showAddCase"
            v-model="showAddCase"
            :suite-id="selectedSuiteId"
            :case-id="selectedCaseId"
            @created="onCaseCreated"
            @updated="onCaseUpdated"
        />
        <ManageSuitesModal
            v-if="showManageSuites"
            v-model="showManageSuites"
            @suite-created="onManageSuiteCreated"
            @suite-deleted="onManageSuiteDeleted"
        />
    </div>
</template>

<script setup lang="ts">
definePageMeta({
    auth: true,
    layout: 'default',
    permissions: ['manage_evals']
})

interface TestMetrics {
    total_test_cases: number
    total_test_runs: number
    last_result_status?: string | null
    last_result_at?: string | null
}

const { t } = useI18n()
const metrics = ref<TestMetrics | null>(null)
const tests = ref<TestCaseRow[]>([])
const searchTerm = ref('')
const suiteFilter = ref<string>('all')
const selectedIds = ref<Set<string>>(new Set())
const testsPage = ref<number>(1)
const testsLimit = ref<number>(20)
const testsHasNext = computed(() => filteredTests.value.length >= testsLimit.value)
const pageSizeOptions = computed(() => [
    { label: t('evals.pagination.pageSize', { n: 10 }), value: 10 },
    { label: t('evals.pagination.pageSize', { n: 20 }), value: 20 },
    { label: t('evals.pagination.pageSize', { n: 50 }), value: 50 },
])
// Server-side filtering; no client text filter needed beyond displaying returned results
const filteredTests = computed(() => tests.value)
const allVisibleSelected = computed(() => filteredTests.value.length > 0 && filteredTests.value.every(t => selectedIds.value.has(t.id)))
const suitesOrdered = ref<TestSuiteItem[]>([])
const suiteFilterOptions = computed(() => {
    const opts = [{ label: t('evals.filter.allSuites'), value: 'all' }]
    const entries = (suitesOrdered.value || []).map(s => ({ label: s.name, value: s.id }))
    return [...opts, ...entries, { label: t('evals.filter.manageSuites'), value: '__manage__' }]
})

const showAddCase = ref(false)
const selectedSuiteId = ref<string>('')
const selectedCaseId = ref<string>('')
const router = useRouter()
const activeTab = ref<'tests' | 'runs'>('tests')
// Components
import AddTestCaseModal from '~/components/monitoring/AddTestCaseModal.vue'
import ManageSuitesModal from '~/components/monitoring/ManageSuitesModal.vue'
const toast = useToast()
const showManageSuites = ref(false)

const derivedStatus = (s?: string | null) => {
    if (!s) return '—'
    // Normalize 'success' -> 'success', others pass through
    const map: Record<string, string> = {
        'pass': 'pass',
        'fail': 'fail',
        'error': 'error',
        'success': 'success',
        'stopped': 'stopped',
        'in_progress': 'in_progress',
    }
    return map[s] || s
}

const formatDate = (iso?: string | null) => {
    if (!iso) return '—'
    try {
        return new Date(iso).toLocaleString()
    } catch {
        return '—'
    }
}

const localizedStatus = (status?: string) => {
    if (!status) return ''
    const keyMap: Record<string, string> = {
        'success': 'evals.run.statusSuccess',
        'fail': 'evals.run.statusFailed',
        'error': 'evals.run.statusError',
        'in_progress': 'evals.run.statusInProgress',
        'pass': 'evals.run.rulePass',
        'stopped': 'evals.run.completionFinished',
    }
    const k = keyMap[status]
    return k ? t(k) : status
}

const statusClass = (status?: string) => {
    if (status === 'success') return 'bg-green-100 text-green-800'
    if (status === 'error') return 'bg-red-100 text-red-800'
    if (status === 'in_progress') return 'bg-[#F4EEE5] text-[#6b6b6b]'
    return 'bg-[#F4EEE5] text-[#6b6b6b]'
}

const tabClass = (tab: 'tests' | 'runs') => {
    const isActive = activeTab.value === tab
    return [
        'whitespace-nowrap px-4 py-1.5 rounded-full text-sm font-medium transition-colors',
        isActive
            ? 'bg-[#2F6F4F] text-white'
            : 'text-[#6b6b6b] hover:text-[#1f2328]'
    ]
}

// ---- Tests table state/helpers ----
interface TestSuiteItem { id: string; name: string }
interface TestCaseRow {
    id: string
    suite_id: string
    suite_name: string
    prompt_json?: { content?: string }
    expectations_json?: { rules?: any[] }
    data_source_ids_json?: string[]
    status?: string
    auto_generated?: boolean
}

const suitesById = ref<Record<string, string>>({})
interface RunItem { id: string; title?: string; started_at?: string; trigger_reason?: string; status?: string; finished_at?: string; build_id?: string; build_number?: number }
const runs = ref<RunItem[]>([])
const runResults = ref<Record<string, { total: number; passed: number; failed: number; error: number }>>({})
const runResultsCaseIds = ref<Record<string, Set<string>>>({})
const runSuiteFilter = ref<string>('all')
const runCaseFilter = ref<string>('all')
const runSearchTerm = ref<string>('')
const runsPage = ref<number>(1)
const runsLimit = ref<number>(20)
const runsHasNext = computed(() => runs.value.length >= runsLimit.value)
const runCaseOptions = computed(() => {
    const base = [{ label: t('evals.filter.allCases'), value: 'all' }]
    // If a suite is chosen, list cases for that suite; otherwise list all known tests
    const chosenSuite = runSuiteFilter.value !== 'all' ? runSuiteFilter.value : null
    const source = (tests.value || []).filter(t => (chosenSuite ? t.suite_id === chosenSuite : true))
    const seen = new Set<string>()
    const opts = source.map(t => {
        if (seen.has(t.id)) return null
        seen.add(t.id)
        const label = (t.prompt_json?.content || '').slice(0, 80) || t.id
        return { label, value: t.id }
    }).filter(Boolean) as { label: string; value: string }[]
    return [...base, ...opts]
})
const filteredRuns = computed(() => {
    const term = (runSearchTerm.value || '').toLowerCase().trim()
    const caseId = runCaseFilter.value !== 'all' ? runCaseFilter.value : null
    return (runs.value || []).filter(r => {
        if (runSuiteFilter.value !== 'all') {
            // server already filtered when loading; keep as soft guard
        }
        if (term) {
            const t = (r.title || '').toLowerCase()
            const trig = (r.trigger_reason || '').toLowerCase()
            if (!t.includes(term) && !trig.includes(term)) return false
        }
        if (caseId) {
            const set = runResultsCaseIds.value[r.id] || new Set<string>()
            if (!set.has(caseId)) return false
        }
        return true
    })
})

const CATEGORY_LABELS = computed<Record<string, string>>(() => ({
    'tool:create_data': t('evals.category.createData'),
    'tool:clarify': t('evals.category.clarify'),
    'tool:describe_table': t('evals.category.describeTable'),
    'metadata': t('evals.category.metadata'),
    'completion': t('evals.category.completion'),
    'judge': t('evals.category.judge'),
}))

function categoryName(cat: string): string {
    if (!cat) return ''
    const known = CATEGORY_LABELS.value[cat]
    if (known) return known
    if (cat.startsWith('tool:')) {
        const raw = cat.split(':')[1] || ''
        const spaced = raw.replace(/_/g, ' ')
        return spaced.replace(/\b\w/g, (m) => m.toUpperCase())
    }
    return cat
}

function categoryKeysForCase(c: TestCaseRow): string[] {
    const rules = (c as any)?.expectations_json?.rules || []
    if (!Array.isArray(rules) || rules.length === 0) return []
    const seen = new Set<string>()
    for (const r of rules) {
        if (r?.type === 'field' && r?.target?.category) {
            seen.add(String(r.target.category))
        } else if (r?.type === 'tool.calls' && r?.tool) {
            seen.add(`tool:${r.tool}`)
        }
    }
    return Array.from(seen)
}

function categoriesForCase(c: TestCaseRow): { key: string; label: string }[] {
    return categoryKeysForCase(c).map(key => ({ key, label: categoryName(key) }))
}

function badgeClassesFor(catKey: string): string {
    const map: Record<string, string> = {
        'tool:create_data': 'bg-[#F4EEE5] text-[#A8330F] border-[#E9E0D3]',
        'tool:clarify': 'bg-amber-50 text-amber-700 border-amber-100',
        'tool:describe_table': 'bg-teal-50 text-teal-700 border-teal-100',
        'metadata': 'bg-slate-50 text-slate-700 border-slate-100',
        'completion': 'bg-purple-50 text-purple-700 border-purple-100',
        'judge': 'bg-[#F4EEE5] text-[#6b6b6b] border-[#E9E0D3]',
    }
    return map[catKey] || 'bg-[#F4EEE5] text-[#6b6b6b] border-[#E9E0D3]'
}

async function loadSuites() {
    const suitesRes = await useMyFetch<TestSuiteItem[]>('/api/tests/suites?limit=100')
    const suitesList = (suitesRes.data.value || []) as TestSuiteItem[]
    suitesOrdered.value = suitesList
    suitesById.value = Object.fromEntries(suitesList.map(s => [s.id, s.name]))
}


async function loadCases() {
    const params = new URLSearchParams()
    if (suiteFilter.value !== 'all') params.set('suite_id', suiteFilter.value)
    if ((searchTerm.value || '').trim().length > 0) params.set('search', searchTerm.value.trim())
    params.set('page', String(testsPage.value))
    params.set('limit', String(testsLimit.value))
    const url = `/api/tests/cases?${params.toString()}`
    const casesRes = await useMyFetch<any[]>(url)
    const items = (casesRes.data.value || []) as any[]
    tests.value = items.map((c: any) => ({
        id: c.id,
        suite_id: c.suite_id,
        suite_name: suitesById.value[c.suite_id] || c.suite_id,
        prompt_json: c.prompt_json,
        expectations_json: c.expectations_json,
        data_source_ids_json: c.data_source_ids_json || [],
        status: c.status,
        auto_generated: !!c.auto_generated,
    }))
    // Clear selections when page changes
    selectedIds.value = new Set()
}

async function loadRuns() {
    try {
        const params = new URLSearchParams()
        if (runSuiteFilter.value !== 'all') params.set('suite_id', runSuiteFilter.value)
        params.set('page', String(runsPage.value))
        params.set('limit', String(runsLimit.value))
        const res = await useMyFetch<RunItem[]>(`/api/tests/runs?${params.toString()}`)
        runs.value = (res.data.value as any[]) || []
        // fetch results per run to compute summary
        const fetches = (runs.value || []).map(r => useMyFetch<any[]>(`/api/tests/runs/${r.id}/results`))
        const responses = await Promise.all(fetches)
        const map: Record<string, { total: number; passed: number; failed: number; error: number }> = {}
        const caseMap: Record<string, Set<string>> = {}
        for (let i = 0; i < responses.length; i++) {
            const r = runs.value[i]
            const rows = (responses[i].data.value as any[]) || []
            const summary = { total: rows.length, passed: 0, failed: 0, error: 0 }
            for (const it of rows) {
                if (it.status === 'pass') summary.passed++
                else if (it.status === 'fail') summary.failed++
                else if (it.status === 'error') summary.error++
                if (!caseMap[r.id]) caseMap[r.id] = new Set<string>()
                if (it.case_id) caseMap[r.id].add(String(it.case_id))
            }
            map[r.id] = summary
        }
        runResults.value = map
        runResultsCaseIds.value = caseMap
    } catch (e) {
        runs.value = []
        runResults.value = {}
        runResultsCaseIds.value = {}
    }
}

function toggleOne(id: string) {
    const s = new Set(selectedIds.value)
    if (s.has(id)) s.delete(id)
    else s.add(id)
    selectedIds.value = s
}

function toggleAllVisible() {
    const s = new Set(selectedIds.value)
    const allSelected = filteredTests.value.every(t => s.has(t.id))
    if (allSelected) {
        for (const t of filteredTests.value) s.delete(t.id)
    } else {
        for (const t of filteredTests.value) s.add(t.id)
    }
    selectedIds.value = s
}

function editCase(c: TestCaseRow) {
    selectedSuiteId.value = c.suite_id
    selectedCaseId.value = c.id
    showAddCase.value = true
}

function goRuns() {
    activeTab.value = 'runs'
}

function resultBadgeClassByStatus(status?: string) {
    if (status === 'success') return 'inline-flex px-2 py-1 rounded-full bg-green-100 text-green-800'
    if (status === 'in_progress') return 'inline-flex px-2 py-1 rounded-full bg-[#F4EEE5] text-[#6b6b6b]'
    if (status === 'fail') return 'inline-flex px-2 py-1 rounded-full bg-red-100 text-red-800'
    return 'inline-flex px-2 py-1 rounded-full bg-[#F4EEE5] text-[#6b6b6b]'
}

function resultSummaryReal(r: RunItem) {
    const c = runResults.value[r.id] || { total: 0, passed: 0, failed: 0, error: 0 }
    // Show compact ratio, independent of status text
    return `${c.passed}/${c.total}`
}

function derivedRunStatus(r: RunItem) {
    const c = runResults.value[r.id] || { total: 0, passed: 0, failed: 0, error: 0 }
    if (r.status === 'in_progress') return 'in_progress'
    if (c.total > 0 && c.passed === c.total) return 'success'
    if (c.total > 0 && c.passed < c.total) return 'fail'
    // fallback to backend status if no results
    return r.status || 'in_progress'
}

function runStatusClass(r: RunItem) {
    const s = derivedRunStatus(r)
    if (s === 'success') return 'bg-green-100 text-green-800'
    if (s === 'fail') return 'bg-red-100 text-red-800'
    return 'bg-[#F4EEE5] text-[#6b6b6b]'
}

async function runSelected() {
    try {
        if (selectedIds.value.size === 0) return
        const selectedCaseIds = tests.value.filter(t => selectedIds.value.has(t.id)).map(t => t.id)
        // Uses main build by default (build_id: null)
        const res: any = await useMyFetch('/api/tests/runs', {
            method: 'POST',
            body: { case_ids: selectedCaseIds, trigger_reason: 'manual' }
        })
        const first = res?.data?.value
        if (first?.id) router.push(`/evals/runs/${first.id}`)
        else activeTab.value = 'runs'
    } catch (e) {
        console.error('Failed to run selected tests', e)
    }
}

function addNewTest() {
    let suiteId = suiteFilter.value !== 'all'
        ? suiteFilter.value
        : ((suitesOrdered.value[0]?.id) || (Object.keys(suitesById.value || {})[0] || ''))
    // Fallback: derive suite from existing tests if suites list hasn't loaded yet
    if (!suiteId && tests.value.length > 0) {
        suiteId = tests.value[0].suite_id
    }
    selectedSuiteId.value = suiteId || ''
    // Ensure we are not in edit mode when adding a new test
    selectedCaseId.value = ''
    showAddCase.value = true
}

async function runCase(c: TestCaseRow) {
    try {
        const res: any = await useMyFetch('/api/tests/runs', {
            method: 'POST',
            body: { case_ids: [c.id], trigger_reason: 'manual' }
        })
        if (res?.error?.value) throw res.error.value
        const run = res?.data?.value
        if (run?.id) router.push(`/evals/runs/${run.id}`)
    } catch (e) {
        console.error('Failed to run test', e)
    }
}

async function promoteCase(c: TestCaseRow) {
    try {
        const res: any = await useMyFetch(`/api/tests/cases/${c.id}/status`, {
            method: 'PATCH',
            body: { status: 'active' },
        })
        if (res?.error?.value) throw res.error.value
        const updated = res?.data?.value
        if (updated) {
            const idx = tests.value.findIndex(t => t.id === c.id)
            if (idx >= 0) {
                const copy = [...tests.value]
                copy[idx] = { ...copy[idx], status: updated.status }
                tests.value = copy
            }
        }
        toast.add({ title: 'Promoted to active', icon: 'i-heroicons-check-circle', color: 'green' })
    } catch (e) {
        console.error('Failed to promote test case', e)
        toast.add({ title: 'Failed to promote', icon: 'i-heroicons-exclamation-circle', color: 'red' })
    }
}

async function deleteCase(c: TestCaseRow) {
    try {
        const ok = window.confirm(t('evals.tests.deleteConfirm'))
        if (!ok) return
        const res: any = await useMyFetch(`/api/tests/cases/${c.id}`, { method: 'DELETE' })
        if (res?.error?.value) throw res.error.value
        // Remove from local state
        tests.value = tests.value.filter(t => t.id !== c.id)
        const s = new Set(selectedIds.value)
        s.delete(c.id)
        selectedIds.value = s
        toast.add({ title: t('evals.tests.toastDeleted'), icon: 'i-heroicons-check-circle', color: 'green' })
    } catch (e) {
        console.error('Failed to delete test case', e)
        try {
            const err: any = (e as any) || {}
            const detail = err?.data?.detail || err?.data?.message || err?.message || t('evals.tests.toastDeleteFailed')
            toast.add({ title: t('evals.tests.toastDeleteFailed'), description: String(detail), icon: 'i-heroicons-x-circle', color: 'red' })
        } catch {}
    }
}

function onCaseCreated(c: any) {
    // Insert the new case into the list
    const insertRow = (suiteName: string) => {
        const row: TestCaseRow = {
            id: c.id,
            suite_id: c.suite_id,
            suite_name: suiteName || suitesById.value[c.suite_id] || '—',
            prompt_json: c.prompt_json,
            expectations_json: c.expectations_json,
            data_source_ids_json: c.data_source_ids_json || [],
        }
        tests.value = [...tests.value, row]
    }
    // Ensure suite map has the title; if not, fetch it once
    if (!suitesById.value[c.suite_id]) {
        useMyFetch(`/api/tests/suites/${c.suite_id}`).then((res: any) => {
            const suite = res?.data?.value
            if (suite?.id && suite?.name) {
                suitesById.value = { ...suitesById.value, [suite.id]: suite.name }
                const exists = (suitesOrdered.value || []).some(s => s.id === suite.id)
                if (!exists) suitesOrdered.value = [...suitesOrdered.value, { id: suite.id, name: suite.name }]
                insertRow(suite.name)
            } else {
                insertRow('—')
            }
        }).catch(() => insertRow('—')).finally(() => {
            toast.add({ title: t('evals.tests.toastCreated'), icon: 'i-heroicons-check-circle', color: 'green' })
        })
    } else {
        insertRow(suitesById.value[c.suite_id])
        toast.add({ title: t('evals.tests.toastCreated'), icon: 'i-heroicons-check-circle', color: 'green' })
    }
    selectedCaseId.value = ''
}

function onCaseUpdated(c: any) {
    const updatedRow: TestCaseRow = {
        id: c.id,
        suite_id: c.suite_id,
        suite_name: suitesById.value[c.suite_id] || '—',
        prompt_json: c.prompt_json,
        expectations_json: c.expectations_json,
        data_source_ids_json: c.data_source_ids_json || [],
    }
    const idx = tests.value.findIndex(t => t.id === c.id)
    if (idx >= 0) {
        const copy = [...tests.value]
        copy[idx] = updatedRow
        tests.value = copy
    } else {
        tests.value = [...tests.value, updatedRow]
    }
    selectedCaseId.value = ''
}

function onManageSuiteCreated(suite: { id: string; name: string }) {
    // Add to local lists
    const exists = (suitesOrdered.value || []).some(s => s.id === suite.id)
    if (!exists) {
        suitesOrdered.value = [...suitesOrdered.value, { id: suite.id, name: suite.name }]
        suitesById.value = { ...suitesById.value, [suite.id]: suite.name }
    }
}

function onManageSuiteDeleted(suiteId: string) {
    // Remove from local lists
    suitesOrdered.value = suitesOrdered.value.filter(s => s.id !== suiteId)
    const copy = { ...suitesById.value }
    delete copy[suiteId]
    suitesById.value = copy
    // Remove tests belonging to this suite from local view
    tests.value = tests.value.filter(t => t.suite_id !== suiteId)
    // Reset filter if it was set to the deleted suite
    if (suiteFilter.value === suiteId) {
        suiteFilter.value = 'all'
    }
}

interface TestRunRow {
    id: string
    suite_name: string
    trigger_reason: string
    status: 'in_progress' | 'success' | 'error'
    started_at?: string
    finished_at?: string
    results: { total: number; passed: number; failed: number; error: number }
}

// Mock: joined TestRun with aggregated TestResult counts
const mockRuns = ref<TestRunRow[]>([
    {
        id: 'run_1',
        suite_name: 'Revenue Checks',
        trigger_reason: 'manual',
        status: 'success',
        started_at: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
        finished_at: new Date(Date.now() - 1000 * 60 * 14).toISOString(),
        results: { total: 8, passed: 8, failed: 0, error: 0 }
    },
    {
        id: 'run_2',
        suite_name: 'Churn Risk',
        trigger_reason: 'schedule',
        status: 'error',
        started_at: new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString(),
        finished_at: new Date(Date.now() - 1000 * 60 * 60 * 5 + 1000 * 90).toISOString(),
        results: { total: 10, passed: 7, failed: 2, error: 1 }
    },
    {
        id: 'run_3',
        suite_name: 'Cost Guardrails',
        trigger_reason: 'context_change',
        status: 'in_progress',
        started_at: new Date(Date.now() - 1000 * 60 * 2).toISOString(),
        finished_at: undefined,
        results: { total: 12, passed: 5, failed: 1, error: 0 }
    }
])

const resultSummary = (r: TestRunRow) => {
    const { total, passed, failed, error } = r.results
    if (r.status === 'success') return `${passed}/${total} success`
    if (r.status === 'in_progress') return `${passed}/${total} passing…`
    const nonPass = failed + error
    return `${passed}/${total} passing (${nonPass} issues)`
}

const resultBadgeClass = (r: TestRunRow) => {
    if (r.status === 'success') return 'inline-flex px-2 py-1 rounded-full bg-green-100 text-green-800'
    if (r.status === 'in_progress') return 'inline-flex px-2 py-1 rounded-full bg-[#F4EEE5] text-[#6b6b6b]'
    return 'inline-flex px-2 py-1 rounded-full bg-red-100 text-red-800'
}

const formatDuration = (start?: string | null, end?: string | null) => {
    if (!start) return '—'
    const s = new Date(start).getTime()
    const e = end ? new Date(end).getTime() : Date.now()
    const ms = Math.max(0, e - s)
    const secs = Math.round(ms / 1000)
    if (secs < 60) return `${secs}s`
    const mins = Math.floor(secs / 60)
    const rem = secs % 60
    return `${mins}m ${rem}s`
}

function prevTestsPage() {
    if (testsPage.value <= 1) return
    testsPage.value -= 1
    loadCases()
}
function nextTestsPage() {
    if (!testsHasNext.value) return
    testsPage.value += 1
    loadCases()
}
function prevRunsPage() {
    if (runsPage.value <= 1) return
    runsPage.value -= 1
    loadRuns()
}
function nextRunsPage() {
    if (!runsHasNext.value) return
    runsPage.value += 1
    loadRuns()
}

onMounted(async () => {
    try {
        const [mRes] = await Promise.all([
            useMyFetch<TestMetrics>('/api/tests/metrics'),
        ])
        if (mRes.data.value) metrics.value = mRes.data.value
        await loadSuites()
        await loadCases()
        await loadRuns()
    } catch (e) {
        console.error('Failed to load test dashboard', e)
    }
})

// Handle suite filter changes including "Manage Test Suites" option
let _prevSuiteFilter = 'all'
watch(suiteFilter, (newVal) => {
    if (newVal === '__manage__') {
        // Revert to previous value and open manage modal
        suiteFilter.value = _prevSuiteFilter
        showManageSuites.value = true
        return
    }
    _prevSuiteFilter = newVal
})

// Re-fetch when filters change (debounced search)
let _searchTimer: any = null
watch([suiteFilter, searchTerm], () => {
    if (suiteFilter.value === '__manage__') return // skip refetch for manage option
    if (_searchTimer) clearTimeout(_searchTimer)
    _searchTimer = setTimeout(() => {
        testsPage.value = 1
        loadCases()
    }, 300)
})

// Watch pagination size for tests
watch(testsLimit, () => {
    testsPage.value = 1
    loadCases()
})

// Handle runSuiteFilter changes including "Manage Test Suites" option
let _prevRunSuiteFilter = 'all'
watch(runSuiteFilter, (newVal) => {
    if (newVal === '__manage__') {
        // Revert to previous value and open manage modal
        runSuiteFilter.value = _prevRunSuiteFilter
        showManageSuites.value = true
        return
    }
    _prevRunSuiteFilter = newVal
})

// Re-fetch runs when run filters change (debounced)
let _runTimer: any = null
watch([runSuiteFilter, runCaseFilter, runSearchTerm], () => {
    if (runSuiteFilter.value === '__manage__') return // skip refetch for manage option
    if (_runTimer) clearTimeout(_runTimer)
    _runTimer = setTimeout(() => {
        runsPage.value = 1
        loadRuns()
    }, 300)
})
watch(runsLimit, () => {
    runsPage.value = 1
    loadRuns()
})
</script>
