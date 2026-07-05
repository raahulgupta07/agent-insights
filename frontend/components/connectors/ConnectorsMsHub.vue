<template>
    <div v-if="enabled" class="mb-8">
        <!-- Quiet section label — no admin buttons here; config lives in
             Settings › Connectors (super-admin). -->
        <div class="flex items-center gap-3 mb-3">
            <span class="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#A89C8C]">{{ $t('connectors.hubTitle') }}</span>
            <div class="h-px flex-1 bg-[#E9E0D3]"></div>
        </div>

        <!-- No LLM key → connecting a source can't create a usable agent. Card + gated actions below. -->
        <div v-if="!llmConfigured" class="mb-4 flex items-start gap-2.5 rounded-xl bg-[#FBF1DD] border border-[#E9D5A8] text-[#8A5A12] px-3.5 py-3">
            <UIcon name="i-heroicons-exclamation-triangle" class="w-4 h-4 mt-0.5 shrink-0 text-[#B4791E]" />
            <div class="min-w-0 flex-1">
                <p class="text-[12px] font-semibold leading-snug">LLM not configured</p>
                <p class="text-[11px] leading-snug mt-0.5 text-[#9A6A1E]">An admin must add a model key in Settings → Models before you can create agents.</p>
            </div>
            <NuxtLink to="/settings/models" class="ml-2 shrink-0 self-center text-[11px] font-semibold text-[#8A5A12] hover:underline whitespace-nowrap">Open Settings →</NuxtLink>
        </div>

        <!-- Connector tiles. Members see: logo · name · status · one action.
             Super-admins ALSO get a hover gear + config chip + "Set up".
             Config is gated on manage_connections — members' DOM never has it. -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div
                v-for="c in visibleCatalog"
                :key="c.key"
                class="group relative p-4 rounded-2xl border bg-white transition-all duration-200"
                :class="isReady(c) ? 'border-[#E9E0D3] hover:-translate-y-0.5 hover:shadow-md hover:border-[#C2541E]/30' : 'border-[#EFE7DA] opacity-80'"
            >
                <!-- ADMIN gear (hover-reveal) -->
                <button
                    v-if="canManage && c.live"
                    @click.stop="openAdminConfig(c.key)"
                    :title="templateFor(c.key) ? $t('common.edit') : $t('connectors.configure')"
                    class="absolute top-3 right-3 w-7 h-7 grid place-items-center rounded-lg text-[#9a958c] opacity-0 group-hover:opacity-100 hover:bg-[#F4EEE5] hover:text-[#C2541E] transition"
                >
                    <UIcon name="i-heroicons-cog-6-tooth" class="w-4 h-4" />
                </button>

                <div class="flex items-center gap-2.5 mb-2.5 pe-6">
                    <div class="w-9 h-9 rounded-xl bg-white border border-[#E9E0D3] flex items-center justify-center p-1.5 shrink-0">
                        <img :src="c.icon" :alt="c.name" class="w-full h-full object-contain" />
                    </div>
                    <h3 class="text-[13.5px] font-semibold text-[#1f2328] leading-tight">{{ c.name }}</h3>
                </div>

                <!-- ADMIN config chip -->
                <div v-if="canManage && c.live" class="mb-2">
                    <span
                        class="inline-flex items-center gap-1 text-[9.5px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded"
                        :class="templateFor(c.key) ? 'text-[#3f9e6a] bg-[#eef6f0]' : 'text-[#B85C2E] bg-[#FBEFE4]'"
                    >
                        <span class="w-1 h-1 rounded-full" :class="templateFor(c.key) ? 'bg-[#3f9e6a]' : 'bg-[#D67037]'"></span>
                        {{ templateFor(c.key) ? $t('connectors.configured') : 'Needs setup' }}
                    </span>
                </div>

                <!-- CONNECTED — already signed in; do NOT offer a fresh "Sign in"
                     (that spawned duplicate agents). Open / Re-sync the existing one;
                     a new agent only via the explicit "another account" path. -->
                <template v-if="readyCloneFor(c.key)">
                    <div class="text-[11px] flex items-center gap-1.5 font-semibold text-[#3f9e6a] mb-3">
                        <span class="w-1.5 h-1.5 rounded-full bg-[#3f9e6a]"></span>{{ $t('connectors.connected') }} · {{ ownerLabel(readyCloneFor(c.key)) }}<span v-if="clonesFor(c.key).length > 1" class="text-[#9a958c] font-normal"> +{{ clonesFor(c.key).length - 1 }}</span>
                    </div>
                    <div class="flex gap-1.5 items-center flex-wrap">
                        <NuxtLink :to="`/agents/${readyCloneFor(c.key).id}`" class="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-lg bg-[#3f9e6a] text-white hover:bg-[#348659]" :title="$t('connectors.open')">✓ {{ $t('connectors.connected') }}</NuxtLink>
                        <button @click="startConnect(c.key)" class="text-xs font-medium text-[#9a958c] hover:text-[#C2541E]">{{ $t('connectors.resync') }}</button>
                        <button @click="startConnect(c.key)" :disabled="!llmConfigured" class="text-xs font-medium text-[#9a958c] hover:text-[#C2541E]" :class="{ 'opacity-50 cursor-not-allowed': !llmConfigured }" :title="'Sign in with a different Microsoft account to add a separate agent'">＋ Another account</button>
                    </div>
                </template>

                <!-- CONFIGURED, NOT CONNECTED → Sign in (first connect only) -->
                <template v-else-if="c.live && templateFor(c.key)">
                    <div class="text-[11px] flex items-center gap-1.5 text-[#9a958c] mb-3">
                        <span class="w-1.5 h-1.5 rounded-full bg-[#3f9e6a]"></span>Ready to connect
                    </div>
                    <button @click="startConnect(c.key)" :disabled="!llmConfigured" class="w-full text-xs font-semibold px-3 py-2 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors" :class="{ 'opacity-50 cursor-not-allowed': !llmConfigured }">{{ $t('connectors.signIn') }} →</button>
                </template>

                <!-- LIVE but NOT CONFIGURED -->
                <template v-else-if="c.live">
                    <div class="text-[11px] flex items-center gap-1.5 text-[#B9AE9C] mb-3">
                        <span class="w-1.5 h-1.5 rounded-full bg-[#D8CDBB]"></span>{{ $t('connectors.comingSoon') }}
                    </div>
                    <!-- admin sees actionable "Set up"; member sees nothing -->
                    <button v-if="canManage" @click="openAdminConfig(c.key)" :disabled="!llmConfigured" class="w-full text-xs font-semibold px-3 py-2 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors" :class="{ 'opacity-50 cursor-not-allowed': !llmConfigured }">Set up →</button>
                    <span v-else class="inline-block text-xs font-medium text-[#B9AE9C]">{{ $t('connectors.signIn') }}</span>
                </template>

                <!-- NOT LIVE (SharePoint / OneDrive) → not available yet -->
                <template v-else>
                    <div class="text-[11px] flex items-center gap-1.5 text-[#B9AE9C] mb-3">
                        <span class="w-1.5 h-1.5 rounded-full bg-[#D8CDBB]"></span>Not available yet
                    </div>
                    <span class="inline-block text-xs font-medium text-[#B9AE9C]">{{ $t('connectors.signIn') }}</span>
                </template>
            </div>
        </div>

        <!-- SUPER-ADMIN CONFIG MODAL (tenant / SQL endpoint → publish template) -->
        <UModal v-if="canManage" v-model="showAdmin">
            <div class="p-6">
                <div class="flex items-start gap-2.5 mb-1">
                    <div class="w-8 h-8 rounded-lg bg-white border border-[#E9E0D3] flex items-center justify-center p-1 shrink-0">
                        <img :src="editingConn.icon" :alt="editingConn.name" class="w-full h-full object-contain" />
                    </div>
                    <div>
                        <h3 class="text-base text-[#1f2328]" style="font-family:'Spectral',serif">Configure · {{ editingConn.name }}</h3>
                        <p class="text-[11px] text-[#9a958c]">Set once. Members sign in with their own account.</p>
                    </div>
                </div>
                <div class="mt-4">
                    <template v-if="editingConn.fields.includes('server_hostname')">
                        <label class="block text-xs font-semibold text-[#6b6b6b] mb-1">{{ $t('connectors.sqlEndpoint') }}</label>
                        <input v-model="cfg.server_hostname" placeholder="xxxxx.datawarehouse.fabric.microsoft.com" class="w-full border border-[#E9E0D3] rounded-lg px-3 py-2 text-sm bg-[#FCFAF6] focus:outline-none focus:border-[#C2541E] mb-3" />
                    </template>
                    <label class="block text-xs font-semibold text-[#6b6b6b] mb-1">{{ $t('connectors.tenantId') }}</label>
                    <input v-model="cfg.tenant_id" placeholder="00000000-0000-0000-0000-000000000000" class="w-full border border-[#E9E0D3] rounded-lg px-3 py-2 text-sm bg-[#FCFAF6] focus:outline-none focus:border-[#C2541E] mb-3" />
                    <p class="text-[11px] text-[#9a958c] bg-[#FCFAF6] border border-[#E9E0D3] rounded-lg p-2.5 leading-relaxed">{{ $t('connectors.autoDbNote') }}</p>
                    <div v-if="adminError" class="text-xs text-[#B4432B] bg-[#F7E7E2] rounded-lg p-2.5 mt-2">{{ adminError }}</div>
                </div>
                <div class="flex items-center gap-2 mt-4">
                    <button v-if="templateFor(editingKey)" @click="resetTemplate" :disabled="resetting" class="text-xs font-medium text-[#a13d3d] hover:bg-[#fdf6f6] px-2.5 py-2 rounded-lg">
                        <Spinner v-if="resetting" class="w-3.5 h-3.5 inline" /> Reset
                    </button>
                    <div class="ms-auto flex gap-2">
                        <button @click="showAdmin = false" class="text-sm px-3 py-2 rounded-lg bg-white border border-[#E9E0D3]">{{ $t('common.cancel') }}</button>
                        <button @click="publishTemplate" :disabled="publishing" class="text-sm px-4 py-2 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] disabled:opacity-50">
                            <Spinner v-if="publishing" class="w-3.5 h-3.5 inline" /> Save config
                        </button>
                    </div>
                </div>
            </div>
        </UModal>

        <!-- DEVICE-CODE CONNECT MODAL -->
        <UModal v-model="showConnect" :prevent-close="connecting">
            <div class="p-6">
                <h3 class="text-lg text-[#1f2328] mb-1" style="font-family:'Spectral',serif">{{ $t('connectors.connectTitle', { name: connectName }) }}</h3>
                <p class="text-xs text-[#6b6b6b] mb-4">{{ $t('connectors.mfaSafe') }}</p>

                <div v-if="dcError" class="text-xs text-[#B4432B] bg-[#F7E7E2] rounded-lg p-3">{{ dcError }}</div>

                <template v-else-if="dcPhase === 'starting'">
                    <div class="flex items-center gap-2 text-sm text-[#6b6b6b] py-4"><Spinner class="w-4 h-4" /> {{ $t('connectors.starting') }}</div>
                </template>

                <template v-else-if="dcPhase === 'code'">
                    <ol class="text-sm text-[#1f2328] space-y-2 mb-3">
                        <li>1. {{ $t('connectors.step1') }} <a :href="verificationUri" target="_blank" class="text-[#A8330F] font-semibold underline">{{ verificationUri }}</a></li>
                        <li>2. {{ $t('connectors.step2') }}</li>
                    </ol>
                    <div @click="copyCode" class="font-mono text-2xl font-bold tracking-widest text-center text-[#A8330F] bg-[#FBF3EB] border border-dashed border-[#C2541E] rounded-xl py-4 cursor-pointer select-all">{{ userCode }}</div>
                    <p class="text-sm text-[#1f2328] mt-2">3. {{ $t('connectors.step3') }}</p>
                    <div class="flex items-center gap-2 text-xs text-[#6b6b6b] bg-[#F6F1EA] rounded-lg p-2.5 mt-3">
                        <Spinner class="w-3.5 h-3.5" /> {{ $t('connectors.waiting') }}
                    </div>
                </template>

                <template v-else-if="dcPhase === 'syncing'">
                    <div class="text-sm text-[#3f9e6a] bg-[#eef6f0] rounded-lg p-3 mb-2 flex items-center gap-2">✓ {{ $t('connectors.signedIn') }}</div>
                    <div class="flex items-center gap-2 text-xs text-[#6b6b6b] bg-[#F6F1EA] rounded-lg p-2.5"><Spinner class="w-3.5 h-3.5" /> {{ $t('connectors.syncing') }}</div>
                </template>

                <div class="flex justify-end mt-4">
                    <button @click="cancelConnect" class="text-sm px-3 py-2 rounded-lg bg-white border border-[#E9E0D3]">{{ dcPhase === 'syncing' ? $t('common.close') : $t('common.cancel') }}</button>
                </div>
            </div>
        </UModal>

        <!-- ADAPTIVE CONNECT MODAL (email+password → auto device-code on MFA) -->
        <ConnectorsRegisterModal v-model="showRegister" :template="registerTemplate" @registered="onRegistered" />
    </div>
