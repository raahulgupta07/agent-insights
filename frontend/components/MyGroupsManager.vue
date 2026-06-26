<template>
    <div class="mt-4">
        <!-- Feature disabled note -->
        <div
            v-if="flagLoaded && !flagEnabled"
            class="rounded-lg border px-4 py-3 text-sm"
            style="border-color:#E9E0D3;background:#FBFAF6;color:#6b6b6b;"
        >
            Personal groups are not enabled for this organization.
        </div>

        <template v-else>
            <!-- Header -->
            <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
                <div>
                    <h2 class="text-base font-semibold" style="color:#1f2328;">Your groups — reusable share targets</h2>
                    <p class="text-sm" style="color:#6b6b6b;">Group people you share with often, then pick the group instead of adding everyone each time.</p>
                </div>
                <UButton color="primary" variant="solid" size="xs" icon="i-heroicons-plus" @click="openCreate">
                    Create group
                </UButton>
            </div>

            <!-- Loading -->
            <div v-if="isLoading" class="flex items-center justify-center py-12 text-sm" style="color:#6b6b6b;">
                <Spinner class="w-4 h-4 me-2" /> Loading…
            </div>

            <!-- Empty state -->
            <button
                v-else-if="groups.length === 0"
                type="button"
                class="w-full rounded-xl border-2 border-dashed flex flex-col items-center justify-center py-14 hover:bg-[#FBFAF6] transition-colors"
                style="border-color:#E9E0D3;"
                @click="openCreate"
            >
                <div class="h-12 w-12 rounded-full flex items-center justify-center mb-3" style="background:#F6EFEA;">
                    <Icon name="heroicons:user-group" class="w-6 h-6" style="color:#A8330F;" />
                </div>
                <span class="text-sm font-medium" style="color:#1f2328;">Create your first group</span>
                <span class="text-xs mt-1" style="color:#6b6b6b;">Bundle the people you share with most.</span>
            </button>

            <!-- Group cards -->
            <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div
                    v-for="group in groups"
                    :key="group.id"
                    class="rounded-xl border p-4 flex flex-col"
                    style="border-color:#E9E0D3;background:#fff;"
                >
                    <div class="flex items-start justify-between gap-2">
                        <div class="flex items-center gap-2.5 min-w-0">
                            <div class="h-9 w-9 rounded-full flex items-center justify-center flex-shrink-0" style="background:#F6EFEA;">
                                <Icon name="heroicons:user-group" class="w-5 h-5" style="color:#A8330F;" />
                            </div>
                            <div class="min-w-0">
                                <div class="text-sm font-semibold truncate" style="color:#1f2328;">{{ group.name }}</div>
                                <div class="text-xs" style="color:#6b6b6b;">
                                    {{ memberCountLabel(group.member_count) }}
                                    <span v-if="group.shared_count != null"> · shared {{ group.shared_count }}×</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div class="flex items-center gap-2 mt-4">
                        <UButton variant="outline" color="gray" size="xs" icon="i-heroicons-users" @click="openManage(group)">
                            Manage
                        </UButton>
                        <UButton variant="ghost" color="red" size="xs" icon="i-heroicons-trash" @click="deleteGroup(group)">
                            Delete
                        </UButton>
                    </div>
                </div>
            </div>
        </template>

        <!-- Create modal -->
        <UModal v-model="showCreate">
            <div class="p-6 relative" style="background:#FBFAF6;">
                <button @click="showCreate = false" class="absolute top-4 end-4 text-gray-400 hover:text-gray-600 outline-none">
                    <Icon name="heroicons:x-mark" class="w-5 h-5" />
                </button>
                <h3 class="text-lg font-semibold" style="color:#1f2328;">Create group</h3>
                <p class="text-sm" style="color:#6b6b6b;">Name it and optionally add members now — you can change them later.</p>
                <hr class="my-4" style="border-color:#E9E0D3;" />

                <form class="space-y-4" @submit.prevent="createGroup">
                    <div class="flex flex-col">
                        <label class="text-sm font-medium mb-2" style="color:#1f2328;">Name</label>
                        <UInput v-model="createForm.name" placeholder="e.g. Finance leads" required />
                    </div>

                    <div class="flex flex-col">
                        <label class="text-sm font-medium mb-2" style="color:#1f2328;">Members</label>
                        <div class="flex items-center gap-2 flex-wrap">
                            <span
                                v-for="m in createForm.members"
                                :key="m.user_id"
                                class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full"
                                style="background:#F6EFEA;color:#A8330F;"
                            >
                                {{ m.label }}
                                <button type="button" class="hover:text-red-500 outline-none" @click="removeCreateMember(m.user_id)">
                                    <Icon name="heroicons:x-mark" class="w-3 h-3" />
                                </button>
                            </span>
                            <UButton type="button" variant="outline" color="gray" size="xs" icon="i-heroicons-plus" @click="openPickerForCreate">
                                Add members
                            </UButton>
                        </div>
                    </div>

                    <div class="flex justify-end gap-2 pt-4">
                        <UButton type="button" variant="ghost" color="gray" @click="showCreate = false">Cancel</UButton>
                        <UButton type="submit" color="primary" :loading="saving" :disabled="!createForm.name.trim()">Create</UButton>
                    </div>
                </form>
            </div>
        </UModal>

        <!-- Manage members modal -->
        <UModal v-model="showManage" :ui="{ width: 'sm:max-w-lg' }">
            <div class="p-6 relative" style="background:#FBFAF6;">
                <button @click="showManage = false" class="absolute top-4 end-4 text-gray-400 hover:text-gray-600 outline-none">
                    <Icon name="heroicons:x-mark" class="w-5 h-5" />
                </button>
                <h3 class="text-lg font-semibold" style="color:#1f2328;">{{ manageGroup?.name }}</h3>
                <p class="text-sm mb-4" style="color:#6b6b6b;">Add or remove people in this group.</p>

                <div class="flex justify-end mb-3">
                    <UButton variant="outline" color="gray" size="xs" icon="i-heroicons-plus" @click="openPickerForManage">
                        Add members
                    </UButton>
                </div>

                <div class="border rounded-lg divide-y max-h-80 overflow-y-auto" style="border-color:#E9E0D3;background:#fff;">
                    <div v-if="manageMembersLoading" class="px-4 py-8 text-center text-sm" style="color:#6b6b6b;">
                        <Spinner class="w-4 h-4 me-2 inline" /> Loading…
                    </div>
                    <div v-else-if="manageMembers.length === 0" class="px-4 py-8 text-center text-sm" style="color:#6b6b6b;">
                        No members yet.
                    </div>
                    <div
                        v-for="m in manageMembers"
                        :key="m.user_id"
                        class="flex items-center justify-between px-4 py-3"
                    >
                        <div class="flex items-center gap-3 min-w-0">
                            <div class="h-8 w-8 rounded-full flex items-center justify-center text-sm font-medium text-gray-600 flex-shrink-0" style="background:#EFEFEF;">
                                {{ (m.name || m.email || '?').charAt(0).toUpperCase() }}
                            </div>
                            <div class="min-w-0">
                                <div class="text-sm font-medium truncate" style="color:#1f2328;">{{ m.name || m.email || 'Unknown' }}</div>
                                <div v-if="m.name && m.email" class="text-xs truncate" style="color:#6b6b6b;">{{ m.email }}</div>
                            </div>
                        </div>
                        <UButton variant="ghost" color="red" size="xs" icon="i-heroicons-x-mark" @click="removeMember(m.user_id)" />
                    </div>
                </div>
            </div>
        </UModal>

        <!-- Shared picker (members only) -->
        <ContactGroupPickerModal
            v-model="showPicker"
            :organization-id="organizationId"
            mode="members"
            :exclude-ids="pickerExcludeIds"
            title="Add members"
            @confirm="onPickerConfirm"
        />
    </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import Spinner from '@/components/Spinner.vue'

