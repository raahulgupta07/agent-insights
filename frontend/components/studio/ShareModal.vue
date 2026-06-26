<template>
    <UModal v-model="isOpen" :ui="{ width: 'sm:max-w-lg' }">
        <div class="p-6">
            <!-- Header -->
            <div class="flex items-center justify-between mb-4">
                <h2 class="text-lg font-medium text-gray-900">{{ $t('studio.shareTitle') }}</h2>
                <button @click="close" class="text-gray-400 hover:text-gray-600">
                    <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
                </button>
            </div>

            <!-- Scope -->
            <div class="mb-6">
                <label class="block text-xs font-medium text-gray-700 mb-2">{{ $t('studio.shareScope') }}</label>
                <div class="space-y-2">
                    <label
                        v-for="opt in scopeOptions"
                        :key="opt.value"
                        class="flex items-start gap-2 rounded-md border p-2.5 transition-colors"
                        :class="[
                            scope === opt.value ? 'border-[#E8C9B5] bg-[#F6EFEA]' : 'border-gray-200',
                            canManage ? 'cursor-pointer hover:border-gray-300' : 'opacity-70 cursor-default'
                        ]"
                    >
                        <input
                            type="radio"
                            :value="opt.value"
                            v-model="scope"
                            :disabled="!canManage"
                            class="mt-0.5 text-[#C2541E] focus:ring-[#C2541E]"
                        />
                        <span>
                            <span class="block text-xs font-medium text-gray-800">{{ opt.label }}</span>
                            <span class="block text-[11px] text-gray-500">{{ opt.hint }}</span>
                        </span>
                    </label>
                </div>

                <!-- Share link (when scope === link and a token exists) -->
                <div v-if="scope === 'link' && shareToken" class="mt-3">
                    <label class="block text-[11px] font-medium text-gray-600 mb-1">{{ $t('studio.shareLink') }}</label>
                    <div class="flex items-center gap-2">
                        <UInput :model-value="shareUrl" readonly size="sm" class="flex-1" @focus="(e: any) => e.target.select()" />
                        <UButton color="gray" variant="outline" size="xs" icon="i-heroicons-clipboard" @click="copyLink">
                            {{ $t('studio.copyLink') }}
                        </UButton>
                    </div>
                    <button
                        v-if="canManage"
                        class="mt-1.5 text-[11px] text-[#C2541E] hover:text-[#A8330F]"
                        @click="saveScope(true)"
                    >
                        {{ $t('studio.regenerateLink') }}
                    </button>
                </div>

                <div v-if="canManage" class="mt-3 flex justify-end">
                    <UButton
                        color="primary"
                        variant="soft"
                        size="xs"
                        :loading="savingScope"
                        @click="saveScope(false)"
                    >
                        {{ $t('studio.saveSharing') }}
                    </UButton>
                </div>
            </div>

            <hr class="border-gray-100 mb-5" />

            <!-- Members -->
            <div>
                <div class="flex items-center justify-between mb-1">
                    <h3 class="text-sm font-medium text-gray-900">{{ $t('studio.membersTitle') }}</h3>
                </div>
                <p class="text-[11px] text-gray-500 mb-3">{{ $t('studio.membersHint') }}</p>

                <!-- Invite by email (owner only) -->
                <div v-if="canManage" class="flex items-center gap-2 mb-3">
                    <UInput
                        v-model="inviteEmail"
                        type="email"
                        :placeholder="$t('studio.inviteEmail')"
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
                    <UButton
                        color="primary"
                        size="xs"
                        :loading="inviting"
                        :disabled="!inviteEmail.trim()"
                        @click="invite"
                    >
                        {{ $t('studio.invite') }}
                    </UButton>
                </div>

                <!-- Member list -->
                <div v-if="loadingMembers" class="flex items-center justify-center py-6 text-gray-400">
                    <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
                </div>

                <ul v-else class="divide-y divide-gray-100 border border-gray-100 rounded-lg overflow-hidden">
                    <li
                        v-for="m in members"
                        :key="m.id"
                        class="flex items-center justify-between px-3 py-2 bg-white"
                    >
                        <div class="min-w-0">
                            <div class="flex items-center gap-1.5">
                                <span class="text-xs font-medium text-gray-800 truncate">
                                    {{ m.user_name || m.user_email || m.user_id }}
                                </span>
                                <span v-if="String(m.user_id) === ownerUserId" class="text-[9px] uppercase tracking-wide text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">
                                    {{ $t('studio.roleOwner') }}
                                </span>
                            </div>
                            <span v-if="m.user_email && m.user_name" class="text-[11px] text-gray-400 truncate">{{ m.user_email }}</span>
                        </div>
                        <div class="flex items-center gap-2 shrink-0">
                            <USelectMenu
                                v-if="canManage && String(m.user_id) !== ownerUserId"
                                :model-value="m.role"
                                :options="roleOptions"
                                value-attribute="value"
                                option-attribute="label"
                                size="2xs"
                                class="w-24"
                                @update:model-value="(r: string) => changeRole(m, r)"
                            />
                            <span v-else class="text-[11px] text-gray-500">{{ roleLabel(m.role) }}</span>
                            <button
                                v-if="canManage && String(m.user_id) !== ownerUserId"
                                class="text-gray-300 hover:text-red-500"
                                :title="$t('studio.removeMember')"
                                @click="removeMember(m)"
                            >
                                <UIcon name="i-heroicons-x-mark" class="w-4 h-4" />
                            </button>
                        </div>
                    </li>
                </ul>
            </div>

            <div v-if="errorMsg" class="mt-4 bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">
                {{ errorMsg }}
            </div>

            <div class="mt-6 flex justify-end">
                <UButton color="gray" variant="outline" size="sm" @click="close">{{ $t('common.close') }}</UButton>
            </div>
        </div>
    </UModal>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

