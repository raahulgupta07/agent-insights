<template>
  <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
    <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto">

      <!-- header: title + readiness-style ring -->
      <div class="flex items-start justify-between gap-4 mb-1">
        <div>
          <h2 class="text-lg font-semibold text-[#1f2328] flex items-center" style="font-family: 'Spectral', ui-serif, Georgia, serif">
            <GoBackChevron v-if="isExcel" />
            {{ $t('scheduled.title') }}
          </h2>
          <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[480px]">Reports that re-run on a cadence and deliver to a channel or inbox automatically.</p>
        </div>
        <div class="shrink-0 text-center">
          <div class="relative w-[54px] h-[54px] mx-auto">
            <svg width="54" height="54" style="transform:rotate(-90deg)">
              <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
              <circle cx="27" cy="27" r="22" stroke="#6b6b6b" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" :stroke-dashoffset="ringOffset" style="transition:stroke-dashoffset .5s" />
            </svg>
            <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#6b6b6b]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ taskCount }}</div>
          </div>
          <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">tasks</div>
        </div>
      </div>

      <!-- toolbar: segmented + new -->
      <div class="flex items-center gap-2 mt-4 mb-4">
        <div class="flex bg-[#F1ECE3] rounded-lg p-0.5 text-[12px]">
          <button
            v-for="opt in statusOptions"
            :key="opt.value"
            type="button"
            @click="statusFilter = opt.value"
            class="px-3 py-1.5 rounded-md font-medium transition-colors"
            :class="statusFilter === opt.value ? 'bg-[#6b6b6b] text-white font-semibold' : 'text-[#6b6b6b] hover:text-[#1f2328]'"
          >{{ opt.label }}</button>
        </div>
        <button
          @click="openNewTask"
          :disabled="creatingTask"
          class="ml-auto flex items-center justify-center gap-2 bg-[#C2541E] text-white text-[13px] rounded-lg px-3 py-2 font-semibold hover:bg-[#A8330F] disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap shrink-0"
        >
          <Spinner v-if="creatingTask" class="w-4 h-4 animate-spin" />
          <UIcon v-else name="i-heroicons-plus" class="w-4 h-4" />
          {{ creatingTask ? $t('scheduled.creating') : $t('scheduled.newTask') }}
        </button>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="mt-4 text-xs text-[#9a958c] inline-flex items-center">
        <Spinner class="me-1" /> {{ $t('scheduled.loading') }}
      </div>

      <!-- section card -->
      <div v-else class="relative border border-[#E9E0D3] rounded-2xl bg-white p-4">
        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">SCHEDULED TASKS</span>

        <!-- Empty -->
        <div
          v-if="filteredTasks.length === 0"
          class="mt-1 flex flex-col items-center justify-center text-center border border-dashed border-[#d8cfc0] rounded-xl bg-gradient-to-b from-white to-[#fdfcf9] py-12"
        >
          <span class="w-12 h-12 rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] flex items-center justify-center text-[#6b6b6b] mb-3">
            <UIcon name="i-heroicons-clock" class="w-6 h-6" />
          </span>
          <div class="text-[13px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ $t('scheduled.empty') }}</div>
          <div class="text-[11px] text-[#9a958c] mt-1 max-w-[320px]">{{ $t('scheduled.emptyDescription') }}</div>
        </div>

        <!-- Table -->
        <table v-else class="w-full text-[12.5px] mt-1">
          <thead>
            <tr class="text-left text-[10px] uppercase tracking-wide text-[#9a958c] border-b border-[#EFEDE6]">
              <th class="py-2 font-semibold">Report</th>
              <th class="py-2 font-semibold">Cadence</th>
              <th class="py-2 font-semibold">Delivers to</th>
              <th class="py-2 font-semibold">Next run</th>
              <th class="py-2 font-semibold text-right">Active</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="task in filteredTasks"
              :key="task.id"
              class="border-b border-[#F3F0E9] last:border-0 hover:bg-[#FCFAF6] transition-colors cursor-pointer"
              @click="openTask(task)"
            >
              <!-- Report -->
              <td class="py-2.5 pe-3 align-top">
                <div class="flex items-start gap-2 max-w-[340px]">
                  <UIcon name="i-heroicons-clock" class="w-4 h-4 text-[#6b6b6b] mt-0.5 shrink-0" />
                  <div class="min-w-0">
                    <div class="text-[12.5px] font-medium text-[#1f2328] line-clamp-2">{{ task.prompt?.content || $t('scheduled.untitledTask') }}</div>
                    <span v-if="task.user_name" class="block text-[10.5px] text-[#9a958c] mt-0.5">{{ $t('scheduled.by', { name: task.user_name }) }}</span>
                  </div>
                </div>
              </td>
              <!-- Cadence -->
              <td class="py-2.5 pe-3 align-top text-[12px] text-[#6b6b6b] whitespace-nowrap">{{ getCronLabel(task.cron_schedule) }}</td>
              <!-- Delivers to -->
              <td class="py-2.5 pe-3 align-top">
                <NuxtLink
                  :to="`/reports/${task.report_id}`"
                  class="text-[12px] text-[#C2541E] hover:text-[#A8330F] inline-flex items-center gap-1"
                  @click.stop
                >
                  <UIcon name="i-heroicons-chat-bubble-left-right" class="w-3.5 h-3.5 shrink-0" />
                  <span class="truncate max-w-[180px]">{{ task.report?.title || $t('scheduled.untitledReport') }}</span>
                </NuxtLink>
              </td>
              <!-- Next run -->
              <td class="py-2.5 pe-3 align-top text-[12px] text-[#6b6b6b] whitespace-nowrap">
                <span v-if="task.last_run_at">{{ $t('scheduled.lastRun', { time: formatRelativeTime(task.last_run_at) }) }}</span>
                <span v-else class="text-[#9a958c]">—</span>
              </td>
              <!-- Active (real enable/disable toggle) -->
              <td class="py-2.5 align-top text-right">
                <button
                  type="button"
                  @click.stop="toggleActive(task)"
                  :disabled="togglingId === task.id"
                  :aria-pressed="task.is_active"
                  :title="task.is_active ? $t('scheduled.active') : $t('scheduled.paused')"
                  class="relative inline-flex h-5 w-9 items-center rounded-full align-middle transition-colors disabled:opacity-50"
                  :class="task.is_active ? 'bg-[#2F6F4F]' : 'bg-[#D8D2C7]'"
                >
                  <span
                    class="inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform"
                    :class="task.is_active ? 'translate-x-4' : 'translate-x-0.5'"
                  ></span>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Results summary -->
      <div v-if="!isLoading && tasks.length > 0" class="mt-4 text-center text-[11px] text-[#9a958c]">
        {{ $t(pagination.total === 1 ? 'scheduled.showingOne' : 'scheduled.showingMany', { shown: tasks.length, total: pagination.total }) }}
      </div>

      <!-- Load more -->
      <div v-if="pagination.has_next" class="mt-3 text-center">
        <button
          @click="loadMore"
          :disabled="isLoadingMore"
          class="text-xs px-3 py-1.5 rounded-lg border border-[#E9E0D3] hover:bg-[#FCFAF6] text-[#6b6b6b] disabled:opacity-50"
        >
          <template v-if="isLoadingMore"><Spinner class="w-3 h-3 inline me-1" /> {{ $t('scheduled.loading') }}</template>
          <template v-else>{{ $t('scheduled.loadMore') }}</template>
        </button>
      </div>
    </div>

    <!-- Scheduled Prompt Modal -->
    <ScheduledPromptModal
      v-if="modalReportId"
      v-model="showModal"
      :report-id="modalReportId"
      :scheduled-prompt="editingTask"
      @saved="onTaskSaved"
    />
  </div>
