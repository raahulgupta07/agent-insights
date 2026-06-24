<template>
    <section>
        <div class="flex items-start justify-between mb-4">
            <div>
                <h2 class="text-sm font-semibold text-gray-900">{{ $t('studio.tablesTitle') || 'Tables' }}</h2>
                <p class="text-xs text-gray-500 mt-0.5">{{ $t('studio.tablesHint') || 'Browse each pinned source\'s tables and describe their columns.' }}</p>
            </div>
        </div>

        <!-- No pinned sources -->
        <div v-if="sources.length === 0" class="py-10 text-center border border-dashed border-gray-200 rounded-lg">
            <UIcon name="i-heroicons-table-cells" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
            <p class="text-xs text-gray-500">{{ $t('studio.noSourcesForTables') || 'Pin a data source to manage its tables.' }}</p>
        </div>

        <template v-else>
            <!-- Source switcher: only when more than one pinned source -->
            <div v-if="sources.length > 1" class="flex items-center gap-1.5 flex-wrap mb-3">
                <button
                    v-for="s in sources"
                    :key="s.id"
                    type="button"
                    class="inline-flex items-center gap-1.5 text-xs rounded-full border px-3 py-1.5 transition-colors"
                    :class="String(activeSourceId) === String(s.agent_id)
                        ? 'border-[#C2683F] bg-[#F6EFEA] text-[#A8542F]'
                        : 'border-gray-200 text-gray-600 hover:bg-gray-50'"
                    @click="activeSourceId = String(s.agent_id)"
                >
                    <DataSourceIcon v-if="s.type" class="h-3.5 shrink-0" :type="s.type" />
                    <UIcon v-else name="i-heroicons-circle-stack" class="w-3.5 h-3.5 shrink-0 text-gray-400" />
                    <span class="truncate max-w-[12rem]">{{ s.name || s.agent_id }}</span>
                </button>
            </div>

            <!-- Tables for the active pinned source. dsId = the source's agent_id
                 (= the data-source id consumed by /data_sources/{id}/... routes). -->
            <div v-if="activeSource" :key="activeSourceId" class="border border-gray-200 rounded-lg p-4">
                <!-- Loading -->
                <div v-if="loading" class="py-8 text-center text-xs text-gray-400">
                    {{ $t('common.loading') || 'Loading…' }}
                </div>

                <!-- Empty -->
                <div v-else-if="tables.length === 0" class="py-8 text-center">
                    <UIcon name="i-heroicons-table-cells" class="w-6 h-6 mx-auto text-gray-300 mb-1" />
                    <p class="text-xs text-gray-500">{{ $t('studio.noTablesFound') || 'No tables found for this source.' }}</p>
                </div>

                <!-- Table list -->
                <div v-else class="space-y-2">
                    <div v-for="table in tables" :key="table.id || table.name" class="border border-gray-100 rounded">
                        <!-- Table header / expand toggle -->
                        <button
                            type="button"
                            class="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 rounded-t"
                            @click="toggleExpand(table)"
                        >
                            <UIcon
                                :name="expanded[table.name] ? 'i-heroicons-chevron-down' : 'i-heroicons-chevron-right'"
                                class="w-3.5 h-3.5 text-gray-400 shrink-0"
                            />
                            <UIcon name="i-heroicons-table-cells" class="w-3.5 h-3.5 text-gray-400 shrink-0" />
                            <span class="text-xs font-medium text-gray-800 truncate">{{ table.name }}</span>
                            <span v-if="table.columns?.length" class="text-[11px] text-gray-400">
                                · {{ table.columns.length }} {{ (table.columns.length === 1 ? ($t('studio.columnSingular') || 'column') : ($t('studio.columnPlural') || 'columns')) }}
                            </span>
                        </button>

                        <!-- Expanded: column grid -->
                        <div v-if="expanded[table.name]" class="px-3 pb-3">
                            <div v-if="loadingCols[tableKey(table)]" class="py-4 text-center text-xs text-gray-400">
                                {{ $t('common.loading') || 'Loading…' }}
                            </div>

                            <template v-else>
                                <div v-if="colState(table).columns.length" class="border border-gray-100 rounded">
                                    <!-- Header row: 3 columns -->
                                    <div class="grid grid-cols-[1fr_1fr_2fr] gap-2 text-xs font-medium text-gray-500 bg-gray-50 px-2 py-1 rounded-t">
                                        <div>{{ $t('studio.colName') || 'Name' }}</div>
                                        <div>{{ $t('studio.colType') || 'Type' }}</div>
                                        <div>{{ $t('studio.colDescription') || 'Description' }}</div>
                                    </div>
                                    <div class="divide-y divide-gray-100">
                                        <div
                                            v-for="col in colState(table).columns"
                                            :key="col.name"
                                            class="grid grid-cols-[1fr_1fr_2fr] gap-2 items-center text-xs px-2 py-1"
                                        >
                                            <div class="text-gray-700 truncate" :title="col.name">{{ col.name }}</div>
                                            <div class="text-gray-500 truncate" :title="col.dtype || col.type">{{ col.dtype || col.type }}</div>

                                            <!-- Editable description for editors -->
                                            <input
                                                v-if="canEdit"
                                                v-model="colState(table).edits[col.name]"
                                                type="text"
                                                :placeholder="$t('studio.colDescriptionPlaceholder') || 'Add a description…'"
                                                class="w-full text-xs rounded border border-[#E7E5DD] px-2 py-1 text-gray-700 placeholder:text-[#9a958c] focus:outline-none focus:border-[#C2683F] focus:ring-1 focus:ring-[#C2683F]"
                                            />
                                            <!-- Read-only for viewers -->
                                            <div v-else class="text-gray-600 truncate" :title="col.description || ''">
                                                {{ col.description || '—' }}
                                            </div>
                                        </div>
                                    </div>
                                </div>

                                <div v-else class="py-3 text-center text-xs text-gray-400">
                                    {{ $t('studio.noColumns') || 'No columns found.' }}
                                </div>

                                <!-- Save descriptions (editors only) -->
                                <div v-if="canEdit && colState(table).columns.length" class="flex items-center justify-end gap-2 mt-2">
                                    <span v-if="hasChanges(table)" class="text-[11px] text-[#9a958c]">
                                        {{ $t('studio.unsavedChanges') || 'Unsaved changes' }}
                                    </span>
                                    <button
                                        type="button"
                                        :disabled="!hasChanges(table) || savingCols[tableKey(table)]"
                                        class="inline-flex items-center gap-1.5 text-xs rounded-md px-3 py-1.5 font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                                        :class="hasChanges(table) && !savingCols[tableKey(table)]
                                            ? 'bg-[#C2683F] text-white hover:bg-[#A8542F]'
                                            : 'bg-gray-100 text-gray-400'"
                                        @click="saveDescriptions(table)"
                                    >
                                        <UIcon
                                            :name="savingCols[tableKey(table)] ? 'i-heroicons-arrow-path' : 'i-heroicons-check'"
                                            class="w-3.5 h-3.5"
                                            :class="savingCols[tableKey(table)] ? 'animate-spin' : ''"
                                        />
                                        {{ $t('studio.saveDescriptions') || 'Save descriptions' }}
                                    </button>
                                </div>
                            </template>
                        </div>
                    </div>
                </div>
            </div>
        </template>
    </section>
