<template>
    <div class="py-6 space-y-5">
        <template v-if="injectedFetchError" />
        <template v-else>
            <!-- Header -->
            <div class="flex items-start gap-4 mb-1">
                <div>
                    <h1 class="text-[19px] font-semibold tracking-[-0.01em] text-[#1C1917]">Memory</h1>
                    <p class="text-[13.5px] text-[#78716C] mt-0.5">
                        Reusable knowledge this agent has learned — how similar tasks were solved before.
                        Shared across users who have the same data, sanitized so no data values are exposed.
                    </p>
                </div>
            </div>

            <!-- Disabled state -->
            <div v-if="loaded && !enabled" class="bg-white border border-[#EAE8E4] rounded-xl p-6 text-center">
                <p class="text-[13.5px] text-[#78716C]">Shared Memory is turned off. Enable it in Settings → Features (Shared Memory).</p>
            </div>

            <!-- Loading -->
            <div v-else-if="!loaded" class="inline-flex items-center text-[#78716C] text-xs">
                <Spinner class="w-4 h-4 me-2" /> Loading…
            </div>

            <!-- Empty -->
            <div v-else-if="!items.length" class="bg-white border border-[#EAE8E4] rounded-xl p-6 text-center">
                <p class="text-[13.5px] text-[#78716C]">Nothing learned yet. As this agent answers verified questions and recovers from errors, reusable patterns appear here.</p>
            </div>

            <!-- Groups by kind -->
            <div v-else class="space-y-5">
                <div v-for="grp in grouped" :key="grp.kind"
                     class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,0.04),0_1px_3px_rgba(28,25,23,0.06)]">
                    <div class="px-4 py-3 border-b border-[#F1EFEC] flex items-center justify-between">
                        <h3 class="text-[13.5px] font-semibold text-[#1C1917]">{{ kindLabel(grp.kind) }}</h3>
                        <span class="text-[11px] text-[#A8A29E]">{{ grp.items.length }}</span>
                    </div>
                    <ul class="divide-y divide-[#F5F3F0]">
                        <li v-for="it in grp.items" :key="it.id" class="px-4 py-3">
                            <div class="flex items-start justify-between gap-3">
                                <div class="min-w-0">
                                    <div class="text-[13px] font-medium text-[#1C1917] truncate">{{ it.title || it.kind }}</div>
                                    <div class="text-[12.5px] text-[#57534E] mt-0.5 font-mono break-all">{{ preview(it) }}</div>
                                </div>
                                <div class="flex items-center gap-2 shrink-0">
                                    <span class="text-[10.5px] px-2 py-0.5 rounded-full bg-[#F0FDF4] text-[#3F9B6B] border border-[#BBF7D0]"
                                          :title="`confirmed ${it.verified_count}×`">✓ {{ it.verified_count }}</span>
                                    <span class="text-[10.5px] px-2 py-0.5 rounded-full bg-[#F5F3F0] text-[#78716C] border border-[#EAE8E4]">{{ scopeLabel(it) }}</span>
                                </div>
                            </div>
                        </li>
                    </ul>
                </div>
            </div>
        </template>
    </div>
</template>

<script setup lang="ts">
import { ref, computed, inject, onMounted } from 'vue'
import type { Ref } from 'vue'

definePageMeta({ auth: true, layout: 'data' })

const route = useRoute()
const dsId = computed(() => String(route.params.id || ''))
const injectedFetchError = inject<Ref<number | null>>('fetchError', ref(null))

const loaded = ref(false)
const enabled = ref(false)
const items = ref<any[]>([])

const KIND_LABELS: Record<string, string> = {
    query_template: 'Reusable query patterns',
    dax_template: 'Reusable query patterns',
    meaning: 'Table & column meanings',
    join: 'Join / relationship logic',
    mistake: 'Mistakes to avoid',
    howto: 'How it was done before',
}
function kindLabel(k: string) { return KIND_LABELS[k] || k }

function scopeLabel(it: any) {
    if (it.scope_kind === 'model') return 'shared · model'
    if (it.scope_kind === 'schema') return 'shared · schema'
    if (it.scope_kind === 'file') return 'shared · file'
    if (it.scope_kind === 'user') return 'private'
    return it.scope_kind
}

function preview(it: any) {
    const c = it.content || {}
    if (it.kind === 'mistake') return c.fix_shape || it.text || ''
    return c.template || c.meaning || it.text || ''
}

const grouped = computed(() => {
    const by: Record<string, any> = {}
    for (const it of items.value) {
        const k = (it.kind === 'dax_template') ? 'query_template' : it.kind
        ;(by[k] = by[k] || { kind: k, items: [] }).items.push(it)
    }
    // stable order: patterns, meanings, joins, howtos, mistakes
    const order = ['query_template', 'meaning', 'join', 'howto', 'mistake']
    return Object.values(by).sort((a: any, b: any) => order.indexOf(a.kind) - order.indexOf(b.kind))
})

async function load() {
    try {
        const { data } = await useMyFetch<any>(`/data_sources/${dsId.value}/memory`, { method: 'GET' })
        const v: any = (data as any)?.value ?? data
        enabled.value = !!v?.enabled
        items.value = Array.isArray(v?.items) ? v.items : []
    } catch (_) {
        enabled.value = false; items.value = []
    } finally {
        loaded.value = true
    }
}

onMounted(load)
</script>