interface GroupMember {
    user_id: string
    name?: string
    email?: string
}
interface MyGroup {
    id: string
    name: string
    description?: string
    member_count: number
    shared_count?: number
    members?: GroupMember[]
}

const props = defineProps<{
    organization: { id: string; name?: string }
}>()

const organizationId = props.organization.id
const toast = useToast()

const flagLoaded = ref(false)
const flagEnabled = ref(false)

const groups = ref<MyGroup[]>([])
const isLoading = ref(true)
const saving = ref(false)

// Create
const showCreate = ref(false)
const createForm = reactive<{ name: string; members: { user_id: string; label: string }[] }>({ name: '', members: [] })

// Manage
const showManage = ref(false)
const manageGroup = ref<MyGroup | null>(null)
const manageMembers = ref<GroupMember[]>([])
const manageMembersLoading = ref(false)

// Picker
const showPicker = ref(false)
const pickerTarget = ref<'create' | 'manage'>('create')

const pickerExcludeIds = computed(() => {
    if (pickerTarget.value === 'create') {
        return createForm.members.map(m => m.user_id)
    }
    return manageMembers.value.map(m => m.user_id)
})

function memberCountLabel(n?: number): string {
    const c = n || 0
    return c === 1 ? '1 member' : `${c} members`
}

async function loadFlag() {
    try {
        const { data } = await useMyFetch<any[]>('/organization/hybrid-flags')
        const rows = (data.value as any[]) || []
        const row = rows.find(r => r?.env_name === 'HYBRID_USER_GROUPS')
        flagEnabled.value = !!row?.effective
    } catch {
        // Fail-soft: if we can't read flags, hide the feature rather than show a broken UI.
        flagEnabled.value = false
    } finally {
        flagLoaded.value = true
    }
}

async function loadGroups() {
    isLoading.value = true
    try {
        const { data, error } = await useMyFetch('/me/groups')
        if (error.value) { groups.value = []; return }
        groups.value = ((data.value as any[]) || []) as MyGroup[]
    } catch {
        groups.value = []
    } finally {
        isLoading.value = false
    }
}

// ── Create ────────────────────────────────────────────────────────────
function openCreate() {
    createForm.name = ''
    createForm.members = []
    showCreate.value = true
}

function removeCreateMember(userId: string) {
    createForm.members = createForm.members.filter(m => m.user_id !== userId)
}