</template>

<script setup lang="ts">
import DataSourceIcon from '~/components/DataSourceIcon.vue'

// Data Agent parity tab. Props contract (shared by all parity tabs):
//   studioId: string         -> the studio id
//   sources:  Source[]       -> pinned data agents [{ id, agent_id, name, type }]
//   canEdit:  boolean        -> caller may mutate (editors); viewers are read-only
const props = defineProps<{ studioId: string; sources: any[]; canEdit: boolean }>()

const { t } = useI18n()
const toast = useToast()

type Column = { name: string; dtype?: string; type?: string; description?: string }
type Table = { id?: string; name: string; columns?: Column[] }
type ColState = {
    columns: Column[]
    // per-column editable description text (v-model target)
    edits: Record<string, string>
    // original descriptions to diff against on save
    original: Record<string, string>
}

// Which pinned source's tables are currently shown. Keyed by agent_id since
// that's the data-source id the /data_sources routes expect.
const activeSourceId = ref<string>('')

const activeSource = computed(() =>
    props.sources.find(s => String(s.agent_id) === String(activeSourceId.value)) || null,
)

// dsId = the active source's data-source id (agent_id).
const dsId = computed(() => (activeSource.value ? String(activeSource.value.agent_id) : ''))

const loading = ref(false)
const tables = ref<Table[]>([])
const expanded = reactive<Record<string, boolean>>({})

// Per-table column state, keyed by table id (fallback name).
const colStates = reactive<Record<string, ColState>>({})
const loadingCols = reactive<Record<string, boolean>>({})
const savingCols = reactive<Record<string, boolean>>({})

function tableKey(table: Table): string {
    return String(table.id || table.name)
}

function colState(table: Table): ColState {
    const key = tableKey(table)
    if (!colStates[key]) colStates[key] = { columns: [], edits: {}, original: {} }
    return colStates[key]
}

// Default to the first pinned source, keep selection valid as the set changes.
watch(
    () => props.sources,
    (list) => {
        if (!list || list.length === 0) { activeSourceId.value = ''; return }
        const stillPinned = list.some(s => String(s.agent_id) === String(activeSourceId.value))
        if (!stillPinned) activeSourceId.value = String(list[0].agent_id)
    },
    { immediate: true, deep: true },
)

