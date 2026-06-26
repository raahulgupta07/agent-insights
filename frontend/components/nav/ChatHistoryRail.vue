<template>
  <!-- Lives inside the fixed shell's bounded zone → just fill its height. -->
  <aside
    class="shrink-0 h-full border-e border-gray-200/80 bg-[#F6F1EA] flex flex-col transition-[width] duration-150"
    :class="collapsed ? 'w-12' : 'w-64'"
  >
    <!-- ===== Collapsed: icon-only rail ===== -->
    <template v-if="collapsed">
      <div class="flex flex-col items-center gap-1 py-2">
        <button
          @click="createNewReport"
          :disabled="creatingReport"
          class="flex items-center justify-center w-8 h-8 rounded-md text-white bg-[#C2541E] hover:bg-[#A8330F] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          title="New report"
        >
          <Spinner v-if="creatingReport" class="animate-spin w-[18px] h-[18px]" />
          <UIcon v-else name="heroicons-plus-circle" class="w-5 h-5" />
        </button>
        <button
          @click="toggleCollapsed"
          class="flex items-center justify-center w-8 h-8 rounded-md text-gray-500 hover:text-gray-900 hover:bg-gray-100 transition-colors"
          title="Expand chat history"
        >
          <UIcon name="heroicons-bars-3" class="w-5 h-5" />
        </button>
      </div>
    </template>

    <!-- ===== Expanded ===== -->
    <template v-else>
      <!-- Header: New report (duplicate of the top New report button) + collapse toggle -->
      <div class="px-2.5 pt-2.5 pb-1.5 flex items-center gap-2">
        <button
          @click="createNewReport"
          :disabled="creatingReport"
          class="flex-1 flex items-center justify-center gap-2 px-3 py-1.5 rounded-md text-[13px] font-medium text-white bg-[#C2541E] hover:bg-[#A8330F] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <span class="flex items-center justify-center w-[18px] h-[18px]">
            <Spinner v-if="creatingReport" class="animate-spin" />
            <UIcon v-else name="heroicons-plus-circle" />
          </span>
          <span>New report</span>
        </button>
        <button
          @click="toggleCollapsed"
          class="shrink-0 flex items-center justify-center w-8 h-8 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          title="Collapse chat history"
        >
          <UIcon name="heroicons-chevron-double-left" class="w-4 h-4" />
        </button>
      </div>

      <!-- Search -->
      <div class="px-2.5 pb-2">
        <div class="relative">
          <UIcon
            name="heroicons-magnifying-glass"
            class="absolute start-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none"
          />
          <input
            v-model="searchTerm"
            type="text"
            placeholder="Search"
            class="w-full ps-8 pe-2 py-1.5 text-[13px] rounded-md border border-gray-200 bg-gray-50 focus:bg-white focus:outline-none focus:ring-1 focus:ring-[#C2541E] focus:border-[#C2541E] transition-colors"
          />
        </div>
      </div>

      <!-- List -->
      <div class="flex-1 overflow-y-auto px-1.5 pb-3">
        <!-- Loading -->
        <div v-if="loading && rows.length === 0" class="py-10 flex items-center justify-center text-gray-400">
          <Spinner class="w-4 h-4 me-2" />
          <span class="text-xs">Loading</span>
        </div>

        <!-- Empty -->
        <div v-else-if="groupedRows.length === 0" class="py-10 px-2 text-center text-xs text-gray-400">
          {{ searchTerm ? 'No matches' : 'No chats yet' }}
        </div>

        <!-- Grouped rows -->
        <template v-else>
          <div v-for="group in groupedRows" :key="group.label" class="mb-2">
            <div class="px-2.5 pt-2 pb-1">
              <span class="text-[10px] font-semibold text-gray-400 uppercase tracking-wider">{{ group.label }}</span>
            </div>
            <ul>
              <li
                v-for="row in group.rows"
                :key="row.id"
                class="group relative"
              >
                <!-- Inline rename -->
                <div
                  v-if="renamingId === row.id"
                  class="flex items-center gap-1 px-2 py-1.5"
                >
                  <input
                    :ref="el => registerRenameInput(row.id, el)"
                    v-model="renameDraft"
                    type="text"
                    class="flex-1 min-w-0 px-2 py-1 text-[13px] rounded border border-[#C2541E] focus:outline-none focus:ring-1 focus:ring-[#C2541E]"
                    @keydown.enter.prevent="commitRename(row)"
                    @keydown.esc.prevent="cancelRename"
                    @blur="commitRename(row)"
                  />
                </div>

                <!-- Normal row -->
                <button
                  v-else
                  @click="openRow(row)"
                  class="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-start transition-colors"
                  :class="row.id === activeId
                    ? 'bg-[#ECEAE1] text-gray-900 font-medium'
                    : 'text-gray-700 hover:bg-gray-100'"
                >
                  <UIcon
                    name="heroicons-chat-bubble-left-right"
                    class="w-4 h-4 shrink-0"
                    :class="row.id === activeId ? 'text-gray-600' : 'text-gray-400'"
                  />
                  <span class="flex-1 min-w-0 truncate text-[13px]">{{ row.title || 'untitled report' }}</span>
                  <UIcon
                    v-if="row.studio_id"
                    name="heroicons-film"
                    class="w-3.5 h-3.5 shrink-0 text-gray-400"
                    title="Agent Studio"
                  />
                  <span class="shrink-0 text-[10px] text-gray-400 group-hover:hidden">{{ row.relativeTime }}</span>
                </button>

                <!-- Hover actions (hidden while renaming) -->
                <div
                  v-if="renamingId !== row.id"
                  class="absolute end-1.5 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center gap-0.5"
                >
                  <button
                    @click.stop="startRename(row)"
                    class="flex items-center justify-center w-6 h-6 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-200/70 transition-colors"
                    title="Rename"
                  >
                    <UIcon name="heroicons-pencil" class="w-3.5 h-3.5" />
                  </button>
                  <button
                    @click.stop="deleteRow(row)"
                    class="flex items-center justify-center w-6 h-6 rounded text-gray-400 hover:text-red-600 hover:bg-gray-200/70 transition-colors"
                    title="Delete"
                  >
                    <UIcon name="heroicons-trash" class="w-3.5 h-3.5" />
                  </button>
                </div>
              </li>
            </ul>
          </div>
        </template>
      </div>
    </template>
  </aside>
