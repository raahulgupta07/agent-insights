<template>
    <div class="mt-6">
        <!-- ===== AGENT DEFAULTS ===== -->
        <div class="relative border border-[#E9E0D3] rounded-xl bg-white p-4 mb-6">
            <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">AGENT DEFAULTS</span>

            <div class="flex items-start justify-between gap-3 mt-1">
                <p class="text-xs text-[#7c7368]">Used when an agent doesn't pick its own model.</p>
                <div class="flex items-center gap-2 shrink-0">
                    <span v-if="savedFlash" class="text-xs text-green-600 flex items-center gap-1">
                        <UIcon name="i-heroicons-check-circle" class="w-4 h-4" /> Saved
                    </span>
                    <button
                        @click="saveDefaults"
                        :disabled="savingDefaults"
                        class="bg-[#C2541E] hover:bg-[#A8330F] text-white text-sm px-3 py-1.5 rounded-lg disabled:opacity-50 flex items-center gap-1.5"
                    >
                        <UIcon v-if="savingDefaults" name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin" />
                        {{ savingDefaults ? 'Saving…' : 'Save' }}
                    </button>
                </div>
            </div>

            <div class="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div v-for="row in defaultRows" :key="row.key">
                    <label class="block text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide mb-1">{{ row.label }}</label>
                    <select
                        v-model="agentDefaults[row.key]"
                        class="w-full border border-[#E9E0D3] rounded-lg px-3 py-1.5 text-sm bg-white text-[#2B2A26] focus:ring-[#C2541E] focus:border-[#C2541E]"
                    >
                        <option :value="null">— use system default —</option>
                        <option v-for="m in defaultModelOptions" :key="m.value" :value="m.value">{{ m.label }}</option>
                    </select>
                </div>
            </div>

            <p v-if="defaultsError" class="mt-2 text-xs text-red-600">{{ defaultsError }}</p>
        </div>

        <LLMsComponent :organization="organization" />
    </div>
</template>

<script setup lang="ts">
const { organization } = useOrganization()
definePageMeta({ auth: true, permissions: ['manage_llm'], layout: 'settings' })

const defaultRows = [
    { key: 'analysis' as const, label: 'Analysis model' },
    { key: 'data_train' as const, label: 'Data Agent training' },
    { key: 'studio_train' as const, label: 'Studio Agent training' },
    { key: 'router' as const, label: 'Router / small' },
]

const agentDefaults = reactive<{ analysis: string | null; data_train: string | null; studio_train: string | null; router: string | null }>({
    analysis: null,
    data_train: null,
    studio_train: null,
    router: null,
})
const defaultModelOptions = ref<{ value: string; label: string }[]>([])
const savingDefaults = ref(false)
const savedFlash = ref(false)
const defaultsError = ref('')

const loadDefaultModelOptions = async () => {
    try {
        const { data } = await useMyFetch<any[]>('/llm/models', { method: 'GET' })
        const models = (data.value as any[]) || []
        defaultModelOptions.value = models
            .filter((m: any) => m && m.enabled !== false)
            .map((m: any) => ({ value: (m.model_id || m.id) as string, label: (m.name || m.model_id || m.id) as string }))
    } catch {
        defaultModelOptions.value = []
    }
}

const loadAgentDefaults = async () => {
    try {
        const { data } = await useMyFetch<any>('/llm/defaults', { method: 'GET' })
        const d = (data.value as any) || {}
        agentDefaults.analysis = d.analysis ?? null
        // fall back to the shared `train` default if a per-surface one isn't set yet
        agentDefaults.data_train = d.data_train ?? d.train ?? null
        agentDefaults.studio_train = d.studio_train ?? d.train ?? null
        agentDefaults.router = d.router ?? null
    } catch {
        // fail-soft: leave as system default
    }
}

const saveDefaults = async () => {
    savingDefaults.value = true
    savedFlash.value = false
    defaultsError.value = ''
    try {
        const { error } = await useMyFetch('/llm/defaults', {
            method: 'PUT',
            body: {
                analysis: agentDefaults.analysis,
                data_train: agentDefaults.data_train,
                studio_train: agentDefaults.studio_train,
                // keep the shared `train` key in sync (back-compat consumers)
                train: agentDefaults.data_train,
                router: agentDefaults.router,
            },
        })
        if (error.value) throw error.value
        savedFlash.value = true
        setTimeout(() => { savedFlash.value = false }, 2500)
    } catch (e: any) {
        defaultsError.value = 'Could not save agent defaults. Please try again.'
    } finally {
        savingDefaults.value = false
    }
}

onMounted(async () => {
    await loadDefaultModelOptions()
    await loadAgentDefaults()
})
</script>
