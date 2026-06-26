<template>
    <div class="bg-[#F1ECE3] h-full overflow-hidden flex flex-col">
        <div class="my-2 me-2 px-6 md:px-8 py-6 text-sm bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto">

            <!-- header: serif title + readiness-style ring (deck count) -->
            <div class="flex items-start justify-between gap-4 mb-1">
                <div>
                    <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Presentations</h2>
                    <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[460px]">Slide decks generated from your reports. Edit slides, analyze the deck, export to .pptx.</p>
                </div>
                <div class="shrink-0 text-center">
                    <div class="relative w-[54px] h-[54px] mx-auto">
                        <svg width="54" height="54" style="transform:rotate(-90deg)">
                            <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
                            <circle cx="27" cy="27" r="22" stroke="#5A4FCF" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" :stroke-dashoffset="Math.round(138 - 138 * ringPct / 100)" style="transition:stroke-dashoffset .5s" />
                        </svg>
                        <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#5A4FCF]" style="font-family: ui-serif, Georgia, serif">{{ presentations.length }}</div>
                    </div>
                    <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">decks</div>
                </div>
            </div>

            <!-- toolbar: search · segmented -->
            <div class="flex items-center gap-2 mt-4 mb-4">
                <div class="relative flex-1 max-w-[420px]">
                    <Icon name="heroicons:magnifying-glass" class="absolute left-2.5 top-2.5 h-4 w-4 text-[#9a958c]" />
                    <input
                        v-model="search"
                        type="text"
                        placeholder="Search decks…"
                        class="w-full border border-[#E9E0D3] rounded-lg pl-8 pr-3 py-2 text-[13px] bg-white text-[#1f2328] placeholder:text-[#9a958c] focus:outline-none"
                    />
                </div>
                <div class="flex bg-[#F1ECE3] rounded-lg p-0.5 text-[12px]">
                    <button
                        v-for="s in segments"
                        :key="s"
                        class="px-3 py-1.5 rounded-md font-medium transition-colors"
                        :class="segment === s ? 'bg-[#5A4FCF] text-white font-semibold' : 'text-[#6b6b6b]'"
                        @click="segment = s"
                    >{{ s }}</button>
                </div>
                <button
                    class="ml-auto shrink-0 inline-flex items-center gap-1.5 px-3 py-2 text-[13px] font-medium rounded-lg border border-[#E9E0D3] text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors"
                    :disabled="loading"
                    @click="fetchPresentations"
                >
                    <Icon name="heroicons:arrow-path" class="h-4 w-4" :class="loading ? 'animate-spin' : ''" />
                    Refresh
                </button>
            </div>

            <!-- section card + band pill -->
            <div class="relative border border-[#E9E0D3] rounded-2xl bg-white p-4">
                <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">YOUR DECKS</span>

                <!-- Loading -->
                <div v-if="loading && !presentations.length" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mt-1">
                    <div
                        v-for="n in 3"
                        :key="n"
                        class="border border-[#E9E0D3] rounded-xl h-48 bg-gradient-to-b from-white to-[#fdfcf9] animate-pulse"
                    />
                </div>

                <!-- Error -->
                <div
                    v-else-if="error"
                    class="py-12 text-center text-[#A8330F]"
                >
                    {{ error }}
                </div>

                <!-- Empty (no decks at all) -->
                <div
                    v-else-if="!presentations.length"
                    class="border border-dashed border-[#d8cfc0] rounded-xl bg-gradient-to-b from-white to-[#fdfcf9] flex flex-col items-center justify-center text-center py-12 mt-1"
                >
                    <span class="w-12 h-12 rounded-xl bg-[#ECEAFB] flex items-center justify-center text-[#5A4FCF] mb-3">
                        <Icon name="heroicons:presentation-chart-line" class="h-6 w-6" />
                    </span>
                    <div class="text-[13px] font-semibold" style="font-family: 'Spectral', ui-serif, Georgia, serif">No presentations yet</div>
                    <div class="text-[11px] text-[#9a958c] mt-1 max-w-[280px]">Open any report → Slides tab → generate a deck. It will appear here.</div>
                    <button
                        class="mt-3 border border-[#E9E0D3] rounded-lg px-3 py-1.5 text-[12px] bg-white hover:bg-[#F4EEE5] transition-colors"
                        @click="navigateTo('/reports')"
                    >
                        Browse reports
                    </button>
                </div>

                <!-- No search/filter matches -->
                <div
                    v-else-if="!filteredPresentations.length"
                    class="py-12 text-center text-[#6b6b6b] text-sm"
                >
                    No decks match your search.
                </div>

                <!-- Grid -->
                <div v-else class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 mt-1">
                    <div
                        v-for="p in filteredPresentations"
                        :key="p.id"
                        class="border border-[#E9E0D3] rounded-xl bg-gradient-to-b from-white to-[#fdfcf9] overflow-hidden flex flex-col hover:border-[#5A4FCF] transition-colors"
                    >
                        <!-- tinted thumbnail strip (click → open split view) -->
                        <div
                            class="h-24 bg-[#ECEAFB] flex items-center justify-center text-[#5A4FCF] overflow-hidden cursor-pointer"
                            @click="openSlides(p)"
                        >
                            <img
                                v-if="thumbs[p.id]"
                                :src="thumbs[p.id]"
                                class="w-full h-full object-cover"
                                alt=""
                            />
                            <Icon v-else name="heroicons:presentation-chart-line" class="h-7 w-7" />
                        </div>
                        <!-- body -->
                        <div class="p-3 flex flex-col flex-1">
                            <div
                                class="text-[13px] font-semibold text-[#1f2328] truncate cursor-pointer"
                                @click="openSlides(p)"
                            >
                                {{ p.title || p.report_title || 'Untitled deck' }}
                            </div>
                            <div v-if="p.title && p.report_title" class="text-[10.5px] text-[#9a958c] truncate mt-0.5">
                                {{ p.report_title }}
                            </div>
                            <!-- meta: {n} slides · .pptx · {relTime} -->
                            <div class="text-[10.5px] text-[#9a958c] mt-0.5">
                                <template v-if="slideCount(p) === 0">no slides yet</template>
                                <template v-else>{{ slideCount(p) }} slide{{ slideCount(p) === 1 ? '' : 's' }} · .pptx<template v-if="relTime(p.created_at)"> · {{ relTime(p.created_at) }}</template></template>
                            </div>
                            <!-- empty-deck badge + status + .pptx download -->
                            <div class="flex items-center gap-1 mt-1.5">
                                <span
                                    v-if="slideCount(p) === 0"
                                    class="text-[9px] bg-[#F1ECE3] rounded-full px-1.5 py-0.5 text-[#9a958c]"
                                    title="This deck has no slides yet — open it to generate some."
                                >empty deck</span>
                                <span
                                    v-if="p.status === 'failed'"
                                    class="text-[9px] font-semibold rounded-full px-1.5 py-0.5 bg-[#F4D7CB] text-[#A8330F]"
                                >failed</span>
                                <span
                                    v-else-if="p.status === 'pending'"
                                    class="text-[9px] font-semibold rounded-full px-1.5 py-0.5 bg-[#F1EEE8] text-[#8a8378]"
                                >generating</span>
                                <button
                                    v-if="p.pptx_ready"
                                    class="ms-auto inline-flex items-center gap-1 text-[11px] font-medium text-[#9a958c] hover:text-[#5A4FCF]"
                                    :disabled="downloading === p.id"
                                    @click.stop="downloadPptx(p)"
                                >
                                    <Icon name="heroicons:arrow-down-tray" class="h-3.5 w-3.5" />
                                    {{ downloading === p.id ? '…' : '.pptx' }}
                                </button>
                            </div>
                            <!-- actions: slides>0 = Open / Chat; slides=0 = single Open & generate -->
                            <div class="grid grid-cols-2 gap-2 mt-3">
                                <template v-if="slideCount(p) > 0">
                                    <button
                                        class="box-border inline-flex items-center justify-center gap-1 min-w-0 whitespace-nowrap border border-[#E9E0D3] rounded-lg py-1.5 text-[12px] bg-white hover:bg-[#F4EEE5] transition-colors"
                                        title="Open the slide workspace — view & edit slides with chat"
                                        @click.stop="openSlides(p)"
                                    >
                                        <Icon name="heroicons:presentation-chart-line" class="h-3.5 w-3.5 shrink-0" />
                                        Open
                                    </button>
                                    <button
                                        class="box-border inline-flex items-center justify-center gap-1 min-w-0 whitespace-nowrap bg-[#5A4FCF] text-white rounded-lg py-1.5 text-[12px] font-semibold hover:opacity-90 transition-opacity"
                                        title="Open the underlying conversation"
                                        @click.stop="openInChat(p)"
                                    >
                                        <Icon name="heroicons:chat-bubble-left-right" class="h-3.5 w-3.5 shrink-0" />
                                        Chat
                                    </button>
                                </template>
                                <button
                                    v-else
                                    class="box-border col-span-2 inline-flex items-center justify-center gap-1 min-w-0 whitespace-nowrap bg-[#5A4FCF] text-white rounded-lg py-1.5 text-[12px] font-semibold hover:opacity-90 transition-opacity"
                                    title="Open the slide workspace — generate & edit slides with chat"
                                    @click.stop="openSlides(p)"
                                >
                                    <Icon name="heroicons:presentation-chart-line" class="h-3.5 w-3.5 shrink-0" />
                                    Open &amp; generate
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
definePageMeta({ auth: true })

