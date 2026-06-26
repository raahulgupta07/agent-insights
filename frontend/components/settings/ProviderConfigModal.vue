<template>
  <Teleport to="body">
    <div
      v-if="modelValue"
      class="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      @click.self="$emit('close')"
    >
      <div
        class="bg-white rounded-2xl shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col"
        @keydown.esc.window="$emit('close')"
      >
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-4 border-b border-[#E9E0D3] flex-shrink-0">
          <h3 class="text-sm font-semibold text-gray-900">{{ title }}</h3>
          <button
            type="button"
            class="w-7 h-7 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
            @click="$emit('close')"
          >
            <UIcon name="i-heroicons-x-mark" class="w-4 h-4" />
          </button>
        </div>

        <!-- Body (scrollable) -->
        <div class="overflow-y-auto flex-1 px-5 py-4">
          <slot />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
defineProps<{
  modelValue: boolean
  title: string
}>()

defineEmits<{
  (e: 'close'): void
}>()

// Close on Esc key
onMounted(() => {
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      // emit handled via @keydown.esc.window in template — this is belt-and-suspenders
    }
  }
  document.addEventListener('keydown', onKey)
  onUnmounted(() => document.removeEventListener('keydown', onKey))
})
</script>
