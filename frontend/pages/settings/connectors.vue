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
                    <div class="w-9 h-9 rounded-lg bg-white border border-[#E9E0D3] flex items-center justify-center p-1.5 shrink-0" :class="isHidden(c.key) ? 'opacity-45' : ''">
                        <img :src="c.icon" :alt="c.name" class="w-full h-full object-contain" />
                    </div>
                    <div class="min-w-0" :class="isHidden(c.key) ? 'opacity-55' : ''">
                        <div class="text-[13.5px] font-semibold text-[#1f2328] leading-tight">{{ c.name }}</div>
                        <div class="text-[11px] text-[#9a958c] mt-0.5">{{ c.desc }}</div>
                    </div>

                    <div class="ms-auto flex items-center gap-3">
                        <!-- Setup-state chip (independent of visibility). -->
                        <span v-if="!c.live" class="text-[11px] font-medium text-[#B9AE9C]">{{ $t('connectors.comingSoon') }}</span>
                        <span
                            v-else
                            class="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded"
                            :class="templateFor(c.key) ? 'text-[#3f9e6a] bg-[#eef6f0]' : 'text-[#9a958c] bg-[#F4EEE5]'"
                        >{{ templateFor(c.key) ? $t('connectors.configured') : $t('connectors.draft') }}</span>

                        <!-- Hidden badge when toggled off. -->
                        <span
                            v-if="isHidden(c.key)"
                            class="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded text-[#8a857c] bg-[#EDE7DC]"
                        >Hidden</span>

                        <!-- Show/Hide on Data Agents — present on EVERY row. -->
                        <UToggle
                            :model-value="!isHidden(c.key)"
                            @update:model-value="setHidden(c.key, !$event)"
                            aria-label="Show on Data Agents"
                            title="Show on Data Agents"
                        />

                        <!-- Configure / Edit — live connectors only. -->
                        <button
                            v-if="c.live"
                            @click="openAdminConfig(c.key)"
                            class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors"
                        >{{ templateFor(c.key) ? $t('common.edit') || 'Edit' : $t('connectors.configure') }}</button>
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
                    <input v-model="cfg.server_hostname" @input="testResult = null" placeholder="xxxxx.datawarehouse.fabric.microsoft.com" class="w-full border border-[#E9E0D3] rounded-lg px-3 py-2 text-sm bg-[#FCFAF6] focus:outline-none focus:border-[#C2541E] mb-3" />
                </template>
                <label class="block text-xs font-semibold text-[#6b6b6b] mb-1">{{ $t('connectors.tenantId') }}</label>
                <input v-model="cfg.tenant_id" @input="testResult = null" placeholder="00000000-0000-0000-0000-000000000000" class="w-full border border-[#E9E0D3] rounded-lg px-3 py-2 text-sm bg-[#FCFAF6] focus:outline-none focus:border-[#C2541E] mb-3" />
                <p class="text-[11px] text-[#9a958c] bg-[#FCFAF6] border border-[#E9E0D3] rounded-lg p-2.5 leading-relaxed">{{ $t('connectors.autoDbNote') }}</p>
                <!-- Test-template result banner. -->
                <div
                    v-if="testResult"
                    class="text-xs rounded-lg p-2.5 mt-2"
                    :class="testResult.ok ? 'text-[#3f9e6a] bg-[#eef6f0]' : 'text-[#B4432B] bg-[#F7E7E2]'"
                >{{ testResult.ok ? '✓' : '✕' }} {{ testResult.reason }}</div>
                <div v-if="adminError" class="text-xs text-[#B4432B] bg-[#F7E7E2] rounded-lg p-2.5 mt-2">{{ adminError }}</div>
                <div class="flex items-center gap-2 mt-4">
                    <!-- Only an already-configured connector can be deleted. -->
                    <button v-if="templateFor(editingKey)" @click="deleteTemplate" :disabled="deleting || publishing" class="text-xs font-medium text-[#a13d3d] hover:bg-[#fdf6f6] px-2.5 py-2 rounded-lg disabled:opacity-50">
                        <Spinner v-if="deleting" class="w-3.5 h-3.5 inline" /> {{ $t('common.delete') || 'Delete' }}
                    </button>
                    <div class="ms-auto flex gap-2 items-center">
                        <button @click="testTemplate" :disabled="testing || publishing" class="text-sm px-3 py-2 rounded-lg bg-white border border-[#E9E0D3] disabled:opacity-50">
                            <span v-if="testing">⟳ Testing…</span>
                            <span v-else>Test</span>
                        </button>
                        <button @click="showAdmin = false" class="text-sm px-3 py-2 rounded-lg bg-white border border-[#E9E0D3]">{{ $t('common.cancel') }}</button>
                        <button
                            v-if="testResult?.ok !== true"
                            @click="publishTemplate"
                            :disabled="publishing"
                            class="text-[11px] text-[#9a958c] hover:text-[#C2541E] underline px-1 disabled:opacity-50"
                        >Save anyway</button>
                        <button @click="publishTemplate" :disabled="publishing || testResult?.ok !== true" class="text-sm px-4 py-2 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] disabled:opacity-50">
                            <Spinner v-if="publishing" class="w-3.5 h-3.5 inline" /> {{ templateFor(editingKey) ? ($t('common.save') || 'Save') : $t('connectors.publish') }}
                        </button>
                    </div>
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

