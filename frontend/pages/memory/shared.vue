<template>
    <div class="max-w-5xl mx-auto px-6 py-8 space-y-6">
        <div>
            <h1 class="text-[22px] font-semibold tracking-[-0.01em] text-[#1C1917]">Shared Memory</h1>
            <p class="text-[13.5px] text-[#78716C] mt-1">
                Reusable knowledge across all your agents, grouped by the data it belongs to. Learned once,
                reused by everyone who has the same data — sanitized so no data values are exposed, and you
                only see the data you have access to.
            </p>
        </div>

        <div v-if="loaded && !enabled" class="bg-white border border-[#EAE8E4] rounded-xl p-6 text-center">
            <p class="text-[13.5px] text-[#78716C]">Shared Memory is turned off. Enable it in Settings → Features (Shared Memory).</p>
        </div>

        <div v-else-if="!loaded" class="inline-flex items-center text-[#78716C] text-xs">
            <Spinner class="w-4 h-4 me-2" /> Loading…
        </div>

        <div v-else-if="!groups.length" class="bg-white border border-[#EAE8E4] rounded-xl p-6 text-center">
            <p class="text-[13.5px] text-[#78716C]">No shared knowledge yet. It builds up as agents answer verified questions and recover from errors.</p>
        </div>

        <div v-else class="space-y-8">
            <!-- 3 tiers: Global (all agents) · By data · Personal -->
            <section v-for="tier in tiers" :key="tier.key" v-show="tier.groups.length">
                <div class="flex items-center gap-2 mb-2">
                    <h2 class="text-[15px] font-semibold text-[#1C1917]">{{ tier.label }}</h2>
                    <span class="text-[11px] text-[#A8A29E]">{{ tier.desc }}</span>
                </div>
                <div class="space-y-4">
                    <div v-for="grp in tier.groups" :key="grp.scope_kind + grp.scope_key"
                         class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,0.04),0_1px_3px_rgba(28,25,23,0.06)]">
                        <div class="px-4 py-3 border-b border-[#F1EFEC] flex items-center justify-between">
                            <div class="flex items-center gap-2">
                                <span class="text-[10.5px] px-2 py-0.5 rounded-full" :class="tier.chip">{{ scopeName(grp) }}</span>
                                <h3 v-if="grp.scope_kind !== 'org' && grp.scope_kind !== 'user'" class="text-[13px] font-mono text-[#57534E] truncate max-w-[340px]">{{ grp.scope_key }}</h3>
                            </div>
                            <span class="text-[11px] text-[#A8A29E]">{{ grp.items.length }} facts</span>
                        </div>
                        <ul class="divide-y divide-[#F5F3F0]">
                            <li v-for="it in grp.items" :key="it.id" class="px-4 py-2.5 flex items-start justify-between gap-3">
                                <div class="min-w-0">
                                    <div class="text-[12.5px] font-medium text-[#1C1917]">
                                        <span class="text-[#A8A29E] mr-1.5">{{ kindTag(it.kind) }}</span>{{ it.title || it.kind }}
                                    </div>
                                    <div class="text-[12px] text-[#78716C] mt-0.5 font-mono break-all">{{ preview(it) }}</div>
                                </div>
                                <span class="text-[10.5px] px-2 py-0.5 rounded-full bg-[#F0FDF4] text-[#3F9B6B] border border-[#BBF7D0] shrink-0">✓ {{ it.verified_count }}</span>
                            </li>
                        </ul>
                    </div>
                </div>
            </section>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

definePageMeta({ auth: true, layout: 'default' })

const loaded = ref(false)
const enabled = ref(false)
const groups = ref<any[]>([])

function kindTag(k: string) {
    return ({ query_template: '⌘', dax_template: '⌘', mistake: '⚠', meaning: '≡', join: '⋈', howto: '★' } as Record<string, string>)[k] || '•'
}

const tiers = computed(() => {
    const by = (t: string) => groups.value.filter((g: any) => (g.tier || 'data') === t)
    return [
        { key: 'global',   label: 'Global',   desc: 'every agent learns from this', chip: 'bg-[#FEF3C7] text-[#B45309] border border-[#FDE68A]', groups: by('global') },
        { key: 'data',     label: 'By data',  desc: 'shared with everyone who has the same data source', chip: 'bg-[#EEF2FF] text-[#4F46E5] border border-[#C7D2FE]', groups: by('data') },
        { key: 'personal', label: 'Personal', desc: 'private to you', chip: 'bg-[#F5F3F0] text-[#78716C] border border-[#EAE8E4]', groups: by('personal') },
    ]
})

function scopeName(grp: any) {
    if (grp.scope_kind === 'org') return 'global · all agents'
    if (grp.scope_kind === 'user') return 'private'
    return grp.scope_kind
}
function preview(it: any) {
    const c = it.content || {}
    if (it.kind === 'mistake') return c.fix_shape || it.text || ''
    return c.template || c.meaning || it.text || ''
}

async function load() {
    try {
        const { data } = await useMyFetch<any>('/memory/shared', { method: 'GET' })
        const v: any = (data as any)?.value ?? data
        enabled.value = !!v?.enabled
        groups.value = Array.isArray(v?.groups) ? v.groups : []
    } catch (_) {
        enabled.value = false; groups.value = []
    } finally {
        loaded.value = true
    }
}

onMounted(load)
</script>
