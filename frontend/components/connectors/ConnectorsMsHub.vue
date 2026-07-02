<template>
    <div v-if="enabled" class="mb-8">
        <!-- Quiet section label — no admin buttons here; config lives in
             Settings › Connectors (super-admin). -->
        <div class="flex items-center gap-3 mb-3">
            <span class="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#A89C8C]">{{ $t('connectors.hubTitle') }}</span>
            <div class="h-px flex-1 bg-[#E9E0D3]"></div>
        </div>

        <!-- Clean connector tiles: logo + name + one status line + one action.
             No DRAFT/CONFIGURED chips, no gear. Unconfigured → "Coming soon". -->
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div
                v-for="c in catalog"
                :key="c.key"
                class="group p-4 rounded-2xl border bg-white transition-all duration-200"
                :class="isReady(c) ? 'border-[#E9E0D3] hover:-translate-y-0.5 hover:shadow-md hover:border-[#C2541E]/30' : 'border-[#EFE7DA] opacity-70'"
            >
                <div class="flex items-center gap-2.5 mb-3">
                    <div class="w-9 h-9 rounded-xl bg-white border border-[#E9E0D3] flex items-center justify-center p-1.5 shrink-0">
                        <img :src="c.icon" :alt="c.name" class="w-full h-full object-contain" />
                    </div>
                    <h3 class="text-[13.5px] font-semibold text-[#1f2328] leading-tight">{{ c.name }}</h3>
                </div>

                <!-- CONNECTED -->
                <template v-if="cloneFor(c.key)">
                    <div class="text-[11px] flex items-center gap-1.5 font-semibold text-[#3f9e6a] mb-3">
                        <span class="w-1.5 h-1.5 rounded-full bg-[#3f9e6a]"></span>{{ $t('connectors.connected') }} · {{ ownerLabel(cloneFor(c.key)) }}
                    </div>
                    <div class="flex gap-1.5 items-center">
                        <NuxtLink :to="`/agents/${cloneFor(c.key).id}`" class="text-xs font-semibold px-3 py-1.5 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F]">{{ $t('connectors.open') }}</NuxtLink>
                        <button @click="startConnect(c.key)" class="text-xs font-medium text-[#9a958c] hover:text-[#C2541E]">{{ $t('connectors.resync') }}</button>
                    </div>
                </template>

                <!-- CONFIGURED, NOT CONNECTED → Sign in -->
                <template v-else-if="c.live && templateFor(c.key)">
                    <div class="text-[11px] flex items-center gap-1.5 text-[#9a958c] mb-3">
                        <span class="w-1.5 h-1.5 rounded-full bg-[#C9BCA9]"></span>{{ $t('connectors.notConnected') }}
                    </div>
                    <button @click="startConnect(c.key)" class="w-full text-xs font-semibold px-3 py-2 rounded-lg bg-[#C2541E] text-white hover:bg-[#A8330F] transition-colors">{{ $t('connectors.signIn') }} →</button>
                </template>

                <!-- NOT LIVE or NOT CONFIGURED → Coming soon (config done in Settings) -->
                <template v-else>
                    <div class="text-[11px] flex items-center gap-1.5 text-[#B9AE9C] mb-3">
                        <span class="w-1.5 h-1.5 rounded-full bg-[#D8CDBB]"></span>{{ $t('connectors.comingSoon') }}
                    </div>
                    <span class="inline-block text-xs font-medium text-[#B9AE9C]">{{ $t('connectors.signIn') }}</span>
                </template>
            </div>
        </div>

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

const props = defineProps<{ agents: any[] }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()

const { t } = useI18n()
const toast = useToast()

const enabled = ref(false)
const templates = ref<any[]>([])

// A tile is "ready" (full-color, actionable) when the connector is live AND a
// super-admin has configured its template. Otherwise it renders "Coming soon".
function isReady(c: any) {
    return !!c.live && !!templateFor(c.key)
}

// Static catalog. `fields` = what the admin sets ONCE (no per-user data / passwords).
// Fabric: server host + tenant; database is auto-discovered from what each user can
// access at sign-in. Power BI (User Sign-in): tenant only — datasets a user can see
// come back automatically. SharePoint/OneDrive queued (same device-code path).
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
function cloneFor(key: string) {
    const tpl = templateFor(key)
    if (!tpl) return null
    return (props.agents || []).find(a => a.template_source_id === tpl.id) || null
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

// (Admin connector CONFIG moved to Settings › Connectors — super-admin only.
//  This hub is now sign-in / connect only.)

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
    const tpl = templateFor(key)
    if (!tpl) return
    registerTemplate.value = { ...tpl, name: catalog.find(c => c.key === key)?.name || tpl.name }
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
