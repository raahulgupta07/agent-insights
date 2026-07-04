<template>
    <!-- Studios v2 design card. Root is a div (role=button) so the action bar can
         hold real buttons without nesting <button> in <button>. All data/logic
         (lifecycle, sources, stats, emits) unchanged — only the skin is the design. -->
    <div
        role="button"
        tabindex="0"
        class="cr-card group relative flex flex-col text-left bg-white overflow-hidden cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]"
        @click="$emit('open')"
        @keydown.enter.prevent="$emit('open')"
        @keydown.space.prevent="$emit('open')"
    >
        <!-- DARK live-activity header -->
        <div class="cr-head">
            <div class="cr-grid" />
            <div class="cr-blob" />

            <!-- lifecycle status pill -->
            <div class="relative flex justify-end">
                <span class="cr-pill" :class="darkPill.cls">
                    <span class="cr-dot" :class="darkPill.dot" />
                    {{ darkPill.label }}
                </span>
            </div>

            <!-- equalizer (has data) / dashed awaiting (draft) -->
            <div v-if="lifecycle !== 'draft'" class="cr-eq">
                <span v-for="n in 6" :key="n" :style="{ animationDelay: (n - 1) * 0.18 + 's', background: eqColors[(n - 1) % eqColors.length] }" />
            </div>
            <div v-else class="cr-await">awaiting first source</div>

            <!-- icon badge overlapping into body -->
            <div class="cr-badge">
                <img v-if="isImageAvatar" :src="studio.avatar || ''" alt="" class="w-full h-full object-cover rounded-[12px]" />
                <span v-else-if="studio.avatar" class="text-2xl">{{ studio.avatar }}</span>
                <UIcon v-else name="i-heroicons-film" class="w-6 h-6 text-[#9A8F80]" />
            </div>
        </div>

        <!-- BODY -->
        <div class="flex flex-col flex-1 px-[17px] pt-8 pb-[17px]">
            <div class="cr-name">{{ studio.name }}</div>
            <div class="cr-persona">{{ voiceLine ? '"' + voiceLine + '"' : (studio.description || '"' + scopeLabel + '"') }}</div>

            <!-- LIVE / IDLE: source label + real stats -->
            <div v-if="lifecycle === 'live' || lifecycle === 'idle'" class="flex-1 flex flex-col">
                <div class="cr-src">
                    <UIcon name="i-heroicons-circle-stack" class="w-3.5 h-3.5 text-[#A89C8C] shrink-0" />
                    <span class="truncate">{{ sourceSummary }}</span>
                </div>
                <div class="cr-stats">
                    <b>{{ studio.chat_count ?? 0 }}</b> chats ·
                    <b>{{ studio.member_count ?? 0 }}</b> {{ (studio.member_count ?? 0) === 1 ? 'member' : 'members' }} ·
                    <b>{{ studio.source_count ?? 0 }}</b> {{ (studio.source_count ?? 0) === 1 ? 'source' : 'sources' }}
                    <template v-if="lastActiveLabel"> · {{ lastActiveLabel }}</template>
                </div>
            </div>

            <!-- READY (data, untrained): blue progress + train nudge -->
            <div v-else-if="lifecycle === 'ready'" class="flex-1 flex flex-col">
                <div class="cr-bar"><i style="width:60%;background:linear-gradient(90deg,#3b6db8,#2a4f8f)" /></div>
                <div class="cr-bar-note" style="color:#3b6db8">Train it to learn your data</div>
            </div>

            <!-- DRAFT (no data): orange progress + connect nudge -->
            <div v-else class="flex-1 flex flex-col">
                <div class="cr-bar"><i style="width:30%;background:linear-gradient(90deg,#D67037,#A8330F)" /></div>
                <div class="cr-bar-note" style="color:#B85C2E">Connect data to activate</div>
            </div>

            <!-- action bar -->
            <div class="mt-auto flex gap-[9px] pt-2">
                <template v-if="lifecycle === 'draft'">
                    <button class="cr-prim" @click.stop="$emit('open')">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></svg>
                        Add data
                    </button>
                    <button class="cr-ghost" @click.stop="$emit('open')">Open</button>
                </template>
                <template v-else>
                    <button class="cr-prim" @click.stop="$emit('open')">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none"><path d="M5 12h13M13 6l6 6-6 6" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        {{ $t('studio.open') || 'Open' }}
                    </button>
                    <button class="cr-ghost" @click.stop="$emit('chat')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>
                        {{ $t('studio.chat') || 'Chat' }}
                    </button>
                </template>
            </div>
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

