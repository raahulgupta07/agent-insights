<template>
  <div class="flex ps-2 md:ps-4 text-sm mx-auto md:w-1/2 md:pt-10">
    <div class="w-full px-4 ps-0 py-4">
      <div>
        <h1 class="text-lg font-semibold text-center">Create Data Agent</h1>
        <p class="mt-2 text-gray-500 text-center">Set data source, select tables, and define additional context</p>
      </div>

      <WizardSteps class="mt-7" current="connect" />

      <!-- Loading connections -->
      <div v-if="loadingConnections" class="flex flex-col items-center justify-center py-16">
        <Spinner class="h-4 w-4 text-gray-400" />
        <p class="text-sm text-gray-500 mt-2">Loading connections...</p>
      </div>

      <div v-else class="mt-6 bg-white rounded-lg border border-gray-200 p-4">
        <!-- Agent name -->
        <div class="mb-4">
          <label class="block text-sm font-medium text-gray-700 mb-1">
            Name <span class="text-red-500">*</span>
          </label>
          <UInput
            v-model="agentName"
            placeholder="e.g., Sales, Marketing, Finance"
            size="lg"
            :disabled="creatingFromConnection"
          />
        </div>

        <!-- Add data: how this agent gets its data — upload files OR connect a source -->
        <div class="mb-4">
          <label class="block text-sm font-medium text-gray-700 mb-1">
            Add data <span class="text-red-500">*</span>
          </label>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              class="flex items-center gap-2 px-3 py-2.5 rounded-lg border text-sm text-left transition-colors"
              :class="dataMethod === 'upload' ? 'border-[#C2541E] bg-[#FBEFE4] text-[#A8330F]' : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'"
              :disabled="creating"
              @click="dataMethod = 'upload'"
            >
              <UIcon name="i-heroicons-arrow-up-tray" class="h-4 w-4 flex-shrink-0" />
              <span>Upload files</span>
            </button>
            <button
              type="button"
              class="flex items-center gap-2 px-3 py-2.5 rounded-lg border text-sm text-left transition-colors"
              :class="dataMethod === 'connect' ? 'border-[#C2541E] bg-[#FBEFE4] text-[#A8330F]' : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'"
              :disabled="creatingFromConnection"
              @click="dataMethod = 'connect'"
            >
              <UIcon name="i-heroicons-link" class="h-4 w-4 flex-shrink-0" />
              <span>Connect a source</span>
            </button>
          </div>
        </div>

        <!-- Upload branch: create the agent from an uploaded spreadsheet/CSV -->
        <template v-if="dataMethod === 'upload'">
          <div class="mb-4">
            <label class="block text-sm font-medium text-gray-700 mb-1">
              File <span class="text-red-500">*</span>
            </label>
            <input
              ref="uploadInput"
              type="file"
              accept=".xlsx,.xls,.csv"
              class="hidden"
              :disabled="creating"
              @change="onUploadFileChange"
            />
            <button
              type="button"
              class="w-full flex items-center justify-center gap-2 px-3 py-6 rounded-lg border-2 border-dashed border-gray-200 text-sm text-gray-500 hover:border-[#C2541E]/40 hover:bg-[#FBEFE4]/40 transition-colors disabled:opacity-50"
              :disabled="creating"
              @click="uploadInput?.click()"
            >
              <UIcon name="i-heroicons-document-arrow-up" class="h-5 w-5" />
              <span v-if="uploadFile">{{ uploadFile.name }}</span>
              <span v-else>Choose an Excel or CSV file</span>
            </button>
            <p class="mt-1.5 text-[11px] text-gray-400">This file becomes the agent's first data source. You can add more later.</p>
          </div>

          <div v-if="errorMessage" class="p-3 bg-red-50 text-red-700 rounded-lg text-sm mb-4">
            {{ errorMessage }}
          </div>

          <div class="flex justify-between items-center pt-4 border-t border-gray-100">
            <NuxtLink to="/agents" class="text-sm text-gray-500 hover:text-gray-700">
              ← Cancel
            </NuxtLink>
            <UButton
              color="primary"
              size="xs"
              :loading="creating"
              :disabled="!canSubmitUpload"
              @click="createAgentFromUpload"
            >
              Save & Continue
            </UButton>
          </div>
        </template>

        <!-- Connect branch: create the agent from an existing/new connection -->
        <template v-else>
        <!-- Connection selector (multi-select for existing connections) -->
        <div class="mb-4">
          <label class="block text-sm font-medium text-gray-700 mb-1">
            Connections <span class="text-red-500">*</span>
          </label>
          <USelectMenu
            v-model="selectedConnections"
            :options="connections"
            placeholder="Select connections"
            size="lg"
            :disabled="creatingFromConnection"
            by="id"
            multiple
            searchable
            searchable-placeholder="Search connections..."
            option-attribute="name"
            :search-attributes="['name', 'type']"
          >
            <template #label>
              <div v-if="selectedConnections.length > 0" class="flex items-center gap-1.5 flex-wrap">
                <template v-for="conn in selectedConnections" :key="conn.id">
                  <div class="flex items-center gap-1 bg-gray-100 rounded px-1.5 py-0.5">
                    <DataSourceIcon :type="conn.type" class="h-3.5 flex-shrink-0" />
                    <span class="text-xs truncate max-w-[100px]">{{ conn.name }}</span>
                  </div>
                </template>
              </div>
              <span v-else class="text-gray-400">Select connections</span>
            </template>
            <template #option="{ option }">
              <div class="flex items-center gap-2 w-full">
                <DataSourceIcon :type="option.type" class="h-4 flex-shrink-0" />
                <div class="flex-1 min-w-0">
                  <div class="font-medium truncate">{{ option.name }}</div>
                  <div class="text-[10px] text-gray-400">
                    {{ option.table_count || 0 }} tables · {{ option.agent_count || 0 }} agents
                  </div>
                </div>
              </div>
            </template>
          </USelectMenu>
          <button
            type="button"
            class="mt-2 inline-flex items-center gap-1.5 text-xs text-[#C2541E] hover:text-[#A8330F]"
            :disabled="creatingFromConnection"
            @click="showAddConnectionModal = true"
          >
            <UIcon name="heroicons-plus-circle" class="h-3.5 w-3.5" />
            <span>Create new connection</span>
          </button>
        </div>

        <!-- Existing connection flow (main form) -->
        <div v-if="selectedConnections.length > 0">
          <div class="flex items-center gap-2 mb-4">
            <UToggle v-model="useLlmSync" :disabled="creatingFromConnection" size="xs" color="primary" />
            <span class="text-xs text-gray-700">Use LLM to learn agent</span>
          </div>

          <div v-if="errorMessage" class="p-3 bg-red-50 text-red-700 rounded-lg text-sm mb-4">
            {{ errorMessage }}
          </div>

          <div class="flex justify-between items-center pt-4 border-t border-gray-100">
            <NuxtLink to="/agents" class="text-sm text-gray-500 hover:text-gray-700">
              ← Cancel
            </NuxtLink>
            <UButton
              color="primary"
              size="xs"
              :loading="creatingFromConnection"
              :disabled="!canSubmitExisting"
              @click="createAgentFromExistingConnection"
            >
              Save & Continue
            </UButton>
          </div>
        </div>

        <!-- No selection yet (just show cancel) -->
        <div v-else class="flex justify-start pt-4 border-t border-gray-100">
          <NuxtLink to="/agents" class="text-sm text-gray-500 hover:text-gray-700">
            ← Cancel
          </NuxtLink>
        </div>
        </template>
      </div>

      <!-- Add Connection Modal -->
      <AddConnectionModal v-model="showAddConnectionModal" :skipSuccessStep="true" @created="handleNewConnectionCreated" />
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({ auth: true })
import Spinner from '~/components/Spinner.vue'
import WizardSteps from '@/components/datasources/WizardSteps.vue'
import AddConnectionModal from '~/components/AddConnectionModal.vue'

