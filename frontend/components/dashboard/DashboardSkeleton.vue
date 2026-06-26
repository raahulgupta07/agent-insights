<template>
  <div class="h-full w-full overflow-y-auto bg-[#F6F1EA] p-5">
    <!-- Generating header line -->
    <div class="flex items-center gap-2 mb-4 text-[11px] font-medium text-[#A8330F]">
      <span class="sk-dot inline-block w-3.5 h-3.5 rounded-full" />
      <span>{{ mode === 'slides' ? 'Generating slides…' : 'Generating dashboard…' }}</span>
      <span class="text-[#9a958c]">building {{ widgetCount }} {{ mode === 'slides' ? 'slides' : 'widgets' }}</span>
    </div>

    <!-- SLIDES mode: a couple of big slide blocks -->
    <template v-if="mode === 'slides'">
      <div class="flex flex-col gap-4">
        <div
          v-for="n in 2"
          :key="'slide-' + n"
          class="rounded-2xl border border-[#E9E0D3] bg-white p-5 shadow-sm"
        >
          <div class="sk-bar h-4 w-1/3 rounded-md" />
          <div class="sk h-56 mt-4 rounded-xl" />
          <div class="sk-bar h-3 w-1/4 rounded-md mt-3" />
        </div>
      </div>
    </template>

    <!-- PAGE mode: KPI row + 2-col widget grid -->
    <template v-else>
      <!-- KPI row (4 small cards) -->
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <div
          v-for="n in 4"
          :key="'kpi-' + n"
          class="rounded-xl border border-[#E9E0D3] bg-white p-3"
        >
          <div class="sk-bar h-2.5 rounded" :style="{ width: 50 + (n % 3) * 8 + '%' }" />
          <div class="sk-bar h-4 mt-2 rounded" :style="{ width: 60 + (n % 2) * 15 + '%' }" />
        </div>
      </div>

      <!-- Widget grid (2-col) -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div
          v-for="n in 4"
          :key="'wid-' + n"
          class="rounded-2xl border border-[#E9E0D3] bg-white p-4 shadow-sm"
        >
          <!-- header bar -->
          <div class="sk-bar h-3 rounded-md" :style="{ width: 45 + (n % 2) * 10 + '%' }" />
          <!-- chart block -->
          <div class="sk mt-3 rounded-xl" :class="n % 2 === 0 ? 'h-40' : 'h-72'" />
          <!-- footer bar -->
          <div class="sk-bar h-2.5 w-1/3 rounded mt-3" />
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  mode?: 'page' | 'slides';
  widgetCount?: number;
}>(), {
  mode: 'page',
  widgetCount: 6,
});
</script>

<style scoped>
/* Warm clay-neutral shimmer (no blue) — mirrors mockup-fixes.html "Dashboard loader". */
.sk,
.sk-bar,
.sk-dot {
  background: linear-gradient(90deg, #ecebe6 25%, #f4f3ee 37%, #ecebe6 63%);
  background-size: 400% 100%;
  animation: dash-shimmer 1.4s ease infinite;
}
@keyframes dash-shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}
</style>
