<template>
  <!-- Scrim + modal shell -->
  <Teleport to="body">
    <Transition name="ldap-fade">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        role="dialog"
        aria-modal="true"
        @mousedown.self="emit('close')"
      >
        <!-- scrim -->
        <div class="absolute inset-0 bg-black/40" />

        <!-- panel -->
        <div
          class="relative z-10 w-full max-w-lg bg-white rounded-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
          style="font-family: 'Hanken Grotesk', system-ui, sans-serif"
        >
          <!-- header -->
          <div class="flex items-center justify-between px-6 pt-5 pb-4 border-b border-[#E9E0D3] shrink-0">
            <h2
              class="text-[17px] font-semibold text-[#1f2328]"
              style="font-family: 'Spectral', ui-serif, Georgia, serif"
            >
              {{ form.id ? 'Configure LDAP / AD directory' : 'Add LDAP / AD directory' }}
            </h2>
            <button
              type="button"
              class="text-[#9a958c] hover:text-[#1f2328] transition-colors"
              @click="emit('close')"
            >
              <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
            </button>
          </div>

          <!-- body (scrollable) -->
          <div class="overflow-y-auto px-6 py-5 space-y-4">

            <!-- validation banner -->
            <div
              v-if="validationError"
              class="text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2"
            >
              {{ validationError }}
            </div>

            <!-- test result banner -->
            <div
              v-if="testResult"
              class="text-[12px] rounded-lg px-3 py-2 border"
              :class="testResult.success
                ? 'bg-[#E7F2EC] border-[#a3d6b9] text-[#1e5c3a]'
                : 'bg-red-50 border-red-200 text-red-700'"
            >
              <template v-if="testResult.success">
                <span class="font-medium">Connected</span>
                <span v-if="testResult.server"> · {{ testResult.server }}</span>
                <span v-if="testResult.user_count != null"> · {{ testResult.user_count }} users</span>
                <span v-if="testResult.group_count != null"> / {{ testResult.group_count }} groups</span>
              </template>
              <template v-else>
                {{ testResult.error || 'Connection failed' }}
              </template>
            </div>

            <!-- Directory name -->
            <div>
              <label class="block text-xs font-medium text-[#1f2328] mb-1">Directory name <span class="text-red-500">*</span></label>
              <input
                v-model="form.name"
                type="text"
                placeholder="e.g. Corporate AD"
                class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
              />
            </div>

            <!-- Host + Port -->
            <div class="grid grid-cols-[1fr_100px] gap-3">
              <div>
                <label class="block text-xs font-medium text-[#1f2328] mb-1">Host <span class="text-red-500">*</span></label>
                <input
                  v-model="form.host"
                  type="text"
                  placeholder="ldap.example.com"
                  class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-[#1f2328] mb-1">Port</label>
                <input
                  v-model.number="form.port"
                  type="number"
                  min="1"
                  max="65535"
                  placeholder="389"
                  class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                />
              </div>
            </div>

            <!-- Bind DN -->
            <div>
              <label class="block text-xs font-medium text-[#1f2328] mb-1">Bind DN</label>
              <input
                v-model="form.bind_dn"
                type="text"
                placeholder="cn=svc-ldap,dc=example,dc=com"
                class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
              />
            </div>

            <!-- Bind password -->
            <div>
              <label class="block text-xs font-medium text-[#1f2328] mb-1">Bind password</label>
              <input
                v-model="form.bind_password"
                type="password"
                :placeholder="form.bind_password_set ? '••••••••  (configured — leave blank to keep)' : 'Service account password'"
                class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
              />
            </div>

            <!-- Base DN -->
            <div>
              <label class="block text-xs font-medium text-[#1f2328] mb-1">Base DN <span class="text-red-500">*</span></label>
              <input
                v-model="form.base_dn"
                type="text"
                placeholder="dc=example,dc=com"
                class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
              />
            </div>

            <!-- User filter -->
            <div>
              <label class="block text-xs font-medium text-[#1f2328] mb-1">User filter <span class="text-red-500">*</span></label>
              <p class="text-[11px] text-[#9a958c] mb-1.5">Must contain <code class="bg-[#F4EEE5] px-1 rounded text-[10px]">{username}</code></p>
              <input
                v-model="form.user_filter"
                type="text"
                placeholder="(sAMAccountName={username})"
                class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                :class="userFilterWarning ? 'border-amber-400' : ''"
              />
              <p v-if="userFilterWarning" class="text-[11px] text-amber-600 mt-1">Filter should contain <code>{username}</code> for login to work.</p>
            </div>

            <!-- Email attr + Name attr -->
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs font-medium text-[#1f2328] mb-1">Email attribute</label>
                <input
                  v-model="form.email_attr"
                  type="text"
                  placeholder="mail"
                  class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                />
              </div>
              <div>
                <label class="block text-xs font-medium text-[#1f2328] mb-1">Name attribute</label>
                <input
                  v-model="form.name_attr"
                  type="text"
                  placeholder="cn"
                  class="w-full rounded-lg border border-[#E9E0D3] bg-[#FBF7F1] px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                />
              </div>
            </div>

            <!-- ─── Advanced collapsible ─── -->
            <details class="group rounded-xl border border-[#E9E0D3] overflow-hidden">
              <summary
                class="flex items-center justify-between px-4 py-3 cursor-pointer text-xs font-medium text-[#6b6b6b] hover:bg-[#F4EEE5] transition-colors select-none list-none"
              >
                <span>Advanced</span>
                <UIcon
                  name="i-heroicons-chevron-down"
                  class="w-4 h-4 transition-transform group-open:rotate-180"
                />
              </summary>

              <div class="px-4 pb-4 pt-2 space-y-4 bg-[#FBF7F1]">

                <!-- Logo picker -->
                <div>
                  <label class="block text-xs font-medium text-[#1f2328] mb-2">Directory logo</label>
                  <IdpLogoPicker v-model="form.logo" />
                </div>

                <!-- SSL + StartTLS toggles -->
                <div class="grid grid-cols-2 gap-3">
                  <label class="flex items-center gap-2.5 rounded-lg border border-[#E9E0D3] bg-white px-3 py-2.5 cursor-pointer hover:border-[#C2541E]/40 transition">
                    <input
                      v-model="form.use_ssl"
                      type="checkbox"
                      class="rounded text-[#C2541E] focus:ring-[#C2541E]"
                    />
                    <span>
                      <span class="block text-xs font-medium text-[#1f2328]">Use SSL / LDAPS</span>
                      <span class="block text-[10px] text-[#9a958c]">Port 636 by convention</span>
                    </span>
                  </label>
                  <label class="flex items-center gap-2.5 rounded-lg border border-[#E9E0D3] bg-white px-3 py-2.5 cursor-pointer hover:border-[#C2541E]/40 transition">
                    <input
                      v-model="form.start_tls"
                      type="checkbox"
                      class="rounded text-[#C2541E] focus:ring-[#C2541E]"
                    />
                    <span>
                      <span class="block text-xs font-medium text-[#1f2328]">Start TLS</span>
                      <span class="block text-[10px] text-[#9a958c]">Upgrade plain → encrypted</span>
                    </span>
                  </label>
                </div>

                <!-- User search base -->
                <div>
                  <label class="block text-xs font-medium text-[#1f2328] mb-1">User search base</label>
                  <input
                    v-model="form.user_search_base"
                    type="text"
                    placeholder="ou=Users,dc=example,dc=com (defaults to Base DN)"
                    class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                  />
                </div>

                <!-- Group search base -->
                <div>
                  <label class="block text-xs font-medium text-[#1f2328] mb-1">Group search base</label>
                  <input
                    v-model="form.group_search_base"
                    type="text"
                    placeholder="ou=Groups,dc=example,dc=com"
                    class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                  />
                </div>

                <!-- Group search filter -->
                <div>
                  <label class="block text-xs font-medium text-[#1f2328] mb-1">Group search filter</label>
                  <input
                    v-model="form.group_search_filter"
                    type="text"
                    placeholder="(objectClass=groupOfNames)"
                    class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                  />
                </div>

                <!-- Group name attr + Group member attr -->
                <div class="grid grid-cols-2 gap-3">
                  <div>
                    <label class="block text-xs font-medium text-[#1f2328] mb-1">Group name attribute</label>
                    <input
                      v-model="form.group_name_attribute"
                      type="text"
                      placeholder="cn"
                      class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                    />
                  </div>
                  <div>
                    <label class="block text-xs font-medium text-[#1f2328] mb-1">Group member attribute</label>
                    <select
                      v-model="form.group_member_attribute"
                      class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                    >
                      <option value="member">member</option>
                      <option value="memberUid">memberUid</option>
                    </select>
                  </div>
                </div>

                <!-- Group member format -->
                <div>
                  <label class="block text-xs font-medium text-[#1f2328] mb-1">Group member format</label>
                  <select
                    v-model="form.group_member_format"
                    class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                  >
                    <option value="dn">DN (Distinguished Name)</option>
                    <option value="uid">UID</option>
                  </select>
                </div>

                <!-- Sync interval + Auto-provision -->
                <div class="grid grid-cols-2 gap-3">
                  <div>
                    <label class="block text-xs font-medium text-[#1f2328] mb-1">Sync interval (minutes)</label>
                    <input
                      v-model.number="form.sync_interval_minutes"
                      type="number"
                      min="5"
                      placeholder="60"
                      class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                    />
                  </div>
                  <div>
                    <label class="block text-xs font-medium text-[#1f2328] mb-1">Connection timeout (s)</label>
                    <input
                      v-model.number="form.connection_timeout"
                      type="number"
                      min="1"
                      placeholder="10"
                      class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                    />
                  </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                  <div>
                    <label class="block text-xs font-medium text-[#1f2328] mb-1">Page size</label>
                    <input
                      v-model.number="form.page_size"
                      type="number"
                      min="1"
                      placeholder="500"
                      class="w-full rounded-lg border border-[#E9E0D3] bg-white px-3 py-2 text-sm text-[#1f2328] placeholder-[#9a958c] focus:outline-none focus:border-[#C2541E] focus:ring-1 focus:ring-[#C2541E]/30 transition"
                    />
                  </div>
                  <label class="flex items-center gap-2.5 rounded-lg border border-[#E9E0D3] bg-white px-3 py-2.5 cursor-pointer hover:border-[#C2541E]/40 transition self-end">
                    <input
                      v-model="form.auto_provision_users"
                      type="checkbox"
                      class="rounded text-[#C2541E] focus:ring-[#C2541E]"
                    />
                    <span>
                      <span class="block text-xs font-medium text-[#1f2328]">Auto-provision users</span>
                      <span class="block text-[10px] text-[#9a958c]">Create accounts on first login</span>
                    </span>
                  </label>
                </div>

              </div>
            </details>

          </div>

          <!-- footer -->
          <div class="flex items-center justify-between gap-3 px-6 py-4 border-t border-[#E9E0D3] shrink-0 bg-white">
            <!-- Test connection (left) -->
            <button
              type="button"
              :disabled="!form.id || testing"
              class="flex items-center gap-1.5 text-xs font-medium text-[#6b6b6b] hover:text-[#1f2328] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              @click="handleTest"
            >
              <UIcon
                :name="testing ? 'i-heroicons-arrow-path' : 'i-heroicons-signal'"
                class="w-4 h-4"
                :class="testing ? 'animate-spin' : ''"
              />
              Test connection
            </button>

            <div class="flex items-center gap-2">
              <button
                type="button"
                class="px-4 py-2 text-sm font-medium text-[#6b6b6b] hover:text-[#1f2328] transition-colors"
                @click="emit('close')"
              >
                Cancel
              </button>
              <button
                type="button"
                :disabled="saving"
                class="px-4 py-2 rounded-lg bg-[#C2541E] hover:bg-[#A8330F] text-white text-sm font-medium transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-1.5"
                @click="handleSave"
              >
                <UIcon v-if="saving" name="i-heroicons-arrow-path" class="w-4 h-4 animate-spin" />
                Save directory
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'

// ─── Types ───────────────────────────────────────────────────────────────────

interface LdapDirectory {
  id?: string
  name?: string
  enabled?: boolean
  logo?: string
  host?: string
  port?: number
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

interface TestResult {
  success: boolean
  server?: string
  vendor?: string
  user_count?: number
  group_count?: number
  error?: string
}

// ─── Props / emits ───────────────────────────────────────────────────────────

const props = defineProps<{
  open: boolean
  directory: LdapDirectory | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved'): void
}>()

// ─── State ───────────────────────────────────────────────────────────────────

const toast = useToast()

const defaultForm = (): LdapDirectory & { bind_password: string } => ({
  id: undefined,
  name: 'New directory',
  enabled: true,
  logo: 'ldap',
  host: '',
  port: 389,
  bind_dn: '',
  bind_password: '',
  bind_password_set: false,
  base_dn: '',
  user_filter: '(sAMAccountName={username})',
  email_attr: 'mail',
  name_attr: 'cn',
  use_ssl: false,
  start_tls: false,
  user_search_base: '',
  group_search_base: '',
  group_search_filter: '',
  group_name_attribute: 'cn',
  group_member_attribute: 'member',
  group_member_format: 'dn',
  sync_interval_minutes: 60,
  auto_provision_users: true,
  connection_timeout: 10,
  page_size: 500,
})

const form = ref<LdapDirectory & { bind_password: string }>(defaultForm())
const saving = ref(false)
const testing = ref(false)
const validationError = ref<string | null>(null)
const testResult = ref<TestResult | null>(null)

// ─── Computed ────────────────────────────────────────────────────────────────

const userFilterWarning = computed(
  () => form.value.user_filter && !form.value.user_filter.includes('{username}')
)

// ─── Watch: populate / reset when modal opens ─────────────────────────────

watch(
  () => props.open,
  (isOpen) => {
    if (!isOpen) return
    validationError.value = null
    testResult.value = null

    if (props.directory) {
      // Editing an existing directory — copy all fields; password intentionally blank
      const d = props.directory
      form.value = {
        id: d.id,
        name: d.name ?? '',
        enabled: d.enabled ?? true,
        logo: d.logo ?? 'ldap',
        host: d.host ?? '',
        port: d.port ?? 389,
        bind_dn: d.bind_dn ?? '',
        bind_password: '',
        bind_password_set: d.bind_password_set ?? false,
        base_dn: d.base_dn ?? '',
        user_filter: d.user_filter ?? '(sAMAccountName={username})',
        email_attr: d.email_attr ?? 'mail',
        name_attr: d.name_attr ?? 'cn',
        use_ssl: d.use_ssl ?? false,
        start_tls: d.start_tls ?? false,
        user_search_base: d.user_search_base ?? '',
        group_search_base: d.group_search_base ?? '',
        group_search_filter: d.group_search_filter ?? '',
        group_name_attribute: d.group_name_attribute ?? 'cn',
        group_member_attribute: d.group_member_attribute ?? 'member',
        group_member_format: d.group_member_format ?? 'dn',
        sync_interval_minutes: d.sync_interval_minutes ?? 60,
        auto_provision_users: d.auto_provision_users ?? true,
        connection_timeout: d.connection_timeout ?? 10,
        page_size: d.page_size ?? 500,
      }
    } else {
      form.value = defaultForm()
    }
  }
)

// ─── Validation ──────────────────────────────────────────────────────────────

function validate(): boolean {
  if (!form.value.name?.trim()) {
    validationError.value = 'Directory name is required.'
    return false
  }
  if (!form.value.host?.trim()) {
    validationError.value = 'Host is required.'
    return false
  }
  if (!form.value.base_dn?.trim()) {
    validationError.value = 'Base DN is required.'
    return false
  }
  if (!form.value.user_filter?.trim()) {
    validationError.value = 'User filter is required.'
    return false
  }
  validationError.value = null
  return true
}

// ─── Build request body ──────────────────────────────────────────────────────

function buildBody(): Record<string, unknown> {
  const body: Record<string, unknown> = {
    name: form.value.name,
    host: form.value.host,
    port: form.value.port,
    bind_dn: form.value.bind_dn,
    base_dn: form.value.base_dn,
    user_filter: form.value.user_filter,
    email_attr: form.value.email_attr || 'mail',
    name_attr: form.value.name_attr || 'cn',
    logo: form.value.logo || 'ldap',
    enabled: form.value.enabled ?? true,
    use_ssl: form.value.use_ssl ?? false,
    start_tls: form.value.start_tls ?? false,
    user_search_base: form.value.user_search_base || null,
    group_search_base: form.value.group_search_base || null,
    group_search_filter: form.value.group_search_filter || null,
    group_name_attribute: form.value.group_name_attribute || 'cn',
    group_member_attribute: form.value.group_member_attribute || 'member',
    group_member_format: form.value.group_member_format || 'dn',
    sync_interval_minutes: form.value.sync_interval_minutes ?? 60,
    auto_provision_users: form.value.auto_provision_users ?? true,
    connection_timeout: form.value.connection_timeout ?? 10,
    page_size: form.value.page_size ?? 500,
  }
  // Only include bind_password when the user actually typed a new one
  if (form.value.bind_password) {
    body.bind_password = form.value.bind_password
  }
  return body
}

// ─── Save ────────────────────────────────────────────────────────────────────

async function handleSave() {
  if (!validate()) return
  saving.value = true
  testResult.value = null

  try {
    const isNew = !form.value.id
    const path = isNew
      ? '/enterprise/ldap/directories'
      : `/enterprise/ldap/directories/${form.value.id}`

    const { data, error } = await useMyFetch(path, {
      method: isNew ? 'POST' : 'PUT',
      body: buildBody(),
    })

    if (error?.value) throw error.value

    toast.add({ title: isNew ? 'Directory created' : 'Directory updated', color: 'green', icon: 'i-heroicons-check-circle' })
    emit('saved')
    emit('close')
  } catch (e: any) {
    console.error('LDAP save failed:', e)
    toast.add({ title: 'Failed to save directory', description: e?.message ?? 'Unknown error', color: 'red' })
  } finally {
    saving.value = false
  }
}

// ─── Test connection ─────────────────────────────────────────────────────────

async function handleTest() {
  if (!form.value.id) return
  testing.value = true
  testResult.value = null

  try {
    const { data, error } = await useMyFetch<TestResult>(
      `/enterprise/ldap/directories/${form.value.id}/test`,
      { method: 'POST' }
    )
    if (error?.value) throw error.value
    testResult.value = data.value as TestResult
  } catch (e: any) {
    testResult.value = { success: false, error: e?.message ?? 'Connection test failed' }
  } finally {
    testing.value = false
  }
}
</script>

<style scoped>
.ldap-fade-enter-active,
.ldap-fade-leave-active {
  transition: opacity 0.18s ease;
}
.ldap-fade-enter-from,
.ldap-fade-leave-to {
  opacity: 0;
}

details > summary::-webkit-details-marker { display: none; }
details > summary { list-style: none; }
</style>