const route = useRoute()

interface Connection {
  id: string
  name: string
  type: string
  table_count?: number
  agent_count?: number
}

const connections = ref<Connection[]>([])
const loadingConnections = ref(true)
const selectedConnections = ref<Connection[]>([])
const agentName = ref('')
const useLlmSync = ref(true)
const creatingFromConnection = ref(false)
const errorMessage = ref('')
const showAddConnectionModal = ref(false)

// How this agent gets its data: upload a file OR connect a source.
const dataMethod = ref<'upload' | 'connect'>('connect')
// Upload branch state
const uploadInput = ref<HTMLInputElement | null>(null)
const uploadFile = ref<File | null>(null)
const creating = ref(false)   // upload-branch create-in-flight

function onUploadFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  uploadFile.value = input.files && input.files.length ? input.files[0] : null
  errorMessage.value = ''
}

const canSubmitUpload = computed(() => {
  return (
    !!uploadFile.value &&
    agentName.value.trim().length > 0 &&
    !creating.value
  )
})

async function handleNewConnectionCreated(connectionData: any) {
  // Refresh connections list
  await loadConnections()

  // Find and select the newly created connection
  if (connectionData?.id) {
    const newConn = connections.value.find(c => c.id === connectionData.id)
    if (newConn && !selectedConnections.value.some(c => c.id === newConn.id)) {
      selectedConnections.value = [...selectedConnections.value, newConn]
    }
  }
}

