<template>
    <div>
        <!-- Flag OFF → disabled explainer, no management UI -->
        <div v-if="flagLoaded && !flagEnabled" class="md:w-2/3">
            <div class="rounded-xl border border-[#EAE8E4] bg-[#F4EEE5] p-5 text-sm text-[#6b6b6b] leading-relaxed">
                Service accounts are turned off. Enable
                <span class="font-medium text-[#1f2328]">“Service Accounts”</span>
                in <span class="font-medium text-[#1f2328]">Settings → Features</span> to create machine
                accounts and issue API keys.
            </div>
        </div>

        <div v-else class="space-y-6">
            <p class="md:w-2/3 text-sm text-[#6b6b6b] leading-relaxed">
                Service accounts are non-human principals for headless / programmatic access. Each account
                can hold one or more API keys. A key's full token is shown
                <span class="font-medium text-[#1f2328]">only once</span>, at creation — store it securely.
            </p>

            <!-- Create account -->
            <div class="md:w-2/3 rounded-2xl border border-[#EAE8E4] bg-[#FBFAF6] p-5 space-y-4">
                <div class="flex items-center gap-2">
                    <Icon name="heroicons:plus-circle" class="w-5 h-5 text-[#C2683F]" />
                    <h2 class="text-base font-semibold text-[#1f2328]">New service account</h2>
                </div>
                <div class="space-y-1.5">
                    <div class="text-sm font-medium text-[#1f2328]">Name</div>
                    <UInput v-model="create.name" placeholder="CI Pipeline" :ui="inputUi" />
                </div>
                <div class="space-y-1.5">
                    <div class="text-sm font-medium text-[#1f2328]">Description <span class="text-[#9a958c] font-normal">(optional)</span></div>
                    <UInput v-model="create.description" placeholder="What this account is for" :ui="inputUi" />
                </div>
                <div class="flex items-center gap-3">
                    <UButton
                        class="rounded-xl px-4 py-2.5 bg-[#C2683F] hover:bg-[#A8330F] text-white border-0 transition-colors cursor-pointer"
                        :loading="create.running"
                        :disabled="!create.name || create.running"
                        @click="createAccount"
                    >Create account</UButton>
                    <span v-if="create.error" class="text-sm text-[#A8330F]">{{ create.error }}</span>
                </div>
            </div>

            <!-- Accounts list -->
            <div class="md:w-2/3 space-y-4">
                <div v-if="loading" class="text-sm text-[#9a958c]">Loading…</div>
                <div v-else-if="!accounts.length" class="rounded-xl border border-[#EAE8E4] bg-white p-5 text-sm text-[#6b6b6b]">
                    No service accounts yet.
                </div>

                <div
                    v-for="acc in accounts"
                    :key="acc.id"
                    class="rounded-2xl border border-[#EAE8E4] bg-white p-5 space-y-3"
                >
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <div class="flex items-center gap-2">
                                <Icon name="heroicons:key" class="w-4 h-4 text-[#C2683F]" />
                                <span class="font-semibold text-[#1f2328] truncate">{{ acc.name }}</span>
                                <span v-if="!acc.is_active" class="text-[11px] px-2 py-0.5 rounded-full bg-[#F4EEE5] text-[#A8330F] border border-[#EAE8E4]">disabled</span>
                            </div>
                            <div v-if="acc.description" class="text-sm text-[#6b6b6b] mt-1">{{ acc.description }}</div>
                            <div class="text-xs text-[#9a958c] mt-1">
                                {{ acc.key_count }} key{{ acc.key_count === 1 ? '' : 's' }} · created {{ fmt(acc.created_at) }}
                                <span v-if="acc.last_used_at"> · last used {{ fmt(acc.last_used_at) }}</span>
                            </div>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <UButton
                                class="rounded-lg px-3 py-1.5 bg-transparent hover:bg-[#F4EEE5] text-[#6b6b6b] border border-[#EAE8E4] text-xs cursor-pointer"
                                @click="toggleExpand(acc)"
                            >{{ expanded === acc.id ? 'Hide keys' : 'Manage keys' }}</UButton>
                            <UButton
                                class="rounded-lg px-3 py-1.5 bg-transparent hover:bg-[#F4EEE5] text-[#A8330F] border border-[#EAE8E4] text-xs cursor-pointer"
                                @click="deleteAccount(acc)"
                            >Delete</UButton>
                        </div>
                    </div>

                    <!-- Expanded: keys -->
                    <div v-if="expanded === acc.id" class="pt-2 border-t border-[#EAE8E4] space-y-3">
                        <!-- Newly issued token — shown ONCE -->
                        <div v-if="newToken && newToken.accId === acc.id" class="rounded-xl border border-[#C2683F] bg-[#FBEFE4] p-4 space-y-2">
                            <div class="flex items-center gap-2 text-sm font-medium text-[#A8330F]">
                                <Icon name="heroicons:exclamation-triangle" class="w-4 h-4" />
                                Copy this token now — you won't see it again.
                            </div>
                            <div class="flex items-center gap-2">
                                <code class="flex-1 min-w-0 break-all text-xs bg-white border border-[#EAE8E4] rounded-lg px-3 py-2 text-[#1f2328]">{{ newToken.token }}</code>
                                <UButton
                                    class="rounded-lg px-3 py-2 bg-[#C2683F] hover:bg-[#A8330F] text-white border-0 text-xs cursor-pointer shrink-0"
                                    @click="copyToken(newToken.token)"
                                >{{ copied ? 'Copied' : 'Copy' }}</UButton>
                            </div>
                        </div>

                        <!-- Issue a key -->
                        <div class="flex items-end gap-2">
                            <div class="flex-1 space-y-1.5">
                                <div class="text-sm font-medium text-[#1f2328]">Issue a new key</div>
                                <UInput v-model="keyName" placeholder="Key name (e.g. Default)" :ui="inputUi" />
                            </div>
                            <UButton
                                class="rounded-xl px-4 py-2.5 bg-[#C2683F] hover:bg-[#A8330F] text-white border-0 transition-colors cursor-pointer shrink-0"
                                :loading="issuing"
                                :disabled="issuing"
                                @click="issueKey(acc)"
                            >Issue key</UButton>
                        </div>

                        <!-- Keys list -->
                        <div v-if="detailLoading" class="text-sm text-[#9a958c]">Loading keys…</div>
                        <div v-else-if="!keys.length" class="text-sm text-[#9a958c]">No keys yet.</div>
                        <div v-else class="space-y-2">
                            <div
                                v-for="k in keys"
                                :key="k.id"
                                class="flex items-center justify-between gap-3 rounded-lg border border-[#EAE8E4] bg-[#FBFAF6] px-3 py-2"
                            >
                                <div class="min-w-0">
                                    <div class="flex items-center gap-2">
                                        <span class="text-sm font-medium text-[#1f2328] truncate">{{ k.name }}</span>
                                        <code class="text-xs text-[#6b6b6b]">{{ k.key_prefix }}…</code>
                                        <span v-if="k.revoked_at" class="text-[11px] px-2 py-0.5 rounded-full bg-[#F4EEE5] text-[#A8330F] border border-[#EAE8E4]">revoked</span>
                                    </div>
                                    <div class="text-xs text-[#9a958c] mt-0.5">
                                        created {{ fmt(k.created_at) }}
                                        <span v-if="k.last_used_at"> · last used {{ fmt(k.last_used_at) }}</span>
                                        <span v-else> · never used</span>
                                    </div>
                                </div>
                                <UButton
                                    v-if="!k.revoked_at"
                                    class="rounded-lg px-3 py-1.5 bg-transparent hover:bg-[#F4EEE5] text-[#A8330F] border border-[#EAE8E4] text-xs cursor-pointer shrink-0"
                                    @click="revokeKey(acc, k)"
                                >Revoke</UButton>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'

