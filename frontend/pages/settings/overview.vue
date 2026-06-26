<script setup lang="ts">
definePageMeta({
    layout: 'settings',
    permissions: ['manage_settings'],
})
</script>

<template>
    <div>
        <div class="flex items-start justify-between gap-4 mb-6">
            <div>
                <h1
                    class="text-2xl font-semibold tracking-tight text-[#1f2328]"
                    style="font-family: 'Spectral', ui-serif, Georgia, serif"
                >Console Overview</h1>
            </div>
        </div>
        <ConsoleOverview />
    </div>
</template>