const canSubmitExisting = computed(() => {
  return (
    selectedConnections.value.length > 0 &&
    agentName.value.trim().length > 0 &&
    !creatingFromConnection.value
  )
})

async function loadConnections() {
  loadingConnections.value = true
  try {
    const response = await useMyFetch('/connections', { method: 'GET' })
    connections.value = (response.data.value || []) as Connection[]
  } catch (err) {
    console.error('Failed to load connections:', err)
  } finally {
    loadingConnections.value = false
  }
}

async function createAgentFromExistingConnection() {
  if (selectedConnections.value.length === 0 || !agentName.value.trim()) return
  creatingFromConnection.value = true
  errorMessage.value = ''

  try {
    const payload = {
      name: agentName.value.trim(),
      connection_ids: selectedConnections.value.map(c => c.id),
      use_llm_sync: useLlmSync.value,
      is_public: false,
      generate_summary: false,
      generate_conversation_starters: false,
      generate_ai_rules: false,
    }

    const response = await useMyFetch('/data_sources', {
      method: 'POST',
      body: payload,
    })

    if (response.error.value) {
      const errData = (response.error.value as any).data as any
      errorMessage.value = errData?.detail || 'Failed to create agent'
      return
    }

    const result = response.data.value as any
    if (result?.id) {
      navigateTo(`/agents/new/${result.id}/schema`)
    } else {
      navigateTo('/agents')
    }
  } catch (err: any) {
    errorMessage.value = err?.message || 'An error occurred'
  } finally {
    creatingFromConnection.value = false
  }
}

// Upload branch: create the agent from an uploaded spreadsheet/CSV. Reuses the
// existing file-upload (/files) → data-source (/data_sources/from-file) calls;
// the from-file DataSource IS this agent (data_source_name = the agent name), so
// the upload attaches to THIS agent rather than spawning a standalone one. Then
// continues into the same schema/context wizard steps as the connector branch.
async function createAgentFromUpload() {
  if (!uploadFile.value || !agentName.value.trim()) return
  creating.value = true
  errorMessage.value = ''

  try {
    // 1. upload the raw file
    const fd = new FormData()
    fd.append('file', uploadFile.value)
    const up = await useMyFetch('/files', { method: 'POST', body: fd })
    const upRes = up.data.value as any
    if (up.error.value || !upRes?.id) {
      errorMessage.value = (up.error.value as any)?.data?.detail || 'File upload failed'
      return
    }

    // 2. create the Data Agent from that file (name = the agent name typed above)
    const payload = {
      file_id: upRes.id,
      data_source_name: agentName.value.trim(),
      sheet_names: null,       // use all sheets
      description: null,
    }
    const response = await useMyFetch('/data_sources/from-file', {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json' },
    })

    if (response.error.value) {
      const errData = (response.error.value as any).data as any
      errorMessage.value = errData?.detail || 'Failed to create agent'
      return
    }

    const result = response.data.value as any
    if (result?.id) {
      navigateTo(`/agents/new/${result.id}/schema`)
    } else {
      navigateTo('/agents')
    }
  } catch (err: any) {
    errorMessage.value = err?.message || 'An error occurred'
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  await loadConnections()

  const forcedNew = String(route.query.mode || '') === 'new_connection'
  const connectionParam = route.query.connection as string

  // Pre-select connection if passed via query param (from AddConnectionModal)
  if (connectionParam) {
    dataMethod.value = 'connect'
    const matchingConn = connections.value.find(c => c.id === connectionParam)
    if (matchingConn) {
      selectedConnections.value = [matchingConn]
    }
  } else if (forcedNew) {
    // Explicit connect intent → open Add Connection modal
    dataMethod.value = 'connect'
    showAddConnectionModal.value = true
  } else if (connections.value.length === 0) {
    // No sources to connect yet → default to the upload branch (user can still
    // switch to "Connect a source" and create one).
    dataMethod.value = 'upload'
  } else if (connections.value.length === 1) {
    // Single connection - auto-select it
    dataMethod.value = 'connect'
    selectedConnections.value = [connections.value[0]]
  }
})
</script>
