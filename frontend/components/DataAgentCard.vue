<template>
    <!-- Data Agent card — Studios v2 skin (cr-* classes mirror StudioCard) applied
         to a data-agent (data source). Root is a div(role=button); whole card
         click → open (connected) or connect (needs sign-in). Action bar holds
         real buttons so no <button>-in-<button> nesting. -->
    <div
        role="button"
        tabindex="0"
        class="cr-card group relative flex flex-col text-left bg-white overflow-hidden cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C2541E]"
        @click="onCardClick"
        @keydown.enter.prevent="onCardClick"
        @keydown.space.prevent="onCardClick"
    >
        <!-- DARK header -->
        <div class="cr-head">
            <div class="cr-grid" />
            <div class="cr-blob" />

            <!-- status pill -->
            <div class="relative flex justify-end">
                <span class="cr-pill" :class="pill.cls">
                    <span class="cr-dot" :class="pill.dot" />
                    {{ pill.label }}
                </span>
            </div>

            <!-- connected → live equalizer; needs-data → dashed awaiting sign-in -->
            <div v-if="connected" class="cr-eq">
                <span v-for="n in 6" :key="n" :style="{ animationDelay: (n - 1) * 0.18 + 's', background: eqColors[(n - 1) % eqColors.length] }" />
            </div>
            <div v-else class="cr-await">awaiting sign-in</div>

            <!-- icon badge overlapping into body: connector logo or generic DB tile -->
            <div class="cr-badge">
                <img v-if="meta?.logo" :src="meta.logo" :alt="meta.name" class="w-full h-full object-contain p-2" />
                <UIcon v-else name="i-heroicons-circle-stack" class="w-6 h-6 text-[#C2541E]" />
            </div>
        </div>

        <!-- BODY -->
        <div class="flex flex-col flex-1 px-[17px] pt-8 pb-[17px]">
            <div class="cr-name flex items-center gap-1.5">
                <span>{{ meta ? meta.name : ds.name }}</span>
                <UTooltip v-if="ds.admin_only" :text="$t('data.adminOnlyHint')">
                    <span class="text-[9px] font-medium uppercase tracking-wide text-[#C2541E] bg-[#F4EEE5] border border-[#E9E0D3] px-1.5 py-0.5 rounded">{{ $t('data.adminOnlyTag') }}</span>
                </UTooltip>
            </div>
            <div class="cr-persona">
                <template v-if="meta?.subtitle">{{ meta.subtitle }}</template>
                <template v-else-if="ds.description">{{ ds.description }}</template>
                <template v-else>Private connection</template>
            </div>

            <!-- CONNECTED: source + table stats -->
            <div v-if="connected" class="flex-1 flex flex-col">
                <div class="cr-src">
                    <UIcon name="i-heroicons-circle-stack" class="w-3.5 h-3.5 text-[#A89C8C] shrink-0" />
                    <span class="truncate">{{ sourceSummary }}</span>
                </div>
                <div class="cr-bar"><i :style="{ width: '100%', background: 'linear-gradient(90deg,#3FA86B,#2F7E50)' }" /></div>
                <div class="cr-bar-note" style="color:#2F7E50">Ready</div>
            </div>

            <!-- NEEDS SIGN-IN: orange progress + connect nudge -->
            <div v-else class="flex-1 flex flex-col">
                <div class="cr-src">
                    <UIcon name="i-heroicons-circle-stack" class="w-3.5 h-3.5 text-[#A89C8C] shrink-0" />
                    <span class="truncate">{{ tableCount }} tables · sign-in needed</span>
                </div>
                <div class="cr-bar"><i :style="{ width: '30%', background: 'linear-gradient(90deg,#D67037,#A8330F)' }" /></div>
                <div class="cr-bar-note" style="color:#B85C2E">Connect data to activate</div>
            </div>

            <!-- action bar -->
            <div class="mt-auto flex gap-[9px] pt-2">
                <template v-if="connected">
                    <button class="cr-prim" @click.stop="$emit('open')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></svg>
                        Chat
                    </button>
                    <button class="cr-ghost" @click.stop="$emit('open')">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none"><path d="M5 12h13M13 6l6 6-6 6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                        Open
                    </button>
                </template>
                <template v-else>
                    <button class="cr-prim" :disabled="connecting" @click.stop="$emit('connect')">
                        <Spinner v-if="connecting" class="w-3.5 h-3.5" />
                        <UIcon v-else name="heroicons-key" class="w-3.5 h-3.5" />
                        Connect
                    </button>
                </template>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

interface Meta { logo: string; name: string; subtitle?: string }
const props = defineProps<{
    ds: any
    meta?: Meta | null
    connected: boolean
    connecting?: boolean
    tableCount: number
    sourceCount: number
}>()
const emit = defineEmits<{ open: []; connect: [] }>()

const eqColors = ['#D67037', '#C2541E', '#E89461', '#B8431A', '#D67037', '#E89461']

