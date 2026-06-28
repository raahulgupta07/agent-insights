<template>
  <teleport to="body">
    <div v-if="modelValue" class="fixed inset-0 z-[80]">
      <!-- Overlay -->
      <div class="absolute inset-0 bg-black/30" @click="close"></div>

      <!-- Right drawer -->
      <div
        class="absolute top-0 right-0 h-full w-full sm:w-[420px] bg-[#FBFAF6] shadow-xl flex flex-col"
        style="border-left:1px solid #E9E0D3;"
      >
        <!-- Header -->
        <div class="flex items-start justify-between gap-2 px-5 py-4 border-b border-[#F0EAE0]">
          <div class="min-w-0">
            <h3 class="text-base font-semibold text-[#1f2328] truncate" style="font-family:'Spectral',ui-serif,Georgia,serif">
              Sharing · {{ connection?.name }}
            </h3>
            <p class="text-[11px] text-[#9a958c] mt-0.5">Choose who can use this connector.</p>
          </div>
          <button @click="close" class="text-[#9a958c] hover:text-[#6b6b6b] shrink-0">
            <UIcon name="heroicons-x-mark" class="w-5 h-5" />
          </button>
        </div>

        <!-- Body -->
        <div class="flex-1 overflow-y-auto px-5 py-4">
          <!-- 3 radio cards -->
          <div class="space-y-2">
            <button
              type="button"
              @click="selected = 'private'"
              :class="['w-full rounded-lg border px-3 py-2.5 text-start transition flex items-start gap-2.5',
                selected === 'private' ? 'border-[#8a6d3b] bg-[#FBF3E2]' : 'border-[#E9E0D3] bg-white hover:border-[#8a6d3b]']"
            >
              <span class="text-base leading-none mt-0.5">🔒</span>
              <span>
                <span class="block text-[13px] font-semibold text-[#1f2328]">Private</span>
                <span class="block text-[11px] text-[#6b6b6b]">Only you</span>
              </span>
            </button>
            <button
              type="button"
              @click="selected = 'shared'"
              :class="['w-full rounded-lg border px-3 py-2.5 text-start transition flex items-start gap-2.5',
                selected === 'shared' ? 'border-[#1F6F8B] bg-[#E4F0F4]' : 'border-[#E9E0D3] bg-white hover:border-[#1F6F8B]']"
            >
              <span class="text-base leading-none mt-0.5">👥</span>
              <span>
                <span class="block text-[13px] font-semibold text-[#1f2328]">Shared</span>
                <span class="block text-[11px] text-[#6b6b6b]">Specific people / groups</span>
              </span>
            </button>
            <button
              type="button"
              @click="selected = 'org'"
              :class="['w-full rounded-lg border px-3 py-2.5 text-start transition flex items-start gap-2.5',
                selected === 'org' ? 'border-[#2F6F4F] bg-[#ECF1EC]' : 'border-[#E9E0D3] bg-white hover:border-[#2F6F4F]']"
            >
              <span class="text-base leading-none mt-0.5">🌐</span>
              <span>
                <span class="block text-[13px] font-semibold text-[#1f2328]">Org-wide</span>
                <span class="block text-[11px] text-[#6b6b6b]">Everyone in the org</span>
              </span>
            </button>
          </div>

          <!-- Grants (only when Shared) -->
          <div v-if="selected === 'shared'" class="mt-5 border-t border-[#F0EAE0] pt-4">
            <div v-if="loadingGrants" class="flex items-center justify-center py-6">
              <Spinner class="w-4 h-4 text-[#1F6F8B]" />
            </div>
            <template v-else>
              <!-- Current grants -->
              <div class="text-[11px] uppercase tracking-wide text-[#9a958c] mb-2">Current access</div>
              <div v-if="grants.length === 0" class="text-xs text-[#9a958c] border border-dashed border-[#E9E0D3] rounded-lg px-3 py-4 text-center">
                No one has been granted access yet.
              </div>
              <ul v-else class="space-y-1.5">
                <li
                  v-for="g in grants"
                  :key="g.id"
                  class="flex items-center justify-between gap-2 rounded-lg border border-[#E9E0D3] bg-white px-3 py-2"
                >
                  <div class="flex items-center gap-2 min-w-0">
                    <span class="inline-flex w-6 h-6 items-center justify-center rounded-md bg-[#E4F0F4] text-[#1F6F8B] shrink-0">
                      <UIcon :name="g.principal_type === 'group' ? 'heroicons-user-group' : 'heroicons-user'" class="w-3.5 h-3.5" />
                    </span>
                    <span class="text-[13px] text-[#1f2328] truncate">{{ principalLabel(g) }}</span>
                  </div>
                  <button
                    @click="removeGrant(g)"
                    :disabled="removingId === g.id"
                    class="text-[#9a958c] hover:text-[#C2541E] disabled:opacity-50 shrink-0"
                    title="Remove access"
                  >
                    <UIcon name="heroicons-x-mark" class="w-4 h-4" />
                  </button>
                </li>
              </ul>

              <!-- Add access -->
              <div class="mt-4">
                <div class="text-[11px] uppercase tracking-wide text-[#9a958c] mb-2">Add access</div>
                <div class="inline-flex rounded-lg border border-[#E9E0D3] bg-white p-0.5 mb-2.5">
                  <button type="button" @click="addType = 'user'"
                    :class="['px-3 py-1 text-xs rounded-md transition', addType === 'user' ? 'bg-[#E4F0F4] text-[#1F6F8B] font-medium' : 'text-[#6b6b6b]']"
                  >Person</button>
                  <button v-if="hasGroups" type="button" @click="addType = 'group'"
                    :class="['px-3 py-1 text-xs rounded-md transition', addType === 'group' ? 'bg-[#E4F0F4] text-[#1F6F8B] font-medium' : 'text-[#6b6b6b]']"
                  >Group</button>
                </div>
                <div class="flex items-center gap-2">
                  <select
                    v-model="selectedPrincipalId"
                    class="flex-1 rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-[13px] text-[#1f2328] focus:outline-none focus:border-[#1F6F8B]"
                  >
                    <option value="">{{ addType === 'group' ? 'Select a group…' : 'Select a person…' }}</option>
                    <option v-for="opt in addType === 'group' ? groupOptions : userOptions" :key="opt.id" :value="opt.id">{{ opt.label }}</option>
                  </select>
                  <button
                    @click="addGrant"
                    :disabled="!selectedPrincipalId || adding"
                    class="inline-flex items-center gap-1.5 rounded-lg bg-[#C2541E] px-3 py-2 text-sm font-medium text-white hover:bg-[#A8330F] transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
                  >
                    <Spinner v-if="adding" class="w-3.5 h-3.5" />
                    <UIcon v-else name="heroicons-plus" class="w-4 h-4" />
                    Add
                  </button>
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- Footer -->
        <div class="px-5 py-4 border-t border-[#F0EAE0] bg-[#FBFAF6]">
          <p class="text-[11px] text-[#8a6d3b] mb-3 leading-snug">
            🔒 Credentials are never shared — others query the data through the agent; they can't see or edit the connection.
          </p>
          <div class="flex justify-end gap-2">
            <UButton color="gray" variant="ghost" @click="close">Cancel</UButton>
            <UButton color="orange" :loading="saving" @click="save">Save</UButton>
          </div>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{
  modelValue: boolean
  connection: any
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'saved', payload: any): void
}>()

