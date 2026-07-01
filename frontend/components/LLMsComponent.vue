<template>
    <div>
        <!-- ===== KEY BANNER (only when no usable API key) ===== -->
        <div v-if="keyLoaded && !hasKey"
             class="flex items-center justify-between gap-3 mb-4 rounded-xl border border-[#E9C9A8] bg-[#FBF1E6] px-4 py-3">
            <div class="flex items-center gap-2.5">
                <UIcon name="i-heroicons-key" class="w-5 h-5 text-[#C2541E] shrink-0" />
                <div>
                    <p class="text-sm font-medium text-[#8a3d12]">No API key set — models are inactive.</p>
                    <p class="text-xs text-[#a4663d]">Add your OpenRouter key to activate all models.</p>
                </div>
            </div>
            <button v-if="useCan('manage_llm_settings')" @click="providerModalOpen = true"
                    class="bg-[#C2541E] hover:bg-[#A8330F] text-white text-sm px-3 py-1.5 rounded-lg shrink-0 whitespace-nowrap">
                Add OpenRouter key
            </button>
        </div>

        <!-- Toolbar: search + Test all + Integrate -->
        <div class="flex justify-between items-center gap-3 mb-5">
            <div class="flex-1 max-w-md">
                <input
                    type="text"
                    v-model="searchQuery"
                    :placeholder="$t('settings.llms.searchPlaceholder')"
                    class="border border-[#E9E0D3] rounded-lg px-3 py-1.5 text-sm focus:ring-[#C2541E] focus:border-[#C2541E] w-full"
                >
            </div>
            <div class="flex items-center gap-2 shrink-0">
                <button
                    @click="testAll"
                    :disabled="testingAll"
                    class="border border-[#E9E0D3] text-[#5a544c] hover:bg-[#FBF8F2] text-sm px-3 py-1.5 rounded-lg disabled:opacity-50 flex items-center gap-1.5"
                >
                    <UIcon :name="testingAll ? 'i-heroicons-arrow-path' : 'i-heroicons-bolt'" :class="testingAll ? 'w-4 h-4 animate-spin' : 'w-4 h-4'" />
                    {{ testingAll ? 'Testing…' : 'Test all' }}
                </button>
                <button
                    v-if="useCan('manage_llm_settings')"
                    @click="providerModalOpen = true"
                    class="bg-[#C2541E] hover:bg-[#A8330F] text-white text-sm px-3 py-1.5 rounded-lg"
                >
                    {{ $t('settings.llms.integrateModels') }}
                </button>
            </div>
        </div>

        <!-- ===== SECTION 1 · PRECONFIGURED ===== -->
        <div class="relative border border-[#E9E0D3] rounded-2xl bg-white p-4 mb-5">
            <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">PRECONFIGURED</span>
            <p class="text-xs text-[#7c7368] mb-3 mt-1">Ship-ready models we set up for you. The default and small-default can't be turned off.</p>
            <table v-if="preconfiguredModels.length" class="min-w-full divide-y divide-[#F0EAE0]">
                <thead>
                    <tr>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide">{{ $t('settings.llms.colModel') }}</th>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide">{{ $t('settings.llms.colProvider') }}</th>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide">{{ $t('settings.llms.colStatus') }}</th>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide">HEALTH</th>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide" v-if="useCan('manage_llm_settings')">{{ $t('settings.llms.colActions') }}</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-[#F0EAE0]">
                    <tr v-for="model in preconfiguredModels" :key="model.id" class="hover:bg-[#FBF8F2]">
                        <td class="px-3 py-3 whitespace-nowrap">
                            <div class="flex items-center">
                                <div class="flex-shrink-0 h-9 w-9 flex items-center justify-center">
                                    <LLMProviderIcon :provider="model.provider.provider_type" :icon="true" class="h-5 w-5" />
                                </div>
                                <div class="ms-3">
                                    <div class="text-sm font-medium text-gray-900">
                                        {{ model.name }}
                                        <span v-if="model.is_default" class="text-xs bg-[#C2541E] text-white px-1.5 py-0.5 rounded-md">{{ $t('settings.llms.badgeDefault') }}</span>
                                        <span v-if="model.is_small_default" class="text-xs bg-green-500 text-white px-1.5 py-0.5 rounded-md ms-1">
                                            <UTooltip :text="$t('settings.llms.smallDefaultTooltip')">{{ $t('settings.llms.badgeSmallDefault') }}</UTooltip>
                                        </span>
                                    </div>
                                    <div v-if="model.model_id !== model.name" class="text-xs text-gray-500">
                                        {{ $t('settings.llms.modelIdLabel') }}: {{ model.model_id }}
                                    </div>
                                </div>
                            </div>
                        </td>
                        <td class="px-3 py-3 whitespace-nowrap text-sm text-gray-500">{{ model.provider.name }}</td>
                        <td class="px-3 py-3 whitespace-nowrap text-sm">
                            <UToggle v-model="model.is_enabled" @change="toggleModel(model.id, $event)" :disabled="!useCan('manage_llm_settings') || model.is_default || model.is_small_default" />
                        </td>
                        <td class="px-3 py-3 whitespace-nowrap text-sm">
                            <button @click="testModel(model.id)" class="flex items-center gap-1.5 text-xs" :title="healthOf(model.id).error || ''">
                                <template v-if="healthOf(model.id).state === 'testing'">
                                    <UIcon name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin text-[#9a958c]" /><span class="text-[#9a958c]">testing…</span>
                                </template>
                                <template v-else-if="healthOf(model.id).state === 'ok'">
                                    <UIcon name="i-heroicons-check-circle-solid" class="w-4 h-4 text-green-600" /><span class="text-green-700">{{ fmtLatency(healthOf(model.id).latency) }}</span>
                                </template>
                                <template v-else-if="healthOf(model.id).state === 'fail'">
                                    <UIcon name="i-heroicons-x-circle-solid" class="w-4 h-4 text-red-500" /><span class="text-red-600">failed</span>
                                </template>
                                <template v-else>
                                    <UIcon name="i-heroicons-play-circle" class="w-4 h-4 text-[#b3ada3]" /><span class="text-[#9a958c] hover:text-[#5a544c]">Test</span>
                                </template>
                            </button>
                        </td>
                        <td class="px-3 py-3 whitespace-nowrap text-sm" v-if="useCan('manage_llm_settings')">
                            <UDropdown :items="getDropdownItems(model)">
                                <UButton class="text-gray-500 hover:text-gray-900" color="white" label="" trailing-icon="i-heroicons-ellipsis-vertical" />
                            </UDropdown>
                        </td>
                    </tr>
                </tbody>
            </table>
            <p v-else class="text-xs text-[#9a958c] py-2">No models match your search.</p>
        </div>

        <!-- ===== SECTION 2 · YOUR MODELS ===== -->
        <div class="relative border border-[#E9E0D3] rounded-2xl bg-white p-4">
            <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">YOUR MODELS</span>
            <p class="text-xs text-[#7c7368] mb-3 mt-1">Models you connect with your own provider and API key.</p>
            <table v-if="customModels.length" class="min-w-full divide-y divide-[#F0EAE0]">
                <thead>
                    <tr>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide">{{ $t('settings.llms.colModel') }}</th>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide">{{ $t('settings.llms.colProvider') }}</th>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide">{{ $t('settings.llms.colStatus') }}</th>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide">HEALTH</th>
                        <th class="px-3 py-2 text-start text-[11px] font-semibold text-[#7c7368] uppercase tracking-wide" v-if="useCan('manage_llm_settings')">{{ $t('settings.llms.colActions') }}</th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-[#F0EAE0]">
                    <tr v-for="model in customModels" :key="model.id" class="hover:bg-[#FBF8F2]">
                        <td class="px-3 py-3 whitespace-nowrap">
                            <div class="flex items-center">
                                <div class="flex-shrink-0 h-9 w-9 flex items-center justify-center">
                                    <LLMProviderIcon :provider="model.provider.provider_type" :icon="true" class="h-5 w-5" />
                                </div>
                                <div class="ms-3">
                                    <div class="text-sm font-medium text-gray-900">
                                        {{ model.name }}
                                        <span v-if="model.is_default" class="text-xs bg-[#C2541E] text-white px-1.5 py-0.5 rounded-md">{{ $t('settings.llms.badgeDefault') }}</span>
                                        <span v-if="model.is_small_default" class="text-xs bg-green-500 text-white px-1.5 py-0.5 rounded-md ms-1">
                                            <UTooltip :text="$t('settings.llms.smallDefaultTooltip')">{{ $t('settings.llms.badgeSmallDefault') }}</UTooltip>
                                        </span>
                                    </div>
                                    <div v-if="model.model_id !== model.name" class="text-xs text-gray-500">
                                        {{ $t('settings.llms.modelIdLabel') }}: {{ model.model_id }}
                                    </div>
                                </div>
                            </div>
                        </td>
                        <td class="px-3 py-3 whitespace-nowrap text-sm text-gray-500">{{ model.provider.name }}</td>
                        <td class="px-3 py-3 whitespace-nowrap text-sm">
                            <UToggle v-model="model.is_enabled" @change="toggleModel(model.id, $event)" :disabled="!useCan('manage_llm_settings') || model.is_default || model.is_small_default" />
                        </td>
                        <td class="px-3 py-3 whitespace-nowrap text-sm">
                            <button @click="testModel(model.id)" class="flex items-center gap-1.5 text-xs" :title="healthOf(model.id).error || ''">
                                <template v-if="healthOf(model.id).state === 'testing'">
                                    <UIcon name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin text-[#9a958c]" /><span class="text-[#9a958c]">testing…</span>
                                </template>
                                <template v-else-if="healthOf(model.id).state === 'ok'">
                                    <UIcon name="i-heroicons-check-circle-solid" class="w-4 h-4 text-green-600" /><span class="text-green-700">{{ fmtLatency(healthOf(model.id).latency) }}</span>
                                </template>
                                <template v-else-if="healthOf(model.id).state === 'fail'">
                                    <UIcon name="i-heroicons-x-circle-solid" class="w-4 h-4 text-red-500" /><span class="text-red-600">failed</span>
                                </template>
                                <template v-else>
                                    <UIcon name="i-heroicons-play-circle" class="w-4 h-4 text-[#b3ada3]" /><span class="text-[#9a958c] hover:text-[#5a544c]">Test</span>
                                </template>
                            </button>
                        </td>
                        <td class="px-3 py-3 whitespace-nowrap text-sm" v-if="useCan('manage_llm_settings')">
                            <UDropdown :items="getDropdownItems(model)">
                                <UButton class="text-gray-500 hover:text-gray-900" color="white" label="" trailing-icon="i-heroicons-ellipsis-vertical" />
                            </UDropdown>
                        </td>
                    </tr>
                </tbody>
            </table>
            <!-- empty: invite to add -->
            <div v-else class="border border-dashed border-[#E9E0D3] rounded-xl p-6 text-center bg-gradient-to-b from-white to-[#fdfcf9]">
                <div class="mx-auto mb-2 flex items-center justify-center w-9 h-9 rounded-lg bg-[#F4EEE5] text-[#C2541E]">
                    <UIcon name="heroicons-plus" class="w-5 h-5" />
                </div>
                <p class="text-sm text-gray-700">{{ searchQuery ? 'No custom models match your search.' : 'No custom models yet.' }}</p>
                <p v-if="!searchQuery" class="text-xs text-[#9a958c] mt-1 mb-3">Connect your own provider and key to add models here.</p>
                <button
                    v-if="useCan('manage_llm_settings') && !searchQuery"
                    @click="providerModalOpen = true"
                    class="bg-[#C2541E] text-white text-sm px-3 py-1.5 rounded-lg hover:bg-[#A8330F]"
                >
                    {{ $t('settings.llms.integrateModels') }}
                </button>
            </div>
        </div>

        <!-- Provider Modal -->
        <LLMProviderModalComponent 
            v-model="providerModalOpen"
            :edit-provider-id="editProviderId"
            @update:modelValue="handleProviderModalClose"
        />

        
    </div>
</template>

<script setup lang="ts">
const props = defineProps({
    organization: {
        type: Object,
        required: true,
    },
});

const { t } = useI18n();
const toast = useToast();
const searchQuery = ref('');

type Provider = { id: string; name: string; provider_type: string };
type Model = {
  id: string;
  name: string;
  model_id: string;
  is_default: boolean;
  is_small_default: boolean;
  is_enabled: boolean;
  is_preset?: boolean;
  is_custom?: boolean;
  provider: Provider;
};

const models = ref<Model[]>([]);
const providers = ref<Provider[]>([]);

const providerModalOpen = ref(false);
const editProviderId = ref<string | null>(null);

const filteredModels = computed<Model[]>(() => {
    const query = searchQuery.value.toLowerCase();
    if (!query) return models.value;

    return models.value.filter(model => {
        return model.name.toLowerCase().includes(query) ||
               model.provider.name.toLowerCase().includes(query);
    });
});

// Preconfigured = the durable backend `is_preset` flag (set by the config seed
// in dash-config.yaml default_llm). Ship-ready models are seeded is_preset=true;
// models a user adds with their own provider are is_preset=false → "Your Models".
// The id-set is a legacy fallback for any row that predates the is_preset flag.
const PRECONFIGURED_MODEL_IDS = new Set<string>([
    'anthropic/claude-haiku-4.5',
    'anthropic/claude-sonnet-4.6',
    'anthropic/claude-sonnet-4',
    'openai/gpt-4o-mini',
    'openai/gpt-5.4-mini',
]);

const isPreconfigured = (m: Model) =>
    m.is_preset === true || m.is_default || m.is_small_default || PRECONFIGURED_MODEL_IDS.has(m.model_id);

const preconfiguredModels = computed<Model[]>(() => filteredModels.value.filter(isPreconfigured));
const customModels = computed<Model[]>(() => filteredModels.value.filter(m => !isPreconfigured(m)));

// ===== Key status (drives the "Add API key" banner) =====
const hasKey = ref(false);
const keyLoaded = ref(false);
const loadKeyStatus = async () => {
    try {
        const res = await useMyFetch<any>('/llm/key_status', { method: 'GET' });
        const d = res.data.value as any;
        hasKey.value = !!(d && d.has_key);
    } catch { hasKey.value = false; }
    finally { keyLoaded.value = true; }
};

// ===== Per-model health (Test / Test all) =====
type Health = { state: 'idle' | 'testing' | 'ok' | 'fail'; latency?: number; error?: string };
const health = ref<Record<string, Health>>({});
const testingAll = ref(false);
const healthOf = (id: string): Health => health.value[id] || { state: 'idle' };
const fmtLatency = (ms?: number) => ms == null ? '' : (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`);

const testModel = async (id: string): Promise<boolean> => {
    health.value = { ...health.value, [id]: { state: 'testing' } };
    try {
        const res = await useMyFetch<any>(`/llm/models/${id}/test`, { method: 'POST' });
        const d = res.data.value as any;
        if (d && d.success) {
            health.value = { ...health.value, [id]: { state: 'ok', latency: d.latency_ms } };
            return true;
        }
        health.value = { ...health.value, [id]: { state: 'fail', error: (d && d.message) || 'Test failed' } };
        return false;
    } catch (e: any) {
        health.value = { ...health.value, [id]: { state: 'fail', error: e?.message || 'Test failed' } };
        return false;
    }
};

const testAll = async () => {
    testingAll.value = true;
    let ok = 0;
    const all = [...preconfiguredModels.value, ...customModels.value];
    for (const m of all) {
        const r = await testModel(m.id);
        if (r) ok++;
    }
    testingAll.value = false;
    toast.add({
        title: `${ok} of ${all.length} models healthy`,
        description: ok === all.length ? 'All models responded.' : (!hasKey.value ? 'Add your API key to activate the rest.' : 'Some models failed — hover the red mark for the error.'),
        icon: ok === all.length ? 'i-heroicons-check-circle' : 'i-heroicons-exclamation-triangle',
        color: ok === all.length ? 'green' : 'orange',
    });
};

const getModels = async () => {
  const response = await useMyFetch<Model[]>('/llm/models', {
      method: 'GET',
  });

  models.value = (response.data.value as unknown as Model[]) || [];
}

const getProviders = async () => {
    const response = await useMyFetch<Provider[]>('/llm/providers', {
        method: 'GET',
    });

    providers.value = (response.data.value as unknown as Provider[]) || [];
}

onMounted(async () => {
    await getModels();
    await loadKeyStatus();
    //await getProviders();
});

const handleProviderModalClose = async (value: boolean) => {
    providerModalOpen.value = value;
    if (!value) {  // Modal is closing
        await getModels();
        editProviderId.value = null;
        // Re-check key status (the user may have just added/changed the key) so
        // the banner clears, then auto-run Test all to light up the health column
        // — only when a usable key is now present.
        const wasKeyless = !hasKey.value;
        await loadKeyStatus();
        if (hasKey.value && wasKeyless) {
            await testAll();
        }
    }
};

const setDefaultModel = async (modelId: string, small = false) => {
    const response = await useMyFetch(`/llm/models/${modelId}/set_default`, {
        method: 'POST',
        query: { small }
    });
    if (response.status.value === 'success') {
        await getModels();
        toast.add({
            title: 'Model updated',
            description: 'Model has been updated successfully',
            color: 'green'
        });
    }
    else {
        toast.add({
            title: 'Error',
            description: 'Could not update model',
            color: 'red'
        });
    }
};

const toggleModel = async (modelId: string, enabled: boolean) => {
    const response = await useMyFetch(`/llm/models/${modelId}/toggle`, {
        method: 'POST',
        query: { enabled }
    });
    if (response.status.value === 'success') {
        await getModels();
        toast.add({
            title: 'Model updated',
            description: 'Model has been updated successfully',
            color: 'green'
        });
    }
    else {
        toast.add({
            title: 'Error',
            description: 'Could not update model',
            color: 'red'
        });
    }
};

const openManageProvider = (providerId: string) => {
    editProviderId.value = providerId;
    providerModalOpen.value = true;
};

const getDropdownItems = (model: Model) => {
    const items: any[][] = [[
        {
            label: t('settings.llms.makeDefault'),
            click: () => {
                setDefaultModel(model.id, false);
            }
        },
        {
            label: t('settings.llms.makeSmallDefault'),
            click: () => {
                setDefaultModel(model.id, true);
            }
        }
    ]];
    if (useCan('manage_llm_settings')) {
        items[0].push({
            label: t('settings.llms.manageProvider'),
            click: () => {
                openManageProvider(model.provider.id);
            }
        });
    }
    return items;
};
</script>