const pill = computed(() =>
    props.connected
        ? { label: 'Connected', cls: 'cr-pill-green', dot: 'cr-dot-green cr-pulse' }
        : { label: 'Needs data', cls: 'cr-pill-amber', dot: 'cr-dot-amber' }
)

const sourceSummary = computed(() => {
    const n = props.sourceCount || 0
    return `${props.tableCount} tables · ${n} ${n === 1 ? 'source' : 'sources'}`
})

function onCardClick() {
    if (props.connected) emit('open')
    else emit('connect')
}
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
.cr-head {
    position: relative; height: 118px;
    background: radial-gradient(130% 120% at 75% -10%, #33251B, #130E0A);
    padding: 15px;
    /* overflow VISIBLE so the logo badge (bottom:-24px) isn't clipped where it
       overhangs into the body. Decorative bg (grid/blob) that spills past the
       card edge is still contained by .cr-card's own overflow-hidden. */
    overflow: visible;
    border-radius: 16px 16px 0 0;
}
.cr-grid {
    position: absolute; inset: 0; pointer-events: none;
    background-image: linear-gradient(rgba(255,255,255,.05) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.05) 1px, transparent 1px);
    background-size: 20px 20px;
    -webkit-mask-image: radial-gradient(120% 90% at 70% 0, #000 30%, transparent 85%);
    mask-image: radial-gradient(120% 90% at 70% 0, #000 30%, transparent 85%);
    animation: cr-drift 7s linear infinite;
}
.cr-blob {
    position: absolute; top: -30px; right: -20px; width: 160px; height: 160px; border-radius: 50%;
    background: radial-gradient(circle, rgba(214,112,55,.34), transparent 65%);
    filter: blur(16px); pointer-events: none;
}
.cr-pill { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 999px; }
.cr-pill-green { color: #6FD49A; background: rgba(63,168,107,.14); border: 1px solid rgba(63,168,107,.3); }
.cr-pill-amber { color: #E5A45B; background: rgba(224,150,46,.14); border: 1px solid rgba(224,150,46,.3); }
.cr-dot { width: 6px; height: 6px; border-radius: 50%; }
.cr-dot-green { background: #3FA86B; }
.cr-dot-amber { background: #E0962E; }
.cr-pulse { animation: cr-pulse 1.8s ease-in-out infinite; }
.cr-eq { position: absolute; left: 78px; bottom: 18px; display: flex; align-items: flex-end; gap: 5px; height: 38px; }
.cr-eq span { width: 6px; height: 100%; border-radius: 2px; transform-origin: bottom; animation: cr-eq 1.1s ease-in-out infinite; }
.cr-await {
    position: absolute; left: 78px; right: 16px; bottom: 18px; height: 34px;
    border: 1.4px dashed rgba(255,255,255,.18); border-radius: 8px;
    display: flex; align-items: center; justify-content: center; font-size: 11px; color: #8A7868;
}
.cr-badge {
    position: absolute; left: 15px; bottom: -24px; width: 56px; height: 56px;
    border-radius: 15px; background: #fff; border: 1px solid #ECE3D5;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 10px 22px -8px rgba(0,0,0,.45); overflow: hidden;
}
.cr-name { font-size: 17.5px; font-weight: 600; color: #211B14; line-height: 1.2; font-family: 'Spectral', ui-serif, Georgia, serif; }
.cr-persona {
    font-family: 'Spectral', ui-serif, Georgia, serif; font-style: italic;
    font-size: 13.5px; color: #8A7F70; margin: 3px 0 15px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cr-src { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #6E6356; margin-bottom: 12px; min-width: 0; }
.cr-bar { height: 6px; border-radius: 99px; background: #EFE7DA; overflow: hidden; margin-bottom: 10px; }
.cr-bar i { display: block; height: 100%; border-radius: 99px; }
.cr-bar-note { font-size: 12.5px; font-weight: 600; margin-bottom: 16px; }
.cr-prim, .cr-ghost {
    flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
    border-radius: 10px; padding: 10px; cursor: pointer; font-family: inherit; font-size: 13.5px; font-weight: 600; transition: .15s;
}
.cr-prim { border: none; background: #C2541E; color: #fff; }
.cr-prim:hover { background: #A8330F; }
.cr-prim:disabled { opacity: .6; cursor: not-allowed; }
.cr-ghost { border: 1px solid #E4D9CA; background: #FCFAF6; color: #574E44; }
.cr-ghost:hover { border-color: #C9BEAF; background: #FFFFFF; }
@keyframes cr-pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: .4; transform: scale(.7); } }
@keyframes cr-eq { 0%,100% { transform: scaleY(.32); } 50% { transform: scaleY(1); } }
@keyframes cr-drift { 0% { background-position: 0 0; } 100% { background-position: 20px 20px; } }
@media (prefers-reduced-motion: reduce) {
    .cr-card, .cr-grid { animation: none !important; transition: none !important; }
}
</style>
