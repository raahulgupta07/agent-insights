<template>
  <UModal v-model="open" :ui="{ width: 'sm:max-w-lg' }">
    <div class="p-5 relative">
      <button @click="emit('update:modelValue', false)" class="absolute top-2 end-2 text-gray-500 hover:text-gray-700 outline-none">
        <Icon name="heroicons:x-mark" class="w-5 h-5" />
      </button>

      <div class="mb-4">
        <h1 class="text-base font-semibold flex items-center">
            <DataSourceIcon :type="connectionType" class="h-4 me-2" />
            {{ $t('data.connectNamed', { name: ds?.name }) }}</h1>
        <p class="mt-1 text-xs text-gray-500">{{ $t('data.provideCredentials') }}</p>
      </div>

      <div v-if="authOptions.length > 1" class="mb-3">
        <label class="text-xs text-gray-600">{{ $t('data.authMethod') }}</label>
        <USelectMenu v-model="authMode" :options="authOptions" option-attribute="label" value-attribute="value" />
      </div>

      <!-- OAuth mode: standard sign-in button -->
      <div v-if="isOAuthMode" class="mt-4">
        <UButton
          size="sm"
          color="primary"
          variant="solid"
          block
          :loading="oauthLoading"
          @click="onOAuthSignIn"
        >
          {{ currentAuthTitle || $t('data.signIn') }}
        </UButton>
      </div>

      <!-- Standard credential form -->
      <template v-else>
        <div class="space-y-3">
          <div v-for="field in credentialFields" :key="field.key" class="flex flex-col">
            <label class="text-xs text-gray-600 mb-1">{{ field.title }}</label>
            <input v-if="field.type === 'string'" :type="field.format === 'password' ? 'password' : 'text'" v-model="form.credentials[field.key]" class="border rounded px-2 py-1 text-sm" />
            <input v-else-if="field.type === 'integer'" type="number" v-model.number="form.credentials[field.key]" class="border rounded px-2 py-1 text-sm" />
            <UCheckbox v-else-if="field.type === 'boolean'" v-model="form.credentials[field.key]">{{ field.title }}</UCheckbox>
            <textarea v-else-if="field.type === 'text' || field.type === 'textarea'" v-model="form.credentials[field.key]" class="border rounded px-2 py-1 text-sm"></textarea>
            <input v-else v-model="form.credentials[field.key]" class="border rounded px-2 py-1 text-sm" />

            <!-- P2: cross-tenant discovery — help the user find their (guest) tenant id -->
            <div v-if="isPowerbiUser && field.key === 'tenant_id'" class="mt-1">
              <UButton size="2xs" color="gray" variant="soft" :loading="discovering" @click="onDiscoverTenants">
                {{ $t('data.findMyTenants') }}
              </UButton>
              <span v-if="discoverError" class="ml-2 text-2xs text-red-600">{{ discoverError }}</span>
              <div v-if="discoveredTenants.length" class="mt-1 space-y-1">
                <div v-for="tn in discoveredTenants" :key="tn.id"
                     class="flex items-center justify-between border rounded px-2 py-1 text-2xs cursor-pointer hover:border-primary"
                     :class="form.credentials['tenant_id'] === tn.id ? 'border-primary bg-primary/5' : ''"
                     @click="form.credentials['tenant_id'] = tn.id">
                  <span class="font-medium">{{ tn.name }}</span>
                  <span class="text-gray-400 font-mono">{{ tn.id }}</span>
                </div>
                <p class="text-2xs text-gray-400">{{ $t('data.pickTenantHint') }}</p>
              </div>
            </div>
          </div>
        </div>

        <!-- P3: device-code sign-in (MFA-safe) -->
        <div v-if="isPowerbiUser" class="mt-3 border-t pt-3">
          <UButton size="2xs" color="gray" variant="soft" :loading="deviceStarting" @click="onDeviceCodeStart">
            {{ $t('data.deviceCodeSignIn') }}
          </UButton>
          <span v-if="deviceError" class="ml-2 text-2xs text-red-600">{{ deviceError }}</span>
          <p class="text-2xs text-gray-400 mt-1">{{ $t('data.deviceCodeHint') }}</p>
          <div v-if="deviceCode" class="mt-2 border rounded p-2 bg-gray-50">
            <div class="text-2xs text-gray-500">{{ $t('data.deviceCodeHint') }}</div>
            <div class="mt-1 flex items-center gap-2">
              <span class="font-mono text-base font-bold tracking-widest">{{ deviceCode.user_code }}</span>
              <a :href="deviceCode.verification_uri" target="_blank" rel="noopener"
                 class="text-2xs text-primary underline">{{ deviceCode.verification_uri }}</a>
            </div>
            <div class="mt-1 text-2xs"
                 :class="deviceStatus === 'success' ? 'text-green-600' : deviceStatus === 'error' ? 'text-red-600' : 'text-gray-500'">
              <span v-if="deviceStatus === 'waiting'">{{ $t('data.deviceWaiting') }}</span>
              <span v-else-if="deviceStatus === 'success'">{{ $t('data.deviceSuccess') }}</span>
              <span v-else-if="deviceStatus === 'error'">{{ deviceError }}</span>
            </div>
          </div>
        </div>

        <!-- #8: scan ALL reachable tenants into one merged catalog -->
        <div v-if="isPowerbiUser" class="mt-3 border-t pt-3">
          <UButton size="2xs" color="gray" variant="soft" :loading="scanningAll" @click="onScanAllTenants">
            {{ $t('data.scanAllTenants') }}
          </UButton>
          <span v-if="scanAllError" class="ml-2 text-2xs text-red-600">{{ scanAllError }}</span>
          <div v-if="scanAllResult.length" class="mt-2 space-y-1">
            <div v-for="tn in scanAllResult" :key="tn.id || tn.name"
                 class="flex items-center justify-between border rounded px-2 py-1 text-2xs">
              <span class="font-medium">{{ tn.name }}</span>
              <span :class="tn.ok ? 'text-green-600' : 'text-red-600'">
                {{ tn.ok ? tn.table_count + ' tables' : (tn.error || $t('data.failed')) }}
              </span>
            </div>
            <p class="text-2xs text-gray-400">{{ $t('data.scanAllHint', { n: scanAllTableCount }) }}</p>
          </div>
        </div>

        <div class="flex justify-between mt-5">
          <UButton size="xs" color="gray" variant="soft" :loading="testing" @click="onTest">{{ $t('data.testConnection') }}</UButton>
          <div class="space-x-2">
            <UButton size="xs" color="gray" variant="soft" @click="emit('update:modelValue', false)">{{ $t('data.cancel') }}</UButton>
            <UButton size="xs" color="primary" variant="solid" :loading="saving" @click="onSave">{{ $t('data.save') }}</UButton>
          </div>
        </div>
      </template>

      <div v-if="testResult" class="mt-3 text-xs">
        <span :class="testResult.success ? 'text-green-600' : 'text-red-600'">
          {{ testResult.success ? $t('data.connectedSuccess') : $t('data.connectionFailed') }}
        </span>
        <span v-if="testResult.message" class="text-gray-500"> - {{ testResult.message }}</span>
      </div>
    </div>
  </UModal>
  
