<template>
  <!-- Studio hover flyout (teleported so it never gets clipped by popovers).
       Mirrors AgentFlyout but for a Studio: shows the auto-generated summary,
       pinned sources and suggested questions. Clicking a question starts a
       grounded report on the studio + all its pinned sources. -->
  <Teleport to="body">
    <Transition
      enter-active-class="transition-all duration-150 ease-out"
      enter-from-class="opacity-0 translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-100 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-1"
    >
      <div
        v-if="visible && studioId"
        class="fixed z-[2000]"
        :style="positionStyle"
        @mouseenter="$emit('mouseenter')"
        @mouseleave="$emit('mouseleave')"
      >
        <div
          class="w-max min-w-[400px] max-w-[min(520px,calc(100vw-24px))] bg-white rounded-xl shadow-2xl border border-gray-200 overflow-hidden flex flex-col"
          :style="panelStyle"
        >
          <!-- Header -->
          <div class="px-4 py-3 border-b border-gray-100 flex-shrink-0">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2 min-w-0 flex-1">
                <span class="w-4 h-4 flex items-center justify-center flex-shrink-0 text-sm leading-none">{{ avatar || '🎬' }}</span>
                <div class="text-sm font-semibold text-gray-900 truncate">{{ name || 'Studio' }}</div>
              </div>
              <NuxtLink
                :to="`/studios/${studioId}`"
                class="text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:underline flex-shrink-0 whitespace-nowrap"
              >
                Open studio →
              </NuxtLink>
            </div>
            <!-- Pinned source chips -->
            <div v-if="sources.length" class="flex flex-wrap gap-1 mt-2">
              <span
                v-for="src in sources.slice(0, 4)"
                :key="src.agent_id"
                class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-gray-200 bg-gray-50 text-[11px] text-gray-600"
              >
                <DataSourceIcon v-if="src.type" :type="src.type" class="h-3 flex-shrink-0" />
                <span class="truncate max-w-[120px]">{{ src.name || 'Source' }}</span>
              </span>
              <span v-if="sources.length > 4" class="text-[11px] text-gray-400 self-center">+{{ sources.length - 4 }}</span>
            </div>
            <div v-else class="mt-2 inline-flex items-center gap-1 text-[11px] text-amber-600">
              <Icon name="heroicons-exclamation-triangle" class="w-3 h-3" />
              No sources pinned yet
            </div>
          </div>

          <div class="p-4 flex-1 min-h-0 overflow-y-auto">
            <div v-if="loading" class="flex items-center justify-center py-8">
              <Spinner class="w-5 h-5 text-gray-400 animate-spin" />
            </div>

            <template v-else>
              <!-- Summary -->
              <div v-if="summary" class="text-xs text-gray-600 leading-relaxed mb-4 max-h-[200px] overflow-auto pe-1">
                {{ summary }}
              </div>

              <!-- Suggested questions -->
              <div v-if="questions.length">
                <div class="text-[10px] uppercase tracking-wider text-gray-400 font-semibold mb-2">Sample questions</div>
                <div class="space-y-1.5">
                  <button
                    v-for="(q, idx) in questions.slice(0, 6)"
                    :key="idx"
                    @click.stop.prevent="startReport(q, idx)"
                    :disabled="creating"
                    :class="[
                      'w-full text-start text-xs px-3 py-2 rounded-lg transition-colors flex items-center gap-2',
                      creating && creatingIdx === idx
                        ? 'bg-indigo-100 border border-indigo-300 text-indigo-700'
                        : 'bg-gray-50 border border-gray-100 text-gray-700 hover:bg-indigo-50 hover:border-indigo-200 hover:text-indigo-700 cursor-pointer',
                      creating && creatingIdx !== idx ? 'opacity-50 cursor-not-allowed' : ''
                    ]"
                  >
                    <Spinner v-if="creating && creatingIdx === idx" class="w-3 h-3 flex-shrink-0 animate-spin" />
                    <span class="flex-1">{{ q.split('\n')[0] }}</span>
                  </button>
                </div>
              </div>

              <div
                v-if="!summary && !questions.length"
                class="text-xs text-gray-400 italic py-6 text-center"
              >
                No studio details yet. Pin a source to generate them.
              </div>
            </template>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'
