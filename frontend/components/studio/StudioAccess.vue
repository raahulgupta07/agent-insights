<template>
    <div>
        <div class="mb-4">
            <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Access &amp; Members</h2>
            <p class="text-xs text-[#6b6b6b] mt-0.5">Decide who can use this agent and which model it runs on. Set up Channels and Email in their own tabs.</p>
        </div>

        <!-- WHO CAN USE -->
        <div class="rounded-2xl border border-[#E9E0D3] bg-white p-4 mb-3">
            <div class="flex items-center justify-between mb-1">
                <h3 class="text-sm font-semibold text-[#1f2328] flex items-center gap-1.5" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                    <UIcon name="i-heroicons-lock-closed" class="w-4 h-4 text-[#C2541E]" /> Who can use this agent
                </h3>
                <span v-if="savingScope" class="text-[10px] text-[#9a958c] inline-flex items-center gap-1"><Spinner class="h-3 w-3" /> saving…</span>
            </div>
            <p class="text-[11px] text-[#6b6b6b] mb-3">Current access: <span class="font-medium text-[#1f2328]">{{ scopeLabel }}</span></p>

            <!-- OpenWebUI-style 2-state: Private vs Public. Link is an advanced option below. -->
            <div class="space-y-2">
                <label
                    v-for="opt in primaryScopeOptions"
                    :key="opt.value"
                    class="flex items-start gap-2 rounded-xl border p-2.5 transition-colors"
                    :class="[
                        scope === opt.value ? 'border-[#E8C9B5] bg-[#F6EFEA]' : 'border-[#E9E0D3]',
                        canEdit ? 'cursor-pointer hover:border-[#dcd9cf]' : 'opacity-70 cursor-default',
                    ]"
                >
                    <input
                        type="radio"
                        :value="opt.value"
                        :checked="scope === opt.value"
                        :disabled="!canEdit || savingScope"
                        class="mt-0.5 text-[#C2541E] focus:ring-[#C2541E]"
                        @change="setScope(opt.value)"
                    />
                    <span class="flex items-start gap-1.5">
                        <UIcon :name="opt.icon" class="w-4 h-4 mt-0.5 shrink-0 text-[#9a958c]" />
                        <span>
                            <span class="block text-xs font-medium text-[#1f2328]">{{ opt.label }}</span>
                            <span class="block text-[11px] text-[#9a958c]">{{ opt.hint }}</span>
                        </span>
                    </span>
                </label>
            </div>

            <!-- Advanced: share-by-link (anyone with the link, no sign-in) -->
            <div class="mt-3 pt-3 border-t border-[#F0EEE6]">
                <button
                    type="button"
                    class="inline-flex items-center gap-1 text-[11px] font-medium text-[#9a958c] hover:text-[#6b6b6b]"
                    @click="showLinkAdvanced = !showLinkAdvanced"
                >
                    <UIcon :name="showLinkAdvanced ? 'i-heroicons-chevron-down' : 'i-heroicons-chevron-right'" class="w-3.5 h-3.5" />
                    Advanced — share by link
                    <span v-if="scope === 'link'" class="ml-1 text-[9px] uppercase tracking-wide text-emerald-700 bg-emerald-100 px-1.5 py-0.5 rounded">active</span>
                </button>

                <div v-if="showLinkAdvanced" class="mt-2 rounded-xl border border-[#E9E0D3] bg-[#FAF8F3] p-2.5">
                    <label
                        class="flex items-start gap-2 cursor-pointer"
                        :class="canEdit ? '' : 'opacity-70 cursor-default'"
                    >
                        <input
                            type="radio"
                            :value="'link'"
                            :checked="scope === 'link'"
                            :disabled="!canEdit || savingScope"
                            class="mt-0.5 text-[#C2541E] focus:ring-[#C2541E]"
                            @change="setScope('link')"
                        />
                        <span>
                            <span class="block text-xs font-medium text-[#1f2328]">Link — anyone with the link</span>
                            <span class="block text-[11px] text-[#9a958c]">Share a link; no sign-in needed to view. Bypasses members & groups.</span>
                        </span>
                    </label>

                    <!-- Share link (when scope === link and a token exists) -->
                    <div v-if="scope === 'link' && shareToken" class="mt-3">
                        <label class="block text-[11px] font-medium text-[#6b6b6b] mb-1">Share link</label>
                        <div class="flex items-center gap-2">
                            <UInput :model-value="shareUrl" readonly size="sm" class="flex-1" @focus="(e: any) => e.target.select()" />
                            <UButton color="gray" variant="outline" size="xs" icon="i-heroicons-clipboard" @click="copyLink">Copy</UButton>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ACCESS (only when Private): groups + people -->
        <div v-if="scope === 'private'" class="rounded-2xl border border-[#E9E0D3] bg-white p-4 mb-3">
            <div class="flex items-center justify-between mb-1">
                <h3 class="text-sm font-semibold text-[#1f2328] flex items-center gap-1.5" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                    <UIcon name="i-heroicons-users" class="w-4 h-4 text-[#C2541E]" /> Access
                </h3>
                <button
                    v-if="canEdit && groupAccessEnabled"
                    type="button"
                    class="inline-flex items-center gap-1 text-[11px] font-semibold text-[#C2541E] hover:text-[#A8330F]"
                    @click="openPicker"
                >
                    <UIcon name="i-heroicons-plus" class="w-3.5 h-3.5" /> Add access
                </button>
            </div>
            <p class="text-[11px] text-[#6b6b6b] mb-3">Groups and people who can open and use the agent.</p>

            <!-- GROUPS (HYBRID_GROUP_ACCESS) -->
            <div v-if="groupAccessEnabled" class="mb-4">
                <span class="text-[10px] uppercase tracking-wide text-[#9a958c] font-medium">Groups</span>
                <div v-if="loadingGrants" class="flex items-center py-3 text-[#9a958c]">
                    <Spinner class="h-3.5 w-3.5" /><span class="ms-2 text-[11px]">Loading…</span>
                </div>
                <ul v-else-if="groupGrants.length" class="mt-1.5 divide-y divide-[#F0EEE6] border border-[#F0EEE6] rounded-xl overflow-hidden">
                    <li v-for="g in groupGrants" :key="g.group_id" class="flex items-center justify-between px-3 py-2 bg-white">
                        <div class="flex items-center gap-2 min-w-0">
                            <UIcon
                                :name="g.external_provider ? 'i-heroicons-shield-check' : 'i-heroicons-user-group'"
                                class="w-4 h-4 shrink-0"
                                :class="g.external_provider ? 'text-[#2F6F8B]' : 'text-[#9a958c]'"
                            />
                            <span class="text-xs font-medium text-[#1f2328] truncate">{{ g.name }}</span>
                            <span class="text-[10px] text-[#9a958c] shrink-0">·{{ g.member_count }}</span>
                            <span
                                v-if="g.external_provider"
                                class="text-[9px] uppercase tracking-wide text-[#2F6F8B] bg-[#E4EEF2] px-1.5 py-0.5 rounded shrink-0"
                            >AD</span>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <USelectMenu
                                v-if="canEdit"
                                :model-value="g.permission"
                                :options="permOptions"
                                value-attribute="value"
                                option-attribute="label"
                                size="2xs"
                                class="w-24"
                                @update:model-value="(p: string) => changeGroupPerm(g, p)"
                            />
                            <span v-else class="text-[11px] text-[#9a958c]">{{ g.permission === 'write' ? 'Editor' : 'Viewer' }}</span>
                            <button
                                v-if="canEdit"
                                class="text-[#9a958c] hover:text-red-500"
                                title="Revoke group access"
                                @click="revokeGroup(g)"
                            >
                                <UIcon name="i-heroicons-x-mark" class="w-4 h-4" />
                            </button>
                        </div>
                    </li>
                </ul>
                <p v-else class="mt-1.5 text-[11px] text-[#9a958c]">No groups yet — use <b>Add access</b> to share with a team or AD group.</p>
            </div>

            <span v-if="groupAccessEnabled" class="text-[10px] uppercase tracking-wide text-[#9a958c] font-medium">People</span>

            <!-- Add member -->
            <div v-if="canEdit" class="flex items-center gap-2 mb-3">
                <UInput
                    v-model="inviteEmail"
                    type="email"
                    placeholder="teammate@company.com"
                    size="sm"
                    class="flex-1"
                    @keyup.enter="invite"
                />
                <USelectMenu
                    v-model="inviteRole"
                    :options="roleOptions"
                    value-attribute="value"
                    option-attribute="label"
                    size="sm"
                    class="w-28"
                />
                <UButton color="orange" size="xs" :loading="inviting" :disabled="!inviteEmail.trim()" @click="invite">Add</UButton>
            </div>

            <div v-if="loadingMembers" class="flex items-center justify-center py-6 text-[#9a958c]">
                <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
            </div>
            <ul v-else class="divide-y divide-[#F0EEE6] border border-[#F0EEE6] rounded-xl overflow-hidden">
                <li v-for="m in members" :key="m.id" class="flex items-center justify-between px-3 py-2 bg-white">
                    <div class="min-w-0">
                        <div class="flex items-center gap-1.5">
                            <span class="text-xs font-medium text-[#1f2328] truncate">{{ m.user_name || m.user_email || m.user_id }}</span>
                            <span v-if="String(m.user_id) === ownerUserId" class="text-[9px] uppercase tracking-wide text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">Owner</span>
                        </div>
                        <span v-if="m.user_email && m.user_name" class="text-[11px] text-[#9a958c] truncate">{{ m.user_email }}</span>
                    </div>
                    <div class="flex items-center gap-2 shrink-0">
                        <USelectMenu
                            v-if="canEdit && String(m.user_id) !== ownerUserId"
                            :model-value="m.role"
                            :options="roleOptions"
                            value-attribute="value"
                            option-attribute="label"
                            size="2xs"
                            class="w-24"
                            @update:model-value="(r: string) => changeRole(m, r)"
                        />
                        <span v-else class="text-[11px] text-[#9a958c]">{{ roleLabel(m.role) }}</span>
                        <button
                            v-if="canEdit && String(m.user_id) !== ownerUserId"
                            class="text-[#9a958c] hover:text-red-500"
                            title="Remove member"
                            @click="removeMember(m)"
                        >
                            <UIcon name="i-heroicons-x-mark" class="w-4 h-4" />
                        </button>
                    </div>
                </li>
                <li v-if="!members.length" class="px-3 py-3 text-[11px] text-[#9a958c] bg-white">No members yet — add a teammate above.</li>
            </ul>
        </div>

        <!-- MODEL (per-agent override) -->
        <div class="rounded-2xl border border-[#E9E0D3] bg-white p-4 mb-3">
            <h3 class="text-sm font-semibold text-[#1f2328] flex items-center gap-1.5 mb-1" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                <UIcon name="i-heroicons-cpu-chip" class="w-4 h-4 text-[#C2541E]" /> Model
            </h3>
            <p class="text-[11px] text-[#6b6b6b] mb-3">Pick the LLM this agent uses. Leave on <span class="font-medium">Org default</span> to follow the org-wide setting.</p>
            <div class="flex items-center gap-2">
                <select
                    :value="modelId"
                    :disabled="!canEdit || savingModel || loadingModels"
                    class="flex-1 text-xs text-[#1f2328] bg-white border border-[#E9E0D3] rounded-lg px-3 py-2 focus:outline-none focus:border-[#C2541E] disabled:opacity-60"
                    @change="(e: any) => setModel(e.target.value)"
                >
                    <option value="">Org default</option>
                    <option v-for="m in models" :key="m.id || m.model_id" :value="m.model_id || m.id">
                        {{ m.name || m.model_id }}{{ m.is_default ? ' (org default)' : '' }}
                    </option>
                </select>
                <span v-if="savingModel" class="text-[10px] text-[#9a958c] inline-flex items-center gap-1"><Spinner class="h-3 w-3" /></span>
            </div>
            <p v-if="loadingModels" class="text-[10px] text-[#9a958c] mt-1.5">Loading models…</p>
        </div>

        <!-- CONNECTION (read-only summary) -->
        <div class="rounded-2xl border border-[#E9E0D3] bg-white p-4 mb-3">
            <h3 class="text-sm font-semibold text-[#1f2328] flex items-center gap-1.5 mb-1" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                <UIcon name="i-heroicons-signal" class="w-4 h-4 text-[#C2541E]" /> Connections
            </h3>
            <p class="text-[11px] text-[#6b6b6b] mb-3">Data sources this agent is grounded on. Manage them in the Connection tab.</p>
            <div v-if="!sources.length" class="text-[11px] text-[#9a958c] py-2">No sources pinned yet.</div>
            <ul v-else class="space-y-1.5">
                <li v-for="s in sources" :key="s.id" class="flex items-center justify-between gap-2 rounded-lg border border-[#F0EEE6] bg-[#F6F1EA] px-3 py-2">
                    <div class="flex items-center gap-2 min-w-0">
                        <DataSourceIcon v-if="s.type" class="h-4 shrink-0" :type="s.type" />
                        <UIcon v-else name="i-heroicons-circle-stack" class="w-4 h-4 shrink-0 text-[#9a958c]" />
                        <span class="text-xs font-medium text-[#1f2328] truncate">{{ s.name || s.agent_id }}</span>
                    </div>
                    <span class="text-[10px] text-[#9a958c] uppercase tracking-wide shrink-0">{{ credentialMode(s) }}</span>
                </li>
            </ul>
        </div>

        <!-- DANGER ZONE (owner only) — merged in from the old Members & Share tab -->
        <div v-if="isOwner" class="mt-8 pt-4 border-t border-[#E9E0D3]">
            <UButton color="red" variant="outline" size="xs" icon="i-heroicons-trash" :loading="deleting" @click="emit('delete-studio')">
                {{ $t('studio.deleteStudio') }}
            </UButton>
        </div>

        <!-- Add-access group picker (HYBRID_GROUP_ACCESS) -->
        <StudioAccessPicker
            v-if="groupAccessEnabled"
            v-model="showPicker"
            :studio-id="studioId"
            :organization-id="orgId"
            :granted-group-ids="grantedGroupIds"
            @added="loadGroupGrants"
            @create-group="onCreateGroup"
        />

        <!-- Inline create-group (P5) -->
        <StudioCreateGroup
            v-if="groupAccessEnabled"
            v-model="showCreateGroup"
            :organization-id="orgId"
            @created="onGroupCreated"
        />

    </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

