<template>
    <div>
        <!-- Header -->
        <div class="mb-6">
            <h1
                class="text-[32px] font-medium text-[#211B14] tracking-tight"
                style="font-family: 'Spectral', ui-serif, Georgia, serif"
            >Feature Flags</h1>
            <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">
                Turn features on or off for this org. Applies live — no restart for most.
                Per-org overrides beat the <span class="font-mono text-xs bg-[#F4EEE5] px-1.5 py-0.5 rounded">.env</span> default.
            </p>
        </div>

        <!-- Controls -->
        <div v-if="!loading && !error" class="mb-5 flex flex-col sm:flex-row sm:items-center gap-3">
            <div class="relative flex-1 max-w-sm">
                <Icon name="heroicons:magnifying-glass" class="absolute start-3 top-2.5 w-4 h-4 text-[#9a958c]" />
                <input
                    v-model="search"
                    type="text"
                    placeholder="Search features…"
                    class="w-full ps-9 pe-3 py-2 text-sm border border-[#E9E0D3] rounded-lg focus:outline-none focus:ring-2 focus:ring-[#C2541E] focus:border-[#C2541E]"
                />
            </div>
            <USelectMenu
                v-model="statusFilter"
                :options="statusFilterOptions"
                value-attribute="value"
                option-attribute="label"
                size="sm"
                class="w-40"
            />
            <span class="text-sm text-[#9a958c] sm:ms-auto">{{ onCount }} / {{ flags.length }} on</span>
        </div>

        <!-- Loading -->
        <div v-if="loading" class="py-8 flex justify-center">
            <Spinner class="w-5 h-5 text-[#9a958c]" />
        </div>

        <!-- Error -->
        <UAlert v-else-if="error" type="danger" :description="error" class="mt-2" />

        <!-- Empty -->
        <div v-else-if="flags.length === 0" class="text-center py-10">
            <div class="mx-auto w-11 h-11 rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] flex items-center justify-center mb-3">
                <Icon name="heroicons:flag" class="w-5 h-5 text-[#C2541E]" />
            </div>
            <p class="text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">No feature flags</p>
        </div>

        <!-- No search results -->
        <div v-else-if="groupedFlags.length === 0" class="text-center py-10 text-sm text-[#9a958c]">
            No features match “{{ search }}”.
        </div>

        <!-- Grouped flag list -->
        <div v-else class="space-y-6">
            <section v-for="group in groupedFlags" :key="group.category">
                <div class="flex items-center gap-2 mb-2">
                    <h2 class="text-[11px] font-semibold text-[#9a958c] uppercase tracking-wider">{{ group.category }}</h2>
                    <span class="text-[11px] text-[#bcb8b0]">{{ group.rows.filter(r => r.effective).length }}/{{ group.rows.length }}</span>
                </div>
                <div class="divide-y divide-[#E9E0D3] border border-[#E9E0D3] rounded-2xl overflow-hidden">
                    <div
                        v-for="row in group.rows"
                        :key="row.env_name"
                        class="flex items-center justify-between gap-4 px-4 py-3.5 bg-white"
                    >
                        <div class="min-w-0 flex-1">
                            <div class="flex items-center gap-2 flex-wrap">
                                <span class="font-medium text-[#1f2328]">{{ row.label }}</span>
                                <!-- Role chip -->
                                <span class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium" :class="roleChipClass(row.role)">{{ row.role }}</span>
                                <!-- Status badge (non-stable only) -->
                                <span
                                    v-if="row.status && row.status !== 'stable'"
                                    class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium"
                                    :class="statusChipClass(row.status)"
                                    :title="row.note || statusLabel(row.status)"
                                >
                                    <Icon :name="statusIcon(row.status)" class="w-3 h-3" />
                                    {{ statusLabel(row.status) }}
                                </span>
                                <!-- Override hint -->
                                <span v-if="row.override !== null" class="inline-flex items-center gap-1 text-[11px] text-[#C2541E]" title="This org has an explicit override that beats the .env default">
                                    <Icon name="heroicons:bolt" class="w-3 h-3" /> overridden
                                </span>
                                <span v-else class="text-[11px] text-[#9a958c]" title="Following the .env default">following default</span>
                            </div>
                            <p v-if="row.note" class="mt-1 text-xs text-[#6b6b6b]">{{ row.note }}</p>
                            <p class="mt-0.5 text-xs font-mono text-[#bcb8b0] truncate">{{ row.env_name }}</p>

                            <!-- Hybrid Search: index controls (only this row, only when on) -->
                            <div v-if="row.env_name === 'HYBRID_SEMANTIC_SEARCH' && row.effective" class="mt-2 flex items-center gap-3">
                                <UButton size="2xs" color="gray" variant="solid" :loading="reindexing" icon="i-heroicons-arrow-path" @click="rebuildIndex">
                                    Rebuild search index
                                </UButton>
                                <span v-if="indexStatus" class="text-[11px] text-[#9a958c]">
                                    {{ indexStatus.indexed }} indexed · {{ indexStatus.embed_model }}
                                </span>
                            </div>
                        </div>

                        <UToggle
                            :model-value="row.effective"
                            :disabled="saving.has(row.env_name)"
                            @update:model-value="(val: boolean) => onToggle(row, val)"
                        />
                    </div>
                </div>
            </section>
        </div>

        <!-- Confirm dialog for risky flags -->
        <UModal v-model="confirmOpen">
            <div class="p-5">
                <div class="flex items-start gap-3">
                    <div class="mt-0.5 flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center" :class="confirmRow?.status === 'unstable' ? 'bg-red-50' : 'bg-amber-50'">
                        <Icon name="heroicons:exclamation-triangle" class="w-5 h-5" :class="confirmRow?.status === 'unstable' ? 'text-red-500' : 'text-amber-500'" />
                    </div>
                    <div class="min-w-0">
                        <h3 class="text-base font-medium text-[#1f2328]">Enable “{{ confirmRow?.label }}”?</h3>
                        <p class="mt-1 text-sm text-[#6b6b6b]">{{ confirmRow?.note || 'This feature may change agent behaviour.' }}</p>
                    </div>
                </div>
                <div class="mt-5 flex justify-end gap-2">
                    <UButton color="gray" variant="ghost" @click="cancelConfirm">Cancel</UButton>
                    <UButton :color="confirmRow?.status === 'unstable' ? 'red' : 'primary'" @click="applyConfirm">Enable anyway</UButton>
                </div>
            </div>
        </UModal>
    </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useToast } from '#imports'