interface Presentation {
    id: string
    report_id: string
    title: string | null
    version: number
    status: string
    slide_count: number
    has_preview: boolean
    pptx_ready: boolean
    report_title: string | null
    created_at: string
    updated_at: string
}

const config = useRuntimeConfig()
const { token } = useAuth()
const { organization } = useOrganization()

const presentations = ref<Presentation[]>([])
const thumbs = ref<Record<string, string>>({})
const loading = ref(false)
const error = ref<string | null>(null)
const downloading = ref<string | null>(null)

// Toolbar: client-side search + segmented filter (UI only, no data/logic change).
const search = ref('')
const segments = ['All', 'Recent'] as const
const segment = ref<(typeof segments)[number]>('All')

// Header ring fill: how many decks already have slides (0..all → 0..100%).
const ringPct = computed(() => {
    const total = presentations.value.length
    if (!total) return 0
    const withSlides = presentations.value.filter((p) => slideCount(p) > 0).length
    return Math.round((withSlides / total) * 100)
})

const filteredPresentations = computed(() => {
    let list = presentations.value
    const q = search.value.trim().toLowerCase()
    if (q) {
        list = list.filter((p) =>
            `${p.title || ''} ${p.report_title || ''}`.toLowerCase().includes(q),
        )
    }
    if (segment.value === 'Recent') {
        const cutoff = Date.now() - 7 * 86400 * 1000
        list = list.filter((p) => {
            const t = new Date(p.created_at).getTime()
            return !isNaN(t) && t >= cutoff
        })
    }
    return list
})