interface Member {
    id: string
    user_id: string
    role: string
    user_name?: string | null
    user_email?: string | null
}
interface Source { id: string; agent_id: string; name?: string | null; type?: string | null; credential_mode?: string | null }
interface Studio { id: string; share_scope?: string; share_token?: string | null; config?: Record<string, any> }

const props = defineProps<{
    studioId: string
    studio: Studio | null
    sources: Source[]
    canEdit: boolean
    ownerUserId: string
    isOwner?: boolean
    deleting?: boolean
}>()

const emit = defineEmits<{
    'share-updated': [payload: { share_scope: string; share_token: string | null }]
    'config-updated': [config: Record<string, any>]
    'delete-studio': []
}>()

const { t } = useI18n()
const toast = useToast()

// ---- WHO CAN USE -------------------------------------------------------
const scope = ref(props.studio?.share_scope || 'private')
const shareToken = ref<string | null>(props.studio?.share_token ?? null)
const savingScope = ref(false)

// OpenWebUI-style 2-state primary toggle. 'private' = members + groups below;
// 'org' surfaces as "Public" (everyone in the org). 'link' lives in Advanced.
const primaryScopeOptions = [
    { value: 'private', label: 'Private — members & groups', hint: 'Only the people and groups you grant below can open and use this agent.', icon: 'i-heroicons-lock-closed' },
    { value: 'org', label: 'Public — everyone in the org', hint: 'Any member of your organization can open and use this agent.', icon: 'i-heroicons-globe-alt' },
]
const showLinkAdvanced = ref((props.studio?.share_scope || 'private') === 'link')
const scopeLabelMap: Record<string, string> = { private: 'Private', org: 'Public', link: 'Link' }
const scopeLabel = computed(() => scopeLabelMap[scope.value] || scope.value)

