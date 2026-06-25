<template>
  <div class="relative">
    <!-- Bell button -->
    <button
      type="button"
      class="relative inline-flex items-center justify-center w-9 h-9 rounded-lg text-[#6b6b6b] hover:text-[#1f2328] hover:bg-[#F4F1EA] transition-colors cursor-pointer"
      title="What's new"
      @click="togglePanel"
    >
      <UIcon name="i-heroicons-bell" class="w-5 h-5" />
      <!-- Unseen badge -->
      <span
        v-if="unseen > 0"
        class="absolute -top-0.5 -right-0.5 min-w-[16px] h-[16px] px-1 rounded-full bg-[#C2683F] text-white text-[10px] font-semibold leading-[16px] text-center"
      >{{ unseen > 9 ? '9+' : unseen }}</span>
    </button>

    <!-- Popover panel -->
    <div
      v-if="open"
      class="absolute right-0 mt-2 w-[360px] max-w-[92vw] rounded-2xl border border-[#E7E5DD] bg-white shadow-lg z-50 overflow-hidden"
    >
      <!-- Header: tabs + close -->
      <div class="flex items-center gap-4 px-4 pt-3 border-b border-[#E7E5DD]">
        <button
          type="button"
          class="relative pb-2 text-sm font-medium transition-colors cursor-pointer"
          :class="activeTab === 'activity' ? 'text-[#1f2328]' : 'text-[#9a958c] hover:text-[#6b6b6b]'"
          @click="activeTab = 'activity'"
        >
          Activity
          <span v-if="activeTab === 'activity'" class="absolute left-0 -bottom-px h-[2px] w-full bg-[#C2683F]" />
        </button>
        <button
          type="button"
          class="relative pb-2 text-sm font-medium transition-colors cursor-pointer"
          :class="activeTab === 'whatsnew' ? 'text-[#1f2328]' : 'text-[#9a958c] hover:text-[#6b6b6b]'"
          @click="activeTab = 'whatsnew'"
        >
          What's new
          <span v-if="activeTab === 'whatsnew'" class="absolute left-0 -bottom-px h-[2px] w-full bg-[#C2683F]" />
        </button>
        <button
          type="button"
          class="ms-auto -mt-1 mb-1 w-7 h-7 inline-flex items-center justify-center rounded-md text-[#9a958c] hover:text-[#1f2328] hover:bg-[#F4F1EA] transition-colors cursor-pointer"
          title="Close"
          @click="open = false"
        >
          <UIcon name="i-heroicons-x-mark" class="w-4 h-4" />
        </button>
      </div>

      <!-- Version chip line -->
      <div class="flex items-center gap-2 px-4 py-2 text-[11px] text-[#6b6b6b] bg-[#FBFAF6] border-b border-[#E7E5DD]">
        <span class="font-mono text-[#1f2328]">v{{ current || '—' }}</span>
        <span class="text-[#cfcabf]">·</span>
        <span>baked</span>
        <span class="text-[#cfcabf]">·</span>
        <span class="inline-flex items-center gap-1">
          <span class="w-[7px] h-[7px] rounded-full" style="background:#2f9e6f" />
          <span class="text-[#2f9e6f] font-medium">Up to date</span>
        </span>
      </div>

      <!-- Body -->
      <div class="max-h-[420px] overflow-y-auto">
        <!-- What's new tab -->
        <template v-if="activeTab === 'whatsnew'">
          <div class="flex items-center justify-between px-4 pt-3 pb-1">
            <h3
              class="text-[15px] font-semibold text-[#1f2328]"
              style="font-family: ui-serif, Georgia, 'Times New Roman', serif"
            >&#10022; What's new</h3>
            <NuxtLink
              to="/changelog"
              class="text-xs font-medium text-[#C2683F] hover:text-[#A8542F] transition-colors cursor-pointer"
              @click="open = false"
            >See all ({{ entries.length }})</NuxtLink>
          </div>

          <div v-if="entries.length" class="px-4 pb-4 pt-1 space-y-2.5">
            <div
              v-for="(e, i) in entries"
              :key="e.version + '-' + i"
              class="rounded-xl border border-[#f0ddd0] bg-[#FBF4EF] p-3"
            >
              <button
                type="button"
                class="w-full flex items-start gap-2 text-left cursor-pointer"
                @click="toggleEntry(i)"
              >
                <div class="flex-1 min-w-0">
                  <div class="text-[11px] font-mono text-[#C2683F]">v{{ e.version }}</div>
                  <div class="text-sm font-semibold text-[#1f2328] truncate">{{ e.title }}</div>
                </div>
                <div class="flex items-center gap-1.5 flex-none">
                  <span class="text-[11px] text-[#9a958c]">{{ e.date }}</span>
                  <UIcon
                    name="i-heroicons-chevron-down"
                    class="w-4 h-4 text-[#9a958c] transition-transform"
                    :class="isExpanded(i) ? 'rotate-180' : ''"
                  />
                </div>
              </button>
              <ul
                v-if="isExpanded(i) && e.features && e.features.length"
                class="mt-2.5 space-y-1.5"
              >
                <li
                  v-for="(f, fi) in e.features"
                  :key="fi"
                  class="flex items-start gap-2 text-[13px] text-[#444] leading-snug"
                >
                  <span class="mt-1.5 w-1 h-1 rounded-full flex-none" style="background:#C2683F" />
                  <span>{{ f }}</span>
                </li>
              </ul>
            </div>
          </div>

          <div v-else class="px-4 py-10 text-center text-sm text-[#9a958c]">
            Nothing new yet.
          </div>
        </template>

        <!-- Activity tab -->
        <template v-else>
          <div class="px-4 py-12 text-center">
            <div class="text-sm text-[#6b6b6b]">No activity yet.</div>
            <div class="text-xs text-[#9a958c] mt-1">Your recent activity will appear here.</div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

