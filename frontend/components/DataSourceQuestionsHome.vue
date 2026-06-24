<template>
    <div v-if="visibleItems.length > 0" class="w-full max-w-2xl mx-auto">
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <button
                v-for="(item, idx) in visibleItems"
                :key="item.key + '-' + idx"
                @click="emitContent(item.value)"
                :class="[
                    'group relative flex flex-col items-start gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-3.5 text-left transition-all duration-300 ease-out hover:border-[#C2683F]/40 hover:bg-[#FBF7F4] hover:shadow-sm',
                    (fadingIndex === idx) ? 'swap-out' : 'swap-in'
                ]">
                <span class="flex items-center gap-1.5">
                    <UIcon :name="item.cat.icon" class="h-4 w-4 text-[#C2683F]" />
                    <span class="text-[10px] font-semibold uppercase tracking-wide text-[#C2683F]/80">{{ item.cat.label }}</span>
                </span>
                <span class="text-[13px] leading-snug font-medium text-gray-800 line-clamp-2">{{ item.label }}</span>
            </button>
        </div>
        <div v-if="pool.length > VISIBLE_COUNT" class="mt-3 flex justify-center">
            <button
                @click="repopulateInitial"
                class="inline-flex items-center gap-1 text-[11px] font-medium text-gray-400 hover:text-[#C2683F] transition-colors">
                <UIcon name="i-heroicons-arrow-path" class="h-3.5 w-3.5" />
                shuffle
            </button>
        </div>
    </div>
    <div v-else-if="shouldShowSpinner" class="flex items-center justify-center">
        <Spinner class="h-4 w-4 text-gray-400" />
    </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted, onMounted, nextTick } from 'vue'
import Spinner from '@/components/Spinner.vue'

const props = defineProps<{
    data_sources: any[]
}>()

const emit = defineEmits(['update-content'])

type Category = { label: string, icon: string }
type Suggestion = { key: string, label: string, value: string, cat: Category }

// Infer a category + icon from the prompt verb/phrasing
function categorize(text: string): Category {
    const t = text.toLowerCase()
    if (/\b(vs|versus|compare|correlation|correlate|against|difference|spread between)\b/.test(t))
        return { label: 'Compare', icon: 'i-heroicons-arrows-right-left' }
    if (/\b(dashboard|overview|build|report|summary)\b/.test(t))
        return { label: 'Dashboard', icon: 'i-heroicons-squares-2x2' }
    if (/\b(over time|trend|growth|monthly|daily|yearly|quarterly|average|avg|forecast|by (month|year|day|week|quarter))\b/.test(t))
        return { label: 'Trend', icon: 'i-heroicons-arrow-trending-up' }
    if (/\b(top|most|highest|lowest|rank|ranking|by total|breakdown|which)\b/.test(t))
        return { label: 'Rank', icon: 'i-heroicons-chart-bar' }
    return { label: 'Explore', icon: 'i-heroicons-magnifying-glass' }
}

// Build a flat pool of suggestions from all selected data sources
const pool = computed<Suggestion[]>(() => {
    if (!props.data_sources || !Array.isArray(props.data_sources)) return []
    const uniqueByLabel = new Map<string, Suggestion>()
    for (const ds of props.data_sources) {
        const starters = Array.isArray(ds?.conversation_starters) ? ds.conversation_starters : []
        for (const raw of starters) {
            const normalized = String(raw ?? '').replace(/\\n/g, '\n')
            const label = normalized.split('\n')[0].trim()
            if (!label) continue
            if (!uniqueByLabel.has(label)) {
                uniqueByLabel.set(label, {
                    key: `${label}-${uniqueByLabel.size}`,
                    label,
                    value: normalized,
                    cat: categorize(label),
                })
            }
        }
    }
    return Array.from(uniqueByLabel.values())
})

const VISIBLE_COUNT = 6
const visibleItems = ref<Suggestion[]>([])
const fadingIndex = ref<number | null>(null)

function pickRandom<T>(arr: T[]): T | undefined {
    if (!arr.length) return undefined
    const index = Math.floor(Math.random() * arr.length)
    return arr[index]
}

function repopulateInitial() {
    const available = [...pool.value]
    const next: Suggestion[] = []
    const desired = Math.min(VISIBLE_COUNT, available.length)
    while (available.length > 0 && next.length < desired) {
        const candidate = pickRandom(available)
        if (!candidate) break
        next.push(candidate)
        const idx = available.indexOf(candidate)
        if (idx >= 0) available.splice(idx, 1)
    }
    visibleItems.value = next
}

function rotateOne() {
    const currentLabels = new Set(visibleItems.value.map(i => i.label))
    const candidates = pool.value.filter(i => !currentLabels.has(i.label))
    if (visibleItems.value.length === 0) return
    // If no unique candidates remain, stop rotating
    if (candidates.length === 0) return
    const replaceIndex = Math.floor(Math.random() * visibleItems.value.length)
    const replacement = pickRandom(candidates)
    if (!replacement) return
    fadingIndex.value = replaceIndex
    setTimeout(async () => {
        const nextArr = visibleItems.value.slice()
        nextArr.splice(replaceIndex, 1, replacement)
        visibleItems.value = nextArr
        await nextTick()
        setTimeout(() => { fadingIndex.value = null }, 50)
    }, 200)
}

let rotationInterval: any
function startRotation() {
    clearInterval(rotationInterval)
    rotationInterval = setInterval(() => {
        rotateOne()
    }, 6000) // rotate one every 6s
}

watch(pool, () => {
    repopulateInitial()
    startRotation()
}, { immediate: true })

onMounted(() => {})

onUnmounted(() => {
    clearInterval(rotationInterval)
})

function emitContent(content: string) {
    emit('update-content', content)
}

// Show spinner only while DS list is loading (undefined/null). Empty array shows nothing.
const shouldShowSpinner = computed(() => props.data_sources === undefined || props.data_sources === null)
</script>

<style scoped>
/* Per-item swap animation without removing element from flow */
.swap-in {
    opacity: 1;
    transform: translateY(0);
    transition: opacity 0.25s ease, transform 0.25s ease;
}
.swap-out {
    opacity: 0;
    transform: translateY(4px);
    transition: opacity 0.25s ease, transform 0.25s ease;
}
</style>