const shareUrl = computed(() => {
    if (!shareToken.value) return ''
    const origin = typeof window !== 'undefined' ? window.location.origin : ''
    return `${origin}/studios/shared/${shareToken.value}`
})

const setScope = async (value: string) => {
    if (!props.canEdit || value === scope.value) return
    const prev = scope.value
    scope.value = value
    savingScope.value = true
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/share`, {
            method: 'PATCH',
            body: { share_scope: value },
        })
        if (error?.value) throw error.value
        const updated = data.value || {}
        scope.value = updated.share_scope || value
        shareToken.value = updated.share_token ?? shareToken.value
        emit('share-updated', { share_scope: scope.value, share_token: shareToken.value })
        toast.add({ title: 'Access updated', color: 'green', icon: 'i-heroicons-check-circle' })
    } catch (e: any) {
        scope.value = prev
        console.error('Failed to update access:', e)
        toast.add({ title: t('studio.actionFailed') || 'Action failed', color: 'red' })
    } finally {
        savingScope.value = false
    }
}

const copyLink = async () => {
    if (!shareUrl.value) return
    try {
        await navigator.clipboard.writeText(shareUrl.value)
        toast.add({ title: 'Link copied', color: 'green', icon: 'i-heroicons-check-circle' })
    } catch {
        toast.add({ title: t('studio.actionFailed') || 'Action failed', color: 'red' })
    }
}

// ---- MEMBERS -----------------------------------------------------------
const members = ref<Member[]>([])
const loadingMembers = ref(false)
const inviteEmail = ref('')
const inviteRole = ref('viewer')
const inviting = ref(false)

const roleOptions = [
    { value: 'viewer', label: 'Viewer' },
    { value: 'editor', label: 'Editor' },
    { value: 'owner', label: 'Owner' },
]
const roleLabel = (r: string) => roleOptions.find(o => o.value === r)?.label || r

const fetchMembers = async () => {
    loadingMembers.value = true
    try {
        const { data, error } = await useMyFetch<Member[]>(`/studios/${props.studioId}/members`, { method: 'GET' })
        if (error?.value) throw error.value
        members.value = data.value || []
    } catch (e: any) {
        console.error('Failed to load members:', e)
    } finally {
        loadingMembers.value = false
    }
}

const invite = async () => {
    const email = inviteEmail.value.trim()
    if (!email) return
    inviting.value = true
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/members`, {
            method: 'POST',
            body: { email, role: inviteRole.value },
        })
        if (error?.value) throw error.value
        inviteEmail.value = ''
        inviteRole.value = 'viewer'
        toast.add({ title: 'Member added', color: 'green', icon: 'i-heroicons-check-circle' })
        await fetchMembers()
    } catch (e: any) {
        console.error('Failed to add member:', e)
        toast.add({ title: t('studio.actionFailed') || 'Action failed', color: 'red' })
    } finally {
        inviting.value = false
    }
}

