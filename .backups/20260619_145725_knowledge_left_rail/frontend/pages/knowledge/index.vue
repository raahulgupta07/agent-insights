<template>
  <div class="py-6">
    <div class="max-w-4xl mx-auto px-4">
      <div class="mb-6">
        <h1 class="text-lg font-semibold text-gray-900">Knowledge</h1>
        <p class="mt-1 text-sm text-gray-500">Ground every answer in what your data means.</p>
      </div>

      <!-- Picker mode: no pinned data source, full behavior incl. Review -->
      <KnowledgePanel />
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({
  auth: true,
  layout: 'default'
})
</script>