// Reload tables whenever the active source changes.
watch(activeSourceId, () => {
    // reset per-source local state
    for (const k of Object.keys(expanded)) delete expanded[k]
    for (const k of Object.keys(colStates)) delete colStates[k]
    if (dsId.value) fetchTables()
    else tables.value = []
}, { immediate: true })

// Fetch the table catalog for the active source (full schema, same route the
// Data Agent Tables tab uses). useMyFetch injects Authorization + X-Organization-Id
// and prepends /api; use BARE paths.
async function fetchTables() {
    if (!dsId.value) return
    loading.value = true
    try {
        const res: any = await useMyFetch(`/data_sources/${dsId.value}/full_schema?page=1&page_size=500`, { method: 'GET' })
        if (res?.status?.value === 'success') {
            const data = res.data?.value
            if (data && typeof data === 'object' && 'tables' in data) {
                tables.value = (data.tables || []) as Table[]
            } else if (Array.isArray(data)) {
                tables.value = data as Table[]
            } else {
                tables.value = []
            }
        } else {
            tables.value = []
        }
    } catch (e) {
        console.error('Studio tables load failed:', e)
        tables.value = []
    } finally {
        loading.value = false
    }
}

function toggleExpand(table: Table) {
    const open = !expanded[table.name]
    expanded[table.name] = open
    if (open && colState(table).columns.length === 0) {
        fetchColumns(table)
    }
}

// Load columns (with descriptions) for one table from the new endpoint.
async function fetchColumns(table: Table) {
    if (!dsId.value || !table.id) {
        // No table id -> fall back to the catalog columns (read-only, no descriptions).
        const st = colState(table)
        st.columns = (table.columns || []).map(c => ({ ...c }))
        st.edits = {}
        st.original = {}
        for (const c of st.columns) { st.edits[c.name] = c.description || ''; st.original[c.name] = c.description || '' }
        return
    }
    const key = tableKey(table)
    loadingCols[key] = true
    try {
        const res: any = await useMyFetch(
            `/data_sources/${dsId.value}/tables/${table.id}/columns`,
            { method: 'GET' },
        )
        if (res?.status?.value === 'success') {
            const data = res.data?.value
            const cols: Column[] = (data?.columns || []) as Column[]
            const st = colState(table)
            st.columns = cols
            st.edits = {}
            st.original = {}
            for (const c of cols) {
                st.edits[c.name] = c.description || ''
                st.original[c.name] = c.description || ''
            }
        }
    } catch (e) {
        console.error('Studio columns load failed:', e)
    } finally {
        loadingCols[key] = false
    }
}

// Has the user changed any description in this table?
function hasChanges(table: Table): boolean {
    const st = colState(table)
    return Object.keys(st.edits).some(name => (st.edits[name] || '') !== (st.original[name] || ''))
}

// Collect only changed descriptions and PUT them.
async function saveDescriptions(table: Table) {
    if (!props.canEdit || !dsId.value || !table.id) return
    const key = tableKey(table)
    if (savingCols[key]) return
    const st = colState(table)

    const descriptions: Record<string, string> = {}
    for (const name of Object.keys(st.edits)) {
        const next = st.edits[name] || ''
        if (next !== (st.original[name] || '')) descriptions[name] = next
    }
    if (Object.keys(descriptions).length === 0) return

    savingCols[key] = true
    try {
        const res: any = await useMyFetch(
            `/data_sources/${dsId.value}/tables/${table.id}/columns`,
            { method: 'PUT', body: { descriptions } },
        )
        if (res?.status?.value === 'success') {
            const data = res.data?.value
            // Prefer the server-returned columns; else fold in local edits.
            if (data?.columns?.length) {
                const cols: Column[] = data.columns as Column[]
                st.columns = cols
                st.edits = {}
                st.original = {}
                for (const c of cols) {
                    st.edits[c.name] = c.description || ''
                    st.original[c.name] = c.description || ''
                }
            } else {
                for (const name of Object.keys(descriptions)) st.original[name] = descriptions[name]
            }
            toast.add({
                title: t('studio.descriptionsSaved') || 'Descriptions updated',
                color: 'green',
                icon: 'i-heroicons-check-circle',
            })
        } else {
            throw new Error('save failed')
        }
    } catch (e) {
        console.error('Studio column descriptions save failed:', e)
        toast.add({
            title: t('studio.descriptionsSaveFailed') || 'Could not save descriptions',
            color: 'red',
            icon: 'i-heroicons-exclamation-triangle',
        })
    } finally {
        savingCols[key] = false
    }
}
</script>