// ---- Show/Hide on Data Agents (per-org key list) ---------------------------
// Visibility is independent of setup state (publish_status). Stored as an array
// of connector keys in organization_settings.config.connectors_hidden — works for
// keyless coming-soon connectors too. GET/PUT the SAME endpoint the general/
// ai-settings pages use; backend MERGES per top-level config key so other config
// (general, ai_features, hybrid_overrides…) is preserved.
const hiddenKeys = ref<string[]>([])

function isHidden(key: string) {
    return hiddenKeys.value.includes(key)
}

async function loadHidden() {
    try {
        const { data } = await useMyFetch('/organization/settings', { method: 'GET' })
        const cfg = (data.value as any)?.config || {}
        hiddenKeys.value = Array.isArray(cfg.connectors_hidden) ? cfg.connectors_hidden : []
    } catch { hiddenKeys.value = [] }
}

async function setHidden(key: string, hidden: boolean) {
    const prev = [...hiddenKeys.value]
    const next = hidden ? [...new Set([...prev, key])] : prev.filter(k => k !== key)
    hiddenKeys.value = next // optimistic
    try {
        const { error } = await useMyFetch('/organization/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config: { connectors_hidden: next } }),
        })
        if (error.value) throw error.value
        toast.add({
            title: hidden ? 'Hidden from Data Agents' : 'Shown on Data Agents',
            color: hidden ? 'orange' : 'green',
            icon: 'i-heroicons-check-circle',
        })
    } catch (e: any) {
        hiddenKeys.value = prev // revert
        toast.add({ title: e?.data?.detail || e?.message || 'Update failed', color: 'red', icon: 'i-heroicons-exclamation-triangle' })
    }
}

async function loadTemplates() {
    try {
        const { data } = await useMyFetch('/connectors/available', { method: 'GET' })
        templates.value = (data.value as any[]) || []
    } catch { templates.value = [] }
}

const showAdmin = ref(false)
const publishing = ref(false)
const deleting = ref(false)
const adminError = ref('')
const testing = ref(false)
const testResult = ref<{ ok: boolean; reason: string } | null>(null)
const cfg = reactive<{ server_hostname: string; tenant_id: string }>({ server_hostname: '', tenant_id: '' })
const editingKey = ref('fabric')
const editingConn = computed(() => catalog.find(c => c.key === editingKey.value) || catalog[0])

function openAdminConfig(key: string) {
    editingKey.value = key
    const tpl = templateFor(key)
    cfg.server_hostname = tpl?.config?.server_hostname || ''
    cfg.tenant_id = tpl?.config?.tenant_id || ''
    adminError.value = ''
    testResult.value = null
    testing.value = false
    showAdmin.value = true
}

// Validate the connector template (tenant / SQL endpoint) before saving. Endpoint
// is provided by a parallel agent; call it by contract. Gates Save on ok===true.
async function testTemplate() {
    testing.value = true
    testResult.value = null
    try {
        const { data, error } = await useMyFetch(`/connectors/${editingKey.value}/test-template`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tenant_id: cfg.tenant_id, server_hostname: cfg.server_hostname || null }),
        })
        if (error.value) throw error.value
        const r = (data.value as any) || {}
        testResult.value = { ok: !!r.ok, reason: r.reason || (r.ok ? 'Connection looks good.' : 'Test failed.') }
    } catch (e: any) {
        testResult.value = { ok: false, reason: 'Could not reach test endpoint' }
    } finally {
        testing.value = false
    }
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
        // Editing an already-configured connector → PATCH the existing data source
        // (PUT /data_sources/{id} propagates config to the backing connection).
        // POSTing again would trip the unique-name-per-org guard ("already exists").
        const existing = templateFor(c.key)
        if (existing) {
            const { error } = await useMyFetch(`/data_sources/${existing.id}`, {
                method: 'PUT',
                body: { config, auth_policy: 'user_required' },
            })
            if (error.value) throw error.value
        } else {
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
        }
        toast.add({ title: t('connectors.published'), color: 'green', icon: 'i-heroicons-check-circle' })
        showAdmin.value = false
        await loadTemplates()
    } catch (e: any) {
        adminError.value = e?.data?.detail || e?.message || t('connectors.publishFailed')
    } finally {
        publishing.value = false
    }
}

async function deleteTemplate() {
    const tpl = templateFor(editingKey.value)
    if (!tpl) return
    if (!confirm(`Delete the ${editingConn.value.name} connector? Members will no longer be able to sign in until it is configured again.`)) return
    deleting.value = true
    adminError.value = ''
    try {
        const { error } = await useMyFetch(`/data_sources/${tpl.id}`, { method: 'DELETE' })
        if (error.value) throw error.value
        toast.add({ title: t('connectors.deleted') || 'Connector deleted', color: 'green', icon: 'i-heroicons-check-circle' })
        showAdmin.value = false
        await loadTemplates()
    } catch (e: any) {
        adminError.value = e?.data?.detail || e?.message || 'Delete failed'
    } finally {
        deleting.value = false
    }
}

onMounted(() => { loadTemplates(); loadHidden() })
</script>