</template>

<script lang="ts" setup>
import { computed, watch, ref, onBeforeUnmount } from 'vue'

const props = defineProps<{ modelValue: boolean, dataSource: any }>()
const emit = defineEmits(['update:modelValue', 'saved'])

const { t } = useI18n()

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v)
})

const ds = computed(() => props.dataSource)
// Use nested connection type (Option A architecture)
const connectionType = computed(() => ds.value?.connection?.type || ds.value?.type)
const connectionId = computed(() => ds.value?.connection?.id || ds.value?.connection_id || ds.value?.connections?.[0]?.id)
const authMode = ref<string>('')
const form = ref<{ auth_mode: string, credentials: Record<string, any>, is_primary?: boolean }>({ auth_mode: '', credentials: {}, is_primary: true })
const authOptions = ref<{ label: string, value: string }[]>([])
const fieldsByAuth = ref<Record<string, any>>({})
const credentialFields = computed(() => {
  const schema = fieldsByAuth.value[authMode.value]
  if (!schema) return []
  const props = (schema.properties || {})
  const req = schema.required || []
  return Object.keys(props).map((k) => {
    const f = props[k] || {}
    return {
      key: k,
      title: f.title || k,
      type: f.type || 'string',
      format: f.format,
      required: req.includes(k)
    }
  })
})

