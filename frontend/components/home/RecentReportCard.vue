<template>
  <NuxtLink
    :to="reportLink"
    class="rrc group block bg-white rounded-2xl border border-[#E9E0D3] overflow-hidden"
  >
    <!-- Thumbnail -->
    <div class="relative h-32 overflow-hidden" :class="(!thumbnailUrl || imageError) ? (isDark ? 'rrc-dark-empty' : 'rrc-chat') : ''">
      <!-- REAL preview from the actual dashboard/report -->
      <img
        v-if="thumbnailUrl && !imageError"
        :src="thumbnailUrl"
        :alt="report.title || 'Report preview'"
        class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
        @error="onImageError"
      />
      <!-- No preview yet: mode icon placeholder (no fake numbers) -->
      <div v-else class="w-full h-full flex items-center justify-center">
        <Icon :name="reportIcon" class="w-12 h-12" :class="isDark ? 'text-[#9A8F80]/50' : 'text-[#C2A07E]'" />
      </div>

      <!-- Edit button - top right -->
      <div
        v-if="isOwner"
        class="absolute top-2 end-2 opacity-0 group-hover:opacity-100 transition-opacity z-10"
        @click.prevent="navigateTo(`/reports/${report.id}`)"
      >
        <div class="p-1.5 bg-white/90 rounded-full hover:bg-white shadow-sm">
          <Icon name="heroicons:pencil-square" class="w-4 h-4 text-gray-600" />
        </div>
      </div>

      <!-- Mode badge - bottom left -->
      <span class="rrc-badge" :class="badgeStyle.cls">{{ badgeStyle.label }}</span>
    </div>

    <!-- Content -->
    <div class="p-[14px] text-start">
      <h3 class="rrc-title">{{ report.title || 'Untitled' }}</h3>
      <p class="rrc-by">{{ report.user?.name ? `by ${report.user.name}` : '' }}</p>

      <!-- Open actions -->
      <div class="flex items-center gap-2 mt-3">
        <button
          type="button"
          class="rrc-ghost"
          @click.stop.prevent="navigateTo(reportLink)"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.5 8.4 8.4 0 0 1-4.2-1.1L3 20l1.1-5.3A8.5 8.5 0 1 1 21 11z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          Chat
        </button>
        <button
          type="button"
          class="rrc-prim"
          @click.stop.prevent="navigateTo(reportLink + '?focus=dashboard')"
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="8" height="8" rx="1.5" stroke="#fff" stroke-width="2"/><rect x="13" y="3" width="8" height="8" rx="1.5" stroke="#fff" stroke-width="2"/><rect x="3" y="13" width="8" height="8" rx="1.5" stroke="#fff" stroke-width="2"/><rect x="13" y="13" width="8" height="8" rx="1.5" stroke="#fff" stroke-width="2"/></svg>
          Dashboard
        </button>
      </div>
    </div>
  </NuxtLink>
</template>

<script setup lang="ts">
interface Report {
  id: string
  title?: string
  slug: string
  status: string
  user: { id: string; name?: string; email?: string }
  artifact_modes: string[]
  conversation_share_enabled: boolean
  conversation_share_token?: string
  artifact_visibility?: string
  conversation_visibility?: string
  thumbnail_url?: string
}

const props = defineProps<{
  report: Report
  viewMode: 'org' | 'my'
  isOwner?: boolean
}>()

const config = useRuntimeConfig()
const imageError = ref(false)

const hasArtifact = computed(() => props.report.artifact_modes?.length > 0)
const hasSlides = computed(() => props.report.artifact_modes?.includes('slides'))
const hasDashboard = computed(() => props.report.artifact_modes?.includes('page'))

const thumbnailUrl = computed(() => {
  if (!props.report.thumbnail_url) return null
  return `${config.public.baseURL}${props.report.thumbnail_url}`
})

const onImageError = () => {
  imageError.value = true
}

const reportLink = computed(() => {
  if (props.viewMode === 'my') {
    return `/reports/${props.report.id}`
  }
  // Org view: published reports
  if (hasArtifact.value) {
    return `/r/${props.report.id}`
  }
  if (props.report.conversation_share_enabled && props.report.conversation_share_token) {
    return `/c/${props.report.conversation_share_token}`
  }
  return `/r/${props.report.id}`
})

const reportIcon = computed(() => {
  if (hasSlides.value) return 'heroicons:presentation-chart-bar'
  if (hasDashboard.value) return 'heroicons:chart-bar-square'
  return 'heroicons:chat-bubble-left-right'
})

// Dark KPI mock for dashboards/slides; light cream mock for chat.
const isDark = computed(() => hasDashboard.value || hasSlides.value)

const badgeStyle = computed(() => {
  if (hasSlides.value) return { label: 'Slides', cls: 'rrc-badge-slides' }
  if (hasDashboard.value) return { label: 'Dashboard', cls: 'rrc-badge-dash' }
  return { label: 'Chat', cls: 'rrc-badge-chat' }
})
</script>

<style scoped>
.rrc {
  box-shadow: 0 8px 22px -16px rgba(60, 40, 20, .25);
  transition: transform .2s, box-shadow .2s;
  font-family: 'Hanken Grotesk', system-ui, sans-serif;
}
.rrc:hover { transform: translateY(-3px); box-shadow: 0 20px 44px -22px rgba(60, 40, 20, .32); }

/* empty-state bg when a dashboard/slides report has no preview yet */
.rrc-dark-empty { background: radial-gradient(120% 100% at 70% 0%, #2A1F18, #120D0A); }

/* light chat thumbnail */
.rrc-chat {
  height: 100%; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #F4EEE5, #EDE4D6);
}

/* badge */
.rrc-badge {
  position: absolute; left: 12px; bottom: 10px;
  font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 6px;
}
.rrc-badge-dash { background: #F4E0D2; color: #A8330F; }
.rrc-badge-slides { background: #E4F3EA; color: #3F9E6A; }
.rrc-badge-chat { background: #FFFFFF; color: #8A7F70; }

/* body */
.rrc-title {
  font-size: 14.5px; font-weight: 600; line-height: 1.3; color: #2A241D;
  margin-bottom: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.rrc-by { font-size: 12px; color: #9A8F80; margin-bottom: 12px; }

.rrc-ghost, .rrc-prim {
  flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px;
  border-radius: 9px; padding: 8px; cursor: pointer;
  font-size: 12.5px; font-weight: 600; transition: .15s; font-family: inherit;
}
.rrc-ghost { border: 1px solid #E4D9CA; background: #FCFAF6; color: #574E44; }
.rrc-ghost:hover { border-color: #C9BEAF; background: #FFFFFF; }
.rrc-prim { border: none; background: #C2541E; color: #fff; }
.rrc-prim:hover { background: #A8330F; }
</style>