const eqColors = ['#D67037', '#C2541E', '#E89461', '#B8431A', '#D67037', '#E89461']

const isImageAvatar = computed(() => {
    const a = props.studio.avatar || ''
    return /^https?:\/\//.test(a) || a.startsWith('/')
})

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

const isLive = computed(() => {
    const ts = props.studio.last_active_at
    if (!ts) return false
    const diff = Date.now() - new Date(ts).getTime()
    return diff < 7 * 24 * 3600 * 1000 // active within 7 days
})

// Lifecycle: Draft (no data) -> Ready (data, never chatted) -> Live (active) -> Idle (quiet).
const lifecycle = computed(() => {
    const src = props.studio.source_count ?? (props.studio.sources_preview?.length || 0)
    if (!src) return 'draft'
    const chats = props.studio.chat_count ?? 0
    if (chats === 0) return 'ready'
    return isLive.value ? 'live' : 'idle'
})

// Dark-header translucent pill styling per lifecycle.
const darkPill = computed(() => {
    switch (lifecycle.value) {
        case 'draft': return { label: 'Needs data', cls: 'cr-pill-amber', dot: 'cr-dot-amber' }
        case 'ready': return { label: 'Ready to train', cls: 'cr-pill-blue', dot: 'cr-dot-blue' }
        case 'live': return { label: 'Live', cls: 'cr-pill-green', dot: 'cr-dot-green cr-pulse' }
        default: return { label: lastActiveLabel.value ? `Idle · ${lastActiveLabel.value.replace(' ago', '')}` : 'Idle', cls: 'cr-pill-gray', dot: 'cr-dot-gray' }
    }
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
</script>

<style scoped>
.cr-card {
    border: 1px solid #E9E0D3;
    border-radius: 18px;
    box-shadow: 0 14px 32px -22px rgba(60, 40, 20, .4);
    transition: transform .22s, box-shadow .22s, border-color .22s;
    font-family: 'Hanken Grotesk', system-ui, sans-serif;
}
.cr-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 30px 60px -28px rgba(60, 40, 20, .42);
    border-color: #E4D4C2;
}

/* dark header */
.cr-head {
    position: relative;
    height: 118px;
    background: radial-gradient(130% 120% at 75% -10%, #33251B, #130E0A);
    padding: 15px;
    /* overflow VISIBLE so the icon badge (bottom:-24px) isn't clipped where it
       overhangs into the body. Decorative bg spill is still contained by
       .cr-card's own overflow-hidden. */
    overflow: visible;
    border-radius: 16px 16px 0 0;
}
.cr-grid {
    position: absolute; inset: 0; pointer-events: none;
    background-image: linear-gradient(rgba(255, 255, 255, .05) 1px, transparent 1px), linear-gradient(90deg, rgba(255, 255, 255, .05) 1px, transparent 1px);
    background-size: 20px 20px;
    -webkit-mask-image: radial-gradient(120% 90% at 70% 0, #000 30%, transparent 85%);
    mask-image: radial-gradient(120% 90% at 70% 0, #000 30%, transparent 85%);
    animation: cr-drift 7s linear infinite;
}
.cr-blob {
    position: absolute; top: -30px; right: -20px; width: 160px; height: 160px; border-radius: 50%;
    background: radial-gradient(circle, rgba(214, 112, 55, .34), transparent 65%);
    filter: blur(16px); pointer-events: none;
}
.cr-pill {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 999px;
}
.cr-pill-green { color: #6FD49A; background: rgba(63, 168, 107, .14); border: 1px solid rgba(63, 168, 107, .3); }
.cr-pill-amber { color: #E5A45B; background: rgba(224, 150, 46, .14); border: 1px solid rgba(224, 150, 46, .3); }
.cr-pill-blue  { color: #8FB6E8; background: rgba(59, 109, 184, .16); border: 1px solid rgba(59, 109, 184, .34); }
.cr-pill-gray  { color: #BFB3A2; background: rgba(180, 165, 145, .14); border: 1px solid rgba(180, 165, 145, .26); }
.cr-dot { width: 6px; height: 6px; border-radius: 50%; }
.cr-dot-green { background: #3FA86B; }
.cr-dot-amber { background: #E0962E; }
.cr-dot-blue  { background: #3b6db8; }
.cr-dot-gray  { background: #9A8F80; }
.cr-pulse { animation: cr-pulse 1.8s ease-in-out infinite; }

.cr-eq {
    position: absolute; left: 78px; bottom: 18px;
    display: flex; align-items: flex-end; gap: 5px; height: 38px;
}
.cr-eq span {
    width: 6px; height: 100%; border-radius: 2px; transform-origin: bottom;
    animation: cr-eq 1.1s ease-in-out infinite;
}
.cr-await {
    position: absolute; left: 78px; right: 16px; bottom: 18px; height: 34px;
    border: 1.4px dashed rgba(255, 255, 255, .18); border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; color: #8A7868;
}
.cr-badge {
    position: absolute; left: 15px; bottom: -24px; width: 56px; height: 56px;
    border-radius: 15px; background: #fff; border: 1px solid #ECE3D5;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 10px 22px -8px rgba(0, 0, 0, .45);
    overflow: hidden;
}

.cr-name { font-size: 17.5px; font-weight: 600; color: #211B14; line-height: 1.2; }
.cr-persona {
    font-family: 'Spectral', ui-serif, Georgia, serif; font-style: italic;
    font-size: 13.5px; color: #8A7F70; margin: 3px 0 15px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cr-src {
    display: flex; align-items: center; gap: 8px;
    font-size: 13px; color: #6E6356; margin-bottom: 12px; min-width: 0;
}
.cr-stats { font-size: 12.5px; color: #9A8F80; margin-bottom: 16px; }
.cr-stats b { color: #3A332B; font-weight: 700; }

.cr-bar { height: 6px; border-radius: 99px; background: #EFE7DA; overflow: hidden; margin-bottom: 10px; }
.cr-bar i { display: block; height: 100%; border-radius: 99px; }
.cr-bar-note { font-size: 12.5px; font-weight: 600; margin-bottom: 16px; }

.cr-prim, .cr-ghost {
    flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
    border-radius: 10px; padding: 10px; cursor: pointer;
    font-family: inherit; font-size: 13.5px; font-weight: 600; transition: .15s;
}
.cr-prim { border: none; background: #C2541E; color: #fff; }
.cr-prim:hover { background: #A8330F; }
.cr-ghost { border: 1px solid #E4D9CA; background: #FCFAF6; color: #574E44; }
.cr-ghost:hover { border-color: #C9BEAF; background: #FFFFFF; }

@keyframes cr-pulse { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: .4; transform: scale(.7); } }
@keyframes cr-eq { 0%, 100% { transform: scaleY(.32); } 50% { transform: scaleY(1); } }
@keyframes cr-drift { 0% { background-position: 0 0; } 100% { background-position: 20px 20px; } }
/* Note: the equalizer + Live dot intentionally keep animating even under
   reduced-motion — they ARE the live-status indicator. Only the heavy
   card hover/grid drift are disabled. */
@media (prefers-reduced-motion: reduce) {
    .cr-card, .cr-grid { animation: none !important; transition: none !important; }
}
</style>
