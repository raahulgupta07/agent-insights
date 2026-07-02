<template>
    <div>
        <!-- Guard: only manage_connections (super-admin) can configure templates. -->
        <div v-if="!canManage" class="text-sm text-[#6b6b6b] py-8 text-center">
            {{ $t('connectors.askAdmin') }}
        </div>

        <div v-else>
            <p class="text-sm text-[#6b6b6b] leading-relaxed mb-5 max-w-2xl">
                Configure each Microsoft connector once (tenant, SQL endpoint). Members then sign in with their
                own account on the <NuxtLink to="/agents" class="text-[#C2541E] font-medium hover:underline">Data Agents</NuxtLink>
                page — no per-user setup, no shared passwords.
            </p>

            <div class="space-y-2.5">
                <div
                    v-for="c in catalog"
                    :key="c.key"
                    class="flex items-center gap-3 p-3.5 rounded-xl border border-[#E9E0D3] bg-white"
                >
                    <div class="w-9 h-9 rounded-lg bg-white border border-[#E9E0D3] flex items-center justify-center p-1.5 shrink-0">
                        <img :src="c.icon" :alt="c.name" class="w-full h-full object-contain" />
                    </div>
                    <div class="min-w-0">
                        <div class="text-[13.5px] font-semibold text-[#1f2328] leading-tight">{{ c.name }}</div>
                        <div class="text-[11px] text-[#9a958c] mt-0.5">{{ c.desc }}</div>
                    </div>

                    <div class="ms-auto flex items-center gap-3">
                        <span v-if="!c.live" class="text-[11px] font-medium text-[#B9AE9C]">{{ $t('connectors.comingSoon') }}</span>
                        <template v-else>
                            <span
                                class="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded"
                                :class="templateFor(c.key) ? 'text-[#3f9e6a] bg-[#eef6f0]' : 'text-[#9a958c] bg-[#F4EEE5]'"
                            >{{ templateFor(c.key) ? $t('connectors.configured') : $t('connectors.draft') }}</span>
                            <button
                                @click="openAdminConfig(c.key)"
                                class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors"
                            >{{ templateFor(c.key) ? $t('common.edit') || 'Edit' : $t('connectors.configure') }}</button>
                        </template>
                    </div>
                </div>
            </div>
        </div>

        <!-- CONFIG MODAL -->
        <UModal v-model="showAdmin">
            <div class="p-6">
                <h3 class="text-lg text-[#1f2328] mb-1" style="font-family:'Spectral',serif">{{ $t('connectors.configureName', { name: editingConn.name }) }}</h3>
                <p class="text-xs text-[#6b6b6b] mb-4">{{ $t('connectors.configureHint') }}</p>
                <template v-if="editingConn.fields.includes('server_hostname')">
                    <label class="block text-xs font-semibold text-[#6b6b6b] mb-1">{{ $t('connectors.sqlEndpoint') }}</label>
                    <input v-model="cfg.server_hostname" placeholder="xxxxx.datawarehouse.fabric.microsoft.com" class="w-full border border-[#E9E0D3] rounded-lg px-3 py-2 text-sm bg-[#FCFAF6] focus:outline-none focus:border-[#C2541E] mb-3" />
                </template>
                <label class="block text-xs font-semibold text-[#6b6b6b] mb-1">{{ $t('connectors.tenantId') }}</label>
                <input v-model="cfg.tenant_id" placeholder="00000000-0000-0000-0000-000000000000" class="w-full border border-[#E9E0D3] rounded-lg px-3 py-2 text-sm bg-[#FCFAF6] focus:outline-none focus:border-[#C2541E] mb-3" />
                <p class="text-[11px] text-[#9a958c] bg-[#FCFAF6] border border-[#E9E0D3] rounded-lg p-2.5 leading-relaxed">{{ $t('connectors.autoDbNote') }}</p>
                <div v-if="adminError" class="text-xs text-[#B4432B] bg-[#F7E7E2] rounded-lg p-2.5 mt-2">{{ adminError }}</div>
                <div class="flex justify-end gap-2 mt-4">
                    <button @click="showAdmin = false" class="text-sm px-3 py-2 rounded-lg bg-white border border-[#E9E0D3]">{{ $t('common.cancel') }}</button>
                    <button @click="publishTemplate" :disabled="publishing" class="text-sm px-4 py-2 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] disabled:opacity-50">
                        <Spinner v-if="publishing" class="w-3.5 h-3.5 inline" /> {{ $t('connectors.publish') }}
                    </button>
                </div>
            </div>
        </UModal>
    </div>