</template>

<script setup lang="ts">
import GoBackChevron from '@/components/excel/GoBackChevron.vue'
import Spinner from '~/components/Spinner.vue'
import ScheduledPromptModal from '~/components/ScheduledPromptModal.vue'

definePageMeta({ auth: true })

const toast = useToast()
const { t } = useI18n()
const { isExcel } = useExcel()
const { selectedAgentObjects } = useAgent()

const tasks = ref<any[]>([])
const isLoading = ref(true)
const isLoadingMore = ref(false)
const currentPage = ref(1)
const pagination = ref({ total: 0, page: 1, limit: 20, total_pages: 0, has_next: false, has_prev: false })
const searchTerm = ref('')
// `search` drives the toolbar input (server fetch via searchTerm + client status filter)
const search = searchTerm
const togglingId = ref<string | null>(null)

// Segmented status filter (client-side over fetched tasks)
const statusFilter = ref<'all' | 'active' | 'paused'>('all')
const statusOptions = computed(() => [
  { value: 'all' as const, label: t('scheduled.filterAll', 'All') },
  { value: 'active' as const, label: t('scheduled.active') },
  { value: 'paused' as const, label: t('scheduled.paused') },
])
const filteredTasks = computed(() => {
  if (statusFilter.value === 'active') return tasks.value.filter((tk: any) => tk.is_active)
  if (statusFilter.value === 'paused') return tasks.value.filter((tk: any) => !tk.is_active)
  return tasks.value
})

