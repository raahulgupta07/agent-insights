<template>
  <div class="relative">
    <!-- Bell button -->
    <button
      type="button"
      class="relative inline-flex items-center justify-center w-9 h-9 rounded-lg text-[#6b6b6b] hover:text-[#1f2328] hover:bg-[#F4EEE5] transition-colors cursor-pointer"
      :title="$t('notifications.title')"
      @click="togglePanel"
    >
      <UIcon name="i-heroicons-bell-alert" class="w-5 h-5" />
      <!-- Unread badge -->
      <span
        v-if="unread > 0"
        class="absolute -top-0.5 -right-0.5 min-w-[16px] h-[16px] px-1 rounded-full bg-[#C2683F] text-white text-[10px] font-semibold leading-[16px] text-center"
      >{{ unread > 9 ? '9+' : unread }}</span>
    </button>

    <!-- Popover panel -->
    <div
      v-if="open"
      class="absolute right-0 mt-2 w-[360px] max-w-[92vw] rounded-2xl border border-[#EAE8E4] bg-white shadow-lg z-50 overflow-hidden"
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-[#EAE8E4]">
        <div class="flex items-center gap-2">
          <h3 class="text-sm font-semibold text-[#1f2328]">{{ $t('notifications.title') }}</h3>
          <span
            v-if="unread > 0"
            class="min-w-[18px] h-[18px] px-1 rounded-full bg-[#C2683F] text-white text-[10px] font-semibold leading-none inline-flex items-center justify-center"
          >{{ unread > 99 ? '99+' : unread }}</span>
        </div>
        <button
          v-if="unread > 0"
          type="button"
          class="text-[12px] text-[#6b6b6b] hover:text-[#1f2328] px-2 py-1 rounded-md hover:bg-[#F4EEE5] transition-colors cursor-pointer"
          @click="markAllRead"
        >{{ $t('notifications.markAllRead') }}</button>
      </div>

      <!-- Body -->
      <div class="max-h-[420px] overflow-y-auto">
        <!-- Empty state -->
        <div v-if="!items.length" class="py-14 flex flex-col items-center text-center gap-2 px-6">
          <div class="flex items-center justify-center w-12 h-12 rounded-full bg-[#F6F1EA]">
            <UIcon name="i-heroicons-bell-slash" class="w-6 h-6 text-[#cfcabf]" />
          </div>
          <p class="text-sm font-medium text-[#1f2328]">{{ $t('notifications.emptyTitle') }}</p>
          <p class="text-xs text-[#9a958c]">{{ $t('notifications.emptyBody') }}</p>
        </div>

        <!-- List -->
        <ul v-else class="divide-y divide-[#EAE8E4]">
          <li
            v-for="n in items"
            :key="n.id"
            class="group relative flex gap-3 px-4 py-3 transition-colors hover:bg-[#F6F1EA] cursor-pointer"
            :class="!n.is_read ? 'bg-[#FBEFE4]/50' : ''"
            @click="onRowClick(n)"
          >
            <div class="mt-1 shrink-0">
              <span
                class="block w-1.5 h-1.5 rounded-full"
                :class="!n.is_read ? 'bg-[#C2683F]' : 'bg-transparent'"
              />
            </div>
            <div class="min-w-0 flex-1 pe-5">
              <span
                class="block text-[13px] truncate"
                :class="!n.is_read ? 'font-semibold text-[#1f2328]' : 'font-medium text-[#4b4b4b]'"
              >{{ n.title }}</span>
              <p v-if="n.body" class="text-[12px] text-[#6b6b6b] mt-0.5 line-clamp-2">{{ n.body }}</p>
              <span class="text-[11px] text-[#9a958c] mt-1 block">{{ relativeTime(n.created_at) }}</span>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

interface InboxNotification {
  id: string
  title: string
  body?: string | null
  link?: string | null
  is_read: boolean
  created_at?: string | null
}

const router = useRouter()

const open = ref(false)
const items = ref<InboxNotification[]>([])
const unread = ref(0)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function loadCount() {
  try {
    const { data, error } = await useMyFetch<any>('/notifications/count', { method: 'GET' })
    if (error.value) throw error.value
    unread.value = typeof data.value?.unread === 'number' ? data.value.unread : 0
  } catch {
    unread.value = 0
  }
}

async function loadItems() {
  try {
    const { data, error } = await useMyFetch<any>('/notifications', { method: 'GET' })
    if (error.value) throw error.value
    const d = data.value || {}
    items.value = Array.isArray(d.items) ? d.items : []
    if (typeof d.unread === 'number') unread.value = d.unread
  } catch {
    items.value = []
  }
}

async function markRead(id: string) {
  try {
    await useMyFetch(`/notifications/${id}/read`, { method: 'POST' })
  } catch {
    // fail-soft
  }
}

async function markAllRead() {
  try {
    await useMyFetch('/notifications/read-all', { method: 'POST' })
  } catch {
    // fail-soft
  }
  items.value = items.value.map(n => ({ ...n, is_read: true }))
  unread.value = 0
}

function togglePanel() {
  open.value = !open.value
  if (open.value) loadItems()
}

function onRowClick(n: InboxNotification) {
  if (!n.is_read) {
    n.is_read = true
    unread.value = Math.max(0, unread.value - 1)
    markRead(n.id)
  }
  if (n.link) {
    open.value = false
    router.push(n.link)
  }
}

function relativeTime(iso?: string | null): string {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (s < 60) return 'just now'
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

onMounted(() => {
  loadCount()
  pollTimer = setInterval(loadCount, 60000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
