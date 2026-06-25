<template>
  <div class="flex-1 flex flex-col min-h-0 bg-white">
    <!-- Toolbar -->
    <div class="h-11 px-3 flex items-center gap-2 border-b border-gray-100 shrink-0">
      <span class="text-xs text-gray-400">Deck:</span>
      <span class="text-sm font-medium text-gray-800 truncate">{{ safeTitle }}</span>
      <div class="ml-auto flex items-center gap-1.5">
        <span class="text-xs text-gray-500">Theme:</span>
        <button
          v-for="t in themeOptions"
          :key="t.key"
          class="px-2 py-1 rounded-md text-xs border transition-colors"
          :class="theme === t.key
            ? 'border-[#C2683F] text-[#C2683F]'
            : 'border-gray-200 text-gray-500 hover:text-gray-700'"
          @click="theme = t.key"
        >
          {{ t.label }}
        </button>
        <button
          class="ml-2 px-2.5 py-1.5 rounded-md bg-[#C2683F] hover:bg-[#A8542F] text-white text-xs flex items-center gap-1 transition-colors disabled:opacity-50"
          :disabled="!slides.length || exporting"
          @click="exportPptx"
        >
          <Icon name="heroicons:arrow-down-tray" class="w-3.5 h-3.5" />
          {{ exporting ? 'Exporting…' : 'Export .pptx' }}
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="!visualizationList.length"
      class="flex-1 flex flex-col items-center justify-center text-gray-400 px-6"
    >
      <Icon name="heroicons:sparkles" class="w-8 h-8 mb-2" />
      <span class="text-sm text-center">No slides yet — add a visualization from this report.</span>
    </div>

    <!-- Body -->
    <div v-else class="flex-1 flex min-h-0">
      <!-- Thumbnail rail -->
      <div class="w-40 shrink-0 border-r border-gray-100 p-2 space-y-2 overflow-y-auto no-scrollbar bg-gray-50">
        <div
          v-for="(slide, i) in slides"
          :key="slide.key"
          class="slide-thumb rounded-md overflow-hidden cursor-pointer transition-shadow"
          :class="{ 'thumb-active': i === currentIndex }"
          @click="currentIndex = i"
        >
          <div class="h-16 flex flex-col justify-center px-2 text-[8px] leading-tight" :class="themeClass">
            <b class="truncate">{{ slide.title }}</b>
            <span v-if="slide.subtitle" class="opacity-70 truncate">{{ slide.subtitle }}</span>
            <div v-else class="flex gap-0.5 mt-1">
              <span class="h-4 w-1.5 inline-block" :style="{ background: barColor }" />
              <span class="h-6 w-1.5 inline-block" :style="{ background: barColor }" />
              <span class="h-3 w-1.5 inline-block opacity-60" :style="{ background: barColor }" />
            </div>
          </div>
          <div class="px-1 py-0.5 text-[9px] text-gray-500 bg-white">
            {{ i + 1 }} · {{ slide.kind }}
          </div>
        </div>
        <button
          class="w-full rounded-md border border-dashed border-gray-300 py-2 text-[11px] text-gray-400 hover:border-[#C2683F] hover:text-[#C2683F] transition-colors"
          @click="addSlide"
        >
          + Add slide
        </button>
      </div>

      <!-- Canvas -->
      <div class="flex-1 flex flex-col items-center justify-center p-6 bg-gray-100 min-h-0 overflow-auto">
        <div
          class="w-full max-w-xl aspect-video rounded-lg shadow-md flex flex-col justify-center px-10"
          :class="themeClass"
        >
          <template v-if="currentSlide?.kind === 'Title'">
            <div class="text-3xl font-bold mb-2">{{ currentSlide.title }}</div>
            <div class="text-base opacity-70">{{ currentSlide.subtitle }}</div>
            <div class="mt-6 text-xs opacity-60">Generated from report artifacts · City Agent Insights</div>
          </template>
          <template v-else-if="currentSlide">
            <div class="text-2xl font-bold mb-3 truncate">{{ currentSlide.title }}</div>
            <img
              v-if="currentSlide.image"
              :src="currentSlide.image"
              alt=""
              class="max-h-40 rounded-md object-contain self-start"
            />
            <div
              v-else
              class="rounded-md border-2 border-dashed border-current/30 opacity-70 px-4 py-8 text-sm flex items-center justify-center"
            >
              {{ currentSlide.body }}
            </div>
          </template>
        </div>

        <!-- Nav -->
        <div class="mt-4 flex items-center gap-4 text-sm text-gray-500">
          <button
            class="px-2 hover:text-gray-800 disabled:opacity-40"
            :disabled="currentIndex <= 0"
            @click="currentIndex = Math.max(0, currentIndex - 1)"
          >◀</button>
          <span>Slide {{ currentIndex + 1 }} / {{ slides.length }}</span>
          <button
            class="px-2 hover:text-gray-800 disabled:opacity-40"
            :disabled="currentIndex >= slides.length - 1"
            @click="currentIndex = Math.min(slides.length - 1, currentIndex + 1)"
          >▶</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

