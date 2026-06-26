<template>
    <UModal v-model="isOpen" :ui="{ width: 'sm:max-w-lg' }">
        <div class="p-6 relative" style="background:#FBFAF6;">
            <!-- Header -->
            <div class="flex items-center justify-between mb-1">
                <h2 class="text-base font-semibold" style="color:#1f2328;">{{ title || 'Add members & groups' }}</h2>
                <button @click="close" class="text-gray-400 hover:text-gray-600 outline-none">
                    <Icon name="heroicons:x-mark" class="w-5 h-5" />
                </button>
            </div>
            <p class="text-sm mb-4" style="color:#6b6b6b;">Pick people and groups to add.</p>

            <!-- Selected chips -->
            <div v-if="selectedChips.length" class="flex flex-wrap gap-1.5 mb-4">
                <span
                    v-for="chip in selectedChips"
                    :key="chip.key"
                    class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full whitespace-nowrap"
                    style="background:#F6EFEA;color:#A8330F;"
                >
                    <Icon :name="chip.kind === 'group' ? 'heroicons:user-group' : 'heroicons:user'" class="w-3 h-3" />
                    {{ chip.label }}
                    <button class="hover:text-red-500 outline-none" @click="toggle(chip.kind, chip.id)">
                        <Icon name="heroicons:x-mark" class="w-3 h-3" />
                    </button>
                </span>
            </div>

            <!-- Search -->
            <div class="relative mb-4">
                <input
                    v-model="search"
                    type="text"
                    placeholder="Search people and groups…"
                    class="w-full ps-9 pe-3 py-2 text-sm border rounded-lg outline-none focus:ring-2"
                    style="border-color:#E9E0D3;background:#fff;color:#1f2328;"
                    @input="onSearchInput"
                />
                <Icon name="heroicons:magnifying-glass" class="absolute start-3 top-2.5 h-4 w-4 text-gray-400" />
            </div>

            <!-- Sections -->
            <div class="max-h-80 overflow-y-auto -mx-1 px-1 space-y-5">
                <!-- YOUR GROUPS -->
                <div v-if="showGroups && myGroups.length">
                    <div class="text-[11px] font-semibold uppercase tracking-wider mb-1.5" style="color:#6b6b6b;">Your groups</div>
                    <div class="space-y-0.5">
                        <button
                            v-for="g in filteredMyGroups"
                            :key="`mine-${g.id}`"
                            type="button"
                            class="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-[#F4EEE5] text-start"
                            @click="toggle('group', g.id)"
                        >
                            <UCheckbox :model-value="isSelected('group', g.id)" @click.stop="toggle('group', g.id)" />
                            <div class="h-7 w-7 rounded-full flex items-center justify-center flex-shrink-0" style="background:#F6EFEA;">
                                <Icon name="heroicons:user-group" class="w-4 h-4" style="color:#A8330F;" />
                            </div>
                            <div class="flex flex-col min-w-0 flex-1">
                                <span class="text-sm truncate" style="color:#1f2328;">{{ g.name }}</span>
                                <span class="text-xs" style="color:#6b6b6b;">{{ memberCountLabel(g.member_count) }}</span>
                            </div>
                            <span class="text-[10px] px-1.5 py-0.5 rounded-full" style="background:#F6EFEA;color:#A8330F;">yours</span>
                        </button>
                    </div>
                </div>

                <!-- ORG GROUPS -->
                <div v-if="showGroups && orgGroups.length">
                    <div class="text-[11px] font-semibold uppercase tracking-wider mb-1.5" style="color:#6b6b6b;">Org groups</div>
                    <div class="space-y-0.5">
                        <button
                            v-for="g in filteredOrgGroups"
                            :key="`org-${g.id}`"
                            type="button"
                            class="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-[#F4EEE5] text-start"
                            @click="toggle('group', g.id)"
                        >
                            <UCheckbox :model-value="isSelected('group', g.id)" @click.stop="toggle('group', g.id)" />
                            <div class="h-7 w-7 rounded-full flex items-center justify-center flex-shrink-0" style="background:#EFEFEF;">
                                <Icon name="heroicons:user-group" class="w-4 h-4 text-gray-500" />
                            </div>
                            <div class="flex flex-col min-w-0 flex-1">
                                <span class="text-sm truncate" style="color:#1f2328;">{{ g.name }}</span>
                                <span class="text-xs" style="color:#6b6b6b;">{{ memberCountLabel(g.member_count) }}</span>
                            </div>
                        </button>
                    </div>
                </div>

                <!-- PEOPLE -->
                <div v-if="showMembers && people.length">
                    <div class="text-[11px] font-semibold uppercase tracking-wider mb-1.5" style="color:#6b6b6b;">People</div>
                    <div class="space-y-0.5">
                        <button
                            v-for="p in filteredPeople"
                            :key="`p-${p.user_id}`"
                            type="button"
                            class="w-full flex items-center gap-2.5 px-2 py-1.5 rounded-lg hover:bg-[#F4EEE5] text-start"
                            @click="toggle('user', p.user_id)"
                        >
                            <UCheckbox :model-value="isSelected('user', p.user_id)" @click.stop="toggle('user', p.user_id)" />
                            <div class="h-7 w-7 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-medium text-gray-600" style="background:#EFEFEF;">
                                {{ initials(p) }}
                            </div>
                            <div class="flex flex-col min-w-0 flex-1">
                                <span class="text-sm truncate" style="color:#1f2328;">{{ p.name || p.email }}</span>
                                <span v-if="p.name && p.email" class="text-xs truncate" style="color:#6b6b6b;">{{ p.email }}</span>
                            </div>
                        </button>
                    </div>
                </div>

                <!-- Loading / empty -->
                <div v-if="loading" class="py-8 text-center text-sm" style="color:#6b6b6b;">
                    <Spinner class="w-4 h-4 me-2 inline" /> Loading…
                </div>
                <div v-else-if="!hasAnyResults" class="py-8 text-center text-sm" style="color:#6b6b6b;">
                    No matches.
                </div>
            </div>

            <!-- Footer -->
            <div class="flex justify-end gap-2 pt-5 mt-1 border-t" style="border-color:#E9E0D3;">
                <UButton variant="ghost" color="gray" @click="close">Cancel</UButton>
                <UButton
                    color="primary"
                    :disabled="totalSelected === 0"
                    @click="confirm"
                >
                    {{ totalSelected ? `Add ${totalSelected} selected` : 'Add selected' }}
                </UButton>
            </div>
        </div>
    </UModal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import Spinner from '@/components/Spinner.vue'

