<template>
  <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
    <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto">

      <!-- header: title + subtitle + readiness ring -->
      <div class="flex items-start justify-between gap-4 mb-1">
        <div>
          <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Agent Templates</h2>
          <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[480px]">
            Reusable agent know-how — rules, metric formulas &amp; example patterns. Bind one to your
            columns; <span class="text-[#2F6F4F] font-semibold">your data never leaves.</span>
          </p>
        </div>
        <div class="shrink-0 text-center">
          <div class="relative w-[54px] h-[54px] mx-auto">
            <svg width="54" height="54" style="transform:rotate(-90deg)">
              <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
              <circle cx="27" cy="27" r="22" stroke="#A8330F" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" :stroke-dashoffset="Math.round(138 - 138 * Math.min(templates.length, 6) / 6)" style="transition:stroke-dashoffset .5s" />
            </svg>
            <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#A8330F]" style="font-family: ui-serif, Georgia, serif">{{ templates.length }}</div>
          </div>
          <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">templates</div>
        </div>
      </div>

      <!-- toolbar: search + scope segmented + new template -->
      <div class="flex flex-wrap items-center gap-3 mt-4 mb-4">
        <!-- search (client filter) -->
        <div class="relative flex-1 min-w-[200px] max-w-[420px]">
          <UIcon
            name="i-heroicons-magnifying-glass"
            class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A89C8C]"
          />
          <input
            v-model="search"
            type="text"
            placeholder="Search templates…"
            class="w-full pl-9 pr-3 py-2 text-[13px] rounded-xl border border-[#E9E0D3] bg-white text-[#1f2328] placeholder:text-[#A89C8C] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]/30 transition-colors"
          />
        </div>

        <!-- scope segmented -->
        <div class="inline-flex items-center gap-1 bg-[#F1ECE3] border border-[#E9E0D3] rounded-xl p-1">
          <button
            v-for="opt in scopes"
            :key="opt.value"
            type="button"
            class="px-3.5 py-1.5 text-[12.5px] font-semibold rounded-lg transition-colors cursor-pointer"
            :class="scope === opt.value
              ? 'bg-[#A8330F] text-white'
              : 'text-[#7A7062] hover:bg-white/70'"
            @click="setScope(opt.value)"
          >{{ opt.label }}</button>
        </div>

        <!-- primary: new template (publish from a studio) -->
        <NuxtLink
          to="/studios"
          class="ms-auto inline-flex items-center gap-1.5 px-3.5 py-2 text-[13px] font-semibold rounded-xl bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors cursor-pointer"
        >
          <UIcon name="i-heroicons-plus" class="w-4 h-4" />
          New template
        </NuxtLink>
      </div>

      <!-- band-pill section -->
      <div class="relative border border-[#E9E0D3] rounded-2xl bg-white p-4">
        <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">YOUR TEMPLATES</span>

        <!-- loading skeletons -->
        <div v-if="loading" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mt-1">
          <div
            v-for="n in 6"
            :key="n"
            class="animate-pulse rounded-xl border border-[#E9E0D3] bg-white p-4"
          >
            <div class="h-12 bg-[#F4EEE5] rounded-xl mb-3" />
            <div class="h-3 w-1/2 bg-[#F4EEE5] rounded mb-2" />
            <div class="h-3 w-1/3 bg-[#F4EEE5] rounded mb-4" />
            <div class="h-8 bg-[#F4EEE5] rounded-xl" />
          </div>
        </div>

        <!-- grid -->
        <div
          v-else-if="filteredTemplates.length"
          class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mt-1"
        >
          <div
            v-for="t in filteredTemplates"
            :key="t.id"
            class="group flex flex-col rounded-xl border border-[#E9E0D3] bg-gradient-to-b from-white to-[#fdfcf9] overflow-hidden hover:border-[#E4D4C2] hover:shadow-[0_14px_34px_-22px_rgba(60,40,20,.34)] transition-all cursor-pointer"
            @click="openDetail(t.id)"
          >
            <!-- tinted header strip -->
            <div class="h-20 bg-[#F6EBE3] flex items-center justify-center text-[#A8330F]">
              <UIcon name="i-heroicons-square-3-stack-3d" class="w-7 h-7" />
            </div>

            <!-- body -->
            <div class="flex flex-col flex-1 p-3">
              <h3 class="text-[13px] font-semibold text-[#1f2328] leading-snug truncate" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ t.name }}</h3>
              <p class="text-[10.5px] text-[#9a958c] mt-0.5">
                v{{ t.version || '1.0.0' }} · {{ t.scope || 'org' }} · by {{ t.author || t.owner || 'Unknown' }}
              </p>

              <!-- badges -->
              <div class="flex flex-wrap items-center gap-1.5 mt-2">
                <span
                  class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold"
                  :class="(t.status === 'published')
                    ? 'bg-[#E7F1EB] text-[#2F6F4F]'
                    : 'bg-[#F1ECE3] text-[#6b6b6b]'"
                >{{ t.status || 'draft' }}</span>
                <span class="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-[#F6EEDD] text-[#9A6A12]">
                  ★ {{ t.stars ?? t.uses ?? 0 }}
                </span>
              </div>

              <!-- actions (equal-width) -->
              <div class="grid grid-cols-2 gap-2 mt-auto pt-3">
                <button
                  type="button"
                  class="inline-flex items-center justify-center px-3 py-1.5 text-[12px] font-semibold rounded-lg border border-[#E9E0D3] bg-white text-[#1f2328] hover:border-[#C9BEAF] transition-colors cursor-pointer whitespace-nowrap"
                  @click.stop="openDetail(t.id)"
                >Preview</button>
                <button
                  type="button"
                  class="inline-flex items-center justify-center px-3 py-1.5 text-[12px] font-semibold rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors cursor-pointer whitespace-nowrap"
                  @click.stop="openWizard(t)"
                >Use template</button>
              </div>
            </div>
          </div>

          <!-- new-template dashed ADD card -->
          <NuxtLink
            to="/studios"
            class="flex flex-col items-center justify-center text-center rounded-xl border border-dashed border-[#d8cfc0] bg-gradient-to-b from-white to-[#fdfcf9] p-4 hover:border-[#C2541E] transition-colors cursor-pointer min-h-[180px]"
          >
            <span class="w-10 h-10 rounded-lg bg-[#F6EBE3] flex items-center justify-center mb-2">
              <UIcon name="i-heroicons-plus" class="w-5 h-5 text-[#C2541E]" />
            </span>
            <div class="text-[13px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">New template</div>
            <div class="text-[11px] text-[#9a958c] mt-0.5">Export an agent's best practices</div>
          </NuxtLink>
        </div>

        <!-- empty -->
        <div
          v-else
          class="text-center py-12 px-6 mt-1"
        >
          <div class="w-[60px] h-[60px] rounded-2xl bg-[#F6EBE3] mx-auto flex items-center justify-center mb-4">
            <UIcon name="i-heroicons-square-3-stack-3d" class="w-7 h-7 text-[#A8330F]" />
          </div>
          <p class="text-[20px] font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
            No templates {{ search ? 'match your search' : 'yet' }}
          </p>
          <p class="text-[13px] text-[#8A7F70] mt-2">
            Export an agent's know-how from a Studio to share it here.
          </p>
        </div>
      </div>

    </div>

    <!-- Use-template popup journey -->
    <BindWizard v-model="wizardOpen" :template-id="wizardTemplateId" :template-name="wizardName" />
  </div>