import DataSourceIcon from '~/components/DataSourceIcon.vue'

const router = useRouter()

const props = defineProps<{
  studioId: string | null
  name?: string | null
  avatar?: string | null
  visible: boolean
  position: { top?: number; bottom?: number; left: number; maxHeight?: number }
}>()

defineEmits<{ mouseenter: []; mouseleave: [] }>()

const positionStyle = computed(() => {
  const style: Record<string, string> = { left: `${props.position.left}px` }
  if (props.position.bottom !== undefined) style.bottom = `${props.position.bottom}px`
  else if (props.position.top !== undefined) style.top = `${props.position.top}px`
  return style
})
const panelStyle = computed(() => {
  const h = props.position.maxHeight
  return h ? { maxHeight: `${h}px` } : {}
})

// State (cached per studio)
const loading = ref(false)
const summary = ref('')
const questions = ref<string[]>([])
const sources = ref<any[]>([])
const cache = ref<Record<string, { summary: string; questions: string[]; sources: any[] }>>({})

const creating = ref(false)
const creatingIdx = ref<number | null>(null)

function _parseQuestions(content: string | null | undefined): string[] {
  if (!content) return []
  try {
    const arr = JSON.parse(content)
    if (Array.isArray(arr)) return arr.map((x) => String(x)).filter(Boolean)
  } catch {
    // fall back: newline-split
    return content.split('\n').map((s) => s.trim()).filter(Boolean)
  }
  return []
}

async function fetchStudio(id: string) {
  if (cache.value[id]) {
    const c = cache.value[id]
    summary.value = c.summary; questions.value = c.questions; sources.value = c.sources
    return
  }
  loading.value = true
  try {
    const [{ data: artData }, { data: srcData }] = await Promise.all([
      useMyFetch<any[]>(`/studios/${id}/artifacts`, { method: 'GET' }),
      useMyFetch<any[]>(`/studios/${id}/sources`, { method: 'GET' }),
    ])
    const arts = (artData.value as any[] | null) || []
    const sum = arts.find((a) => a.kind === 'summary')?.content || ''
    const sq = arts.find((a) => a.kind === 'suggested_questions')?.content
    const srcs = (srcData.value as any[] | null) || []
    const entry = { summary: sum, questions: _parseQuestions(sq), sources: srcs }
    cache.value[id] = entry
    if (props.studioId === id) {
      summary.value = entry.summary; questions.value = entry.questions; sources.value = entry.sources
    }
  } catch (e) {
    console.error('Failed to load studio flyout:', e)
  } finally {
    loading.value = false
  }
}

async function startReport(question: string, idx: number) {
  if (creating.value || !props.studioId) return
  creating.value = true
  creatingIdx.value = idx
  try {
    const dataSources = sources.value.map((x: any) => String(x.agent_id))
    const { data, error } = await useMyFetch<any>('/reports', {
      method: 'POST',
      body: {
        title: `${props.name || 'Studio'} chat`,
        files: [],
        new_message: question,
        data_sources: dataSources,
        studio_id: props.studioId,
      },
    })
    if (error?.value) throw new Error('Report creation failed')
    const created = (data.value as any)
    if (created?.id) {
      await router.push({ path: `/reports/${created.id}`, query: { new_message: question } })
    }
  } catch (e) {
    console.error('Failed to start studio report:', e)
  } finally {
    creating.value = false
    creatingIdx.value = null
  }
}

watch(() => props.studioId, (id, old) => {
  if (id && id !== old) {
    summary.value = ''; questions.value = []; sources.value = []
    fetchStudio(id)
  }
}, { immediate: true })
</script>
