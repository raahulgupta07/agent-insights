<template>
  <div class="flex justify-center px-4 md:px-6 text-sm bg-[#F6F1EA] min-h-full">
    <div class="w-full max-w-3xl py-2">
      <!-- Header -->
      <div class="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1
            class="text-2xl font-semibold tracking-tight text-[#1f2328]"
            style="font-family: 'Spectral', ui-serif, Georgia, serif"
          >What's new</h1>
          <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">
            Releases and improvements to CityAgent Analytics.
          </p>
        </div>
        <span
          v-if="current"
          class="flex-none inline-flex items-center gap-1.5 text-[11px] font-mono text-[#1f2328] bg-white border border-[#E9E0D3] rounded-lg px-2.5 py-1.5"
        >
          v{{ current }}
          <span class="text-[#cfcabf]">·</span>
          <span class="w-[7px] h-[7px] rounded-full" style="background:#2f9e6f" />
          <span class="text-[#2f9e6f] font-medium">Up to date</span>
        </span>
      </div>

      <!-- Loading -->
      <div
        v-if="loading"
        class="rounded-lg border border-[#E9E0D3] bg-white px-6 py-10 text-center text-sm text-[#6b6b6b]"
      >Loading…</div>

      <!-- Entries -->
      <div v-else-if="entries.length" class="space-y-3">
        <div
          v-for="(e, i) in entries"
          :key="e.version + '-' + i"
          class="rounded-2xl border border-[#f0ddd0] bg-[#FBF4EF] p-4"
        >
          <div class="flex items-start justify-between gap-3 mb-2">
            <div>
              <div class="text-[11px] font-mono text-[#C2541E]">v{{ e.version }}</div>
              <h2
                class="text-[15px] font-semibold text-[#1f2328]"
                style="font-family: 'Spectral', ui-serif, Georgia, serif"
              >{{ e.title }}</h2>
            </div>
            <span class="flex-none text-xs text-[#9a958c] pt-1">{{ e.date }}</span>
          </div>
          <ul v-if="e.features && e.features.length" class="space-y-1.5">
            <li
              v-for="(f, fi) in e.features"
              :key="fi"
              class="flex items-start gap-2 text-[13px] text-[#444] leading-snug"
            >
              <span class="mt-1.5 w-1 h-1 rounded-full flex-none" style="background:#C2541E" />
              <span>{{ f }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- Empty -->
      <div
        v-else
        class="rounded-lg border border-[#E9E0D3] bg-white px-6 py-12 text-center text-sm text-[#9a958c]"
      >No changelog entries yet.</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'

const current = ref<string>('')
const entries = ref<any[]>([])
const loading = ref(true)

async function loadChangelog() {
  loading.value = true
  try {
    const { data, error } = await useMyFetch<any>('/changelog', { method: 'GET' })
    if (error.value) throw error.value
    const d = data.value || {}
    current.value = d.current || ''
    entries.value = Array.isArray(d.entries) ? d.entries : []
  } catch {
    current.value = ''
    entries.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadChangelog)
</script>
