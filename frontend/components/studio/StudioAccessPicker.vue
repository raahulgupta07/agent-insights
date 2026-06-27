<template>
    <!-- Add-access modal (OpenWebUI-style). Share this studio to one or more
         groups, incl. AD/LDAP-synced groups. People are added via the People
         box in StudioAccess; this picker is groups-only. -->
    <UModal v-model="isOpen" :ui="{ width: 'sm:max-w-lg' }">
        <div class="bg-white rounded-xl overflow-hidden">
            <div class="flex items-center justify-between px-4 py-3 border-b border-[#EFEDE6]">
                <div>
                    <h3 class="text-sm font-semibold text-[#1f2328]" style="font-family: ui-serif, Georgia, serif">Add access</h3>
                    <p class="text-[11px] text-[#9a958c] mt-0.5">Grant groups permission to this agent.</p>
                </div>
                <button type="button" class="text-[#9a958c] hover:text-[#6b6b6b]" @click="close">
                    <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
                </button>
            </div>

            <div class="px-4 py-3 border-b border-[#EFEDE6]">
                <input
                    v-model="search"
                    type="text"
                    placeholder="Search groups…"
                    class="w-full text-xs border border-[#E9E0D3] rounded-lg px-2.5 py-2 text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E]"
                />
            </div>

            <div class="px-4 py-3">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-[10px] uppercase tracking-wide text-[#9a958c] font-medium">Groups</span>
                    <button
                        type="button"
                        class="text-[11px] text-[#C2541E] hover:text-[#A8330F] font-medium"
                        @click="emit('create-group')"
                    >
                        + Create group
                    </button>
                </div>

                <div v-if="loading" class="flex items-center justify-center py-8 text-[#9a958c]">
                    <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">Loading…</span>
                </div>
                <div v-else-if="!filteredGroups.length" class="py-8 text-center text-[11px] text-[#9a958c]">
                    {{ search ? 'No groups match.' : 'No groups yet. Create one, or sync from AD/LDAP.' }}
                </div>
                <ul v-else class="space-y-0.5 max-h-72 overflow-y-auto">
                    <li
                        v-for="g in filteredGroups"
                        :key="g.id"
                        class="flex items-center gap-2 rounded-lg px-2 py-1.5"
                        :class="g.alreadyGranted ? 'opacity-55' : 'hover:bg-[#faf8f3] cursor-pointer'"
                        @click="!g.alreadyGranted && toggle(g.id)"
                    >
                        <input
                            type="checkbox"
                            :checked="selected.has(g.id) || g.alreadyGranted"
                            :disabled="g.alreadyGranted"
                            class="text-[#C2541E] focus:ring-[#C2541E] rounded"
                            @click.stop="!g.alreadyGranted && toggle(g.id)"
                        />
                        <UIcon
                            :name="g.external_provider ? 'i-heroicons-shield-check' : 'i-heroicons-user-group'"
                            class="w-4 h-4 shrink-0"
                            :class="g.external_provider ? 'text-[#2F6F8B]' : 'text-[#9a958c]'"
                        />
                        <span class="text-xs text-[#1f2328] truncate flex-1">{{ g.name }}</span>
                        <span class="text-[10px] text-[#9a958c] shrink-0">·{{ g.member_count }}</span>
                        <span
                            v-if="g.external_provider"
                            class="text-[9px] uppercase tracking-wide text-[#2F6F8B] bg-[#E4EEF2] px-1.5 py-0.5 rounded shrink-0"
                        >{{ providerLabel(g.external_provider) }}</span>
                        <span
                            v-else-if="g.personal"
                            class="text-[9px] uppercase tracking-wide text-[#C2541E] bg-[#F6E8DD] px-1.5 py-0.5 rounded shrink-0"
                        >mine</span>
                        <span
                            v-else
                            class="text-[9px] uppercase tracking-wide text-[#9a958c] bg-[#F0EEE6] px-1.5 py-0.5 rounded shrink-0"
                        >local</span>
                        <span v-if="g.alreadyGranted" class="text-[9px] text-emerald-700 shrink-0">granted</span>
                    </li>
                </ul>

                <div class="mt-2 flex items-center justify-between">
                    <button
                        type="button"
                        class="inline-flex items-center gap-1 text-[11px] text-[#9a958c] hover:text-[#6b6b6b]"
                        :disabled="syncing"
                        @click="syncAd"
                    >
                        <UIcon :name="syncing ? 'i-heroicons-arrow-path' : 'i-heroicons-arrow-path'" class="w-3.5 h-3.5" :class="syncing ? 'animate-spin' : ''" />
                        {{ syncing ? 'Syncing…' : 'Sync from AD/LDAP' }}
                    </button>
                    <span v-if="syncMsg" class="text-[10px] text-[#9a958c]">{{ syncMsg }}</span>
                </div>
            </div>

            <div class="px-4 py-3 border-t border-[#EFEDE6] flex items-center justify-between gap-3">
                <div class="flex items-center gap-3 text-[11px]">
                    <span class="text-[#6b6b6b]">Permission</span>
                    <label class="inline-flex items-center gap-1 cursor-pointer">
                        <input type="radio" value="read" v-model="permission" class="text-[#C2541E] focus:ring-[#C2541E]" />
                        <span class="text-[#1f2328]">Viewer</span>
                    </label>
                    <label class="inline-flex items-center gap-1 cursor-pointer">
                        <input type="radio" value="write" v-model="permission" class="text-[#C2541E] focus:ring-[#C2541E]" />
                        <span class="text-[#1f2328]">Editor</span>
                    </label>
                </div>
                <div class="flex items-center gap-2">
                    <UButton color="gray" variant="ghost" size="xs" @click="close">Cancel</UButton>
                    <UButton color="orange" size="xs" :loading="adding" :disabled="!selected.size" @click="addSelected">
                        Add{{ selected.size ? ` (${selected.size})` : '' }}
                    </UButton>
                </div>
            </div>
        </div>
    </UModal>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

interface OrgGroup {
    id: string
    name: string
    member_count: number
    external_provider?: string | null
    personal?: boolean   // owned by the current user (My Groups), not an org/synced group
}

const props = defineProps<{
    modelValue: boolean
    studioId: string
    organizationId: string
    grantedGroupIds: string[]   // already-shared groups → shown disabled
}>()

const emit = defineEmits<{
    'update:modelValue': [v: boolean]
    'added': []
    'create-group': []
}>()

const toast = useToast()

const isOpen = computed({
    get: () => props.modelValue,
    set: (v) => emit('update:modelValue', v),
})

const groups = ref<OrgGroup[]>([])
const loading = ref(false)
const search = ref('')
const selected = ref<Set<string>>(new Set())
const permission = ref<'read' | 'write'>('read')
const adding = ref(false)

const grantedSet = computed(() => new Set((props.grantedGroupIds || []).map(String)))

const filteredGroups = computed(() => {
    const q = search.value.trim().toLowerCase()
    return groups.value
        .map(g => ({ ...g, alreadyGranted: grantedSet.value.has(String(g.id)) }))
        .filter(g => !q || g.name.toLowerCase().includes(q))
})

const providerLabel = (p?: string | null) => {
    const v = (p || '').toLowerCase()
    if (v.includes('azure') || v.includes('ad')) return 'AD'
    if (v.includes('ldap')) return 'LDAP'
    if (v.includes('okta')) return 'Okta'
    if (v.includes('scim')) return 'SCIM'
    return 'synced'
}

const toggle = (id: string) => {
    const s = new Set(selected.value)
    s.has(id) ? s.delete(id) : s.add(id)
    selected.value = s
}

const loadGroups = async () => {
    if (!props.organizationId) return
    loading.value = true
    try {
        const merged: OrgGroup[] = []
        const seen = new Set<string>()

        // 1) Personal "My Groups" — works for every member (incl. non-admins).
        try {
            const { data: mineData, error: mineErr } = await useMyFetch<any[]>(`/me/groups`)
            if (!mineErr?.value) {
                for (const g of (mineData.value as any[]) || []) {
                    if (seen.has(String(g.id))) continue
                    seen.add(String(g.id))
                    merged.push({ id: g.id, name: g.name, member_count: g.member_count ?? 0, personal: true })
                }
            }
        } catch (e) { /* feature off → no personal groups, ignore */ }

        // 2) Org / admin / AD-LDAP-synced groups — admin-only route, 403 for
        //    normal users → just skip and show personal groups only.
        try {
            const { data, error } = await useMyFetch<any[]>(`/organizations/${props.organizationId}/groups`)
            if (!error?.value) {
                for (const g of (data.value as any[]) || []) {
                    if (seen.has(String(g.id))) continue
                    seen.add(String(g.id))
                    merged.push({ id: g.id, name: g.name, member_count: g.member_count ?? 0, external_provider: g.external_provider })
                }
            }
        } catch (e) { /* non-admin → org groups not visible, ignore */ }

        groups.value = merged
    } catch (e) {
        console.error('Failed to load groups:', e)
        groups.value = []
    } finally {
        loading.value = false
    }
}

const addSelected = async () => {
    if (!selected.value.size) return
    adding.value = true
    let ok = 0
    try {
        for (const gid of selected.value) {
            const { error } = await useMyFetch(`/studios/${props.studioId}/group-grants`, {
                method: 'POST',
                body: { group_id: gid, permission: permission.value },
            })
            if (!error?.value) ok++
        }
        toast.add({ title: `Shared to ${ok} group${ok === 1 ? '' : 's'}`, color: 'green', icon: 'i-heroicons-check-circle' })
        selected.value = new Set()
        emit('added')
        close()
    } catch (e) {
        console.error('Failed to add group grants:', e)
        toast.add({ title: 'Action failed', color: 'red' })
    } finally {
        adding.value = false
    }
}

// ── AD/LDAP sync (Phase 5 surface; backend already exists) ────────────────
const syncing = ref(false)
const syncMsg = ref('')
const syncAd = async () => {
    syncing.value = true
    syncMsg.value = ''
    try {
        const { data, error } = await useMyFetch<any>(`/enterprise/ldap/sync`, { method: 'POST' })
        if (error?.value) throw error.value
        const r = data.value || {}
        const created = r.groups_created ?? 0
        const updated = r.groups_updated ?? 0
        syncMsg.value = `+${created} new · ${updated} updated`
        await loadGroups()
    } catch (e: any) {
        // LDAP may be unconfigured → soft message, not a hard error.
        syncMsg.value = 'LDAP not configured'
    } finally {
        syncing.value = false
    }
}

const close = () => { isOpen.value = false }

watch(isOpen, (v) => {
    if (v) {
        selected.value = new Set()
        search.value = ''
        permission.value = 'read'
        syncMsg.value = ''
        loadGroups()
    }
})
</script>