const { organization, ensureOrganization } = useOrganization()
const orgId = computed(() => organization.value?.id || '')
const toast = useToast()

const selected = ref<'private' | 'shared' | 'org'>('private')
const saving = ref(false)

// Grants state (mirrors ManageConnectionAccessModal)
const loadingGrants = ref(false)
const grants = ref<any[]>([])
const members = ref<any[]>([])
const groups = ref<any[]>([])
const addType = ref<'user' | 'group'>('user')
const selectedPrincipalId = ref('')
const adding = ref(false)
const removingId = ref<string | null>(null)

const hasGroups = computed(() => groups.value.length > 0)
const userOptions = computed(() =>
  members.value.map((m: any) => ({
    id: m.user?.id || m.user_id,
    label: m.user?.name || m.user?.email || m.email || 'Unknown',
  })).filter((o: any) => o.id)
)
const groupOptions = computed(() =>
  groups.value.map((g: any) => ({ id: g.id, label: g.name || g.id }))
)

function principalLabel(g: any): string {
  if (g.principal_type === 'group') {
    const grp = groups.value.find((x: any) => x.id === g.principal_id)
    return grp?.name || 'Group'
  }
  const m = members.value.find((x: any) => (x.user?.id || x.user_id) === g.principal_id)
  return m?.user?.name || m?.user?.email || m?.email || 'Person'
}