async function createGroup() {
    if (!createForm.name.trim()) return
    saving.value = true
    try {
        const { error } = await useMyFetch('/me/groups', {
            method: 'POST',
            body: {
                name: createForm.name.trim(),
                member_user_ids: createForm.members.map(m => m.user_id),
            },
        })
        if (error.value) {
            toast.add({ title: (error.value as any).data?.detail || 'Failed to create group', color: 'red' })
            return
        }
        toast.add({ title: 'Group created', color: 'green' })
        showCreate.value = false
        await loadGroups()
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || e?.message || 'Failed to create group', color: 'red' })
    } finally {
        saving.value = false
    }
}

// ── Manage ────────────────────────────────────────────────────────────
async function openManage(group: MyGroup) {
    manageGroup.value = group
    showManage.value = true
    manageMembersLoading.value = true
    try {
        // Prefer the embedded members payload; otherwise re-fetch the list to refresh.
        if (group.members) {
            manageMembers.value = group.members
        } else {
            const { data } = await useMyFetch('/me/groups')
            const fresh = ((data.value as any[]) || []).find((g: any) => g.id === group.id)
            manageMembers.value = (fresh?.members as GroupMember[]) || []
        }
    } catch {
        manageMembers.value = []
    } finally {
        manageMembersLoading.value = false
    }
}

async function refreshManage() {
    if (!manageGroup.value) return
    const { data } = await useMyFetch('/me/groups')
    const list = ((data.value as any[]) || []) as MyGroup[]
    groups.value = list
    const fresh = list.find(g => g.id === manageGroup.value!.id)
    manageGroup.value = fresh || manageGroup.value
    manageMembers.value = (fresh?.members as GroupMember[]) || manageMembers.value
}

async function removeMember(userId: string) {
    if (!manageGroup.value) return
    try {
        const { error } = await useMyFetch(`/me/groups/${manageGroup.value.id}/members/${userId}`, {
            method: 'DELETE',
        })
        if (error.value) {
            toast.add({ title: (error.value as any).data?.detail || 'Failed to remove member', color: 'red' })
            return
        }
        toast.add({ title: 'Member removed', color: 'green' })
        await refreshManage()
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || e?.message || 'Failed to remove member', color: 'red' })
    }
}

async function deleteGroup(group: MyGroup) {
    if (!window.confirm(`Delete group "${group.name}"? This can't be undone.`)) return
    try {
        const { error } = await useMyFetch(`/me/groups/${group.id}`, { method: 'DELETE' })
        if (error.value) {
            toast.add({ title: (error.value as any).data?.detail || 'Failed to delete group', color: 'red' })
            return
        }
        toast.add({ title: 'Group deleted', color: 'green' })
        await loadGroups()
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || e?.message || 'Failed to delete group', color: 'red' })
    }
}

// ── Picker wiring ─────────────────────────────────────────────────────
function openPickerForCreate() {
    pickerTarget.value = 'create'
    showPicker.value = true
}
function openPickerForManage() {
    pickerTarget.value = 'manage'
    showPicker.value = true
}

async function onPickerConfirm(payload: { userIds: string[]; groupIds: string[] }) {
    const userIds = payload.userIds || []
    if (!userIds.length) return

    if (pickerTarget.value === 'create') {
        // Stage members on the create form (group not persisted yet).
        const existing = new Set(createForm.members.map(m => m.user_id))
        for (const uid of userIds) {
            if (!existing.has(uid)) {
                // Label resolved lazily; the picker doesn't return labels, so show the id-fallback.
                createForm.members.push({ user_id: uid, label: shortLabel(uid) })
            }
        }
        // Try to enrich labels from contacts so chips read nicely.
        await enrichCreateLabels(userIds)
        return
    }

    // Manage: persist immediately.
    if (!manageGroup.value) return
    try {
        const { error } = await useMyFetch(`/me/groups/${manageGroup.value.id}/members`, {
            method: 'POST',
            body: { user_ids: userIds },
        })
        if (error.value) {
            toast.add({ title: (error.value as any).data?.detail || 'Failed to add members', color: 'red' })
            return
        }
        toast.add({ title: userIds.length === 1 ? 'Member added' : 'Members added', color: 'green' })
        await refreshManage()
    } catch (e: any) {
        toast.add({ title: e?.data?.detail || e?.message || 'Failed to add members', color: 'red' })
    }
}

function shortLabel(id: string): string {
    return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

async function enrichCreateLabels(userIds: string[]) {
    try {
        const { data } = await useMyFetch('/me/contacts')
        const contacts = ((data.value as any[]) || []) as GroupMember[]
        const byId = new Map(contacts.map(c => [c.user_id, c]))
        for (const m of createForm.members) {
            if (userIds.includes(m.user_id)) {
                const c = byId.get(m.user_id)
                if (c) m.label = c.name || c.email || m.label
            }
        }
    } catch {
        // labels stay as id-fallback — non-fatal
    }
}

onMounted(async () => {
    await loadFlag()
    if (flagEnabled.value) {
        await loadGroups()
    } else {
        isLoading.value = false
    }
})
</script>