</template>

<script lang="ts" setup>
import Spinner from '~/components/Spinner.vue'
import ConnectorsRegisterModal from '~/components/connectors/ConnectorsRegisterModal.vue'
import { useCan } from '~/composables/usePermissions'
import { useLlmConfigured } from '~/composables/useLlmConfigured'

// Org has no LLM key → connecting a source can't yield a usable agent. FAIL-OPEN (default true).
const { llmConfigured } = useLlmConfigured()

const props = defineProps<{ agents: any[] }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()

const { t } = useI18n()
const toast = useToast()

const enabled = ref(false)
const templates = ref<any[]>([])
// Super-admin only: gates the gear, config chip, "Set up", and the config modal.
const canManage = computed(() => useCan('manage_connections'))

// A tile is "ready" (full-color, actionable) when the connector is live AND a
// super-admin has configured its template. Otherwise it renders "Coming soon".
function isReady(c: any) {
    return !!c.live && !!templateFor(c.key)
}

// A connector is "configured" when a super-admin has published a template for it
// AND that template isn't disabled. Drives tile VISIBILITY for non-admins.
function isConfigured(c: any) {
    const tpl = templateFor(c.key)
    return !!tpl && tpl?.publish_status !== 'disabled'
}

// Static catalog. `fields` = what the admin sets ONCE (no per-user data / passwords).
// Fabric: server host + tenant; database is auto-discovered from what each user can
// access at sign-in. Power BI (User Sign-in): tenant only — datasets a user can see
// come back automatically. SharePoint/OneDrive queued (same device-code path).
const baseCatalog = [
    { key: 'fabric', type: 'ms_fabric', name: 'Microsoft Fabric', icon: '/data_sources_icons/ms_fabric.png', desc: 'Lakehouse & warehouse SQL endpoint.', live: true, fields: ['server_hostname', 'tenant_id'] },
    { key: 'powerbi', type: 'powerbi_user', name: 'Power BI (User Sign-in)', icon: '/data_sources_icons/powerbi.png', desc: 'Datasets & reports — each user sees their own.', live: true, fields: ['tenant_id'] },
    { key: 'sharepoint', type: 'sharepoint', name: 'SharePoint', icon: '/data_sources_icons/sharepoint.png', desc: 'Sites, docs & lists.', live: false, fields: ['tenant_id'] },
    { key: 'onedrive', type: 'onedrive', name: 'OneDrive', icon: '/data_sources_icons/onedrive.png', desc: 'Your personal files.', live: false, fields: ['tenant_id'] },
]