</template>

<script setup lang="ts">
import { useMyFetch } from '~/composables/useMyFetch'
import BindWizard from '~/components/templates/BindWizard.vue'

const scopes = [
  { value: 'org', label: 'Org' },
  { value: 'global', label: 'Global' },
  { value: 'all', label: 'All' },
]

const scope = ref<string>('all')
const q = ref<string>('')
const search = ref<string>('')
const templates = ref<any[]>([])
const loading = ref(true)

// Client-side instant filter over already-fetched templates.
const filteredTemplates = computed(() => {
  const s = search.value.trim().toLowerCase()
  if (!s) return templates.value
  return templates.value.filter((t: any) =>
    [t.name, t.slug, t.description, t.author, t.owner]
      .filter(Boolean)
      .some((v: any) => String(v).toLowerCase().includes(s))
  )
})

let searchTimer: any = null
function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadTemplates, 300)
}

function setScope(v: string) {
  if (scope.value === v) return
  scope.value = v
  loadTemplates()
}

function openDetail(id: string) {
  navigateTo(`/templates/${id}`)
}

// Use-template popup
const wizardOpen = ref(false)
const wizardTemplateId = ref('')
const wizardName = ref('')
function openWizard(t: any) {
  wizardTemplateId.value = t.id
  wizardName.value = t.name || ''
  wizardOpen.value = true
}

async function loadTemplates() {
  loading.value = true
  try {
    const params = new URLSearchParams()
    params.set('scope', scope.value)
    if (q.value.trim()) params.set('q', q.value.trim())
    const { data, error } = await useMyFetch<any>(`/templates?${params.toString()}`, { method: 'GET' })
    if (error.value) throw error.value
    const d = data.value || {}
    templates.value = Array.isArray(d.templates) ? d.templates : []
  } catch {
    templates.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadTemplates)
</script>
