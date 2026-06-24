<template>
    <section>
        <!-- Header -->
        <div class="flex items-start justify-between mb-4">
            <div>
                <h2 class="text-sm font-semibold text-gray-900">{{ $t('studio.tabEvals') || 'Evals' }}</h2>
                <p class="text-xs text-gray-500 mt-0.5">{{ $t('studio.evalsHint') || 'Test cases and run history for this studio\'s pinned Data Agents.' }}</p>
            </div>
            <div v-if="canEdit && activeSource" class="flex items-center gap-2 shrink-0">
                <UButton :disabled="selectedIds.size === 0" color="primary" size="xs" icon="i-heroicons-play" @click="runSelected">
                    {{ $t('evals.tests.runSelected') || 'Run selected' }}
                </UButton>
                <UButton color="primary" size="xs" variant="soft" icon="i-heroicons-plus" @click="addNewTest">
                    {{ $t('evals.tests.addNew') || 'Add new' }}
                </UButton>
            </div>
        </div>

        <!-- No pinned sources -->
        <div v-if="sources.length === 0" class="py-10 text-center border border-dashed border-gray-200 rounded-lg">
            <UIcon name="i-heroicons-beaker" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
            <p class="text-xs text-gray-500">{{ $t('studio.evalsNoSources') || 'Pin a Data Agent to view and run its evals.' }}</p>
        </div>

        <template v-else>
            <!-- Inner source switcher (only when >1 pinned source) -->
            <div v-if="sources.length > 1" class="flex items-center gap-1.5 mb-4 flex-wrap">
                <span class="text-[11px] font-medium text-gray-400 uppercase tracking-wider me-1">{{ $t('studio.sourcesTitle') || 'Sources' }}</span>
                <button
                    v-for="s in sources"
                    :key="s.id"
                    type="button"
                    class="inline-flex items-center gap-1.5 text-xs rounded-full px-2.5 py-1 border transition-colors"
                    :class="String(s.agent_id) === activeAgentId
                        ? 'border-[#E8C9B5] bg-[#F6EFEA] text-[#A8542F]'
                        : 'border-gray-200 text-gray-600 hover:bg-gray-50'"
                    @click="selectSource(s.agent_id)"
                >
                    <DataSourceIcon v-if="s.type" class="h-3.5 shrink-0" :type="s.type" />
                    <UIcon v-else name="i-heroicons-circle-stack" class="w-3.5 h-3.5 shrink-0 text-gray-400" />
                    <span class="truncate max-w-[12rem]">{{ s.name || s.agent_id }}</span>
                </button>
            </div>

            <!-- Metric cards -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
                <div class="bg-white p-4 border border-gray-200 rounded-xl">
                    <div class="text-xl font-bold text-gray-900">{{ agentCases.length }}</div>
                    <div class="text-xs text-gray-500 mt-0.5">{{ $t('evals.totalTestCases') || 'Test cases' }}</div>
                </div>
                <div class="bg-white p-4 border border-gray-200 rounded-xl">
                    <div class="text-xl font-bold text-gray-900">{{ agentRuns.length }}</div>
                    <div class="text-xs text-gray-500 mt-0.5">{{ $t('evals.totalTestRuns') || 'Test runs' }}</div>
                </div>
                <div class="bg-white p-4 border border-gray-200 rounded-xl">
                    <div class="mt-0.5">
                        <span v-if="lastRunStatus" :class="['inline-flex items-center px-2 py-1 rounded-full text-xs font-medium', statusClass(lastRunStatus)]">
                            {{ localizedStatus(lastRunStatus) }}
                        </span>
                        <span v-else class="text-gray-400 text-sm">—</span>
                    </div>
                    <div class="text-xs text-gray-500 mt-0.5">{{ $t('evals.lastTestResult') || 'Last result' }}</div>
                </div>
            </div>

            <!-- Sub-tabs -->
            <div class="border-b border-gray-200 mb-4">
                <nav class="-mb-px flex space-x-6">
                    <button type="button" @click="activeTab = 'tests'" :class="subTabClass('tests')">{{ $t('evals.tabs.tests') || 'Tests' }}</button>
                    <button type="button" @click="activeTab = 'runs'" :class="subTabClass('runs')">{{ $t('evals.tabs.runs') || 'Runs' }}</button>
                </nav>
            </div>

            <!-- Tests sub-tab -->
            <div v-if="activeTab === 'tests'">
                <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
                    <div class="px-4 py-2.5 border-b border-gray-200 flex items-center gap-3">
                        <div class="text-xs font-medium text-gray-700 me-auto">{{ $t('evals.tests.title') || 'Test cases' }}</div>
                        <input
                            v-model="searchTerm"
                            type="text"
                            :placeholder="$t('evals.tests.search') || 'Search…'"
                            class="border border-gray-300 rounded px-2 py-1 text-xs w-40"
                        />
                    </div>
                    <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead class="bg-gray-50">
                                <tr>
                                    <th v-if="canEdit" class="px-4 py-2.5 w-10">
                                        <input type="checkbox" :checked="allVisibleSelected" @change="toggleAllVisible" />
                                    </th>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.tests.colPrompt') || 'Prompt' }}</th>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.tests.colRules') || 'Rules' }}</th>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.tests.colSuite') || 'Suite' }}</th>
                                    <th v-if="canEdit" class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.tests.colOptions') || 'Options' }}</th>
                                </tr>
                            </thead>
                            <tbody class="bg-white divide-y divide-gray-200 text-xs">
                                <tr v-if="loadingCases">
                                    <td :colspan="caseColspan" class="px-5 py-6 text-center text-gray-400">{{ $t('common.loading') }}</td>
                                </tr>
                                <tr v-for="c in pagedCases" :key="c.id" class="hover:bg-gray-50">
                                    <td v-if="canEdit" class="px-4 py-2.5 w-10 text-center">
                                        <input type="checkbox" :checked="selectedIds.has(c.id)" @change="toggleOne(c.id)" />
                                    </td>
                                    <td class="px-5 py-2.5">
                                        <div class="flex items-center gap-1.5 max-w-[420px]">
                                            <span v-if="c.status === 'draft'" class="inline-flex items-center rounded-full bg-amber-100 text-amber-800 text-[10px] font-medium px-2 py-0.5 shrink-0">Draft</span>
                                            <span v-else-if="c.status === 'archived'" class="inline-flex items-center rounded-full bg-gray-200 text-gray-700 text-[10px] font-medium px-2 py-0.5 shrink-0">Archived</span>
                                            <span v-if="c.auto_generated" class="inline-flex items-center rounded-full bg-purple-100 text-purple-800 text-[10px] font-medium px-2 py-0.5 shrink-0">Auto</span>
                                            <span class="truncate flex-1" :title="c.prompt_json?.content || ''">{{ c.prompt_json?.content || '—' }}</span>
                                        </div>
                                    </td>
                                    <td class="px-5 py-2.5 text-gray-700">
                                        <div class="flex flex-wrap gap-1 max-w-xs">
                                            <span
                                                v-for="cat in categoriesForCase(c)"
                                                :key="cat.key"
                                                :class="['inline-flex items-center rounded-full border text-[11px] px-2 py-0.5', badgeClassesFor(cat.key)]"
                                            >{{ cat.label }}</span>
                                        </div>
                                    </td>
                                    <td class="px-5 py-2.5">{{ c.suite_name }}</td>
                                    <td v-if="canEdit" class="px-5 py-2.5">
                                        <div class="flex items-center gap-1.5">
                                            <UButton v-if="c.status === 'draft'" color="green" size="2xs" variant="soft" icon="i-heroicons-check-badge" @click="promoteCase(c)">Promote</UButton>
                                            <UButton color="gray" size="2xs" variant="soft" icon="i-heroicons-pencil-square" @click="editCase(c)">{{ $t('evals.tests.actionEdit') || 'Edit' }}</UButton>
                                            <UButton color="primary" size="2xs" variant="soft" icon="i-heroicons-play" @click="runCase(c)">{{ $t('evals.tests.actionRunTest') || 'Run' }}</UButton>
                                            <UButton color="red" size="2xs" variant="ghost" icon="i-heroicons-trash" @click="deleteCase(c)" />
                                        </div>
                                    </td>
                                </tr>
                                <tr v-if="!loadingCases && pagedCases.length === 0">
                                    <td :colspan="caseColspan" class="px-5 py-6 text-center text-gray-500">{{ $t('evals.tests.empty') || 'No test cases for this source yet.' }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                    <div class="px-4 py-2.5 border-t border-gray-200 flex items-center justify-between">
                        <div class="text-xs text-gray-500">{{ $t('evals.pagination.showing', { page: casesPage, n: pagedCases.length }) }}</div>
                        <div class="flex items-center gap-1.5">
                            <UButton size="2xs" variant="soft" :disabled="casesPage <= 1" @click="casesPage--">{{ $t('evals.pagination.prev') || 'Prev' }}</UButton>
                            <UButton size="2xs" variant="soft" :disabled="!casesHasNext" @click="casesPage++">{{ $t('evals.pagination.next') || 'Next' }}</UButton>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Runs sub-tab -->
            <div v-else>
                <div class="bg-white border border-gray-200 rounded-lg overflow-hidden">
                    <div class="px-4 py-2.5 border-b border-gray-200">
                        <div class="text-xs font-medium text-gray-700">{{ $t('evals.runs.title') || 'Run history' }}</div>
                    </div>
                    <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead class="bg-gray-50">
                                <tr>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.runs.colTitle') || 'Title' }}</th>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.runs.colStarted') || 'Started' }}</th>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.runs.colTrigger') || 'Trigger' }}</th>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.runs.colStatus') || 'Status' }}</th>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.runs.colResults') || 'Results' }}</th>
                                    <th class="px-5 py-2.5 text-start text-[11px] font-medium text-gray-500 uppercase tracking-wider">{{ $t('evals.runs.colDuration') || 'Duration' }}</th>
                                </tr>
                            </thead>
                            <tbody class="bg-white divide-y divide-gray-200 text-xs">
                                <tr v-if="loadingRuns">
                                    <td colspan="6" class="px-5 py-6 text-center text-gray-400">{{ $t('common.loading') }}</td>
                                </tr>
                                <tr v-for="r in agentRuns" :key="r.id" class="hover:bg-gray-50">
                                    <td class="px-5 py-2.5">
                                        <NuxtLink :to="`/evals/runs/${r.id}`" class="text-[#C2683F] hover:underline">
                                            {{ r.title || $t('evals.runs.fallbackTitle') || 'Test run' }}
                                        </NuxtLink>
                                    </td>
                                    <td class="px-5 py-2.5">{{ formatDate(r.started_at) }}</td>
                                    <td class="px-5 py-2.5 capitalize">{{ r.trigger_reason || $t('evals.run.triggerManually') || 'manual' }}</td>
                                    <td class="px-5 py-2.5">
                                        <span class="inline-flex px-2 py-1 text-xs font-medium rounded-full" :class="runStatusClass(r)">
                                            {{ localizedStatus(derivedRunStatus(r)) || '—' }}
                                        </span>
                                    </td>
                                    <td class="px-5 py-2.5">
                                        <span :class="resultBadgeClass(r)">{{ resultSummary(r) }}</span>
                                    </td>
                                    <td class="px-5 py-2.5">{{ formatDuration(r.started_at, r.finished_at) }}</td>
                                </tr>
                                <tr v-if="!loadingRuns && agentRuns.length === 0">
                                    <td colspan="6" class="px-5 py-6 text-center text-gray-500">{{ $t('evals.runs.empty') || 'No runs yet.' }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </template>

        <!-- Add / edit test case modal (reused from Data Agent evals) -->
        <AddTestCaseModal
            v-if="showAddCase"
            v-model="showAddCase"
            :suite-id="selectedSuiteId"
            :case-id="selectedCaseId"
            @created="onCaseCreated"
            @updated="onCaseUpdated"
        />
    </section>
</template>

<script setup lang="ts">
import AddTestCaseModal from '~/components/monitoring/AddTestCaseModal.vue'
import DataSourceIcon from '~/components/DataSourceIcon.vue'

// Data Agent parity tab. Props contract (shared by all parity tabs):
//   studioId: string         -> the studio id
//   sources:  Source[]       -> pinned data agents [{ id, agent_id, name, type }]
//   canEdit:  boolean        -> caller may mutate
// Evals are not studio-scoped in the backend — they live per data source
// (TestCase.data_source_ids_json). So this tab reuses the existing /api/tests
// routes exactly as the Data Agent page does, and filters to the pinned source
// the user is viewing (the inner source switcher). Run/create are gated on canEdit.
const props = defineProps<{ studioId: string; sources: any[]; canEdit: boolean }>()

const { t } = useI18n()
const router = useRouter()
const toast = useToast()

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
interface RunItem {
    id: string
    title?: string
    started_at?: string
    finished_at?: string
    trigger_reason?: string
    status?: string
}

const activeTab = ref<'tests' | 'runs'>('tests')

// Which pinned source's evals we're viewing. Defaults to the first pinned source.
const activeAgentId = ref<string>('')
const activeSource = computed(() => props.sources.find(s => String(s.agent_id) === activeAgentId.value) || null)

const loadingCases = ref(false)
const loadingRuns = ref(false)
const allCases = ref<TestCaseRow[]>([])
const allRuns = ref<RunItem[]>([])
const runResults = ref<Record<string, { total: number; passed: number; failed: number; error: number }>>({})
const runResultsCaseIds = ref<Record<string, Set<string>>>({})
const suitesById = ref<Record<string, string>>({})
const searchTerm = ref('')
const selectedIds = ref<Set<string>>(new Set())
const casesPage = ref(1)
const casesLimit = 20
const showAddCase = ref(false)
const selectedSuiteId = ref('')
const selectedCaseId = ref('')

const caseColspan = computed(() => (props.canEdit ? 5 : 3))

// Pick the active source. Keeps within the studio's pinned sources only.
function selectSource(agentId: string) {
    activeAgentId.value = String(agentId)
    selectedIds.value = new Set()
    casesPage.value = 1
}

// Filter cases to the active pinned source (same scoping the Data Agent page uses).
const agentCases = computed(() => {
    const id = activeAgentId.value
    if (!id) return []
    const term = searchTerm.value.trim().toLowerCase()
    return allCases.value.filter(c => {
        const hasAgent = (c.data_source_ids_json || []).includes(id)
        if (!hasAgent) return false
        if (term) return (c.prompt_json?.content || '').toLowerCase().includes(term)
        return true
    })
})

// Runs that contain any of the active source's cases.
const agentCaseIds = computed(() => new Set(agentCases.value.map(c => c.id)))
const agentRuns = computed(() => {
    if (!activeAgentId.value) return []
    return allRuns.value.filter(r => {
        const caseIds = runResultsCaseIds.value[r.id]
        if (!caseIds) return false
        return [...caseIds].some(id => agentCaseIds.value.has(id))
    })
})

const pagedCases = computed(() => {
    const start = (casesPage.value - 1) * casesLimit
    return agentCases.value.slice(start, start + casesLimit)
})
const casesHasNext = computed(() => agentCases.value.length > casesPage.value * casesLimit)
const allVisibleSelected = computed(() => pagedCases.value.length > 0 && pagedCases.value.every(c => selectedIds.value.has(c.id)))

const lastRunStatus = computed(() => {
    const runs = agentRuns.value
    if (!runs.length) return null
    return derivedRunStatus(runs[0])
})

watch(searchTerm, () => { casesPage.value = 1 })

function subTabClass(tab: string) {
    const isActive = activeTab.value === tab
    return [
        'whitespace-nowrap py-2.5 px-1 border-b-2 text-xs font-medium',
        isActive ? 'border-[#C2683F] text-[#C2683F]' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300',
    ]
}

function statusClass(status?: string) {
    if (status === 'success') return 'bg-green-100 text-green-800'
    if (status === 'fail') return 'bg-red-100 text-red-800'
    return 'bg-gray-100 text-gray-800'
}

function localizedStatus(status?: string) {
    if (!status) return ''
    const map: Record<string, string> = {
        success: 'evals.run.statusSuccess',
        fail: 'evals.run.statusFailed',
        error: 'evals.run.statusError',
        in_progress: 'evals.run.statusInProgress',
        pass: 'evals.run.rulePass',
        stopped: 'evals.run.completionFinished',
    }
    const k = map[status]
    const tr = k ? t(k) : ''
    return tr && tr !== k ? tr : status
}

function derivedRunStatus(r: RunItem) {
    const c = runResults.value[r.id] || { total: 0, passed: 0, failed: 0, error: 0 }
    if (r.status === 'in_progress') return 'in_progress'
    if (c.total > 0 && c.passed === c.total) return 'success'
    if (c.total > 0 && c.passed < c.total) return 'fail'
    return r.status || 'in_progress'
}

function runStatusClass(r: RunItem) {
    const s = derivedRunStatus(r)
    if (s === 'success') return 'bg-green-100 text-green-800'
    if (s === 'fail') return 'bg-red-100 text-red-800'
    return 'bg-gray-100 text-gray-800'
}

function resultSummary(r: RunItem) {
    const c = runResults.value[r.id] || { total: 0, passed: 0, failed: 0, error: 0 }
    return `${c.passed}/${c.total}`
}

function resultBadgeClass(r: RunItem) {
    const s = derivedRunStatus(r)
    if (s === 'success') return 'inline-flex px-2 py-1 rounded-full bg-green-100 text-green-800'
    if (s === 'fail') return 'inline-flex px-2 py-1 rounded-full bg-red-100 text-red-800'
    return 'inline-flex px-2 py-1 rounded-full bg-gray-100 text-gray-800'
}

function formatDate(iso?: string | null) {
    if (!iso) return '—'
    try { return new Date(iso).toLocaleString() } catch { return '—' }
}

function formatDuration(start?: string | null, end?: string | null) {
    if (!start) return '—'
    const s = new Date(start).getTime()
    const e = end ? new Date(end).getTime() : Date.now()
    const secs = Math.round(Math.max(0, e - s) / 1000)
    if (secs < 60) return `${secs}s`
    return `${Math.floor(secs / 60)}m ${secs % 60}s`
}

const CATEGORY_LABELS = computed<Record<string, string>>(() => ({
    'tool:create_data': t('evals.category.createData'),
    'tool:clarify': t('evals.category.clarify'),
    'tool:describe_table': t('evals.category.describeTable'),
    'metadata': t('evals.category.metadata'),
    'completion': t('evals.category.completion'),
    'judge': t('evals.category.judge'),
}))

function categoryKeysForCase(c: TestCaseRow): string[] {
    const rules = (c as any)?.expectations_json?.rules || []
    if (!Array.isArray(rules) || !rules.length) return []
    const seen = new Set<string>()
    for (const r of rules) {
        if (r?.type === 'field' && r?.target?.category) seen.add(String(r.target.category))
        else if (r?.type === 'tool.calls' && r?.tool) seen.add(`tool:${r.tool}`)
    }
    return Array.from(seen)
}

function categoriesForCase(c: TestCaseRow) {
    return categoryKeysForCase(c).map(key => ({
        key,
        label: CATEGORY_LABELS.value[key] || key,
    }))
}

function badgeClassesFor(catKey: string) {
    const map: Record<string, string> = {
        'tool:create_data': 'bg-[#F6EFEA] text-[#A8542F] border-[#E8C9B5]',
        'tool:clarify': 'bg-amber-50 text-amber-700 border-amber-100',
        'tool:describe_table': 'bg-teal-50 text-teal-700 border-teal-100',
        'metadata': 'bg-slate-50 text-slate-700 border-slate-100',
        'completion': 'bg-purple-50 text-purple-700 border-purple-100',
        'judge': 'bg-gray-100 text-gray-700 border-gray-200',
    }
    return map[catKey] || 'bg-zinc-50 text-zinc-700 border-zinc-100'
}

function toggleOne(id: string) {
    const s = new Set(selectedIds.value)
    s.has(id) ? s.delete(id) : s.add(id)
    selectedIds.value = s
}

function toggleAllVisible() {
    const s = new Set(selectedIds.value)
    const allSel = pagedCases.value.every(c => s.has(c.id))
    for (const c of pagedCases.value) allSel ? s.delete(c.id) : s.add(c.id)
    selectedIds.value = s
}

function editCase(c: TestCaseRow) {
    if (!props.canEdit) return
    selectedSuiteId.value = c.suite_id
    selectedCaseId.value = c.id
    showAddCase.value = true
}

function addNewTest() {
    if (!props.canEdit) return
    selectedSuiteId.value = Object.keys(suitesById.value)[0] || ''
    selectedCaseId.value = ''
    showAddCase.value = true
}

async function runCase(c: TestCaseRow) {
    if (!props.canEdit) return
    try {
        const res: any = await useMyFetch('/api/tests/runs', { method: 'POST', body: { case_ids: [c.id], trigger_reason: 'manual' } })
        if (res?.error?.value) throw res.error.value
        const run = res?.data?.value
        if (run?.id) router.push(`/evals/runs/${run.id}`)
    } catch (e) {
        toast.add({ title: t('studio.actionFailed') || 'Failed to run test', color: 'red' })
    }
}

async function runSelected() {
    if (!props.canEdit || !selectedIds.value.size) return
    try {
        const case_ids = [...selectedIds.value]
        const res: any = await useMyFetch('/api/tests/runs', { method: 'POST', body: { case_ids, trigger_reason: 'manual' } })
        if (res?.error?.value) throw res.error.value
        const run = res?.data?.value
        if (run?.id) router.push(`/evals/runs/${run.id}`)
        else { activeTab.value = 'runs'; await loadRuns() }
    } catch {
        toast.add({ title: t('studio.actionFailed') || 'Failed to run tests', color: 'red' })
    }
}

async function promoteCase(c: TestCaseRow) {
    if (!props.canEdit) return
    try {
        const res: any = await useMyFetch(`/api/tests/cases/${c.id}/status`, { method: 'PATCH', body: { status: 'active' } })
        if (res?.error?.value) throw res.error.value
        const updated = res?.data?.value
        if (updated) {
            const idx = allCases.value.findIndex(x => x.id === c.id)
            if (idx >= 0) { const copy = [...allCases.value]; copy[idx] = { ...copy[idx], status: updated.status }; allCases.value = copy }
        }
        toast.add({ title: t('studio.statusActive') || 'Promoted to active', color: 'green' })
    } catch {
        toast.add({ title: t('studio.actionFailed') || 'Failed to promote', color: 'red' })
    }
}

async function deleteCase(c: TestCaseRow) {
    if (!props.canEdit) return
    if (!window.confirm(t('evals.tests.deleteConfirm') || t('studio.deleteConfirmGeneric'))) return
    try {
        const res: any = await useMyFetch(`/api/tests/cases/${c.id}`, { method: 'DELETE' })
        if (res?.error?.value) throw res.error.value
        allCases.value = allCases.value.filter(x => x.id !== c.id)
        const s = new Set(selectedIds.value); s.delete(c.id); selectedIds.value = s
        toast.add({ title: t('evals.tests.toastDeleted') || 'Deleted', color: 'green' })
    } catch {
        toast.add({ title: t('studio.actionFailed') || 'Failed to delete', color: 'red' })
    }
}

function rowFromCase(c: any): TestCaseRow {
    return {
        id: c.id,
        suite_id: c.suite_id,
        suite_name: suitesById.value[c.suite_id] || '—',
        prompt_json: c.prompt_json,
        expectations_json: c.expectations_json,
        data_source_ids_json: c.data_source_ids_json || [],
        status: c.status,
        auto_generated: !!c.auto_generated,
    }
}

function onCaseCreated(c: any) {
    allCases.value = [...allCases.value, rowFromCase(c)]
    selectedCaseId.value = ''
    toast.add({ title: t('evals.tests.toastCreated') || 'Created', color: 'green' })
}

function onCaseUpdated(c: any) {
    const row = rowFromCase(c)
    const idx = allCases.value.findIndex(x => x.id === c.id)
    if (idx >= 0) { const copy = [...allCases.value]; copy[idx] = row; allCases.value = copy }
    else allCases.value = [...allCases.value, row]
    selectedCaseId.value = ''
}

async function loadSuites() {
    try {
        const res = await useMyFetch<any[]>('/api/tests/suites?limit=100')
        const list = (res.data.value || []) as any[]
        suitesById.value = Object.fromEntries(list.map((s: any) => [s.id, s.name]))
    } catch { /* permission/route gap → leave empty, don't crash */ }
}

async function loadCases() {
    loadingCases.value = true
    try {
        const res = await useMyFetch<any[]>('/api/tests/cases?limit=500')
        const items = (res.data.value || []) as any[]
        allCases.value = items.map(rowFromCase)
    } catch {
        // 404 (route/permission unavailable) → empty tab rather than crash.
        allCases.value = []
    } finally {
        loadingCases.value = false
    }
}

async function loadRuns() {
    loadingRuns.value = true
    try {
        const res = await useMyFetch<any[]>('/api/tests/runs?limit=100')
        const runs = (res.data.value as any[]) || []
        allRuns.value = runs
        const fetches = runs.map((r: any) => useMyFetch<any[]>(`/api/tests/runs/${r.id}/results`))
        const responses = await Promise.all(fetches)
        const map: Record<string, any> = {}
        const caseMap: Record<string, Set<string>> = {}
        for (let i = 0; i < responses.length; i++) {
            const r = runs[i]
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
    } catch {
        allRuns.value = []
    } finally {
        loadingRuns.value = false
    }
}

// Keep the active source valid as the studio's pinned sources change. Default to
// the first pinned source; if the current one was unpinned, fall back to the first.
watch(() => props.sources, (list) => {
    const ids = (list || []).map((s: any) => String(s.agent_id))
    if (!ids.length) { activeAgentId.value = ''; return }
    if (!activeAgentId.value || !ids.includes(activeAgentId.value)) {
        activeAgentId.value = ids[0]
        selectedIds.value = new Set()
        casesPage.value = 1
    }
}, { immediate: true, deep: true })

onMounted(async () => {
    if (props.sources.length === 0) return
    await loadSuites()
    await loadCases()
    await loadRuns()
})
</script>