function close() {
  emit('update:modelValue', false)
}

async function fetchGrants() {
  if (!orgId.value || !props.connection?.id) return
  const { data } = await useMyFetch(
    `/organizations/${orgId.value}/resource-grants?resource_type=connection&resource_id=${props.connection.id}`,
    { method: 'GET' }
  )
  grants.value = (data.value as any[]) || []
}
async function fetchMembers() {
  if (!orgId.value) return
  try {
    const { data } = await useMyFetch(`/organizations/${orgId.value}/members`, { method: 'GET' })
    members.value = (data.value as any[]) || []
  } catch { members.value = [] }
}
async function fetchGroups() {
  if (!orgId.value) return
  try {
    const { data } = await useMyFetch(`/organizations/${orgId.value}/groups`, { method: 'GET' })
    groups.value = (data.value as any[]) || []
  } catch { groups.value = [] }
}

async function loadGrants() {
  loadingGrants.value = true
  try {
    await ensureOrganization()
    await Promise.all([fetchMembers(), fetchGroups()])
    await fetchGrants()
  } catch (e) {
    console.error('Failed to load connector access:', e)
  } finally {
    loadingGrants.value = false
  }
}

async function addGrant() {
  if (!selectedPrincipalId.value || !orgId.value || !props.connection?.id) return
  adding.value = true
  try {
    await useMyFetch(`/organizations/${orgId.value}/resource-grants`, {
      method: 'POST',
      body: JSON.stringify({
        resource_type: 'connection',
        resource_id: props.connection.id,
        principal_type: addType.value,
        principal_id: selectedPrincipalId.value,
        permissions: ['query'],
      }),
      headers: { 'Content-Type': 'application/json' },
    })
    selectedPrincipalId.value = ''
    await fetchGrants()
  } catch (e: any) {
    toast.add({ title: 'Failed to add access', description: e?.data?.detail || String(e), color: 'red' })
  } finally {
    adding.value = false
  }
}

async function removeGrant(g: any) {
  if (!orgId.value) return
  removingId.value = g.id
  try {
    await useMyFetch(`/organizations/${orgId.value}/resource-grants/${g.id}`, { method: 'DELETE' })
    await fetchGrants()
  } catch (e: any) {
    toast.add({ title: 'Failed to remove access', description: e?.data?.detail || String(e), color: 'red' })
  } finally {
    removingId.value = null
  }
}

async function save() {
  if (!props.connection?.id || saving.value) return
  saving.value = true
  try {
    const grantsPayload = selected.value === 'shared'
      ? grants.value.map((g: any) => ({ principal_type: g.principal_type, principal_id: g.principal_id }))
      : undefined
    const { data, error } = await useMyFetch(`/connections/${props.connection.id}/visibility`, {
      method: 'PATCH',
      body: JSON.stringify({ visibility: selected.value, ...(grantsPayload ? { grants: grantsPayload } : {}) }),
      headers: { 'Content-Type': 'application/json' },
    })
    if (error?.value) {
      toast.add({ title: (error.value as any).data?.detail || 'Failed to update sharing', color: 'red' })
      return
    }
    toast.add({
      title: selected.value === 'org' ? 'Published org-wide' : selected.value === 'private' ? 'Made private' : 'Sharing updated',
      color: 'green',
    })
    emit('saved', (data.value as any) || { id: props.connection.id, visibility: selected.value })
    close()
  } catch (e: any) {
    toast.add({ title: e?.data?.detail || e?.message || 'Failed to update sharing', color: 'red' })
  } finally {
    saving.value = false
  }
}

// Init selection from connection.visibility + lazy-load grants when Shared.
watch(() => props.modelValue, (open) => {
  if (open) {
    const v = props.connection?.visibility
    selected.value = (v === 'private' || v === 'shared' || v === 'org') ? v : 'private'
    grants.value = []
    selectedPrincipalId.value = ''
    addType.value = 'user'
    if (selected.value === 'shared') loadGrants()
  }
})

// Load grants the first time Shared is selected while open.
watch(selected, (val) => {
  if (props.modelValue && val === 'shared' && members.value.length === 0 && grants.value.length === 0 && !loadingGrants.value) {
    loadGrants()
  }
})
</script>
