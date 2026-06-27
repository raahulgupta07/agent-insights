<template>
  <div class="max-w-3xl mx-auto px-6 py-8">
    <!-- Header -->
    <div class="flex items-start justify-between mb-6">
      <div>
        <h1 class="text-xl font-semibold text-[#1f2328]" style="font-family: ui-serif, Georgia, serif">My Groups</h1>
        <p class="text-xs text-[#9a958c] mt-1 max-w-md">
          Personal contact groups you own. Use them as reusable share targets when
          giving people access to an agent. Group names are unique across the whole
          organization.
        </p>
      </div>
      <UButton color="orange" size="sm" icon="i-heroicons-plus" @click="openCreate">New group</UButton>
    </div>

    <!-- Disabled state -->
    <div v-if="featureOff" class="rounded-xl border border-[#EFEDE6] bg-[#FAF8F3] p-6 text-center">
      <UIcon name="i-heroicons-user-group" class="w-6 h-6 text-[#9a958c] mx-auto mb-2" />
      <p class="text-sm text-[#6b6b6b]">Personal groups are not enabled on this server.</p>
    </div>

    <!-- List -->
    <div v-else>
      <div v-if="loading" class="flex items-center justify-center py-12 text-[#9a958c]">
        <Spinner class="h-5 w-5" /><span class="ms-2 text-sm">Loading…</span>
      </div>

      <div v-else-if="!groups.length" class="rounded-xl border border-dashed border-[#E9E0D3] bg-white p-10 text-center">
        <UIcon name="i-heroicons-user-group" class="w-7 h-7 text-[#C2541E] mx-auto mb-2" />
        <p class="text-sm text-[#1f2328] font-medium">No groups yet</p>
        <p class="text-xs text-[#9a958c] mt-1 mb-4">Create a group of people you share agents with often.</p>
        <UButton color="orange" size="sm" icon="i-heroicons-plus" @click="openCreate">Create your first group</UButton>
      </div>

      <ul v-else class="space-y-2">
        <li
          v-for="g in groups"
          :key="g.id"
          class="rounded-xl border border-[#EFEDE6] bg-white px-4 py-3"
        >
          <div class="flex items-center gap-3">
            <UIcon name="i-heroicons-user-group" class="w-5 h-5 text-[#C2541E] shrink-0" />
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-[#1f2328] truncate">{{ g.name }}</span>
                <span class="text-[10px] text-[#9a958c]">{{ g.member_count }} member{{ g.member_count === 1 ? '' : 's' }}</span>
                <span v-if="g.shared_count" class="text-[10px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded">shared with {{ g.shared_count }}</span>
              </div>
              <p v-if="g.description" class="text-[11px] text-[#9a958c] truncate">{{ g.description }}</p>
            </div>
            <UButton color="gray" variant="ghost" size="2xs" icon="i-heroicons-pencil-square" @click="openEdit(g)" />
            <UButton color="red" variant="ghost" size="2xs" icon="i-heroicons-trash" @click="confirmDelete(g)" />
          </div>

          <!-- Members chips -->
          <div v-if="g.members && g.members.length" class="flex flex-wrap gap-1.5 mt-2 ps-8">
            <span
              v-for="m in g.members"
              :key="m.user_id"
              class="inline-flex items-center gap-1 text-[10px] text-[#6b6b6b] bg-[#F5F3EC] rounded-full px-2 py-0.5"
            >
              {{ m.name || m.email }}
              <button type="button" class="text-[#bdb7ac] hover:text-[#C2541E]" @click="removeMember(g, m.user_id)">
                <UIcon name="i-heroicons-x-mark" class="w-3 h-3" />
              </button>
            </span>
          </div>
        </li>
      </ul>
    </div>

    <!-- Create / Edit modal -->
    <UModal v-model="modalOpen" :ui="{ width: 'sm:max-w-md' }">
      <div class="bg-white rounded-xl overflow-hidden">
        <div class="flex items-center justify-between px-4 py-3 border-b border-[#EFEDE6]">
          <h3 class="text-sm font-semibold text-[#1f2328]" style="font-family: ui-serif, Georgia, serif">
            {{ editing ? 'Edit group' : 'New group' }}
          </h3>
          <button type="button" class="text-[#9a958c] hover:text-[#6b6b6b]" @click="modalOpen = false">
            <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
          </button>
        </div>

        <div class="px-4 py-3 space-y-3">
          <div>
            <label class="block text-[11px] font-medium text-[#6b6b6b] mb-1">Name</label>
            <input
              v-model="form.name"
              type="text"
              placeholder="Finance team"
              class="w-full text-xs border border-[#E9E0D3] rounded-lg px-2.5 py-2 text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E]"
              @keyup.enter="save"
            />
          </div>
          <div>
            <label class="block text-[11px] font-medium text-[#6b6b6b] mb-1">Description <span class="text-[#9a958c]">(optional)</span></label>
            <input
              v-model="form.description"
              type="text"
              placeholder="People I share dashboards with"
              class="w-full text-xs border border-[#E9E0D3] rounded-lg px-2.5 py-2 text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E]"
            />
          </div>

          <div v-if="!editing">
            <label class="block text-[11px] font-medium text-[#6b6b6b] mb-1">Add members <span class="text-[#9a958c]">({{ selected.size }})</span></label>
            <input
              v-model="contactSearch"
              type="text"
              placeholder="Search org members…"
              class="w-full text-xs border border-[#E9E0D3] rounded-lg px-2.5 py-2 mb-1.5 text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E]"
            />
            <div v-if="loadingContacts" class="flex items-center py-3 text-[#9a958c]">
              <Spinner class="h-3.5 w-3.5" /><span class="ms-2 text-[11px]">Loading…</span>
            </div>
            <ul v-else-if="filteredContacts.length" class="max-h-40 overflow-y-auto border border-[#F0EEE6] rounded-lg divide-y divide-[#F5F3EC]">
              <li
                v-for="c in filteredContacts"
                :key="c.user_id"
                class="flex items-center gap-2 px-2.5 py-1.5 hover:bg-[#faf8f3] cursor-pointer"
                @click="toggleContact(c.user_id)"
              >
                <input type="checkbox" :checked="selected.has(c.user_id)" class="text-[#C2541E] focus:ring-[#C2541E] rounded" @click.stop="toggleContact(c.user_id)" />
                <span class="text-xs text-[#1f2328] truncate flex-1">{{ c.name || c.email }}</span>
                <span class="text-[10px] text-[#9a958c] truncate">{{ c.email }}</span>
              </li>
            </ul>
            <p v-else class="text-[11px] text-[#9a958c] py-2">No members found.</p>
          </div>
        </div>

        <div class="px-4 py-3 border-t border-[#EFEDE6] flex items-center justify-end gap-2">
          <UButton color="gray" variant="ghost" size="xs" @click="modalOpen = false">Cancel</UButton>
          <UButton color="orange" size="xs" :loading="saving" :disabled="!form.name.trim()" @click="save">
            {{ editing ? 'Save' : 'Create' }}
          </UButton>
        </div>
      </div>
    </UModal>
  </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

definePageMeta({ auth: true })

interface Member { user_id: string; name?: string; email?: string }
interface MyGroup {
  id: string
  name: string
  description?: string | null
  member_count: number
  members: Member[]
  shared_count: number
}
interface Contact { user_id: string; name?: string; email?: string }

const toast = useToast()

const groups = ref<MyGroup[]>([])
const loading = ref(false)
const featureOff = ref(false)

const load = async () => {
  loading.value = true
  try {
    const { data, error } = await useMyFetch<MyGroup[]>(`/me/groups`)
    if (error?.value) {
      const status = (error.value as any)?.statusCode || (error.value as any)?.status
      if (status === 404) { featureOff.value = true; groups.value = []; return }
      throw error.value
    }
    featureOff.value = false
    groups.value = (data.value as MyGroup[]) || []
  } catch (e) {
    console.error('Failed to load my groups:', e)
    groups.value = []
  } finally {
    loading.value = false
  }
}

// ── contacts (for create) ──────────────────────────────────────────────────
const contacts = ref<Contact[]>([])
const loadingContacts = ref(false)
const contactSearch = ref('')
const selected = ref<Set<string>>(new Set())

const filteredContacts = computed(() => {
  const q = contactSearch.value.trim().toLowerCase()
  if (!q) return contacts.value
  return contacts.value.filter(c => (c.name || '').toLowerCase().includes(q) || (c.email || '').toLowerCase().includes(q))
})
const toggleContact = (id: string) => {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
const loadContacts = async () => {
  loadingContacts.value = true
  try {
    const { data, error } = await useMyFetch<Contact[]>(`/me/contacts`)
    if (error?.value) throw error.value
    contacts.value = (data.value as Contact[]) || []
  } catch (e) {
    contacts.value = []
  } finally {
    loadingContacts.value = false
  }
}

// ── create / edit ──────────────────────────────────────────────────────────
const modalOpen = ref(false)
const editing = ref<MyGroup | null>(null)
const saving = ref(false)
const form = ref<{ name: string; description: string }>({ name: '', description: '' })

const openCreate = () => {
  editing.value = null
  form.value = { name: '', description: '' }
  selected.value = new Set()
  contactSearch.value = ''
  modalOpen.value = true
  loadContacts()
}
const openEdit = (g: MyGroup) => {
  editing.value = g
  form.value = { name: g.name, description: g.description || '' }
  modalOpen.value = true
}

const save = async () => {
  const nm = form.value.name.trim()
  if (!nm) return
  saving.value = true
  try {
    if (editing.value) {
      const { error } = await useMyFetch(`/me/groups/${editing.value.id}`, {
        method: 'PATCH',
        body: { name: nm, description: form.value.description.trim() || null },
      })
      if (error?.value) throw error.value
      toast.add({ title: 'Group updated', color: 'green', icon: 'i-heroicons-check-circle' })
    } else {
      const memberIds = Array.from(selected.value)
      const { error } = await useMyFetch(`/me/groups`, {
        method: 'POST',
        body: { name: nm, description: form.value.description.trim() || null, member_user_ids: memberIds },
      })
      if (error?.value) throw error.value
      toast.add({ title: `Group "${nm}" created`, color: 'green', icon: 'i-heroicons-check-circle' })
    }
    modalOpen.value = false
    await load()
  } catch (e: any) {
    const status = e?.statusCode || e?.status || e?.response?.status
    const detail = e?.data?.detail || e?.response?._data?.detail
    let msg = 'Could not save group.'
    if (status === 409) msg = detail || 'A group with that name already exists.'
    else if (status === 404) msg = 'Personal groups are not enabled.'
    toast.add({ title: msg, color: 'red' })
  } finally {
    saving.value = false
  }
}

const confirmDelete = async (g: MyGroup) => {
  if (!window.confirm(`Delete group "${g.name}"? This removes it from any agents it was shared with.`)) return
  try {
    const { error } = await useMyFetch(`/me/groups/${g.id}`, { method: 'DELETE' })
    if (error?.value) throw error.value
    toast.add({ title: 'Group deleted', color: 'green', icon: 'i-heroicons-check-circle' })
    await load()
  } catch (e) {
    toast.add({ title: 'Could not delete group', color: 'red' })
  }
}

const removeMember = async (g: MyGroup, userId: string) => {
  try {
    const { error } = await useMyFetch(`/me/groups/${g.id}/members/${userId}`, { method: 'DELETE' })
    if (error?.value) throw error.value
    await load()
  } catch (e) {
    toast.add({ title: 'Could not remove member', color: 'red' })
  }
}

onMounted(load)
</script>