interface SlideModel {
  key: string
  kind: 'Title' | 'Chart'
  title: string
  subtitle?: string
  body?: string
  image?: string
}

type ThemeKey = 'clay' | 'dark' | 'edit'

const props = defineProps<{
  visualizations?: any[]
  reportTitle?: string
}>()

const currentIndex = ref(0)
const theme = ref<ThemeKey>('clay')
const exporting = ref(false)
const extraSlides = ref(0)

const themeOptions: { key: ThemeKey; label: string }[] = [
  { key: 'clay', label: 'Minimal Clay' },
  { key: 'dark', label: 'Dark' },
  { key: 'edit', label: 'Editorial' },
]

const safeTitle = computed(() => props.reportTitle?.trim() || 'Untitled Deck')

const visualizationList = computed(() =>
  Array.isArray(props.visualizations) ? props.visualizations.filter(Boolean) : []
)

const themeClass = computed(() => `theme-${theme.value}`)

const barColor = computed(() => (theme.value === 'dark' ? '#e9c4ac' : '#C2683F'))

// Per-theme background fill for the exported pptx (hex without '#').
const themeBg: Record<ThemeKey, string> = {
  clay: 'FBF7F4',
  dark: '1F2430',
  edit: 'FFFFFF',
}
const themeFg: Record<ThemeKey, string> = {
  clay: '3B2A20',
  dark: 'F3F4F6',
  edit: '1F2937',
}

function vizTitle(v: any, i: number): string {
  return (v && (v.title || v.name)) || `Slide ${i + 2}`
}

function vizImage(v: any): string | undefined {
  if (!v) return undefined
  return v.thumbnail || v.thumbnail_url || v.image || v.image_url || v.preview || undefined
}

const slides = computed<SlideModel[]>(() => {
  const out: SlideModel[] = [
    {
      key: 'title',
      kind: 'Title',
      title: safeTitle.value,
      subtitle: 'City Agent Insights',
    },
  ]
  visualizationList.value.forEach((v, i) => {
    out.push({
      key: String(v?.id ?? `viz-${i}`),
      kind: 'Chart',
      title: vizTitle(v, i),
      body: vizTitle(v, i),
      image: vizImage(v),
    })
  })
  // user-added blank slides
  for (let i = 0; i < extraSlides.value; i++) {
    out.push({
      key: `extra-${i}`,
      kind: 'Chart',
      title: 'New slide',
      body: 'Empty slide',
    })
  }
  return out
})

const currentSlide = computed<SlideModel | undefined>(() => slides.value[currentIndex.value])

function addSlide() {
  extraSlides.value += 1
  currentIndex.value = slides.value.length - 1
}

async function exportPptx() {
  if (!slides.value.length) return
  exporting.value = true
  try {
    const mod: any = await import('pptxgenjs')
    const PptxGenJs = mod.default || mod
    const pptx = new PptxGenJs()
    const bg = themeBg[theme.value]
    const fg = themeFg[theme.value]
    for (const slide of slides.value) {
      const s = pptx.addSlide()
      s.background = { color: bg }
      s.addText(slide.title || '', {
        x: 0.5, y: 0.4, w: 9, h: 1,
        fontSize: slide.kind === 'Title' ? 32 : 24,
        bold: true, color: fg,
      })
      const sub = slide.kind === 'Title' ? (slide.subtitle || '') : (slide.body || '')
      if (sub) {
        s.addText(sub, {
          x: 0.5, y: 1.6, w: 9, h: 1,
          fontSize: 16, color: fg,
        })
      }
    }
    await pptx.writeFile({ fileName: `${safeTitle.value}.pptx` })
  } catch (e) {
    console.warn('export library not installed', e)
    // eslint-disable-next-line no-undef
    try { (globalThis as any).useToast?.().add({ title: 'Export failed', description: 'export library not installed' }) } catch {}
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.no-scrollbar::-webkit-scrollbar { display: none; }
.no-scrollbar { -ms-overflow-style: none; scrollbar-width: none; }

.slide-thumb.thumb-active { outline: 2px solid #C2683F; outline-offset: 1px; }

.theme-clay { background: linear-gradient(135deg, #FBF7F4, #F3E7DF); color: #3b2a20; }
.theme-dark { background: linear-gradient(135deg, #1f2430, #2c3444); color: #f3f4f6; }
.theme-edit { background: #ffffff; color: #1f2937; border-left: 6px solid #C2683F; }
</style>