watch(open, async (val) => {
  if (val && connectionType.value) {
    await loadFields()
  }
})

async function loadFields() {
  const { data } = await useMyFetch(`/data_sources/${connectionType.value}/fields`, { method: 'GET', query: { auth_policy: 'user_required' } })
  const payload = data.value as any
  const byAuth = (payload?.credentials_by_auth) || {}
  fieldsByAuth.value = byAuth
  catalogOwnership.value = payload?.catalog_ownership || 'shared'
  // build options
  const names = Object.keys((payload?.auth?.by_auth) || {})
  authOptions.value = names.map((n) => ({ label: payload.auth.by_auth[n]?.title || n, value: n }))
  // The OAuth-only direct-redirect path is handled by `useConnectionSignIn`
  // before this modal ever opens. By the time we're here, the user actually
  // has a choice to make — render the standard form with the registry's
  // default auth selected.
  const defaultAuth = payload?.auth?.default
  authMode.value = (defaultAuth && names.includes(defaultAuth)) ? defaultAuth : names[0] || ''
  form.value.auth_mode = authMode.value
  form.value.credentials = {}
}

const catalogOwnership = ref<string>('shared')

watch(authMode, (v) => {
  form.value.auth_mode = v || ''
  form.value.credentials = {}
})

const isOAuthMode = computed(() => authMode.value === 'oauth')
const currentAuthTitle = computed(() => {
  const opt = authOptions.value.find(o => o.value === authMode.value)
  return opt?.label || t('data.signIn')
})
const oauthLoading = ref(false)

async function onOAuthSignIn() {
  if (!connectionId.value) {
    testResult.value = { success: false, message: t('data.noConnectionForSource') }
    return
  }
  try {
    oauthLoading.value = true
    const { data, error } = await useMyFetch(`/connections/${connectionId.value}/oauth/authorize`, { method: 'GET' })
    if (error.value) throw error.value
    const result = data.value as any
    if (result?.authorization_url) {
      window.location.href = result.authorization_url
    }
  } catch (e: any) {
    testResult.value = { success: false, message: e?.message || t('data.oauthStartFailed') }
  } finally {
    oauthLoading.value = false
  }
}

const saving = ref(false)
const testing = ref(false)
const testResult = ref<{ success: boolean, message?: string } | null>(null)

// P2: cross-tenant discovery (Power BI user sign-in)
const isPowerbiUser = computed(() => connectionType.value === 'powerbi_user')
const discovering = ref(false)
const discoverError = ref('')
const discoveredTenants = ref<{ id: string, name: string, domain?: string }[]>([])

// P3: device-code sign-in (MFA-safe)
const deviceStarting = ref(false)
const deviceCode = ref<any>(null)
const deviceStatus = ref<'' | 'waiting' | 'success' | 'error'>('')
const deviceError = ref('')
let devicePollTimer: any = null

function stopDevicePoll() {
  if (devicePollTimer) { clearInterval(devicePollTimer); devicePollTimer = null }
}

async function onDeviceCodeStart() {
  deviceError.value = ''
  deviceStatus.value = ''
  deviceCode.value = null
  stopDevicePoll()
  const tenant_id = form.value.credentials['tenant_id']
  if (!tenant_id) { deviceError.value = t('data.enterTenantFirst'); return }
  try {
    deviceStarting.value = true
    const { data, error } = await useMyFetch(`/data_sources/${ds.value.id}/my-credentials/device-code/start`, {
      method: 'POST', body: { tenant_id, client_id: form.value.credentials['client_id'] || null }
    })
    if (error.value) throw error.value
    const r = data.value as any
    if (!r?.ok) { deviceError.value = r?.error || t('data.failed'); return }
    deviceCode.value = r
    deviceStatus.value = 'waiting'
    const intervalMs = Math.max(2, (r.interval || 5)) * 1000
    devicePollTimer = setInterval(pollDeviceCode, intervalMs)
  } catch (e: any) {
    deviceError.value = e?.message || t('data.failed')
  } finally {
    deviceStarting.value = false
  }
}