const open = ref(false)
const activeTab = ref<'activity' | 'whatsnew'>('whatsnew')

const current = ref<string>('')
const entries = ref<any[]>([])
const unseen = ref<number>(0)

// Locally-expanded older cards (latest is always expanded via isExpanded)
const expanded = ref<Set<number>>(new Set())

function isExpanded(i: number) {
  return i === 0 || expanded.value.has(i)
}
function toggleEntry(i: number) {
  if (i === 0) return // latest stays open
  const next = new Set(expanded.value)
  if (next.has(i)) next.delete(i)
  else next.add(i)
  expanded.value = next
}

async function loadChangelog() {
  try {
    const { data, error } = await useMyFetch<any>('/changelog', { method: 'GET' })
    if (error.value) throw error.value
    const d = data.value || {}
    current.value = d.current || ''
    entries.value = Array.isArray(d.entries) ? d.entries : []
  } catch {
    current.value = ''
    entries.value = []
  }
}

async function loadUnseen() {
  try {
    const { data, error } = await useMyFetch<any>('/changelog/unseen', { method: 'GET' })
    if (error.value) throw error.value
    const d = data.value || {}
    unseen.value = typeof d.count === 'number' ? d.count : 0
    if (d.current && !current.value) current.value = d.current
  } catch {
    unseen.value = 0
  }
}

async function markSeen() {
  try {
    await useMyFetch('/changelog/seen', { method: 'POST' })
  } catch {
    // fail-soft
  }
}

function togglePanel() {
  open.value = !open.value
  if (open.value) {
    // default tab depends on whether there is something unseen
    activeTab.value = unseen.value > 0 ? 'whatsnew' : 'activity'
    if (unseen.value > 0) {
      markSeen()
      unseen.value = 0 // optimistic
    }
  }
}

onMounted(async () => {
  await Promise.all([loadChangelog(), loadUnseen()])
})
</script>
