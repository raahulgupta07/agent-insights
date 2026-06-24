<template>
    <div class="flex justify-center ps-2 md:ps-4 text-sm bg-[#FBFAF6] min-h-full">
        <div class="w-full max-w-7xl px-4 ps-0 py-2">
            <div>
                <h1
                    class="text-2xl font-semibold text-[#1f2328] tracking-tight flex items-center"
                    style="font-family: ui-serif, Georgia, 'Times New Roman', serif"
                >
                    {{ $t('nav.presentations') }}
                </h1>
                <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">
                    Decks built from your reports — open a report and use the Slides tab to create one.
                </p>
            </div>

            <div class="mt-6">
                <!-- Card grid (empty state for v1 — no presentations backend yet) -->
                <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6">
                    <div
                        class="col-span-2 md:col-span-4 lg:col-span-5 bg-white border border-[#E7E5DD] rounded-2xl"
                    >
                        <div class="py-12 flex flex-col items-center text-center">
                            <div class="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-[#F4F1EA] border border-[#E7E5DD]">
                                <Icon
                                    name="heroicons:presentation-chart-line"
                                    class="h-6 w-6 text-[#C2683F]"
                                />
                            </div>
                            <h3
                                class="mt-3 text-base font-semibold text-[#1f2328]"
                                style="font-family: ui-serif, Georgia, 'Times New Roman', serif"
                            >
                                No presentations yet
                            </h3>
                            <p class="mt-1 text-sm text-[#6b6b6b] max-w-md">
                                Open any report → Slides tab → Export .pptx. Saved decks will appear here.
                            </p>
                            <button
                                class="mt-4 inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-[#C2683F] text-white hover:bg-[#A8542F] transition-colors"
                                @click="navigateTo('/reports')"
                            >
                                Browse reports
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
definePageMeta({ auth: true })
</script>