// Header ring (count = total scheduled tasks; fill = share that are active)
const taskCount = computed(() => pagination.value.total || tasks.value.length)
const ringOffset = computed(() => {
  const total = tasks.value.length
  if (!total) return 138
  const active = tasks.value.filter((tk: any) => tk.is_active).length
  return Math.round(138 - 138 * (active / total))
})

// Real enable/disable toggle → PUT /reports/{report_id}/scheduled-prompts/{sp_id}
const toggleActive = async (task: any) => {
  if (togglingId.value) return
  togglingId.value = task.id
  const next = !task.is_active
  try {
    const response: any = await useMyFetch(`/reports/${task.report_id}/scheduled-prompts/${task.id}`, {
      method: 'PUT',
      body: JSON.stringify({ is_active: next }),
    })
    if (response.error?.value) throw new Error('toggle failed')
    task.is_active = next
  } catch {
    toast.add({ title: t('common.error'), description: t('scheduled.createFailed'), color: 'red' })
  } finally {
    togglingId.value = null
  }
}

// Scheduled prompt modal (shared for create + edit)
const showModal = ref(false)
const modalReportId = ref<string | null>(null)
const editingTask = ref<any | null>(null)
const creatingTask = ref(false)

const openTask = (task: any) => {
  editingTask.value = task
  modalReportId.value = task.report_id
  showModal.value = true
}

const openNewTask = async () => {
  if (creatingTask.value) return
  creatingTask.value = true
  try {
    const dataSourceIds = selectedAgentObjects.value.map((a: any) => a.id)
    const response = await useMyFetch('/reports', {
      method: 'POST',
      body: JSON.stringify({
        title: t('scheduled.defaultTitle'),
        files: [],
        data_sources: dataSourceIds,
      }),
    })
    if ((response as any).error?.value) throw new Error('Report creation failed')
    const data = ((response as any).data?.value) as any
    editingTask.value = null
    modalReportId.value = data.id
    showModal.value = true
  } catch {
    toast.add({ title: t('common.error'), description: t('scheduled.createFailed'), color: 'red' })
  } finally {
    creatingTask.value = false
  }
}

const onTaskSaved = () => {
  showModal.value = false
  currentPage.value = 1
  fetchTasks(1, searchTerm.value)
}

const fetchTasks = async (page: number = 1, search: string = '') => {
  if (page === 1) isLoading.value = true
  try {
    const response = await useMyFetch('/scheduled-prompts', {
      method: 'GET',
      query: {
        page,
        limit: pagination.value.limit,
        filter: 'my',
        search: search?.trim() || undefined,
      },
    })
    if (response.status.value === 'success' && response.data.value) {
      const data = response.data.value as any
      if (page === 1) {
        tasks.value = data.scheduled_prompts
      } else {
        tasks.value = [...tasks.value, ...data.scheduled_prompts]
      }
      pagination.value = data.meta
    } else {
      throw new Error('Could not fetch scheduled tasks')
    }
  } catch (error) {
    console.error('Error fetching scheduled tasks:', error)
    if (page === 1) tasks.value = []
  } finally {
    isLoading.value = false
    isLoadingMore.value = false
  }
}

const loadMore = async () => {
  isLoadingMore.value = true
  currentPage.value++
  await fetchTasks(currentPage.value, searchTerm.value)
}

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr)
  const diff = Math.max(0, Date.now() - date.getTime())
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return t('queries.timeMinutesAgo', { n: mins })
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return t('queries.timeHoursAgo', { n: hrs })
  const days = Math.floor(hrs / 24)
  return t('queries.timeDaysAgo', { n: days })
}

const { getCronLabel } = useCronLabel()

let _searchTimer: any = null
watch(searchTerm, () => {
  if (_searchTimer) clearTimeout(_searchTimer)
  _searchTimer = setTimeout(() => {
    currentPage.value = 1
    fetchTasks(1, searchTerm.value)
  }, 300)
})

onMounted(async () => {
  await nextTick()
  await fetchTasks(1, '')
})
</script>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