const changeRole = async (m: Member, role: string) => {
    if (!role || role === m.role) return
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/members/${m.user_id}`, {
            method: 'PATCH',
            body: { role },
        })
        if (error?.value) throw error.value
        await fetchMembers()
    } catch (e: any) {
        console.error('Failed to change role:', e)
        toast.add({ title: t('studio.actionFailed') || 'Action failed', color: 'red' })
    }
}

const removeMember = async (m: Member) => {
    if (!window.confirm('Remove this member?')) return
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/members/${m.user_id}`, { method: 'DELETE' })
        if (error?.value) throw error.value
        toast.add({ title: 'Member removed', color: 'green', icon: 'i-heroicons-check-circle' })
        await fetchMembers()
    } catch (e: any) {
        console.error('Failed to remove member:', e)
        toast.add({ title: t('studio.actionFailed') || 'Action failed', color: 'red' })
    }
}

// ---- GROUP ACCESS (HYBRID_GROUP_ACCESS) --------------------------------
const { organization, ensureOrganization } = useOrganization()
const orgId = computed(() => organization.value?.id || '')
const groupAccessEnabled = ref(false)
const groupGrants = ref<any[]>([])
const loadingGrants = ref(false)
const showPicker = ref(false)
const permOptions = [
    { value: 'read', label: 'Viewer' },
    { value: 'write', label: 'Editor' },
]
const grantedGroupIds = computed(() => groupGrants.value.map(g => String(g.group_id)))

