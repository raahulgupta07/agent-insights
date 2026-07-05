<template>
  <!-- Agent hover flyout (teleported so it never gets clipped by popovers).
       Thin wrapper: header chrome + positioning; the tabbed body is the shared
       <AgentDetail>. -->
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
        v-if="visible && agentId"
        class="fixed z-[2000]"
        :style="positionStyle"
        @mouseenter="$emit('mouseenter')"
        @mouseleave="$emit('mouseleave')"
      >
        <div
          class="w-max min-w-[400px] max-w-[min(520px,calc(100vw-24px))] bg-white rounded-xl shadow-2xl border border-gray-200 overflow-hidden flex flex-col"
          :style="panelStyle"
        >
          <!-- Header with connection info -->
          <div class="px-4 py-3 border-b border-gray-100 flex-shrink-0">
            <!-- Title row -->
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2 min-w-0 flex-1">
                <!-- Status dot — far left -->
                <span
                  v-if="hasActiveConnection"
                  class="w-2 h-2 rounded-full bg-green-500 flex-shrink-0"
                  :title="$t('agentFlyout.connected')"
                ></span>
                <span
                  v-else-if="agentDetails?.connections?.length"
                  class="w-2 h-2 rounded-full bg-gray-300 flex-shrink-0"
                  :title="$t('agentFlyout.notConnected')"
                ></span>
                <span v-else class="w-2 h-2 rounded-full bg-gray-200 flex-shrink-0"></span>

                <!-- Connection icons -->
                <div v-if="agentDetails?.connections?.length" class="flex -space-x-1 flex-shrink-0">
                  <DataSourceIcon
                    v-for="conn in (agentDetails.connections || []).slice(0, 3)"
                    :key="conn.id"
                    :type="conn.type"
                    class="h-4 flex-shrink-0 ring-1 ring-white rounded"
                  />
                </div>

                <!-- Title -->
                <div class="text-sm font-semibold text-gray-900 truncate">
                  {{ agentDetails?.name || $t('agentFlyout.loading') }}
                </div>
              </div>

              <!-- Open agent link - top right -->
              <NuxtLink
                v-if="agentId"
                :to="`/agents/${agentId}`"
                class="text-xs font-medium text-indigo-600 hover:text-indigo-700 hover:underline flex-shrink-0 whitespace-nowrap"
              >
                {{ $t('agentFlyout.openAgent') }}
              </NuxtLink>
            </div>

            <!-- Description — full width below -->
            <div v-if="agentDetails?.description" class="text-xs text-gray-500 mt-1.5 leading-snug line-clamp-2">
              {{ agentDetails.description }}
            </div>
          </div>

          <!-- Shared tabbed body (Overview / Tables / Instructions / Queries) -->
          <AgentDetail
            ref="detailRef"
            :agent-id="agentId"
            @loaded="agentDetails = $event"
            @connect="emit('connect', $event)"
          />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import DataSourceIcon from '~/components/DataSourceIcon.vue'
import AgentDetail from '~/components/AgentDetail.vue'

const props = defineProps<{
  agentId: string | null
  visible: boolean
  position: { top?: number; bottom?: number; left: number; maxHeight?: number }
}>()

const emit = defineEmits<{
  mouseenter: []
  mouseleave: []
  // Emitted with the fetched agent details when the user clicks Connect. The
  // parent owns the credentials modal / OAuth flow.
  connect: [agent: any]
}>()

// Agent details come from the child <AgentDetail> via its `loaded` event so the
// header can show name / connection dots without a second fetch.
const agentDetails = ref<any>(null)
const detailRef = ref<any>(null)

// Compute position style - prefer bottom if provided (grows upward)
const positionStyle = computed(() => {
  const style: Record<string, string> = {
    left: `${props.position.left}px`
  }
  if (props.position.bottom !== undefined) {
    style.bottom = `${props.position.bottom}px`
  } else if (props.position.top !== undefined) {
    style.top = `${props.position.top}px`
  }
  return style
})

// Cap the panel to the space available above its anchor so it never grows off
// the top of the viewport — the content area scrolls internally instead.
const panelStyle = computed(() => {
  const h = props.position.maxHeight
  return h ? { maxHeight: `${h}px` } : {}
})

const hasActiveConnection = computed(() => {
  const connections = agentDetails.value?.connections || []
  return connections.some((conn: any) => conn?.user_status?.connection === 'success')
})

// Allow the parent to clear cached details after a successful connect.
function refreshDetails() {
  detailRef.value?.refreshDetails?.()
}
defineExpose({ refreshDetails })
</script>
