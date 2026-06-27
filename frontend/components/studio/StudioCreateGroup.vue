<template>
    <!-- Inline create-group. Creates a PERSONAL "My Group" (owner = current user)
         via /me/groups so any member — admin or not — can make reusable share
         targets. Org/admin-wide groups are managed in Settings → Groups. Group
         names are unique across the whole organization (409 on collision). -->
    <UModal v-model="isOpen" :ui="{ width: 'sm:max-w-md' }">
        <div class="bg-white rounded-xl overflow-hidden">
            <div class="flex items-center justify-between px-4 py-3 border-b border-[#EFEDE6]">
                <h3 class="text-sm font-semibold text-[#1f2328]" style="font-family: ui-serif, Georgia, serif">Create group</h3>
                <button type="button" class="text-[#9a958c] hover:text-[#6b6b6b]" @click="close">
                    <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
                </button>
            </div>

            <div class="px-4 py-3 space-y-3">
                <div>
                    <label class="block text-[11px] font-medium text-[#6b6b6b] mb-1">Name</label>
                    <input
                        v-model="name"
                        type="text"
                        placeholder="Finance-Core"
                        class="w-full text-xs border border-[#E9E0D3] rounded-lg px-2.5 py-2 text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E]"
                        @keyup.enter="create"
                    />
                </div>
                <div>
                    <label class="block text-[11px] font-medium text-[#6b6b6b] mb-1">Description <span class="text-[#9a958c]">(optional)</span></label>
                    <input
                        v-model="description"
                        type="text"
                        placeholder="APAC finance analysts"
                        class="w-full text-xs border border-[#E9E0D3] rounded-lg px-2.5 py-2 text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E]"
                    />
                </div>

                <div>
                    <label class="block text-[11px] font-medium text-[#6b6b6b] mb-1">Add members <span class="text-[#9a958c]">({{ selected.size }})</span></label>
                    <input
                        v-model="search"
                        type="text"
                        placeholder="Search org users…"
                        class="w-full text-xs border border-[#E9E0D3] rounded-lg px-2.5 py-2 mb-1.5 text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E]"
                    />
                    <div v-if="loadingUsers" class="flex items-center py-3 text-[#9a958c]">
                        <Spinner class="h-3.5 w-3.5" /><span class="ms-2 text-[11px]">Loading…</span>
                    </div>
                    <ul v-else-if="filteredUsers.length" class="max-h-44 overflow-y-auto border border-[#F0EEE6] rounded-lg divide-y divide-[#F5F3EC]">
                        <li
                            v-for="u in filteredUsers"
                            :key="u.user_id || u.membership_id"
                            class="flex items-center gap-2 px-2.5 py-1.5 hover:bg-[#faf8f3] cursor-pointer"
                            @click="toggle(u)"
                        >
                            <input
                                type="checkbox"
                                :checked="selected.has(u.user_id || u.membership_id)"
                                class="text-[#C2541E] focus:ring-[#C2541E] rounded"
                                @click.stop="toggle(u)"
                            />
                            <span class="text-xs text-[#1f2328] truncate flex-1">{{ u.name }}</span>
                            <span class="text-[10px] text-[#9a958c] truncate">{{ u.email }}</span>
                        </li>
                    </ul>
                    <p v-else class="text-[11px] text-[#9a958c] py-2">No org users found.</p>
                </div>
            </div>

            <div class="px-4 py-3 border-t border-[#EFEDE6] flex items-center justify-end gap-2">
                <UButton color="gray" variant="ghost" size="xs" @click="close">Cancel</UButton>
                <UButton color="orange" size="xs" :loading="creating" :disabled="!name.trim()" @click="create">Create</UButton>
            </div>
        </div>
    </UModal>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

interface OrgUser {
    user_id: string | null
    membership_id: string
    name: string
    email: string
}

const props = defineProps<{
    modelValue: boolean
    organizationId: string
}>()

const emit = defineEmits<{
    'update:modelValue': [v: boolean]
    'created': [group: { id: string; name: string }]
}>()

const toast = useToast()

const isOpen = computed({
    get: () => props.modelValue,
    set: (v) => emit('update:modelValue', v),
})

const name = ref('')
const description = ref('')
const search = ref('')
const users = ref<OrgUser[]>([])
const loadingUsers = ref(false)
const selected = ref<Set<string>>(new Set())
const creating = ref(false)

const filteredUsers = computed(() => {
    const q = search.value.trim().toLowerCase()
    if (!q) return users.value
    return users.value.filter(u => u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q))
})

const toggle = (u: OrgUser) => {
    const key = u.user_id || u.membership_id
    const s = new Set(selected.value)
    s.has(key) ? s.delete(key) : s.add(key)
    selected.value = s
}

const loadUsers = async () => {
    loadingUsers.value = true
    try {
        // /me/contacts = registered org members, readable by any member (the
        // admin-only /organizations/{org}/members route 403s for normal users).
        const { data, error } = await useMyFetch<any[]>(`/me/contacts`)
        if (error?.value) throw error.value
        users.value = ((data.value as any[]) || []).map(c => ({
            user_id: c.user_id || null,
            membership_id: c.user_id || '',
            name: c.name || c.email || 'Member',
            email: c.email || '',
        }))
    } catch (e) {
        console.error('Failed to load contacts:', e)
        users.value = []
    } finally {
        loadingUsers.value = false
    }
}

const create = async () => {
    const nm = name.value.trim()
    if (!nm) return
    creating.value = true
    try {
        // Member user_ids chosen in the picker. The creator is auto-added server-side.
        const memberIds = users.value
            .filter(u => u.user_id && selected.value.has(u.user_id))
            .map(u => u.user_id as string)

        const { data, error } = await useMyFetch<any>(`/me/groups`, {
            method: 'POST',
            body: { name: nm, description: description.value.trim() || null, member_user_ids: memberIds },
        })
        if (error?.value) throw error.value
        const group = data.value
        if (!group?.id) throw new Error('No group id returned')

        toast.add({ title: `Group "${nm}" created`, color: 'green', icon: 'i-heroicons-check-circle' })
        emit('created', { id: group.id, name: group.name || nm })
        close()
    } catch (e: any) {
        console.error('Failed to create group:', e)
        const status = e?.statusCode || e?.status || e?.response?.status
        const detail = e?.data?.detail || e?.response?._data?.detail
        let msg = 'Could not create group.'
        if (status === 409) msg = detail || 'A group with that name already exists.'
        else if (status === 404 || status === 402) msg = 'Groups are not enabled on the server.'
        toast.add({ title: msg, color: 'red' })
    } finally {
        creating.value = false
    }
}

const close = () => { isOpen.value = false }

watch(isOpen, (v) => {
    if (v) {
        name.value = ''
        description.value = ''
        search.value = ''
        selected.value = new Set()
        loadUsers()
    }
})
</script>