const loadGroupAccessFlag = async () => {
    try {
        const { data } = await useMyFetch<any[]>('/organization/hybrid-flags')
        const rows = (data.value as any[]) || []
        const row = rows.find(r => r?.env_name === 'HYBRID_GROUP_ACCESS')
        groupAccessEnabled.value = !!row?.effective
    } catch {
        groupAccessEnabled.value = false
    }
}

const loadGroupGrants = async () => {
    if (!groupAccessEnabled.value) return
    loadingGrants.value = true
    try {
        const { data, error } = await useMyFetch<any[]>(`/studios/${props.studioId}/group-grants`, { method: 'GET' })
        if (error?.value) throw error.value
        groupGrants.value = (data.value as any[]) || []
    } catch (e) {
        console.error('Failed to load group grants:', e)
        groupGrants.value = []
    } finally {
        loadingGrants.value = false
    }
}

const openPicker = () => { showPicker.value = true }

const changeGroupPerm = async (g: any, permission: string) => {
    if (!permission || permission === g.permission) return
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/group-grants`, {
            method: 'POST',
            body: { group_id: g.group_id, permission },
        })
        if (error?.value) throw error.value
        await loadGroupGrants()
    } catch (e) {
        console.error('Failed to change group permission:', e)
        toast.add({ title: t('studio.actionFailed') || 'Action failed', color: 'red' })
    }
}

const revokeGroup = async (g: any) => {
    if (!window.confirm(`Revoke access for "${g.name}"?`)) return
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/group-grants/${g.group_id}`, { method: 'DELETE' })
        if (error?.value) throw error.value
        toast.add({ title: 'Group access revoked', color: 'green', icon: 'i-heroicons-check-circle' })
        await loadGroupGrants()
    } catch (e) {
        console.error('Failed to revoke group:', e)
        toast.add({ title: t('studio.actionFailed') || 'Action failed', color: 'red' })
    }
}