// Power BI and Microsoft Fabric are ALWAYS two separate tiles — connect Fabric →
// Fabric agent, connect Power BI → Power BI agent. (The old unified
// HYBRID_MS_UNIFIED_SIGNIN joint "Microsoft (Fabric + Power BI)" tile was removed.)
const catalog = computed(() => baseCatalog)

// Tile visibility: a LIVE connector shows only when it's configured (a non-disabled
// template exists) OR the viewer is an admin (who can still click "Set up →").
// Coming-soon connectors (SharePoint/OneDrive, !c.live) ALWAYS show.
const visibleCatalog = computed(() => catalog.value.filter((c: any) => !c.live || isConfigured(c) || canManage.value))

function templateFor(key: string) {
    const type = catalog.value.find(c => c.key === key)?.type
    return templates.value.find(tp => tp.type === type) || null
}
// All of THIS user's clones for a connector. `props.agents` is already owner-scoped
// (the caller's own agents), so match by the explicit template link OR — resiliently,
// when the template id has drifted / a clone was made by an older path — by the
// connector TYPE. This is what makes the tile flip to "Connected" instead of wrongly
// offering "Sign in" again (which is how duplicate agents got created). Generic for
// all Microsoft connectors (Fabric / Power BI / SharePoint / OneDrive).
function clonesFor(key: string) {
    const tpl = templateFor(key)
    const type = catalog.value.find(c => c.key === key)?.type
    return (props.agents || []).filter((a: any) => {
        if (a.is_user_template) return false
        if (tpl && a.template_source_id === tpl.id) return true
        const at = a.connections?.[0]?.type || a.type
        return !!type && at === type && !!a.template_source_id
    })
}
function cloneFor(key: string) {
    return clonesFor(key)[0] || null
}
// Only a clone that actually has tables is USABLE → the tile may say "Connected".
// A leftover 0-table clone (e.g. a Fabric clone with no warehouse) must NOT.
function readyCloneFor(key: string) {
    return clonesFor(key).find((a: any) => a && (a.ready === true || (a.table_count || 0) > 0)) || null
}
function ownerLabel(clone: any) {
    return (clone?.name || '').split('·').pop()?.trim() || t('connectors.you')
}

