<template>
    <!-- Concept 1 "Hero Gradient" studio card. Root is a div (role=button) so the
         hover action bar can hold real buttons without nesting <button> in <button>. -->
    <div
        role="button"
        tabindex="0"
        class="studio-card group relative block text-left rounded-2xl border border-[#E7E5DD] bg-white overflow-hidden cursor-pointer transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg hover:border-[#dcd9cf] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2683F]"
        @click="$emit('open')"
        @keydown.enter.prevent="$emit('open')"
        @keydown.space.prevent="$emit('open')"
    >
        <!-- Persona-tinted gradient band (hue hashed from the studio name) -->
        <div class="h-14 w-full relative" :style="bandStyle">
            <div class="absolute inset-0 opacity-90" :style="bandGradient" />
            <!-- live status dot -->
            <span class="absolute top-2.5 right-3 inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-white/85 backdrop-blur"
                  :class="isLive ? 'text-green-600' : 'text-gray-400'">
                <span class="w-1.5 h-1.5 rounded-full" :class="isLive ? 'bg-green-500 animate-pulse' : 'bg-gray-300'" />
                {{ isLive ? $t('studio.live') || 'live' : $t('studio.idle') || 'idle' }}
            </span>
        </div>

        <!-- Avatar overlapping the band -->
        <div class="px-4 -mt-7 relative">
            <div class="flex items-end justify-between">
                <div class="shrink-0 flex items-center justify-center w-14 h-14 rounded-xl bg-white shadow-sm ring-2 ring-white text-2xl overflow-hidden"
                     :style="avatarRing">
                    <img v-if="isImageAvatar" :src="studio.avatar || ''" alt="" class="w-full h-full object-cover rounded-[10px]" />
                    <span v-else-if="studio.avatar">{{ studio.avatar }}</span>
                    <UIcon v-else name="i-heroicons-film" class="w-6 h-6 text-gray-400" />
                </div>
                <span :class="scopeBadgeClass" class="mb-1 shrink-0 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded">
                    {{ scopeLabel }}
                </span>
            </div>
        </div>

        <div class="px-4 pt-2 pb-4">
            <!-- Name + role -->
            <div class="flex items-center gap-1.5">
                <span class="font-semibold text-gray-900 text-sm leading-tight truncate">{{ studio.name }}</span>
            </div>
            <span v-if="roleLabel" class="text-[11px] text-gray-400">{{ roleLabel }}</span>

            <!-- Persona / voice one-liner -->
            <p v-if="voiceLine" class="text-xs text-gray-500 italic line-clamp-1 mt-1">"{{ voiceLine }}"</p>
            <p v-else-if="studio.description" class="text-xs text-gray-500 line-clamp-1 mt-1">{{ studio.description }}</p>

            <!-- Source logo stack -->
            <div class="flex items-center gap-2 mt-3 min-h-[20px]">
                <div v-if="sourcePreview.length" class="flex -space-x-1.5">
                    <span
                        v-for="(s, i) in sourcePreview"
                        :key="i"
                        class="inline-flex items-center justify-center w-5 h-5 rounded-md bg-gray-50 ring-1 ring-white"
                        :title="s.name"
                    >
                        <DataSourceIcon v-if="s.type" class="h-3" :type="s.type" />
                        <UIcon v-else name="i-heroicons-circle-stack" class="w-3 h-3 text-gray-400" />
                    </span>
                </div>
                <span class="text-[11px] text-gray-400 truncate">{{ sourceSummary }}</span>
            </div>

            <!-- Stat tiles -->
            <div class="grid grid-cols-4 gap-1.5 mt-3">
                <div class="rounded-lg bg-gray-50 py-1.5 text-center">
                    <div class="text-sm font-semibold text-gray-800 leading-none">{{ studio.chat_count ?? 0 }}</div>
                    <div class="text-[9px] text-gray-400 uppercase tracking-wide mt-0.5">{{ $t('studio.statChats') || 'chats' }}</div>
                </div>
                <div class="rounded-lg bg-gray-50 py-1.5 text-center">
                    <div class="text-sm font-semibold text-gray-800 leading-none">{{ studio.member_count ?? 0 }}</div>
                    <div class="text-[9px] text-gray-400 uppercase tracking-wide mt-0.5">{{ $t('studio.statMembers') || 'members' }}</div>
                </div>
                <div class="rounded-lg bg-gray-50 py-1.5 text-center">
                    <div class="text-sm font-semibold text-gray-800 leading-none">{{ evalPct }}</div>
                    <div class="text-[9px] text-gray-400 uppercase tracking-wide mt-0.5">{{ $t('studio.statEval') || 'eval' }}</div>
                </div>
                <div class="rounded-lg bg-gray-50 py-1.5 text-center">
                    <div class="text-sm font-semibold text-gray-800 leading-none">{{ studio.source_count ?? 0 }}</div>
                    <div class="text-[9px] text-gray-400 uppercase tracking-wide mt-0.5">{{ $t('studio.statSources') || 'src' }}</div>
                </div>
            </div>

            <!-- Activity sparkline + last active -->
            <div class="flex items-center justify-between mt-3 h-5">
                <svg v-if="hasActivity" :viewBox="`0 0 ${spark.w} ${spark.h}`" class="h-5 w-24" preserveAspectRatio="none">
                    <polyline
                        :points="spark.points"
                        fill="none"
                        :stroke="accent"
                        stroke-width="1.5"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                    />
                </svg>
                <span v-else class="text-[11px] text-gray-300">{{ $t('studio.noActivity') || 'no activity yet' }}</span>
                <span class="text-[11px] text-gray-400">{{ lastActiveLabel }}</span>
            </div>
        </div>

        <!-- Hover action bar -->
        <div class="absolute inset-x-0 bottom-0 px-3 py-2 bg-white/95 backdrop-blur border-t border-gray-100 flex items-center gap-2 translate-y-full group-hover:translate-y-0 transition-transform duration-200">
            <UButton color="orange" size="2xs" icon="i-heroicons-arrow-right" class="flex-1 justify-center !bg-[#C2683F] hover:!bg-[#A8542F]" @click.stop="$emit('open')">
                {{ $t('studio.open') || 'Open' }}
            </UButton>
            <UButton color="gray" variant="soft" size="2xs" icon="i-heroicons-plus" class="flex-1 justify-center" @click.stop="$emit('chat')">
                {{ $t('studio.chat') || 'Chat' }}
            </UButton>
        </div>
    </div>