import Spinner from '@/components/Spinner.vue'

interface FlagRow {
    key: string
    env_name: string
    label: string
    role: 'agent' | 'user' | 'review'
    category: string
    status: 'stable' | 'experimental' | 'needs_dep' | 'unstable' | 'daemon'
    note: string
    default_env: boolean
    override: boolean | null
    effective: boolean
}

definePageMeta({ auth: true, permissions: ['manage_settings'], layout: 'settings' })

const loading = ref(true)
const error = ref('')
const flags = ref<FlagRow[]>([])
const saving = ref<Set<string>>(new Set())
const search = ref('')
const statusFilter = ref<'all' | 'on' | 'off'>('all')
const toast = useToast()

const statusFilterOptions = [
    { value: 'all', label: 'All' },
    { value: 'on', label: 'Enabled' },
    { value: 'off', label: 'Disabled' },
]

const onCount = computed(() => flags.value.filter(f => f.effective).length)

// Filter by search + on/off, then group by category preserving API order.
const groupedFlags = computed(() => {
    const q = search.value.trim().toLowerCase()
    const filtered = flags.value.filter(f => {
        if (statusFilter.value === 'on' && !f.effective) return false
        if (statusFilter.value === 'off' && f.effective) return false
        if (!q) return true
        return f.label.toLowerCase().includes(q)
            || f.env_name.toLowerCase().includes(q)
            || f.category.toLowerCase().includes(q)
    })
    const order: string[] = []
    const map: Record<string, FlagRow[]> = {}
    for (const f of filtered) {
        if (!map[f.category]) { map[f.category] = []; order.push(f.category) }
        map[f.category].push(f)
    }
    return order.map(category => ({ category, rows: map[category] }))
})

const roleChipClass = (role: string): string => {
    switch (role) {
        case 'agent': return 'bg-violet-50 text-violet-700'
        case 'user': return 'bg-[#F6EFEA] text-[#A8330F]'
        case 'review': return 'bg-amber-50 text-amber-700'
        default: return 'bg-[#F4EEE5] text-[#6b6b6b]'
    }
}

const statusLabel = (s: string): string => ({
    experimental: 'experimental',
    needs_dep: 'needs setup',
    unstable: 'unstable',
    daemon: 'needs restart',
} as Record<string, string>)[s] || s