interface Member {
    id: string
    studio_id: string
    user_id: string
    role: string
    user_name?: string | null
    user_email?: string | null
}

const props = defineProps<{
    modelValue: boolean
    studioId: string
    ownerUserId: string
    canManage: boolean
    shareScope: string
    shareToken?: string | null
}>()

const emit = defineEmits<{
    'update:modelValue': [value: boolean]
    'updated': [payload: { share_scope: string; share_token: string | null }]
}>()

const { t } = useI18n()
const toast = useToast()

const isOpen = computed({
    get: () => props.modelValue,
    set: (v) => emit('update:modelValue', v),
})

const scope = ref(props.shareScope || 'private')
const shareToken = ref<string | null>(props.shareToken ?? null)
const savingScope = ref(false)

const members = ref<Member[]>([])
const loadingMembers = ref(false)
const inviteEmail = ref('')
const inviteRole = ref('viewer')
const inviting = ref(false)
const errorMsg = ref<string | null>(null)

const scopeOptions = computed(() => [
    { value: 'private', label: t('studio.scopePrivate'), hint: t('studio.scopePrivateHint') },
    { value: 'org', label: t('studio.scopeOrg'), hint: t('studio.scopeOrgHint') },
    { value: 'link', label: t('studio.scopeLink'), hint: t('studio.scopeLinkHint') },
])
const roleOptions = computed(() => [
    { value: 'viewer', label: t('studio.roleViewer') },
    { value: 'editor', label: t('studio.roleEditor') },
    { value: 'owner', label: t('studio.roleOwner') },
])
const roleLabel = (r: string) => roleOptions.value.find(o => o.value === r)?.label || r

const shareUrl = computed(() => {
    if (!shareToken.value) return ''
    const origin = typeof window !== 'undefined' ? window.location.origin : ''
    return `${origin}/studios/shared/${shareToken.value}`
})

const close = () => { isOpen.value = false }

const fetchMembers = async () => {
    loadingMembers.value = true
    errorMsg.value = null
    try {
        const { data, error } = await useMyFetch<Member[]>(`/studios/${props.studioId}/members`, { method: 'GET' })
        if (error?.value) throw error.value
        members.value = data.value || []
    } catch (e: any) {
        console.error('Failed to load members:', e)
        errorMsg.value = t('studio.actionFailed')
    } finally {
        loadingMembers.value = false
    }
}

const saveScope = async (regenerate: boolean) => {
    savingScope.value = true
    errorMsg.value = null
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/share`, {
            method: 'PATCH',
            body: { share_scope: scope.value, regenerate },
        })
        if (error?.value) throw error.value
        const updated = data.value || {}
        scope.value = updated.share_scope || scope.value
        shareToken.value = updated.share_token ?? null
        emit('updated', { share_scope: scope.value, share_token: shareToken.value })
        toast.add({ title: t('studio.savedSharing'), color: 'green', icon: 'i-heroicons-check-circle' })
    } catch (e: any) {
        console.error('Failed to save sharing:', e)
        errorMsg.value = t('studio.actionFailed')
    } finally {
        savingScope.value = false
    }
}

const invite = async () => {
    const email = inviteEmail.value.trim()
    if (!email) return
    inviting.value = true
    errorMsg.value = null
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/members`, {
            method: 'POST',
            body: { email, role: inviteRole.value },
        })
        if (error?.value) throw error.value
        inviteEmail.value = ''
        inviteRole.value = 'viewer'
        toast.add({ title: t('studio.memberInvited'), color: 'green', icon: 'i-heroicons-check-circle' })
        await fetchMembers()
    } catch (e: any) {
        console.error('Failed to invite member:', e)
        errorMsg.value = t('studio.actionFailed')
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
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    }
}

const removeMember = async (m: Member) => {
    if (!window.confirm(t('studio.removeMember') + '?')) return
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/members/${m.user_id}`, { method: 'DELETE' })
        if (error?.value) throw error.value
        toast.add({ title: t('studio.memberRemoved'), color: 'green', icon: 'i-heroicons-check-circle' })
        await fetchMembers()
    } catch (e: any) {
        console.error('Failed to remove member:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    }
}

const copyLink = async () => {
    if (!shareUrl.value) return
    try {
        await navigator.clipboard.writeText(shareUrl.value)
        toast.add({ title: t('studio.linkCopied'), color: 'green', icon: 'i-heroicons-check-circle' })
    } catch {
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    }
}

// Re-sync local state + reload members whenever the modal opens.
watch(
    () => props.modelValue,
    (open) => {
        if (open) {
            scope.value = props.shareScope || 'private'
            shareToken.value = props.shareToken ?? null
            errorMsg.value = null
            fetchMembers()
        }
    },
    { immediate: true }
)
</script>