</template>

<script setup lang="ts">
import DataSourceIcon from '~/components/DataSourceIcon.vue'

interface SourcePreview { name: string; type?: string | null }
interface Studio {
    id: string
    name: string
    description?: string | null
    persona?: string | null
    avatar?: string | null
    share_scope: string
    source_count?: number
    member_count?: number
    role?: string
    // Concept-1 advanced fields (all optional; degrade gracefully when absent).
    chat_count?: number
    last_active_at?: string | null
    eval_pass_rate?: number | null
    activity_7d?: number[]
    sources_preview?: SourcePreview[]
}

const props = defineProps<{ studio: Studio }>()
defineEmits<{ open: []; chat: [] }>()

const { t } = useI18n()

const isImageAvatar = computed(() => {
    const a = props.studio.avatar || ''
    return /^https?:\/\//.test(a) || a.startsWith('/')
})

// Persona-derived hue: deterministic hash of the name -> 0..360. Gives every
// studio a unique, stable accent without storing a color.
const hue = computed(() => {
    const s = props.studio.name || 'studio'
    let h = 0
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360
    return h
})
// Claude warm palette — calm, no rainbow hue hashing (user disliked the purple-blue band).
const accent = computed(() => '#C2683F')
const bandStyle = computed(() => ({ background: '#F4F1EA' }))
const bandGradient = computed(() => ({
    background: 'linear-gradient(120deg, #F6EFE8, #EFE7DC)',
}))
const avatarRing = computed(() => ({ boxShadow: '0 0 0 2px white, 0 0 0 3.5px #E7E5DD' }))

