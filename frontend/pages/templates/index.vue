<template>
  <div class="wk-page min-h-full bg-[#F6F1EA] text-[#1A1611]">
    <div class="w-full max-w-[1500px] px-6 sm:px-10 py-8 pb-24">
      <!-- Header -->
      <div class="flex items-start justify-between gap-6 mb-6">
        <div class="max-w-[620px]">
          <h1 class="wk-h1">Templates</h1>
          <p class="mt-2 text-[15px] leading-relaxed text-[#6E6356]">
            Reusable agent know-how — rules, metric formulas and example patterns. Bind one to
            your own columns and get your own agent.
            <span class="text-[#3E7A4D] font-semibold">Your data never leaves.</span>
          </p>
        </div>
        <NuxtLink
          to="/studios"
          class="wk-ghost flex-none inline-flex items-center gap-2 px-4 py-2.5 text-[14px] font-semibold rounded-[11px] border border-[#E4C9B6] bg-[#FCFAF6] text-[#A8330F] transition-colors cursor-pointer"
        >
          <UIcon name="i-heroicons-plus" class="w-4 h-4" />
          Publish
        </NuxtLink>
      </div>

      <!-- Controls: scope toggle + search -->
      <div class="flex flex-wrap items-center justify-between gap-4 mb-6">
        <!-- Scope toggle -->
        <div class="inline-flex items-center gap-1 bg-[#EFE7DA] rounded-[11px] p-1">
          <button
            v-for="opt in scopes"
            :key="opt.value"
            type="button"
            class="px-4 py-1.5 text-[13.5px] font-semibold rounded-lg transition-colors cursor-pointer"
            :class="scope === opt.value
              ? 'bg-[#C2541E] text-white'
              : 'text-[#7A7062] hover:bg-white/60'"
            @click="setScope(opt.value)"
          >{{ opt.label }}</button>
        </div>

        <!-- Search -->
        <div class="relative w-full sm:w-[320px]">
          <UIcon
            name="i-heroicons-magnifying-glass"
            class="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A89C8C]"
          />
          <input
            v-model="q"
            type="text"
            placeholder="Search templates…"
            class="w-full pl-10 pr-3 py-2.5 text-[14px] rounded-[11px] border border-[#E4D9CA] bg-white text-[#1A1611] placeholder:text-[#A89C8C] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]/40 transition-colors"
            @input="onSearch"
          />
        </div>
      </div>

      <!-- Loading skeletons -->
      <div v-if="loading" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="n in 6"
          :key="n"
          class="animate-pulse rounded-2xl border border-[#E9E0D3] bg-white p-5"
        >
          <div class="h-11 w-11 bg-[#F4EEE5] rounded-xl mb-4" />
          <div class="h-3 w-1/2 bg-[#F4EEE5] rounded mb-3" />
          <div class="h-12 bg-[#F4EEE5] rounded" />
        </div>
      </div>

      <!-- Grid -->
      <div
        v-else-if="templates.length"
        class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
      >
        <div
          v-for="t in templates"
          :key="t.id"
          class="wk-card flex flex-col rounded-2xl border border-[#E9E0D3] bg-white p-5 cursor-pointer"
          @click="openDetail(t.id)"
        >
          <!-- Icon tile + version -->
          <div class="flex items-start justify-between gap-2 mb-5">
            <div class="w-[46px] h-[46px] rounded-[13px] flex items-center justify-center flex-none"
                 style="background: linear-gradient(150deg,#FBEADF,#F4D8C6)">
              <UIcon name="i-heroicons-square-3-stack-3d" class="w-[22px] h-[22px] text-[#A8330F]" />
            </div>
            <span
              v-if="t.version"
              class="font-mono text-[11.5px] text-[#8A7F70] bg-[#F4EEE5] rounded-[7px] px-2 py-0.5"
            >v{{ t.version }}</span>
          </div>

          <!-- Name + description -->
          <h3 class="wk-card-title">{{ t.name }}</h3>
          <p class="text-[13.5px] text-[#8A7F70] leading-snug line-clamp-2 mb-4 min-h-[34px]">
            {{ t.description || 'No description.' }}
          </p>

          <!-- Domain tags -->
          <div v-if="t.domain_tags && t.domain_tags.length" class="flex flex-wrap gap-1.5 mb-4">
            <span
              v-for="tag in t.domain_tags.slice(0, 4)"
              :key="tag"
              class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#F4EEE5] text-[#8A7F70]"
            >{{ tag }}</span>
          </div>

          <!-- Footer: author + uses + CTA -->
          <div class="mt-auto pt-3.5 border-t border-[#ECE2D3] flex items-center justify-between gap-2">
            <div class="flex items-center gap-1.5 min-w-0 text-[13px] text-[#9A8F80]">
              <span class="truncate">{{ t.author || 'Unknown' }}</span>
              <span class="text-[#D9C8B6]">·</span>
              <span class="inline-flex items-center gap-0.5 flex-none">
                <span class="text-[#C2854F]">★</span>{{ t.uses ?? 0 }}
              </span>
            </div>
            <button
              type="button"
              class="wk-prim flex-none inline-flex items-center gap-1.5 px-4 py-2 text-[13.5px] font-semibold rounded-[10px] bg-[#C2541E] text-white transition-colors cursor-pointer"
              @click.stop="openWizard(t)"
            >Use template</button>
          </div>
        </div>
      </div>

      <!-- Empty -->
      <div
        v-else
        class="text-center py-16 px-6 bg-white border border-[#E9E0D3] rounded-2xl"
      >
        <div class="w-[60px] h-[60px] rounded-2xl bg-[#FBEFE4] mx-auto flex items-center justify-center mb-4">
          <UIcon name="i-heroicons-square-3-stack-3d" class="w-7 h-7 text-[#C2854F]" />
        </div>
        <p class="wk-card-title text-[20px]">
          No templates {{ q ? 'match your search' : 'yet' }}
        </p>
        <p class="text-[14px] text-[#8A7F70] mt-2">
          Export an agent's know-how from a Studio to share it here.
        </p>
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
const templates = ref<any[]>([])
const loading = ref(true)

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

<style scoped>
.wk-page { font-family: 'Hanken Grotesk', system-ui, sans-serif; }
.wk-h1 {
  font-family: 'Spectral', Georgia, serif;
  font-weight: 500;
  font-size: 33px;
  letter-spacing: -.015em;
  color: #211B14;
  margin: 0;
}
.wk-card-title {
  font-family: 'Spectral', Georgia, serif;
  font-weight: 600;
  font-size: 18px;
  color: #211B14;
  margin: 0 0 2px;
}
.wk-card { transition: transform .2s, box-shadow .2s, border-color .2s; box-shadow: 0 10px 26px -18px rgba(60,40,20,.26); }
.wk-card:hover { transform: translateY(-3px); box-shadow: 0 22px 46px -24px rgba(60,40,20,.36); border-color: #E4D4C2; }
.wk-prim:hover { background: #A8330F !important; }
.wk-ghost:hover { border-color: #C9BEAF !important; background: #FFFFFF !important; }
</style>
