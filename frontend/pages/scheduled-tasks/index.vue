<template>
  <div class="flex justify-center ps-2 md:ps-4 text-sm bg-[#FBFAF6] min-h-full">
    <div class="w-full max-w-7xl px-4 ps-0 py-2 text-[#1f2328]">
      <div>
        <div class="flex items-start justify-between gap-4">
          <div>
            <h1
              class="text-2xl font-semibold text-[#1f2328] tracking-tight flex items-center"
              style="font-family: ui-serif, Georgia, 'Times New Roman', serif"
            >
              <GoBackChevron v-if="isExcel" />
              {{ $t('scheduled.title') }}
            </h1>
            <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">Automatically run prompts on a recurring schedule.</p>
          </div>
          <button
            @click="openNewTask"
            :disabled="creatingTask"
            class="flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl bg-[#C2683F] text-white hover:bg-[#A8542F] disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          >
            <Spinner v-if="creatingTask" class="w-4 h-4 animate-spin" />
            <UIcon v-else name="i-heroicons-plus" class="w-4 h-4" />
            {{ creatingTask ? $t('scheduled.creating') : $t('scheduled.newTask') }}
          </button>
        </div>

        <div class="mt-6 flex flex-col md:flex-row md:items-center gap-3">
          <div class="flex-1 w-full">
            <div class="relative">
              <input
                v-model="searchTerm"
                type="text"
                :placeholder="$t('scheduled.searchPlaceholder')"
                class="w-full ps-10 pe-4 py-2.5 bg-white text-[#1f2328] border border-[#E7E5DD] rounded-xl placeholder:text-[#9a958c] focus:outline-none focus:ring-2 focus:ring-[#C2683F]/40 focus:border-[#C2683F]"
              />
              <UIcon
                name="i-heroicons-magnifying-glass"
                class="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#9a958c]"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="text-xs text-gray-500 inline-flex items-center">
        <Spinner class="me-1" /> {{ $t('scheduled.loading') }}
      </div>

      <!-- Empty -->
      <div v-else-if="tasks.length === 0" class="flex flex-col items-center justify-center py-16 px-4 text-center">
        <span class="inline-flex w-11 h-11 mb-3 items-center justify-center rounded-xl bg-[#F4F1EA] border border-[#E7E5DD] text-[#C2683F]">
          <UIcon name="i-heroicons-clock" class="w-6 h-6" />
        </span>
        <h3 class="text-[15px] font-semibold text-[#1f2328] mb-1" style="font-family: ui-serif, Georgia, 'Times New Roman', serif">{{ $t('scheduled.empty') }}</h3>
        <p class="text-sm text-[#9a958c] text-center max-w-sm">
          {{ $t('scheduled.emptyDescription') }}
        </p>
      </div>

      <!-- Task cards -->
      <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
        <div
          v-for="task in tasks"
          :key="task.id"
          class="border border-gray-100 bg-white rounded-lg p-4 hover:shadow-md hover:border-gray-200 transition-all cursor-pointer h-full"
          @click="openTask(task)"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 mb-1">
                <span
                  class="text-[10px] px-1.5 py-0.5 rounded border"
                  :class="task.is_active
                    ? 'text-green-700 border-green-200 bg-green-50'
                    : 'text-gray-700 border-gray-200 bg-gray-50'"
                >{{ task.is_active ? $t('scheduled.active') : $t('scheduled.paused') }}</span>
                <span class="text-[11px] text-gray-400">{{ getCronLabel(task.cron_schedule) }}</span>
                <span v-if="task.last_run_at" class="text-[11px] text-gray-400">&middot; {{ $t('scheduled.lastRun', { time: formatRelativeTime(task.last_run_at) }) }}</span>
              </div>
              <div class="text-sm font-medium text-gray-900 mb-1 line-clamp-2">{{ task.prompt?.content || $t('scheduled.untitledTask') }}</div>
              <div class="flex items-center gap-3 mt-2">
                <NuxtLink
                  :to="`/reports/${task.report_id}`"
                  class="text-[11px] text-[#C2683F] hover:text-[#A8542F] flex items-center gap-1"
                  @click.stop
                >
                  <UIcon name="heroicons-chat-bubble-left-right" class="w-3 h-3" />
                  {{ task.report?.title || $t('scheduled.untitledReport') }}
                </NuxtLink>
                <span v-if="task.user_name" class="text-[11px] text-gray-400">{{ $t('scheduled.by', { name: task.user_name }) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Results summary -->
      <div v-if="!isLoading && tasks.length > 0" class="mt-6 text-center text-[11px] text-gray-500">
        {{ $t(pagination.total === 1 ? 'scheduled.showingOne' : 'scheduled.showingMany', { shown: tasks.length, total: pagination.total }) }}
      </div>

      <!-- Load more -->
      <div v-if="pagination.has_next" class="mt-4 text-center">
        <button
          @click="loadMore"
          :disabled="isLoadingMore"
          class="text-xs px-3 py-1.5 rounded border border-gray-200 hover:bg-gray-50 text-gray-600 disabled:opacity-50"
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