definePageMeta({ auth: true, permissions: ['manage_members'], layout: 'settings' })

const inputUi = { base: 'w-full', rounded: 'rounded-lg', color: { white: { outline: 'bg-white border border-[#EAE8E4] focus:border-[#C2683F] focus:ring-0' } } }

interface SAKey {
    id: string
    name: string
    key_prefix: string
    created_at: string
    last_used_at?: string | null
    revoked_at?: string | null
    expires_at?: string | null
}
interface ServiceAccount {
    id: string
    name: string
    description?: string | null
    is_active: boolean
    created_at: string
    key_count: number
    last_used_at?: string | null
}

// HYBRID_SERVICE_ACCOUNTS gate.
const flagLoaded = ref(false)
const flagEnabled = ref(false)
async function loadFlag() {
    try {
        const { data } = await useMyFetch<any[]>('/api/organization/hybrid-flags')
        const rows = (data.value as any[]) || []
        flagEnabled.value = !!rows.find(r => r?.env_name === 'HYBRID_SERVICE_ACCOUNTS')?.effective
    } catch {
        flagEnabled.value = false
    } finally {
        flagLoaded.value = true
    }
}

const accounts = ref<ServiceAccount[]>([])
const loading = ref(true)
const create = reactive<{ name: string; description: string; running: boolean; error: string }>({ name: '', description: '', running: false, error: '' })