async function loadFlag() {
    try {
        const { data } = await useMyFetch('/organization/hybrid-flags', { method: 'GET' })
        const rows = (data.value as any[]) || []
        const row = rows.find(r => r.key === 'PER_USER_CONNECTOR' || r.env_name === 'HYBRID_PER_USER_CONNECTOR')
        enabled.value = !!row?.effective
    } catch { enabled.value = false }
}
async function loadTemplates() {
    try {
        const { data } = await useMyFetch('/connectors/available', { method: 'GET' })
        templates.value = (data.value as any[]) || []
    } catch { templates.value = [] }
}

// ---- super-admin inline config (gear / Set up → configure template) ----------
// Same fields + publish as Settings › Connectors, gated on manage_connections.
const showAdmin = ref(false)
const publishing = ref(false)
const resetting = ref(false)
const adminError = ref('')
const cfg = reactive<{ server_hostname: string; tenant_id: string }>({ server_hostname: '', tenant_id: '' })
const editingKey = ref('fabric')
const editingConn = computed(() => catalog.value.find(c => c.key === editingKey.value) || baseCatalog[0])

function openAdminConfig(key: string) {
    if (!llmConfigured.value) return
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
        // Database is NEVER set here — auto-discovered per user at sign-in.
        const config: any = {}
        if (c.fields.includes('server_hostname')) config.server_hostname = cfg.server_hostname.trim()
        config.tenant_id = cfg.tenant_id.trim() || null
        const body = {
            name: c.name, type: c.type, config,
            auth_policy: 'user_required', allowed_user_auth_modes: ['device_code'],
            is_user_template: true,
        }
        const { error } = await useMyFetch('/data_sources', { method: 'POST', body })
        if (error.value) throw error.value
        toast.add({ title: t('connectors.published'), color: 'green', icon: 'i-heroicons-check-circle' })
        showAdmin.value = false
        await loadTemplates()
        emit('refresh')
    } catch (e: any) {
        adminError.value = e?.data?.detail || e?.message || t('connectors.publishFailed')
    } finally {
        publishing.value = false
    }
}