const statusIcon = (s: string): string => ({
    experimental: 'heroicons:beaker',
    needs_dep: 'heroicons:wrench',
    unstable: 'heroicons:no-symbol',
    daemon: 'heroicons:arrow-path',
} as Record<string, string>)[s] || 'heroicons:information-circle'

const statusChipClass = (s: string): string => ({
    experimental: 'bg-sky-50 text-sky-700',
    needs_dep: 'bg-amber-50 text-amber-700',
    unstable: 'bg-red-50 text-red-600',
    daemon: 'bg-slate-100 text-slate-600',
} as Record<string, string>)[s] || 'bg-[#F4EEE5] text-[#6b6b6b]'

// Confirm gate for risky enables (unstable / needs setup).
const confirmOpen = ref(false)
const confirmRow = ref<FlagRow | null>(null)

const onToggle = (row: FlagRow, newValue: boolean) => {
    if (newValue && (row.status === 'unstable' || row.status === 'needs_dep')) {
        confirmRow.value = row
        confirmOpen.value = true
        return
    }
    toggleFlag(row, newValue)
}

const cancelConfirm = () => { confirmOpen.value = false; confirmRow.value = null }
const applyConfirm = () => {
    const row = confirmRow.value
    confirmOpen.value = false
    confirmRow.value = null
    if (row) toggleFlag(row, true)
}

const fetchFlags = async () => {
    loading.value = true
    error.value = ''
    try {
        const response = await useMyFetch('/api/organization/hybrid-flags')
        if (response.status.value !== 'success') {
            const e = response.error?.value?.data || { message: 'Failed to load feature flags.' }
            throw new Error(e.message || e.detail || 'Failed to load feature flags.')
        }
        const data = response.data.value as FlagRow[]
        flags.value = Array.isArray(data) ? data : []
    } catch (err: any) {
        error.value = err.message || 'Failed to load feature flags.'
        toast.add({ title: 'Could not load feature flags', description: error.value, color: 'red', timeout: 5000, icon: 'i-heroicons-exclamation-circle' })
    } finally {
        loading.value = false
    }
}

const toggleFlag = async (row: FlagRow, newValue: boolean) => {
    const prevEffective = row.effective
    const prevOverride = row.override
    row.effective = newValue
    saving.value.add(row.env_name)
    try {
        const response = await useMyFetch(`/api/organization/hybrid-flags/${row.env_name}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: newValue }),
        })
        if (response.status.value !== 'success') {
            const e = response.error?.value?.data || { message: 'Failed to update feature flag.' }
            throw new Error(e.message || e.detail || 'Failed to update feature flag.')
        }
        const updated = response.data.value as FlagRow
        if (updated && typeof updated === 'object') Object.assign(row, updated)
        const restartNote = row.status === 'daemon' ? ' (restart to take effect)' : ''
        toast.add({ title: 'Feature flag updated', description: `${row.label} ${row.effective ? 'enabled' : 'disabled'}${restartNote}`, color: 'green', timeout: 3000 })
    } catch (err: any) {
        row.effective = prevEffective
        row.override = prevOverride
        toast.add({ title: 'Could not update feature flag', description: err.message || 'Failed to update feature flag.', color: 'red', timeout: 5000, icon: 'i-heroicons-exclamation-circle' })
    } finally {
        saving.value.delete(row.env_name)
    }
}

// --- Hybrid Search index controls ---
const reindexing = ref(false)
const indexStatus = ref<{ indexed: number; embed_model: string; enabled: boolean } | null>(null)

const fetchIndexStatus = async () => {
    try {
        const r = await useMyFetch('/api/knowledge/search-index/status')
        if (r.status.value === 'success') indexStatus.value = r.data.value as any
    } catch { /* ignore */ }
}

const rebuildIndex = async () => {
    reindexing.value = true
    try {
        const r = await useMyFetch('/api/knowledge/reindex', { method: 'POST' })
        if (r.status.value !== 'success') throw new Error('Reindex failed')
        const s = r.data.value as any
        toast.add({ title: 'Search index rebuilt', description: `${s.indexed ?? 0} indexed, ${s.embedded ?? 0} embedded`, color: 'green', timeout: 4000 })
        await fetchIndexStatus()
    } catch (e: any) {
        toast.add({ title: 'Reindex failed', description: e.message || 'Could not rebuild search index', color: 'red', timeout: 5000 })
    } finally {
        reindexing.value = false
    }
}

onMounted(async () => {
    await fetchFlags()
    await fetchIndexStatus()
})
</script>
