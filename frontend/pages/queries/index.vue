<template>
  <div class="flex justify-center px-4 md:px-6 text-sm bg-[#F6F1EA] min-h-full">
    <div class="w-full max-w-7xl py-2 text-[#1f2328]">
      <div class="mb-6">
        <h1 class="text-[32px] font-medium text-[#211B14] tracking-tight flex items-center" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ $t('queries.title') }}</h1>
        <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">{{ $t('queries.subtitle') }}</p>

        <!-- Search -->
        <div class="mt-4">
          <div class="relative">
            <input v-model="q" type="text" :placeholder="$t('queries.searchPlaceholder')" class="w-full ps-10 pe-4 py-2.5 bg-white border border-[#E9E0D3] rounded-xl text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none focus:ring-2 focus:ring-[#C2541E]/40 focus:border-[#C2541E] transition-colors" @keyup.enter="reload()" />
            <UIcon name="i-heroicons-magnifying-glass" class="absolute start-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#9a958c]" />
          </div>
        </div>

        <!-- Filter tabs -->
        <div class="mt-4 flex items-center gap-1 border-b border-[#E9E0D3]">
          <button
            @click="filterType = 'published'"
            :class="[
              'px-3 py-2 text-sm border-b-2 transition-colors',
              filterType === 'published'
                ? 'border-[#C2541E] text-[#1f2328] font-semibold'
                : 'border-transparent text-[#6b6b6b] hover:text-[#1f2328]'
            ]"
          >
            {{ $t('queries.published') }}
          </button>
          <button
            @click="filterType = 'suggested'"
            :class="[
              'px-3 py-2 text-sm border-b-2 transition-colors inline-flex items-center',
              filterType === 'suggested'
                ? 'border-[#C2541E] text-[#1f2328] font-semibold'
                : 'border-transparent text-[#6b6b6b] hover:text-[#1f2328]'
            ]"
          >
            {{ isAdmin ? $t('queries.draftSuggested') : $t('queries.myDrafts') }}
            <span v-if="suggestedCount > 0" class="ms-1.5 px-1.5 py-0.5 rounded-full text-[10px] bg-[#F4EEE5] text-[#6b6b6b]">{{ suggestedCount }}</span>
          </button>
        </div>
      </div>

      <div v-if="loading" class="text-sm text-[#6b6b6b] inline-flex items-center">
        <Spinner class="me-1" /> {{ $t('queries.loading') }}
      </div>
      <div v-else-if="filteredItems.length === 0" class="mt-12 flex flex-col items-center text-center">
        <div class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] text-[#C2541E]">
          <Icon
            :name="filterType === 'suggested' ? 'heroicons:light-bulb' : 'heroicons:cube'"
            class="w-6 h-6"
          />
        </div>
        <h3 class="text-[15px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
          {{ filterType === 'suggested' ? $t('queries.noDrafts') : $t('queries.noPublished') }}
        </h3>
        <p class="mt-1 text-sm text-[#9a958c] max-w-sm">
          {{ filterType === 'suggested'
            ? $t('queries.draftsDescription')
            : $t('queries.publishedDescription')
          }}
        </p>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
        <div
          v-for="item in filteredItems"
          :key="item.id"
          class="bg-white border border-[#E9E0D3] rounded-2xl p-4 hover:shadow-lg hover:-translate-y-0.5 hover:border-[#d9d6cd] transition-all cursor-pointer flex flex-col h-full"
          @click="navigateToEntity(item.id)"
        >
          <div class="min-w-0 flex-1 flex flex-col">
            <div class="flex items-center gap-2 mb-2">
              <span
                class="text-[10px] px-1.5 py-0.5 rounded-md border font-medium"
                :class="item.type === 'metric' ? 'text-[#3f9e6a] border-[#cde7d6] bg-[#eef6f0]' : 'text-[#6b6b6b] border-[#E9E0D3] bg-[#F4EEE5]'"
              >{{ (item.type || '').toUpperCase() }}</span>

              <!-- Green check badge for approved/published entities -->
              <span
                v-if="getEntityType(item) === 'global'"
                class="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md text-[#3f9e6a] bg-[#eef6f0] font-medium"
                title="Approved"
              >
                <Icon name="heroicons:check-badge" class="w-3.5 h-3.5" />
                <span class="w-1.5 h-1.5 rounded-full bg-[#3f9e6a]"></span>
              </span>

              <!-- Entity workflow status badge -->
              <span
                v-if="getEntityType(item) === 'archived'"
                class="text-[10px] px-1.5 py-0.5 rounded-md border text-[#b4504a] border-[#e6cfcd] bg-[#f7eeed] font-medium"
              >{{ $t('queries.archivedBadge') }}</span>
              <span
                v-else-if="getEntityType(item) === 'draft'"
                class="text-[10px] px-1.5 py-0.5 rounded-md border text-[#6b6b6b] border-[#E9E0D3] bg-[#F4EEE5] font-medium"
              >{{ $t('queries.draftBadge') }}</span>
              <span
                v-else-if="getEntityType(item) === 'private'"
                class="text-[10px] px-1.5 py-0.5 rounded-md border text-[#6b6b6b] border-[#E9E0D3] bg-[#F4EEE5] font-medium"
              >{{ $t('queries.draftBadge') }}</span>
              <span
                v-else-if="getEntityType(item) === 'suggested'"
                class="text-[10px] px-1.5 py-0.5 rounded-md border text-[#C2541E] border-[#ecd8cb] bg-[#FBEFE4] font-medium"
              >{{ $t('queries.suggestedBadge') }}</span>

              <span class="ms-auto text-[11px] text-[#9a958c]">{{ timeAgo(item.updated_at) }}</span>
            </div>
            <div class="text-[15px] font-semibold text-[#1f2328] mb-1" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ item.title || item.slug }}</div>
            <div class="text-[13px] text-[#6b6b6b] line-clamp-2 leading-snug">{{ item.description || $t('queries.noDescription') }}</div>

            <!-- SQL preview tile -->
            <div v-if="item.code" class="mt-3 bg-[#F4EEE5] border border-[#E9E0D3] rounded-xl px-3 py-2.5 overflow-hidden">
              <pre class="text-[11px] text-[#1f2328] leading-relaxed whitespace-pre-wrap break-words line-clamp-3" style="font-family: ui-monospace, 'SF Mono', Menlo, monospace">{{ item.code }}</pre>
            </div>

            <!-- Metadata icons -->
            <div class="flex items-center gap-3 mt-3">
              <div v-if="item.data_sources && item.data_sources.length > 0" class="flex items-center gap-1.5">
                <img
                  v-for="ds in item.data_sources.slice(0, 3)"
                  :key="ds.id"
                  :src="dataSourceIcon(ds.type)"
                  :alt="ds.type"
                  :title="ds.name || ds.type"
                  class="w-4 h-4 rounded border border-[#E9E0D3] bg-white object-contain p-0.5"
                  @error="(e: any) => e.target && (e.target.style.visibility = 'hidden')"
                />
                <span v-if="item.data_sources.length > 3" class="text-[11px] text-[#9a958c]">+{{ item.data_sources.length - 3 }}</span>
              </div>

              <!-- Data stats -->
              <div v-if="hasStats(item)" class="flex items-center gap-3 text-[11px] text-[#6b6b6b]">
                <div v-if="item.data?.info?.total_rows !== undefined" class="flex items-center gap-1" :title="$t('queries.rowsTitle')">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"></path>
                  </svg>
                  <span>{{ getRowCount(item) }}</span>
                </div>
                <div v-if="item.data?.info?.total_columns !== undefined" class="flex items-center gap-1" :title="$t('queries.columnsTitle')">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 4v16M15 4v16"></path>
                  </svg>
                  <span>{{ getColumnCount(item) }}</span>
                </div>
              </div>
            </div>

            <!-- Tags -->
            <div v-if="item.tags && item.tags.length > 0" class="flex items-center gap-1.5 flex-wrap mt-3 pt-3 border-t border-[#E9E0D3]">
              <span
                v-for="tag in item.tags.slice(0, 4)"
                :key="tag"
                class="text-[10px] px-1.5 py-0.5 rounded-md bg-[#F4EEE5] border border-[#E9E0D3] text-[#6b6b6b]"
              >{{ tag }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Results summary -->
      <div v-if="!loading && filteredItems.length > 0" class="mt-6 text-center text-[11px] text-[#9a958c]">
        {{ summaryLabel }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMyFetch } from '~/composables/useMyFetch'
import { useCan } from '~/composables/usePermissions'
import { useAuth } from '#imports'
import Spinner from '~/components/Spinner.vue'

type MinimalDS = { id: string; name?: string; type?: string }
type EntityList = { 
  id: string
  type: string
  title: string
  slug: string
  description?: string | null
  updated_at: string
  data_sources?: MinimalDS[]
  data?: {
    info?: {
      total_rows?: number
      total_columns?: number
    }
  }
  status?: string
  private_status?: string | null
  global_status?: string | null
  owner_id?: string
}

const router = useRouter()
const { t } = useI18n()
const { data: authData } = useAuth()
const { selectedAgents } = useAgent()
const items = ref<EntityList[]>([])
const allItems = ref<EntityList[]>([])
const loading = ref(true)
const page = ref(1)
const limit = 20
const q = ref('')
const filterType = ref<'published' | 'suggested'>('published')
const isAdmin = computed(() => useCan('update_entities'))

const currentUserId = computed(() => (authData.value as any)?.user?.id)

const suggestedCount = computed(() => {
  return allItems.value.filter(item => {
    const type = getEntityType(item)
    return (type === 'private' || type === 'suggested' || type === 'draft') && !isArchived(item)
  }).length
})

// Filter items based on current filter type and user permissions
const filteredItems = computed(() => {
  let filtered = allItems.value

  // Always exclude archived entities
  filtered = filtered.filter(item => !isArchived(item))

  if (filterType.value === 'published') {
    // Show only global/published entities (approved AND published)
    filtered = filtered.filter(item => getEntityType(item) === 'global')
  } else if (filterType.value === 'suggested') {
    // Show draft and suggested entities
    filtered = filtered.filter(item => {
      const type = getEntityType(item)
      return type === 'private' || type === 'suggested' || type === 'draft'
    })
    
    // If not admin, show only user's own drafts/suggestions
    if (!isAdmin.value) {
      filtered = filtered.filter(item => item.owner_id === currentUserId.value)
    }
  }

  // Apply search filter
  if (q.value) {
    const search = q.value.toLowerCase()
    filtered = filtered.filter(item => 
      item.title?.toLowerCase().includes(search) || 
      item.slug?.toLowerCase().includes(search) ||
      item.description?.toLowerCase().includes(search)
    )
  }

  return filtered
})

const summaryLabel = computed(() => {
  const count = filteredItems.value.length
  if (filterType.value === 'suggested') {
    return t(count === 1 ? 'queries.showingDraftsOne' : 'queries.showingDraftsMany', { count })
  }
  return t(count === 1 ? 'queries.showingPublishedOne' : 'queries.showingPublishedMany', { count })
})

watch(filterType, () => {
  page.value = 1
})

// Reload when selected agents change
watch(selectedAgents, () => {
  page.value = 1
  loadEntities()
})

onMounted(async () => { await loadEntities() })

async function loadEntities() {
  loading.value = true
  try {
    // Build query params with agent filter
    const params: Record<string, string> = {}
    if (selectedAgents.value.length > 0) {
      params.data_source_ids = selectedAgents.value.join(',')
    }
    const queryString = new URLSearchParams(params).toString()
    const url = queryString ? `/api/entities?${queryString}` : '/api/entities'

    // Fetch entities - backend will filter by data source access and selected agents
    const { data, error } = await useMyFetch(url, { method: 'GET' })
    if (error.value) throw error.value
    allItems.value = data.value as any
    loading.value = false
  } catch {
    allItems.value = []
    loading.value = false
  }
}

function isArchived(entity: EntityList): boolean {
  return entity.status === 'archived' || entity.private_status === 'archived'
}

function getEntityType(entity: EntityList): string {
  if (isArchived(entity)) return 'archived'
  if (entity.private_status && !entity.global_status) return 'private'
  if (entity.private_status && entity.global_status === 'suggested') return 'suggested'
  // Global approved entities - check if they're published or draft
  if (!entity.private_status && entity.global_status === 'approved') {
    if (entity.status === 'published') return 'global'
    if (entity.status === 'draft') return 'draft'  // Admin draft
  }
  return 'unknown'
}

function reload() {
  loadEntities()
}

function navigateToEntity(id: string) {
  router.push(`/queries/${id}`)
}

function timeAgo(iso: string | Date | null | undefined) {
  if (!iso) return '—'
  const d = typeof iso === 'string' ? new Date(iso) : iso
  const diff = Math.max(0, Date.now() - (d?.getTime?.() || 0))
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return t('queries.timeMinutesAgo', { n: mins })
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return t('queries.timeHoursAgo', { n: hrs })
  const days = Math.floor(hrs / 24)
  return t('queries.timeDaysAgo', { n: days })
}

function dataSourceIcon(type?: string) {
  if (!type) return '/public/icons/database.png'
  const key = String(type).toLowerCase()
  return `/data_sources_icons/${key}.png`
}

function formatCount(num?: number): string {
  if (num === undefined || num === null) return '—'
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
  return String(num)
}

function getRowCount(item: EntityList): string {
  return formatCount(item.data?.info?.total_rows)
}

function getColumnCount(item: EntityList): string {
  return formatCount(item.data?.info?.total_columns)
}

function hasStats(item: EntityList): boolean {
  return !!(item.data?.info?.total_rows !== undefined || item.data?.info?.total_columns !== undefined)
}
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