</template>

<script setup lang="ts">
  import Spinner from '~/components/Spinner.vue'

  interface RailReport {
    id: string
    title?: string | null
    created_at?: string
    updated_at?: string
    studio_id?: string | null
    type?: string
  }

  const route = useRoute()
  const router = useRouter()
  // New chat reuses the live AgentSelector context (selected agents + active studio).
  const { selectedAgentObjects, selectedStudioId } = useAgent()

  const COLLAPSE_KEY = 'dash_chat_rail_collapsed'

  const rows = ref<RailReport[]>([])
  const loading = ref(false)
  const searchTerm = ref('')
  const creatingReport = ref(false)
  const collapsed = ref(false)

  // The report id currently being viewed — drives active-row highlight.
  const activeId = computed(() => (route.params.id as string) || '')

  // ---- Collapse state (persisted) -------------------------------------------
  onMounted(() => {
    try {
      collapsed.value = localStorage.getItem(COLLAPSE_KEY) === '1'
    } catch {}
    fetchReports()
    window.addEventListener('report:titled', onReportTitled as EventListener)
  })
  onUnmounted(() => {
    window.removeEventListener('report:titled', onReportTitled as EventListener)
  })

  // Live auto-title: the report page dispatches this on the first question so the
  // matching rail row updates instantly (no refetch needed).
  function onReportTitled(e: Event) {
    const d = (e as CustomEvent).detail || {}
    if (!d.id || !d.title) return
    const hit = rows.value.find(r => r.id === d.id)
    if (hit) hit.title = d.title
  }

  const toggleCollapsed = () => {
    collapsed.value = !collapsed.value
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed.value ? '1' : '0')
    } catch {}
  }

  // ---- Fetch -----------------------------------------------------------------
  const fetchReports = async () => {
    loading.value = true
    try {
      const response: any = await useMyFetch('/reports', {
        method: 'GET',
        query: { filter: 'my', limit: 50 },
      })
      if (response?.error?.value) throw response.error.value
      const body = response?.data?.value as any
      rows.value = Array.isArray(body?.reports) ? body.reports : []
    } catch {
      // 404 / network / shape errors -> empty, never crash the layout.
      rows.value = []
    } finally {
      loading.value = false
    }
  }

  // Refetch when navigating between report pages so a newly created chat appears
  // and the active row updates.
  watch(() => route.params.id, () => {
    fetchReports()
  })

  // ---- Date bucketing + relative time ----------------------------------------
  const parseDate = (r: RailReport): Date | null => {
    const iso = r.created_at || r.updated_at
    if (!iso) return null
    const d = new Date(iso)
    return isNaN(d.getTime()) ? null : d
  }

  const relativeTime = (d: Date | null): string => {
    if (!d) return ''
    const diff = Date.now() - d.getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return 'now'
    if (mins < 60) return `${mins}m`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours}h`
    const days = Math.floor(hours / 24)
    if (days < 7) return `${days}d`
    const weeks = Math.floor(days / 7)
    if (weeks < 5) return `${weeks}w`
    const months = Math.floor(days / 30)
    if (months < 12) return `${months}mo`
    return `${Math.floor(days / 365)}y`
  }

  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

  const bucketOf = (d: Date | null): string => {
    if (!d) return 'Older'
    const today = startOfDay(new Date())
    const dayMs = 86400000
    const day = startOfDay(d)
    if (day === today) return 'Today'
    if (day === today - dayMs) return 'Yesterday'
    if (day > today - 7 * dayMs) return 'Previous 7 days'
    return 'Older'
  }

  const BUCKET_ORDER = ['Today', 'Yesterday', 'Previous 7 days', 'Older']

  // Collapse repeated reports that share the same (normalized) title — and same
  // data source when that field exists — keeping only the most-recent one.
  // Runs BEFORE search/grouping so the filter operates on the deduped set.
  // "untitled report" placeholders are treated as DISTINCT (never collapsed
  // into one) — only identical NON-placeholder titles are merged.
  const dedupedRows = computed(() => {
    const sortKey = (r: RailReport) => {
      const d = parseDate(r)
      return d ? d.getTime() : 0
    }
    const dataSourceOf = (r: any): string =>
      r?.data_source_id ?? r?.dataSourceId ?? r?.data_source ?? r?.studio_id ?? ''

    const seen = new Map<string, RailReport>()
    const result: RailReport[] = []
    for (const r of rows.value) {
      const raw = (r.title || '').trim()
      const norm = raw.toLowerCase()
      // Null/empty/placeholder titles stay distinct — push through untouched.
      if (!norm || norm === 'untitled report') {
        result.push(r)
        continue
      }
      const key = `${norm}::${dataSourceOf(r)}`
      const prev = seen.get(key)
      if (!prev) {
        seen.set(key, r)
        result.push(r)
      } else if (sortKey(r) > sortKey(prev)) {
        // Newer duplicate wins — swap it into the kept slot, preserving order.
        const idx = result.indexOf(prev)
        if (idx !== -1) result[idx] = r
        seen.set(key, r)
      }
    }
    return result
  })

  // Client-side title filter (operates on the deduped set).
  const filteredRows = computed(() => {
    const q = searchTerm.value.trim().toLowerCase()
    if (!q) return dedupedRows.value
    return dedupedRows.value.filter(r => (r.title || 'untitled report').toLowerCase().includes(q))
  })

  const groupedRows = computed(() => {
    const buckets: Record<string, Array<RailReport & { relativeTime: string }>> = {}
    for (const r of filteredRows.value) {
      const d = parseDate(r)
      const label = bucketOf(d)
      ;(buckets[label] ||= []).push({ ...r, relativeTime: relativeTime(d) })
    }
    return BUCKET_ORDER
      .filter(label => buckets[label]?.length)
      .map(label => ({ label, rows: buckets[label] }))
  })

  // ---- Navigation ------------------------------------------------------------
  const openRow = (row: RailReport) => {
    if (row.id === activeId.value) return
    router.push(`/reports/${row.id}`)
  }

  // ---- New chat (lazy creation: report is created on first message, not now) ----
  const createNewReport = async () => {
    await router.push('/reports/new')
  }

  // ---- Inline rename ---------------------------------------------------------
  const renamingId = ref<string | null>(null)
  const renameDraft = ref('')
  const renameInputs = new Map<string, HTMLInputElement>()
  let renameCommitting = false

  const registerRenameInput = (id: string, el: any) => {
    if (el) renameInputs.set(id, el as HTMLInputElement)
    else renameInputs.delete(id)
  }

  const startRename = async (row: RailReport) => {
    renamingId.value = row.id
    renameDraft.value = row.title || ''
    await nextTick()
    const el = renameInputs.get(row.id)
    el?.focus()
    el?.select()
  }

  const cancelRename = () => {
    renamingId.value = null
    renameDraft.value = ''
  }

  const commitRename = async (row: RailReport) => {
    // @blur and @keydown.enter can both fire — guard against a double submit.
    if (renameCommitting || renamingId.value !== row.id) return
    const next = renameDraft.value.trim()
    if (!next || next === (row.title || '')) {
      cancelRename()
      return
    }
    renameCommitting = true
    try {
      const response: any = await useMyFetch(`/reports/${row.id}`, {
        method: 'PUT',
        body: JSON.stringify({ title: next }),
      })
      if (response?.error?.value) throw response.error.value
      // Optimistic local update + refresh to stay in sync with server ordering.
      const hit = rows.value.find(r => r.id === row.id)
      if (hit) hit.title = next
      await fetchReports()
    } catch {
      // leave the list as-is on failure
    } finally {
      renameCommitting = false
      cancelRename()
    }
  }

  // ---- Delete ----------------------------------------------------------------
  const deleteRow = async (row: RailReport) => {
    const label = row.title || 'untitled report'
    if (!window.confirm(`Delete "${label}"?`)) return
    try {
      const response: any = await useMyFetch(`/reports/${row.id}`, { method: 'DELETE' })
      if (response?.error?.value) throw response.error.value
      rows.value = rows.value.filter(r => r.id !== row.id)
      // If we deleted the open chat, fall back to the library.
      if (row.id === activeId.value) await router.push('/reports')
      else await fetchReports()
    } catch {
      // ignore — keep the row visible on failure
    }
  }
</script>
