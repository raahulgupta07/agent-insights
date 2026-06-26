<template>
    <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
        <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 min-h-0 flex flex-col overflow-hidden">
            <ConsoleInstructions show-header fill class="flex-1 min-h-0" />
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
