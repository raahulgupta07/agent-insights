<template>
  <div style="font-family: 'Hanken Grotesk', system-ui, sans-serif">

    <!-- Panel header -->
    <div class="mb-5">
      <h2
        class="text-lg font-semibold text-[#1f2328]"
        style="font-family: 'Spectral', ui-serif, Georgia, serif"
      >
        LDAP / AD Directories
      </h2>
      <p class="text-xs text-[#6b6b6b] mt-0.5">
        Connect one or more directories — users sign in with their directory username &amp; password.
      </p>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="flex items-center gap-2 py-8 text-[#9a958c] text-sm">
      <UIcon name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin" />
      Loading directories…
    </div>

    <!-- Directory list -->
    <div v-else-if="directories.length" class="rounded-2xl border border-[#E9E0D3] bg-white overflow-hidden">
      <ul class="divide-y divide-[#F0EBE2]">
        <li
          v-for="dir in directories"
          :key="dir.id"
          class="flex items-center gap-3 px-4 py-3 hover:bg-[#FBF7F1] transition-colors"
        >
          <!-- Logo tile -->
          <div
            class="w-9 h-9 shrink-0 rounded-xl border border-[#E9E0D3] bg-[#F4EEE5] flex items-center justify-center overflow-hidden p-1.5"
            v-html="idpLogoSvg(dir.logo || 'ldap')"
          />

          <!-- Name + host:port -->
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium text-[#1f2328] truncate">{{ dir.name }}</div>
            <div class="text-[11px] text-[#9a958c] truncate">{{ dir.host }}:{{ dir.port }}</div>
          </div>

          <!-- Status pill -->
          <span
            class="text-[10px] font-medium px-2 py-0.5 rounded-full shrink-0"
            :class="dir.enabled
              ? 'bg-[#E7F2EC] text-[#1e5c3a]'
              : 'bg-[#F0EBE2] text-[#9a958c]'"
          >
            {{ dir.enabled ? 'Enabled' : 'Disabled' }}
          </span>

          <!-- Enable / disable toggle -->
          <button
            v-if="canEdit"
            type="button"
            :title="dir.enabled ? 'Disable' : 'Enable'"
            class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[#F4EEE5] text-[#9a958c] hover:text-[#1f2328] transition-colors"
            :class="{ 'opacity-60': togglingId === dir.id }"
            :disabled="togglingId === dir.id"
            @click="toggleEnabled(dir)"
          >
            <UIcon
              :name="dir.enabled ? 'i-heroicons-pause-circle' : 'i-heroicons-play-circle'"
              class="w-4 h-4"
            />
          </button>

          <!-- Test button -->
          <button
            type="button"
            title="Test connection"
            class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[#F4EEE5] text-[#9a958c] hover:text-[#1f2328] transition-colors"
            :class="{ 'opacity-60': testingId === dir.id }"
            :disabled="testingId === dir.id"
            @click="testDirectory(dir)"
          >
            <UIcon
              :name="testingId === dir.id ? 'i-heroicons-arrow-path' : 'i-heroicons-signal'"
              class="w-4 h-4"
              :class="testingId === dir.id ? 'animate-spin' : ''"
            />
          </button>

          <!-- Configure button -->
          <button
            v-if="canEdit"
            type="button"
            title="Configure"
            class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg hover:bg-[#F4EEE5] text-[#9a958c] hover:text-[#1f2328] transition-colors"
            @click="openEdit(dir)"
          >
            <UIcon name="i-heroicons-pencil-square" class="w-4 h-4" />
          </button>

          <!-- Delete -->
          <button
            v-if="canEdit"
            type="button"
            title="Delete"
            class="shrink-0 w-8 h-8 flex items-center justify-center rounded-lg hover:bg-red-50 text-[#9a958c] hover:text-red-600 transition-colors"
            @click="confirmDelete(dir)"
          >
            <UIcon name="i-heroicons-x-mark" class="w-4 h-4" />
          </button>
        </li>
      </ul>
    </div>

    <!-- Empty state -->
    <div
      v-else
      class="rounded-2xl border border-dashed border-[#E9E0D3] bg-white flex flex-col items-center justify-center py-12 px-6 text-center"
    >
      <div class="w-12 h-12 rounded-xl border border-[#E9E0D3] bg-[#F4EEE5] flex items-center justify-center mb-3">
        <UIcon name="i-heroicons-server-stack" class="w-6 h-6 text-[#C2541E]" />
      </div>
      <p class="text-sm font-medium text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
        No directories yet
      </p>
      <p class="text-[12px] text-[#9a958c] mt-1 max-w-xs">
        Add an LDAP or Active Directory server so users can sign in with their corporate credentials.
      </p>
    </div>

    <!-- Add button -->
    <div v-if="canEdit" class="mt-4">
      <button
        type="button"
        class="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#C2541E] hover:bg-[#A8330F] text-white text-sm font-medium transition-colors"
        @click="openCreate"
      >
        <UIcon name="i-heroicons-plus" class="w-4 h-4" />
        Add LDAP / AD directory
      </button>
    </div>

    <!-- Modal -->
    <LdapDirectoryModal
      :open="modalOpen"
      :directory="editingDirectory"
      @close="closeModal"
      @saved="reload"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { idpLogoSvg } from '~/utils/idpLogos'
import LdapDirectoryModal from '~/components/idp/LdapDirectoryModal.vue'

// ─── Types ───────────────────────────────────────────────────────────────────

interface LdapDirectory {
  id: string
  name: string
  enabled: boolean
  logo?: string
  host: string
  port: number
  bind_dn?: string
  bind_password_set?: boolean
  base_dn?: string
  user_filter?: string
  email_attr?: string
  name_attr?: string
  use_ssl?: boolean
  start_tls?: boolean
  user_search_base?: string
  group_search_base?: string
  group_search_filter?: string
  group_name_attribute?: string
  group_member_attribute?: string
  group_member_format?: string
  sync_interval_minutes?: number
  auto_provision_users?: boolean
  connection_timeout?: number
  page_size?: number
}

// ─── Props ───────────────────────────────────────────────────────────────────

const props = withDefaults(
  defineProps<{ canEdit?: boolean }>(),
  { canEdit: true }
)

// ─── State ───────────────────────────────────────────────────────────────────

const toast = useToast()

const directories = ref<LdapDirectory[]>([])
const loading = ref(false)
const togglingId = ref<string | null>(null)
const testingId = ref<string | null>(null)

const modalOpen = ref(false)
const editingDirectory = ref<LdapDirectory | null>(null)

// ─── Load ────────────────────────────────────────────────────────────────────

async function reload() {
  loading.value = true
  try {
    const { data, error } = await useMyFetch<{ directories: LdapDirectory[] } | LdapDirectory[]>(
      '/enterprise/ldap/directories',
      { method: 'GET' }
    )
    if (error?.value) throw error.value

    const raw = data.value
    if (Array.isArray(raw)) {
      directories.value = raw
    } else {
      directories.value = raw?.directories ?? []
    }
  } catch (e: any) {
    console.error('Failed to load LDAP directories:', e)
    toast.add({ title: 'Could not load directories', color: 'red' })
  } finally {
    loading.value = false
  }
}

onMounted(reload)

// ─── Enable / disable ────────────────────────────────────────────────────────

async function toggleEnabled(dir: LdapDirectory) {
  togglingId.value = dir.id
  try {
    const { error } = await useMyFetch(`/enterprise/ldap/directories/${dir.id}`, {
      method: 'PUT',
      body: { enabled: !dir.enabled },
    })
    if (error?.value) throw error.value
    dir.enabled = !dir.enabled
    toast.add({
      title: dir.enabled ? 'Directory enabled' : 'Directory disabled',
      color: 'green',
      icon: 'i-heroicons-check-circle',
    })
  } catch (e: any) {
    console.error('Toggle failed:', e)
    toast.add({ title: 'Failed to update directory', color: 'red' })
  } finally {
    togglingId.value = null
  }
}

// ─── Test ────────────────────────────────────────────────────────────────────

async function testDirectory(dir: LdapDirectory) {
  testingId.value = dir.id
  try {
    const { data, error } = await useMyFetch<{
      success: boolean; server?: string; vendor?: string; user_count?: number; group_count?: number; error?: string
    }>(`/enterprise/ldap/directories/${dir.id}/test`, { method: 'POST' })

    if (error?.value) throw error.value
    const r = data.value

    if (r?.success) {
      const parts: string[] = ['Connected']
      if (r.server) parts.push(r.server)
      if (r.user_count != null) parts.push(`${r.user_count} users`)
      if (r.group_count != null) parts.push(`${r.group_count} groups`)
      toast.add({ title: parts.join(' · '), color: 'green', icon: 'i-heroicons-check-circle' })
    } else {
      toast.add({ title: 'Connection failed', description: r?.error ?? 'Unknown error', color: 'red' })
    }
  } catch (e: any) {
    toast.add({ title: 'Test failed', description: e?.message ?? 'Unknown error', color: 'red' })
  } finally {
    testingId.value = null
  }
}

// ─── Delete ──────────────────────────────────────────────────────────────────

async function confirmDelete(dir: LdapDirectory) {
  if (!window.confirm(`Delete directory "${dir.name}"? This cannot be undone.`)) return
  try {
    const { error } = await useMyFetch(`/enterprise/ldap/directories/${dir.id}`, { method: 'DELETE' })
    if (error?.value) throw error.value
    toast.add({ title: 'Directory deleted', color: 'green', icon: 'i-heroicons-check-circle' })
    await reload()
  } catch (e: any) {
    console.error('Delete failed:', e)
    toast.add({ title: 'Failed to delete directory', color: 'red' })
  }
}

// ─── Modal helpers ───────────────────────────────────────────────────────────

function openCreate() {
  editingDirectory.value = null
  modalOpen.value = true
}

function openEdit(dir: LdapDirectory) {
  editingDirectory.value = dir
  modalOpen.value = true
}

function closeModal() {
  modalOpen.value = false
  editingDirectory.value = null
}
</script>