// Create-group (P5): open the inline modal. On success, refresh the granted
// list and the picker's group list (picker reloads when reopened).
const showCreateGroup = ref(false)
const onCreateGroup = () => { showPicker.value = false; showCreateGroup.value = true }
const onGroupCreated = async () => {
    showCreateGroup.value = false
    // Reopen the picker so the new group shows in its list.
    await loadGroupGrants()
    showPicker.value = true
}

// ---- MODEL -------------------------------------------------------------
const models = ref<any[]>([])
const loadingModels = ref(false)
const savingModel = ref(false)
const modelId = computed(() => props.studio?.config?.model_id || '')

const loadModels = async () => {
    loadingModels.value = true
    try {
        const { data } = await useMyFetch<any[]>('/api/llm/models?is_enabled=true')
        models.value = Array.isArray(data.value) ? data.value : []
    } catch (e: any) {
        console.error('Failed to load models:', e)
    } finally {
        loadingModels.value = false
    }
}

const setModel = async (value: string) => {
    if (!props.canEdit) return
    savingModel.value = true
    try {
        // Preserve every other config key — only change model_id (empty = clear override).
        const nextConfig = { ...(props.studio?.config || {}) }
        if (value) nextConfig.model_id = value
        else delete nextConfig.model_id
        const { error } = await useMyFetch(`/studios/${props.studioId}`, {
            method: 'PATCH',
            body: { config: nextConfig },
        })
        if (error?.value) throw error.value
        emit('config-updated', nextConfig)
        toast.add({ title: value ? 'Model updated' : 'Reverted to org default', color: 'green', icon: 'i-heroicons-check-circle' })
    } catch (e: any) {
        console.error('Failed to update model:', e)
        toast.add({ title: t('studio.actionFailed') || 'Action failed', color: 'red' })
    } finally {
        savingModel.value = false
    }
}

// ---- CONNECTION --------------------------------------------------------
const credentialMode = (s: Source) => {
    const m = (s.credential_mode || '').toLowerCase()
    if (m === 'shared' || m === 'org') return 'shared creds'
    if (m === 'user' || m === 'per_user') return 'per-user creds'
    return s.type || 'data source'
}

// Keep local scope/token in sync if the parent studio changes.
watch(() => props.studio, (s) => {
    scope.value = s?.share_scope || 'private'
    shareToken.value = s?.share_token ?? null
})

onMounted(async () => {
    fetchMembers()
    loadModels()
    await ensureOrganization()
    await loadGroupAccessFlag()
    if (groupAccessEnabled.value) await loadGroupGrants()
})
</script>
