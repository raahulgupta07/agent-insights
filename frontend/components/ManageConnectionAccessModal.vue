<template>
  <UModal v-model="isOpen" :ui="{ width: 'sm:max-w-lg' }">
    <div class="p-5 bg-[#FBFAF6]">
      <!-- Header -->
      <div class="flex items-start justify-between gap-2 mb-1">
        <div>
          <h3 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
            Manage access
          </h3>
          <p class="text-xs text-[#6b6b6b] mt-0.5">
            Choose who can use <span class="font-medium text-[#1f2328]">{{ connection?.name }}</span> in their Studios.
          </p>
        </div>
        <button @click="isOpen = false" class="text-[#9a958c] hover:text-[#6b6b6b]">
          <UIcon name="heroicons-x-mark" class="w-5 h-5" />
        </button>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center py-10">
        <Spinner class="w-5 h-5 text-[#1F6F8B] animate-spin" />
      </div>

      <template v-else>
        <!-- Current grants -->
        <div class="mt-4">
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
        </div>

        <!-- Add access -->
        <div class="mt-5 border-t border-[#F0EAE0] pt-4">
          <div class="text-[11px] uppercase tracking-wide text-[#9a958c] mb-2">Add access</div>

          <!-- user|group toggle -->
          <div class="inline-flex rounded-lg border border-[#E9E0D3] bg-white p-0.5 mb-2.5">
            <button
              type="button"
              @click="addType = 'user'"
              :class="['px-3 py-1 text-xs rounded-md transition', addType === 'user' ? 'bg-[#E4F0F4] text-[#1F6F8B] font-medium' : 'text-[#6b6b6b]']"
            >Person</button>
            <button
              v-if="hasGroups"
              type="button"
              @click="addType = 'group'"
              :class="['px-3 py-1 text-xs rounded-md transition', addType === 'group' ? 'bg-[#E4F0F4] text-[#1F6F8B] font-medium' : 'text-[#6b6b6b]']"
            >Group</button>
          </div>

          <div class="flex items-center gap-2">
            <select
              v-model="selectedPrincipalId"
              class="flex-1 rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-[13px] text-[#1f2328] focus:outline-none focus:border-[#1F6F8B]"
            >
              <option value="">{{ addType === 'group' ? 'Select a group…' : 'Select a person…' }}</option>
              <option
                v-for="opt in addType === 'group' ? groupOptions : userOptions"
                :key="opt.id"
                :value="opt.id"
              >{{ opt.label }}</option>
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
  </UModal>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{
  modelValue: boolean
  connection: any
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const isOpen = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// orgId resolved the same way as StudioAccess.vue — the canonical FE source.
const { organization, ensureOrganization } = useOrganization()
const orgId = computed(() => organization.value?.id || '')

const toast = useToast()

const loading = ref(false)
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
  } catch (e) {
    members.value = []
  }
}

async function fetchGroups() {
  if (!orgId.value) return
  try {
    const { data } = await useMyFetch(`/organizations/${orgId.value}/groups`, { method: 'GET' })
    groups.value = (data.value as any[]) || []
  } catch (e) {
    // Groups endpoint may be unavailable / forbidden — degrade to user-only picker.
    groups.value = []
  }
}

async function load() {
  loading.value = true
  try {
    await ensureOrganization()
    await Promise.all([fetchMembers(), fetchGroups()])
    await fetchGrants()
  } catch (e) {
    console.error('Failed to load connection access:', e)
  } finally {
    loading.value = false
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

watch(isOpen, (val) => {
  if (val) {
    grants.value = []
    selectedPrincipalId.value = ''
    addType.value = 'user'
    load()
  }
})
</script>