interface GroupRow {
    id: string
    name: string
    member_count?: number
}
interface Contact {
    user_id: string
    name?: string
    email?: string
}

const props = withDefaults(defineProps<{
    modelValue: boolean
    organizationId: string
    multiple?: boolean
    selectedIds?: string[]
    excludeIds?: string[]
    mode?: 'members' | 'groups' | 'both'
    title?: string
}>(), {
    multiple: true,
    selectedIds: () => [],
    excludeIds: () => [],
    mode: 'both',
    title: '',
})

const emit = defineEmits<{
    (e: 'update:modelValue', value: boolean): void
    (e: 'confirm', payload: { userIds: string[]; groupIds: string[] }): void
}>()

const isOpen = computed({
    get: () => props.modelValue,
    set: (v: boolean) => emit('update:modelValue', v),
})

const showGroups = computed(() => props.mode === 'groups' || props.mode === 'both')
const showMembers = computed(() => props.mode === 'members' || props.mode === 'both')

const search = ref('')
const loading = ref(false)
const myGroups = ref<GroupRow[]>([])
const orgGroups = ref<GroupRow[]>([])
const people = ref<Contact[]>([])

// Selection — group ids + user ids. Seeded from selectedIds (treated as either,
// resolved against loaded data so a preselected id lights up the right row).
const selectedGroupIds = ref<Set<string>>(new Set())
const selectedUserIds = ref<Set<string>>(new Set())

const excludeSet = computed(() => new Set(props.excludeIds || []))

function isSelected(kind: 'group' | 'user', id: string): boolean {
    return kind === 'group' ? selectedGroupIds.value.has(id) : selectedUserIds.value.has(id)
}

function toggle(kind: 'group' | 'user', id: string) {
    const set = kind === 'group' ? selectedGroupIds : selectedUserIds
    const next = new Set(set.value)
    if (next.has(id)) {
        next.delete(id)
    } else {
        if (!props.multiple) {
            // single-select mode: clear everything first
            selectedGroupIds.value = new Set()
            selectedUserIds.value = new Set()
        }
        next.add(id)
    }
    set.value = next
}

const totalSelected = computed(() => selectedGroupIds.value.size + selectedUserIds.value.size)

const q = computed(() => search.value.trim().toLowerCase())

function matchesGroup(g: GroupRow): boolean {
    if (excludeSet.value.has(g.id)) return false
    if (!q.value) return true
    return (g.name || '').toLowerCase().includes(q.value)
}
function matchesPerson(p: Contact): boolean {
    if (excludeSet.value.has(p.user_id)) return false
    if (!q.value) return true
    return (p.name || '').toLowerCase().includes(q.value) || (p.email || '').toLowerCase().includes(q.value)
}

