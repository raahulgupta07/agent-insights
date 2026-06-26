<template>
    <section>
        <!-- Header -->
        <div class="flex items-start justify-between mb-4">
            <div>
                <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                    Skills
                </h2>
                <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-2xl">
                    Domain methods bound to this studio's data. Approve a pending skill to let the
                    agent use it, or reject it. Dormant skills are missing a column — add it and
                    re-train. Nothing affects answers until a skill is active.
                </p>
            </div>
            <button
                type="button"
                :disabled="loading"
                class="inline-flex items-center gap-1.5 text-xs text-[#6b6b6b] hover:text-[#1f2328] border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 transition-colors"
                @click="load"
            >
                <Spinner v-if="loading" class="h-3.5 w-3.5" />
                <UIcon v-else name="i-heroicons-arrow-path" class="w-3.5 h-3.5" />
                Refresh
            </button>
        </div>

        <!-- Empty -->
        <div v-if="!loading && !packs.length" class="py-10 text-center border border-dashed border-[#E9E0D3] rounded-2xl">
            <UIcon name="i-heroicons-sparkles" class="w-7 h-7 mx-auto text-[#9a958c] mb-1.5" />
            <p class="text-xs text-[#6b6b6b]">No skills bound yet. Run Auto-train to bind matching domain packs, or paste an analysis in the Teach tab.</p>
        </div>

        <!-- Cards -->
        <div v-if="packs.length" class="space-y-3">
            <div
                v-for="p in sorted"
                :key="p.id"
                class="rounded-2xl border bg-white p-4 transition-colors"
                :class="p.status === 'rejected' ? 'border-[#EFE7DF] opacity-60' : 'border-[#E9E0D3]'"
            >
                <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0 flex-1">
                        <!-- name + status + source + winrate -->
                        <div class="flex items-center gap-2 flex-wrap mb-1.5">
                            <span class="text-sm font-semibold text-[#1f2328] truncate">{{ p.name }}</span>
                            <span class="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border" :class="statusBadge(p.status).cls">
                                <UIcon :name="statusBadge(p.status).icon" class="w-3 h-3" />
                                {{ statusBadge(p.status).label }}
                            </span>
                            <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-[#F4EEE5] border border-[#E9E0D3] text-[#6b6b6b]">{{ sourceLabel(p.source) }}</span>
                            <span v-if="p.conf" class="text-[10px] text-[#9a958c]">bind {{ Math.round((p.conf || 0) * 100) }}%</span>
                            <span
                                v-if="p.winrate && p.winrate.samples"
                                class="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                                :class="(p.winrate.score ?? 1) >= 0.5 ? 'bg-[#E4F1EA] text-[#2f7d53]' : 'bg-[#FBE4E4] text-[#A83F3F]'"
                                :title="`${p.winrate.samples} vote(s)`"
                            >
                                {{ Math.round((p.winrate.score || 0) * 100) }}% win · {{ p.winrate.samples }}
                            </span>
                        </div>

                        <!-- binding -->
                        <div v-if="Object.keys(p.binding || {}).length" class="text-[11px] text-[#6b6b6b] mb-1">
                            <span class="text-[#9a958c]">maps:</span>
                            <code
                                v-for="(col, key) in p.binding"
                                :key="key"
                                class="inline-block ms-1 mb-1 bg-[#F4EEE5] border border-[#E9E0D3] rounded px-1.5 py-0.5"
                            >{{ key }} → {{ col }}</code>
                        </div>

                        <!-- missing (dormant) -->
                        <div v-if="(p.missing || []).length" class="text-[11px] text-[#A8330F] mb-1">
                            <UIcon name="i-heroicons-exclamation-triangle" class="w-3 h-3 inline -mt-0.5" />
                            needs a column for: {{ p.missing.join(', ') }} — add it and re-train.
                        </div>

                        <!-- method snippet -->
                        <button v-if="p.method_text" type="button" class="text-[11px] text-[#37618A] hover:underline" @click="p._open = !p._open">
                            {{ p._open ? 'Hide method' : 'Show method' }}
                        </button>
                        <pre v-if="p._open && p.method_text" class="mt-1.5 text-[11px] text-[#4a4a4a] bg-[#FAF8F3] border border-[#E9E0D3] rounded-lg p-2.5 whitespace-pre-wrap leading-relaxed">{{ p.method_text }}</pre>
                    </div>

                    <!-- actions -->
                    <div v-if="canEdit" class="flex flex-col items-end gap-1.5 shrink-0">
                        <button
                            v-if="p.status !== 'active' && !(p.missing || []).length"
                            type="button"
                            :disabled="p._busy"
                            class="inline-flex items-center gap-1 text-[11px] font-semibold text-white bg-[#3f9e6a] hover:bg-[#357f57] rounded-lg px-2.5 py-1 transition-colors disabled:opacity-50"
                            @click="setStatus(p, 'active')"
                        >
                            <UIcon name="i-heroicons-check" class="w-3.5 h-3.5" /> Approve
                        </button>
                        <button
                            v-if="p.status === 'active'"
                            type="button"
                            :disabled="p._busy"
                            class="inline-flex items-center gap-1 text-[11px] text-[#6b6b6b] hover:text-[#1f2328] border border-[#E9E0D3] rounded-lg px-2.5 py-1 transition-colors"
                            @click="setStatus(p, 'pending')"
                        >
                            <UIcon name="i-heroicons-pause" class="w-3.5 h-3.5" /> Deactivate
                        </button>
                        <button
                            v-if="p.status !== 'rejected'"
                            type="button"
                            :disabled="p._busy"
                            class="inline-flex items-center gap-1 text-[11px] text-[#A83F3F] hover:text-[#822f2f] border border-[#EAD4D4] rounded-lg px-2.5 py-1 transition-colors"
                            @click="setStatus(p, 'rejected')"
                        >
                            <UIcon name="i-heroicons-x-mark" class="w-3.5 h-3.5" /> Reject
                        </button>
                        <button
                            v-if="p.status === 'rejected'"
                            type="button"
                            :disabled="p._busy"
                            class="inline-flex items-center gap-1 text-[11px] text-[#6b6b6b] hover:text-[#1f2328] border border-[#E9E0D3] rounded-lg px-2.5 py-1 transition-colors"
                            @click="setStatus(p, 'pending')"
                        >
                            <UIcon name="i-heroicons-arrow-uturn-left" class="w-3.5 h-3.5" /> Restore
                        </button>
                        <button
                            v-if="p.promotable"
                            type="button"
                            :disabled="p._busy"
                            class="inline-flex items-center gap-1 text-[11px] text-[#37618A] hover:text-[#27486a] border border-[#CFE0EE] rounded-lg px-2.5 py-1 transition-colors"
                            title="Share this skill with every studio in the org"
                            @click="promote(p)"
                        >
                            <UIcon name="i-heroicons-building-office-2" class="w-3.5 h-3.5" /> Promote to org
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </section>
</template>

<script setup lang="ts">
const props = defineProps<{ studioId: string; sources?: any[]; canEdit: boolean }>()
const toast = useToast()

const loading = ref(false)
const packs = ref<any[]>([])

const _order: Record<string, number> = { active: 0, pending: 1, dormant: 2, rejected: 3 }
const sorted = computed(() =>
    [...packs.value].sort((a, b) => (_order[a.status] ?? 9) - (_order[b.status] ?? 9))
)

function statusBadge(s: string) {
    switch (s) {
        case 'active': return { label: 'Active', icon: 'i-heroicons-check-circle', cls: 'border-[#CFE0CF] bg-[#EEF5EE] text-[#2f7d53]' }
        case 'pending': return { label: 'Pending', icon: 'i-heroicons-clock', cls: 'border-[#E8C9B5] bg-[#F6EFEA] text-[#A8330F]' }
        case 'dormant': return { label: 'Dormant', icon: 'i-heroicons-moon', cls: 'border-[#E9E0D3] bg-[#F4EEE5] text-[#6b6b6b]' }
        case 'rejected': return { label: 'Rejected', icon: 'i-heroicons-x-circle', cls: 'border-[#EAD4D4] bg-[#FBF2F2] text-[#A83F3F]' }
        default: return { label: s, icon: 'i-heroicons-tag', cls: 'border-[#E9E0D3] bg-[#F4EEE5] text-[#6b6b6b]' }
    }
}

function sourceLabel(src: string) {
    return src === 'user' ? 'authored' : src === 'org' ? 'org-shared' : 'library'
}

async function load() {
    if (loading.value) return
    loading.value = true
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/packs`)
        if (error.value) throw error.value
        const list: any[] = ((data.value as any)?.packs) || []
        packs.value = list.map(p => ({ ...p, _busy: false, _open: false }))
    } catch (e: any) {
        toast.add({ title: 'Could not load skills', description: String(e?.data?.detail || e?.message || e), color: 'red', icon: 'i-heroicons-exclamation-triangle' })
    } finally {
        loading.value = false
    }
}

async function setStatus(p: any, status: string) {
    if (p._busy) return
    p._busy = true
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/packs/${p.pack_id}/status`, {
            method: 'POST',
            body: { status },
        })
        if (error.value) throw error.value
        p.status = status
        toast.add({ title: `Skill ${status === 'active' ? 'approved' : status}`, color: status === 'rejected' ? 'orange' : 'green', icon: 'i-heroicons-check-circle' })
    } catch (e: any) {
        toast.add({ title: 'Update failed', description: String(e?.data?.detail || e?.message || e), color: 'red', icon: 'i-heroicons-exclamation-triangle' })
    } finally {
        p._busy = false
    }
}

async function promote(p: any) {
    if (p._busy) return
    p._busy = true
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/packs/${p.pack_id}/promote`, {
            method: 'POST',
        })
        if (error.value) throw error.value
        toast.add({ title: 'Promoted to org', description: 'Every studio in the org will bind it on its next train.', color: 'green', icon: 'i-heroicons-building-office-2' })
    } catch (e: any) {
        toast.add({ title: 'Promote failed', description: String(e?.data?.detail || e?.message || e), color: 'red', icon: 'i-heroicons-exclamation-triangle' })
    } finally {
        p._busy = false
    }
}

onMounted(load)
</script>