async function pollDeviceCode() {
  if (!deviceCode.value) { stopDevicePoll(); return }
  try {
    const { data, error } = await useMyFetch(`/data_sources/${ds.value.id}/my-credentials/device-code/poll`, {
      method: 'POST', body: {
        tenant_id: form.value.credentials['tenant_id'],
        device_code: deviceCode.value.device_code,
        auth_mode: authMode.value,
        username: form.value.credentials['username'] || null,
        client_id: form.value.credentials['client_id'] || null,
      }
    })
    if (error.value) throw error.value
    const r = data.value as any
    if (r?.status === 'pending') return
    if (r?.ok && r?.status === 'success') {
      stopDevicePoll()
      deviceStatus.value = 'success'
      emit('saved')
      setTimeout(() => emit('update:modelValue', false), 1200)
      return
    }
    stopDevicePoll()
    deviceStatus.value = 'error'
    deviceError.value = r?.error || t('data.failed')
  } catch (e: any) {
    stopDevicePoll()
    deviceStatus.value = 'error'
    deviceError.value = e?.message || t('data.failed')
  }
}

onBeforeUnmount(stopDevicePoll)
watch(open, (v) => { if (!v) stopDevicePoll() })

// #8: scan ALL reachable tenants
const scanningAll = ref(false)
const scanAllError = ref('')
const scanAllResult = ref<{ id?: string, name: string, ok: boolean, table_count: number, error?: string }[]>([])
const scanAllTableCount = ref(0)

async function onScanAllTenants() {
  scanAllError.value = ''
  scanAllResult.value = []
  const username = form.value.credentials['username']
  const password = form.value.credentials['password']
  if (!username || !password) {
    scanAllError.value = t('data.enterEmailPasswordFirst')
    return
  }
  try {
    scanningAll.value = true
    const { data, error } = await useMyFetch(`/data_sources/${ds.value.id}/my-credentials/scan-all-tenants`, {
      method: 'POST', body: { username, password, client_id: form.value.credentials['client_id'] || null }
    })
    if (error.value) throw error.value
    const r = data.value as any
    if (!r?.ok) { scanAllError.value = r?.error || t('data.failed'); return }
    scanAllResult.value = r.tenants || []
    scanAllTableCount.value = r.table_count || 0
    emit('saved')
  } catch (e: any) {
    scanAllError.value = e?.message || t('data.failed')
  } finally {
    scanningAll.value = false
  }
}

async function onDiscoverTenants() {
  discoverError.value = ''
  discoveredTenants.value = []
  const username = form.value.credentials['username']
  const password = form.value.credentials['password']
  if (!username || !password) {
    discoverError.value = t('data.enterEmailPasswordFirst')
    return
  }
  try {
    discovering.value = true
    const { data, error } = await useMyFetch('/data_sources/powerbi/discover-tenants', {
      method: 'POST', body: { username, password }
    })
    if (error.value) throw error.value
    const r = data.value as any
    if (!r?.ok) { discoverError.value = r?.error || t('data.failed'); return }
    discoveredTenants.value = r.tenants || []
    if (!discoveredTenants.value.length) discoverError.value = t('data.noTenantsFound')
  } catch (e: any) {
    discoverError.value = e?.message || t('data.failed')
  } finally {
    discovering.value = false
  }
}

async function onSave() {
  try {
    saving.value = true
    const { error } = await useMyFetch(`/data_sources/${ds.value.id}/my-credentials`, { method: 'POST', body: form.value })
    if (error.value) throw error.value
    emit('saved')
    emit('update:modelValue', false)
  } catch (e) {
    // optionally toast
  } finally {
    saving.value = false
  }
}

async function onTest() {
  try {
    testing.value = true
    const { data, error } = await useMyFetch(`/data_sources/${ds.value.id}/my-credentials/test`, { method: 'POST', body: form.value })
    if (error.value) throw error.value
    testResult.value = data.value as any
  } catch (e: any) {
    testResult.value = { success: false, message: e?.message || t('data.failed') }
  } finally {
    testing.value = false
  }
}

</script>