// Don't show a group twice — if a "your group" id also appears in org list, the
// YOUR GROUPS section wins; filter it out of org groups.
const myGroupIdSet = computed(() => new Set(myGroups.value.map(g => g.id)))

const filteredMyGroups = computed(() => myGroups.value.filter(matchesGroup))
const filteredOrgGroups = computed(() => orgGroups.value.filter(g => !myGroupIdSet.value.has(g.id) && matchesGroup(g)))
const filteredPeople = computed(() => people.value.filter(matchesPerson))

const hasAnyResults = computed(() =>
    (showGroups.value && (filteredMyGroups.value.length || filteredOrgGroups.value.length)) ||
    (showMembers.value && filteredPeople.value.length)
)

// Chips — resolve labels from loaded data, fall back to the raw id.
const selectedChips = computed(() => {
    const chips: { key: string; kind: 'group' | 'user'; id: string; label: string }[] = []
    for (const id of selectedGroupIds.value) {
        const g = myGroups.value.find(x => x.id === id) || orgGroups.value.find(x => x.id === id)
        chips.push({ key: `g-${id}`, kind: 'group', id, label: g?.name || 'Group' })
    }
    for (const id of selectedUserIds.value) {
        const p = people.value.find(x => x.user_id === id)
        chips.push({ key: `u-${id}`, kind: 'user', id, label: p?.name || p?.email || 'Person' })
    }
    return chips
})

function initials(p: Contact): string {
    const base = p.name || p.email || '?'
    return base.charAt(0).toUpperCase()
}
function memberCountLabel(n?: number): string {
    const c = n || 0
    return c === 1 ? '1 member' : `${c} members`
}

async function loadMyGroups() {
    if (!showGroups.value) return
    try {
        const { data, error } = await useMyFetch('/me/groups')
        if (error.value) { myGroups.value = []; return }
        myGroups.value = ((data.value as any[]) || []).map(g => ({ id: g.id, name: g.name, member_count: g.member_count }))
    } catch {
        // Feature flag off / 404 → just hide the section.
        myGroups.value = []
    }
}

async function loadOrgGroups() {
    if (!showGroups.value) return
    try {
        const { data, error } = await useMyFetch(`/organizations/${props.organizationId}/groups`)
        if (error.value) { orgGroups.value = []; return }
        orgGroups.value = ((data.value as any[]) || []).map(g => ({ id: g.id, name: g.name, member_count: g.member_count }))
    } catch {
        orgGroups.value = []
    }
}

async function loadPeople() {
    if (!showMembers.value) return
    try {
        const { data, error } = await useMyFetch(`/me/contacts?q=${encodeURIComponent(search.value.trim())}`)
        if (error.value) { people.value = []; return }
        people.value = ((data.value as any[]) || []).map(c => ({ user_id: c.user_id, name: c.name, email: c.email }))
    } catch {
        people.value = []
    }
}

// Server-side q for /me/contacts is debounced; client-side filtering covers groups.
let searchTimer: any = null
function onSearchInput() {
    if (!showMembers.value) return
    if (searchTimer) clearTimeout(searchTimer)
    searchTimer = setTimeout(() => { loadPeople() }, 250)
}

function seedSelection() {
    // Resolve preselected ids against loaded data: id present in any group list →
    // group; id present in people → user; otherwise leave it as a group id guess.
    const groupIds = new Set([...myGroups.value, ...orgGroups.value].map(g => g.id))
    const userIds = new Set(people.value.map(p => p.user_id))
    const g = new Set<string>()
    const u = new Set<string>()
    for (const id of props.selectedIds || []) {
        if (userIds.has(id)) u.add(id)
        else if (groupIds.has(id)) g.add(id)
        else g.add(id) // unknown → assume group (caller intent for share targets)
    }
    selectedGroupIds.value = g
    selectedUserIds.value = u
}

async function loadAll() {
    loading.value = true
    try {
        await Promise.all([loadMyGroups(), loadOrgGroups(), loadPeople()])
        seedSelection()
    } finally {
        loading.value = false
    }
}

function close() {
    isOpen.value = false
}

function confirm() {
    emit('confirm', {
        userIds: Array.from(selectedUserIds.value),
        groupIds: Array.from(selectedGroupIds.value),
    })
    isOpen.value = false
}

watch(() => props.modelValue, (open) => {
    if (open) {
        search.value = ''
        loadAll()
    }
})
</script>