const expanded = ref<string | null>(null)
const keys = ref<SAKey[]>([])
const detailLoading = ref(false)
const keyName = ref('')
const issuing = ref(false)
const newToken = ref<{ accId: string; token: string } | null>(null)
const copied = ref(false)

function fmt(s?: string | null): string {
    if (!s) return ''
    try { return new Date(s).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) } catch { return s }
}

async function loadAccounts() {
    loading.value = true
    try {
        const { data } = await useMyFetch<ServiceAccount[]>('/service-accounts')
        accounts.value = (data.value as ServiceAccount[]) || []
    } catch {
        accounts.value = []
    } finally {
        loading.value = false
    }
}

async function createAccount() {
    if (!create.name || create.running) return
    create.running = true
    create.error = ''
    try {
        const { error } = await useMyFetch('/service-accounts', { method: 'POST', body: { name: create.name, description: create.description || null } })
        if (error?.value) throw error.value
        create.name = ''
        create.description = ''
        await loadAccounts()
    } catch {
        create.error = 'Could not create account.'
    } finally {
        create.running = false
    }
}

async function deleteAccount(acc: ServiceAccount) {
    if (!confirm(`Delete "${acc.name}"? All its API keys will be revoked.`)) return
    try {
        await useMyFetch(`/service-accounts/${acc.id}`, { method: 'DELETE' })
        if (expanded.value === acc.id) expanded.value = null
        await loadAccounts()
    } catch { /* fail-soft */ }
}

async function toggleExpand(acc: ServiceAccount) {
    if (expanded.value === acc.id) { expanded.value = null; return }
    expanded.value = acc.id
    newToken.value = null
    keyName.value = ''
    await loadKeys(acc.id)
}

async function loadKeys(accId: string) {
    detailLoading.value = true
    keys.value = []
    try {
        const { data } = await useMyFetch<ServiceAccount & { keys: SAKey[] }>(`/service-accounts/${accId}`)
        keys.value = ((data.value as any)?.keys as SAKey[]) || []
    } catch {
        keys.value = []
    } finally {
        detailLoading.value = false
    }
}

async function issueKey(acc: ServiceAccount) {
    if (issuing.value) return
    issuing.value = true
    try {
        const { data, error } = await useMyFetch<SAKey & { token: string }>(`/service-accounts/${acc.id}/keys`, { method: 'POST', body: { name: keyName.value || 'Default' } })
        if (error?.value) throw error.value
        const token = (data.value as any)?.token
        if (token) newToken.value = { accId: acc.id, token }
        keyName.value = ''
        copied.value = false
        await loadKeys(acc.id)
        await loadAccounts()
    } catch { /* fail-soft */ } finally {
        issuing.value = false
    }
}

async function revokeKey(acc: ServiceAccount, k: SAKey) {
    if (!confirm(`Revoke "${k.name}"? Any client using it will stop working.`)) return
    try {
        await useMyFetch(`/service-accounts/${acc.id}/keys/${k.id}`, { method: 'DELETE' })
        await loadKeys(acc.id)
        await loadAccounts()
    } catch { /* fail-soft */ }
}

async function copyToken(token: string) {
    try { await navigator.clipboard.writeText(token); copied.value = true } catch { /* ignore */ }
}

onMounted(async () => {
    await loadFlag()
    if (flagEnabled.value) await loadAccounts()
})
</script>
