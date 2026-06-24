<template>
    <div>
        <!-- Header -->
        <div class="mb-6">
            <h1
                class="text-2xl font-semibold text-[#1f2328] tracking-tight"
                style="font-family: ui-serif, Georgia, 'Times New Roman', serif"
            >Feature Flags</h1>
            <p class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">
                Turn hybrid-brain features on or off for this org. Applies live.
            </p>
        </div>

        <!-- Info note -->
        <div class="mb-6 flex items-start gap-2 rounded-xl border border-[#E7E5DD] bg-[#FBFAF6] px-4 py-3">
            <Icon name="heroicons:information-circle" class="w-5 h-5 text-[#C2683F] mt-0.5 flex-shrink-0" />
            <p class="text-sm text-[#6b6b6b]">
                Overrides are stored per-org and beat the <span class="font-mono text-xs bg-[#F4F1EA] px-1.5 py-0.5 rounded">.env</span> default.
            </p>
        </div>

        <!-- Loading state -->
        <div v-if="loading" class="py-8 flex justify-center">
            <ULoader />
        </div>

        <!-- Error message -->
        <UAlert v-else-if="error" type="danger" :description="error" class="mt-2" />

        <!-- Empty state -->
        <div v-else-if="flags.length === 0" class="text-center py-10">
            <div class="mx-auto w-11 h-11 rounded-xl bg-[#F4F1EA] border border-[#E7E5DD] flex items-center justify-center mb-3">
                <Icon name="heroicons:flag" class="w-5 h-5 text-[#C2683F]" />
            </div>
            <p
                class="text-[#1f2328]"
                style="font-family: ui-serif, Georgia, 'Times New Roman', serif"
            >No feature flags</p>
            <p class="text-sm text-[#9a958c] mt-1">No hybrid-brain features are exposed for this org.</p>
        </div>

        <!-- Flags list -->
        <div v-else class="divide-y divide-[#E7E5DD] border border-[#E7E5DD] rounded-2xl overflow-hidden">
            <div
                v-for="row in flags"
                :key="row.env_name"
                class="flex items-center justify-between gap-4 px-4 py-3.5 bg-white"
            >
                <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2 flex-wrap">
                        <span class="font-medium text-[#1f2328]">{{ row.label }}</span>
                        <!-- Role chip -->
                        <span
                            class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
                            :class="roleChipClass(row.role)"
                        >{{ row.role }}</span>
                        <!-- Overridden hint -->
                        <span
                            v-if="row.override !== null"
                            class="inline-flex items-center gap-1 text-[11px] text-[#C2683F]"
                            title="This org has an explicit override that beats the .env default"
                        >
                            <Icon name="heroicons:bolt" class="w-3 h-3" />
                            overridden
                        </span>
                        <span
                            v-else
                            class="text-[11px] text-[#9a958c]"
                            title="Following the .env default"
                        >following default</span>
                    </div>
                    <p class="mt-1 text-xs font-mono text-[#9a958c] truncate">{{ row.env_name }}</p>
                </div>

                <UToggle
                    :model-value="row.effective"
                    :disabled="saving.has(row.env_name)"
                    @update:model-value="(val: boolean) => toggleFlag(row, val)"
                />
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useToast } from '#imports'

interface FlagRow {
    key: string
    env_name: string
    label: string
    role: 'agent' | 'user' | 'review'
    default_env: boolean
    override: boolean | null
    effective: boolean
}

definePageMeta({ auth: true, permissions: ['manage_settings'], layout: 'settings' })

const loading = ref(true)
const error = ref('')
const flags = ref<FlagRow[]>([])
const saving = ref<Set<string>>(new Set())

const toast = useToast()

const roleChipClass = (role: string): string => {
    switch (role) {
        case 'agent':
            return 'bg-violet-50 text-violet-700'
        case 'user':
            return 'bg-[#F6EFEA] text-[#A8542F]'
        case 'review':
            return 'bg-amber-50 text-amber-700'
        default:
            return 'bg-[#F4F1EA] text-[#6b6b6b]'
    }
}

// Fetch the flag list
const fetchFlags = async () => {
    loading.value = true
    error.value = ''
    try {
        const response = await useMyFetch('/api/organization/hybrid-flags')

        if (response.status.value !== 'success') {
            const errorData = response.error?.value?.data || { message: 'Failed to load feature flags.' }
            throw new Error(errorData.message || errorData.detail || 'Failed to load feature flags.')
        }

        const data = response.data.value as FlagRow[]
        flags.value = Array.isArray(data) ? data : []
    } catch (err: any) {
        error.value = err.message || 'Failed to load feature flags.'
        toast.add({
            title: 'Could not load feature flags',
            description: error.value,
            color: 'red',
            timeout: 5000,
            icon: 'i-heroicons-exclamation-circle'
        })
    } finally {
        loading.value = false
    }
}

// Toggle a single flag (optimistic, revert on error)
const toggleFlag = async (row: FlagRow, newValue: boolean) => {
    const previousEffective = row.effective
    const previousOverride = row.override

    // Optimistic update
    row.effective = newValue
    saving.value.add(row.env_name)

    try {
        const response = await useMyFetch(`/api/organization/hybrid-flags/${row.env_name}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ enabled: newValue })
        })

        if (response.status.value !== 'success') {
            const errorData = response.error?.value?.data || { message: 'Failed to update feature flag.' }
            throw new Error(errorData.message || errorData.detail || 'Failed to update feature flag.')
        }

        // Sync from server's authoritative row
        const updated = response.data.value as FlagRow
        if (updated && typeof updated === 'object') {
            Object.assign(row, updated)
        }

        toast.add({
            title: 'Feature flag updated',
            description: `${row.label} ${row.effective ? 'enabled' : 'disabled'}`,
            color: 'green',
            timeout: 3000
        })
    } catch (err: any) {
        // Revert
        row.effective = previousEffective
        row.override = previousOverride

        toast.add({
            title: 'Could not update feature flag',
            description: err.message || 'Failed to update feature flag.',
            color: 'red',
            timeout: 5000,
            icon: 'i-heroicons-exclamation-circle'
        })
    } finally {
        saving.value.delete(row.env_name)
    }
}

onMounted(async () => {
    await fetchFlags()
})
</script>