// Relative time for card meta ("3d ago").
function relTime(ts?: string) {
    if (!ts) return ''
    const d = new Date(ts).getTime()
    if (isNaN(d)) return ''
    const s = Math.floor((Date.now() - d) / 1000)
    if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`
    if (s < 604800) return `${Math.floor(s / 86400)}d ago`
    return `${Math.floor(s / 604800)}w ago`
}

function authHeaders(): Record<string, string> {
    const h: Record<string, string> = { Authorization: `${token.value}` }
    if (organization.value?.id) h['X-Organization-Id'] = organization.value.id
    return h
}

async function fetchPresentations() {
    loading.value = true
    error.value = null
    try {
        const { data, error: fetchErr } = await useMyFetch<Presentation[]>('/api/artifacts/presentations', { method: 'GET' })
        if (fetchErr.value) throw new Error('Failed to load presentations')
        presentations.value = data.value || []
        loadThumbs()
    } catch (e: any) {
        error.value = e?.message || 'Failed to load presentations'
    } finally {
        loading.value = false
    }
}

// Preview images are auth-gated → fetch as blob, hand the card an object URL.
async function loadThumbs() {
    for (const p of presentations.value) {
        if (!p.has_preview || thumbs.value[p.id]) continue
        try {
            const res = await fetch(`${config.public.baseURL}/artifacts/${p.id}/preview/0`, {
                method: 'GET',
                headers: authHeaders(),
            })
            if (!res.ok) continue
            const blob = await res.blob()
            thumbs.value = { ...thumbs.value, [p.id]: window.URL.createObjectURL(blob) }
        } catch { /* leave icon fallback */ }
    }
}

// Slide count helper (decks with 0 slides get an empty-state cue + "generate" copy).
function slideCount(p: Presentation): number {
    return p.slide_count || 0
}

// Open with the presentation on the right + chat on the left (split view).
function openSlides(p: Presentation) {
    navigateTo(`/reports/${p.report_id}?focus=slides`)
}

// Open the underlying conversation in plain chat (no auto-split).
function openInChat(p: Presentation) {
    navigateTo(`/reports/${p.report_id}`)
}

async function downloadPptx(p: Presentation) {
    if (downloading.value) return
    downloading.value = p.id
    try {
        const res = await fetch(`${config.public.baseURL}/artifacts/${p.id}/export/pptx`, {
            method: 'GET',
            headers: authHeaders(),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const buf = await res.arrayBuffer()
        const blob = new Blob([buf], {
            type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        })
        const safe = String(p.title || 'presentation').replace(/[^\w\s.-]/g, '').slice(0, 120) || 'presentation'
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${safe}.pptx`
        a.style.display = 'none'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)
    } catch {
        /* ignore — button stays available to retry */
    } finally {
        downloading.value = null
    }
}

onMounted(fetchPresentations)
</script>