</template>

<script lang="ts" setup>
import Spinner from '~/components/Spinner.vue'
import { useCan } from '~/composables/usePermissions'

definePageMeta({ auth: true, layout: 'settings' })

const { t } = useI18n()
const toast = useToast()
const canManage = computed(() => useCan('manage_connections'))

const templates = ref<any[]>([])

// Mirror of the connect-hub catalog: what the admin sets ONCE per connector.
const catalog = [
    { key: 'fabric', type: 'ms_fabric', name: 'Microsoft Fabric', icon: '/data_sources_icons/ms_fabric.png', desc: 'Lakehouse & warehouse SQL endpoint.', live: true, fields: ['server_hostname', 'tenant_id'] },
    { key: 'powerbi', type: 'powerbi_user', name: 'Power BI (User Sign-in)', icon: '/data_sources_icons/powerbi.png', desc: 'Datasets & reports — each user sees their own.', live: true, fields: ['tenant_id'] },
    { key: 'sharepoint', type: 'sharepoint', name: 'SharePoint', icon: '/data_sources_icons/sharepoint.png', desc: 'Sites, docs & lists.', live: false, fields: ['tenant_id'] },
    { key: 'onedrive', type: 'onedrive', name: 'OneDrive', icon: '/data_sources_icons/onedrive.png', desc: 'Your personal files.', live: false, fields: ['tenant_id'] },
]

function templateFor(key: string) {
    const type = catalog.find(c => c.key === key)?.type
    return templates.value.find(tp => tp.type === type) || null
}

async function loadTemplates() {
    try {
        const { data } = await useMyFetch('/connectors/available', { method: 'GET' })
        templates.value = (data.value as any[]) || []
    } catch { templates.value = [] }
}

const showAdmin = ref(false)
const publishing = ref(false)
const adminError = ref('')
const cfg = reactive<{ server_hostname: string; tenant_id: string }>({ server_hostname: '', tenant_id: '' })
const editingKey = ref('fabric')
const editingConn = computed(() => catalog.find(c => c.key === editingKey.value) || catalog[0])

function openAdminConfig(key: string) {
    editingKey.value = key
    const tpl = templateFor(key)
    cfg.server_hostname = tpl?.config?.server_hostname || ''
    cfg.tenant_id = tpl?.config?.tenant_id || ''
    adminError.value = ''
    showAdmin.value = true
}

async function publishTemplate() {
    publishing.value = true
    adminError.value = ''
    try {
        const c = editingConn.value
        // Database is NEVER set here — auto-discovered from what each user can
        // access at sign-in.
        const config: any = {}
        if (c.fields.includes('server_hostname')) config.server_hostname = cfg.server_hostname.trim()
        config.tenant_id = cfg.tenant_id.trim() || null
        const body = {
            name: c.name,
            type: c.type,
            config,
            auth_policy: 'user_required',
            allowed_user_auth_modes: ['device_code'],
            is_user_template: true,
        }
        const { error } = await useMyFetch('/data_sources', { method: 'POST', body })
        if (error.value) throw error.value
        toast.add({ title: t('connectors.published'), color: 'green', icon: 'i-heroicons-check-circle' })
        showAdmin.value = false
        await loadTemplates()
    } catch (e: any) {
        adminError.value = e?.data?.detail || e?.message || t('connectors.publishFailed')
    } finally {
        publishing.value = false
    }
}

onMounted(loadTemplates)
</script>