async function resetTemplate() {
    const tpl = templateFor(editingKey.value)
    if (!tpl) return
    if (!confirm(`Reset ${editingConn.value.name}? Members will no longer be able to sign in until it is configured again.`)) return
    resetting.value = true
    adminError.value = ''
    try {
        const { error } = await useMyFetch(`/data_sources/${tpl.id}`, { method: 'DELETE' })
        if (error.value) throw error.value
        toast.add({ title: 'Connector reset', color: 'green', icon: 'i-heroicons-check-circle' })
        showAdmin.value = false
        await loadTemplates()
        emit('refresh')
    } catch (e: any) {
        adminError.value = e?.data?.detail || e?.message || 'Reset failed'
    } finally {
        resetting.value = false
    }
}

// ---- adaptive connect modal (email+password → auto device-code on MFA) ----
const showRegister = ref(false)
const registerTemplate = ref<any>(null)

// ---- device-code connect (kept for fallback; the adaptive modal owns the flow) ----
const showConnect = ref(false)
const connecting = ref(false)
const dcPhase = ref<'starting' | 'code' | 'syncing'>('starting')
const dcError = ref('')
const userCode = ref('')
const verificationUri = ref('')
const connectName = ref('')
let deviceCode = ''
let templateId = ''
let pollHandle: ReturnType<typeof setTimeout> | null = null
let pollInterval = 5000
let cancelled = false

