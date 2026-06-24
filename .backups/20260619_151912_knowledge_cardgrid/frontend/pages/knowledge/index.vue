<template>
  <!-- Anchored left-rail layout: the title + section nav live in the flush
       full-height rail (KnowledgePanel renders it); content fills the rest. -->
  <KnowledgePanel
    nav-layout="left"
    title="Knowledge"
    subtitle="Ground every answer in what your data means."
  />
</template>

<script setup lang="ts">
definePageMeta({
  auth: true,
  layout: 'default'
})
</script>
