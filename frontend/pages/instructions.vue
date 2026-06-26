<template>
    <div class="flex justify-center px-4 md:px-6 text-sm bg-[#F6F1EA] min-h-full">
        <div class="w-full max-w-7xl py-2 h-full">
            <ConsoleInstructions show-header />
        </div>
    </div>
</template>

<script setup lang="ts">
import ConsoleInstructions from '~/components/ConsoleInstructions.vue'

definePageMeta({
    auth: true,
    layout: 'default'
})
</script>