// Tile "Sign in" / "Resync" → open the ADAPTIVE modal (email+password first; it
// falls back to device-code automatically if the account needs MFA).
function startConnect(key: string) {
    if (!llmConfigured.value) return
    const tpl = templateFor(key)
    if (!tpl) return
    const c = catalog.value.find(cc => cc.key === key)
    registerTemplate.value = { ...tpl, name: c?.name || tpl.name }
    showRegister.value = true
}
function onRegistered(ds: any) {
    showRegister.value = false
    emit('refresh')
    const id = ds?.id
    if (id) navigateTo(`/agents/${id}?sync=live`)
}
function schedulePoll() {
    pollHandle = setTimeout(poll, pollInterval)
}
async function poll() {
    if (cancelled) return
    try {
        const { data, error } = await useMyFetch(`/connectors/${templateId}/device-code/poll`, { method: 'POST', body: { device_code: deviceCode } })
        if (error.value) throw error.value
        const r = data.value as any
        if (r.status === 'pending') {
            if (r.slow_down) pollInterval += 5000
            schedulePoll(); return
        }
        if (r.status === 'success') {
            dcPhase.value = 'syncing'
            connecting.value = false
            emit('refresh')
            setTimeout(() => {
                showConnect.value = false
                if (r.data_source_id) navigateTo(`/agents/${r.data_source_id}`)
            }, 900)
            return
        }
        dcError.value = r.error || t('connectors.signInFailed')
        connecting.value = false
    } catch (e: any) {
        dcError.value = e?.data?.detail || e?.message || t('connectors.signInFailed')
        connecting.value = false
    }
}
function cancelConnect() {
    cancelled = true
    if (pollHandle) clearTimeout(pollHandle)
    showConnect.value = false
    connecting.value = false
}
function copyCode() {
    if (navigator.clipboard) navigator.clipboard.writeText(userCode.value)
    toast.add({ title: t('connectors.codeCopied'), color: 'green' })
}

onBeforeUnmount(() => { if (pollHandle) clearTimeout(pollHandle) })

onMounted(async () => {
    await loadFlag()
    if (enabled.value) await loadTemplates()
})
</script>