const voiceLine = computed(() => {
    const p = (props.studio.persona || '').trim()
    if (!p) return ''
    // First sentence / clause, capped.
    const first = p.split(/[.\n]/)[0].trim()
    return first.length > 70 ? first.slice(0, 67) + '…' : first
})

const sourcePreview = computed(() => (props.studio.sources_preview || []).slice(0, 3))
const sourceSummary = computed(() => {
    const n = props.studio.source_count ?? sourcePreview.value.length
    const names = sourcePreview.value.map(s => s.name)
    if (!n) return t('studio.noSources') || 'No sources'
    if (names.length) {
        const extra = n - names.length
        return extra > 0 ? `${names.join(' · ')} +${extra}` : names.join(' · ')
    }
    return `${n} ${n === 1 ? 'source' : 'sources'}`
})

const evalPct = computed(() => {
    const r = props.studio.eval_pass_rate
    return r === null || r === undefined ? '—' : `${Math.round(r * 100)}%`
})

// Activity sparkline from activity_7d (oldest -> newest), normalized.
const hasActivity = computed(() => (props.studio.activity_7d || []).some(v => v > 0))
const spark = computed(() => {
    const data = props.studio.activity_7d || []
    const w = 96, h = 20, pad = 1
    const max = Math.max(1, ...data)
    const step = data.length > 1 ? (w - pad * 2) / (data.length - 1) : 0
    const points = data
        .map((v, i) => `${(pad + i * step).toFixed(1)},${(h - pad - (v / max) * (h - pad * 2)).toFixed(1)}`)
        .join(' ')
    return { w, h, points }
})

const isLive = computed(() => {
    const ts = props.studio.last_active_at
    if (!ts) return false
    const diff = Date.now() - new Date(ts).getTime()
    return diff < 7 * 24 * 3600 * 1000 // active within 7 days
})

const lastActiveLabel = computed(() => {
    const ts = props.studio.last_active_at
    if (!ts) return ''
    const diff = Date.now() - new Date(ts).getTime()
    const m = Math.floor(diff / 60000)
    if (m < 1) return t('studio.activeNow') || 'just now'
    if (m < 60) return `${m}m ago`
    const hrs = Math.floor(m / 60)
    if (hrs < 24) return `${hrs}h ago`
    const d = Math.floor(hrs / 24)
    return `${d}d ago`
})

const scopeLabel = computed(() => {
    const s = (props.studio.share_scope || 'private').toLowerCase()
    if (s === 'org') return t('studio.scopeOrg')
    if (s === 'link') return t('studio.scopeLink')
    return t('studio.scopePrivate')
})
const scopeBadgeClass = computed(() => {
    const s = (props.studio.share_scope || 'private').toLowerCase()
    if (s === 'org') return 'bg-[#F4F1EA] text-[#7a756c]'
    if (s === 'link') return 'bg-[#F3E7DF] text-[#C2683F]'
    return 'bg-[#F4F1EA] text-[#6b6b6b]'
})
const roleLabel = computed(() => {
    const r = (props.studio.role || '').toLowerCase()
    if (r === 'owner') return t('studio.roleOwner')
    if (r === 'editor') return t('studio.roleEditor')
    if (r === 'viewer') return t('studio.roleViewer')
    return ''
})
</script>

<style scoped>
.line-clamp-1 {
    display: -webkit-box;
    -webkit-line-clamp: 1;
    line-clamp: 1;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
/* Action bar sits over the bottom; give the card a little extra room so the
   sparkline row isn't hidden until hover reveals the bar. */
.studio-card { padding-bottom: 0; }
</style>
