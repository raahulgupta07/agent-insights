<template>
  <NuxtLink
    :to="reportLink"
    class="group block bg-white rounded-2xl border border-[#E7E5DD] overflow-hidden hover:shadow-lg hover:border-[#dcd9cf] hover:-translate-y-1 transition-all duration-200"
  >
    <!-- Thumbnail -->
    <div class="aspect-[4/3] relative overflow-hidden" :class="!thumbnailUrl || imageError ? badgeStyle.cardBg : ''">
      <!-- Actual thumbnail -->
      <img
        v-if="thumbnailUrl && !imageError"
        :src="thumbnailUrl"
        :alt="report.title || 'Report preview'"
        class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-200"
        @error="onImageError"
      />
      <!-- Placeholder when no thumbnail -->
      <div
        v-else
        class="w-full h-full flex items-center justify-center"
      >
        <Icon
          :name="reportIcon"
          class="w-12 h-12"
          :class="badgeStyle.iconColor"
        />
      </div>

      <!-- Edit button - top right -->
      <div
        v-if="isOwner"
        class="absolute top-2 end-2 opacity-0 group-hover:opacity-100 transition-opacity"
        @click.prevent="navigateTo(`/reports/${report.id}`)"
      >
        <div class="p-1.5 bg-white/90 rounded-full hover:bg-white shadow-sm">
          <Icon name="heroicons:pencil-square" class="w-4 h-4 text-gray-600" />
        </div>
      </div>

      <!-- Mode badge - bottom left -->
      <div class="absolute bottom-2 start-2">
        <span
          :class="[
            'px-2 py-0.5 text-xs font-medium rounded-full',
            badgeStyle.bg,
            badgeStyle.text
          ]"
        >
          {{ badgeStyle.label }}
        </span>
      </div>
    </div>

    <!-- Content -->
    <div class="p-3 text-start">
      <h3 class="font-medium text-gray-900 truncate text-sm">
        {{ report.title || 'Untitled' }}
      </h3>
      <p class="text-xs text-gray-400 mt-1 truncate">
        {{ report.user?.name ? `by ${report.user.name}` : '' }}
      </p>

      <!-- Open actions -->
      <div class="flex items-center gap-2 mt-3">
        <button
          type="button"
          class="flex-1 inline-flex items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium border border-[#E7E5DD] bg-white text-[#1f2328] hover:bg-[#F4F1EA] transition-colors cursor-pointer"
          @click.stop.prevent="navigateTo(reportLink)"
        >
          <UIcon name="i-heroicons-chat-bubble-left-right" class="w-3.5 h-3.5" />
          Open in chat
        </button>
        <button
          type="button"
          class="flex-1 inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold bg-[#C2683F] text-white hover:bg-[#A8542F] transition-colors cursor-pointer"
          @click.stop.prevent="navigateTo(reportLink + '?focus=dashboard')"
        >
          <UIcon name="i-heroicons-squares-2x2" class="w-3.5 h-3.5" />
          Open as dashboard
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

const badgeStyle = computed(() => {
  if (hasSlides.value) {
    return { bg: 'bg-[#eef6f0]', text: 'text-[#3f9e6a]', label: 'Slides', cardBg: 'bg-[#F4F1EA]', iconColor: 'text-[#3f9e6a]/40' }
  }
  if (hasDashboard.value) {
    return { bg: 'bg-[#F3E7DF]', text: 'text-[#C2683F]', label: 'Dashboard', cardBg: 'bg-[#F4F1EA]', iconColor: 'text-[#C2683F]/40' }
  }
  return { bg: 'bg-[#F4F1EA]', text: 'text-[#6b6b6b]', label: 'Chat', cardBg: 'bg-[#F4F1EA]', iconColor: 'text-[#9a958c]' }
})
</script>
