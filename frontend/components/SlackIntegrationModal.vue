<template>
    <div class="p-4">
      <div class="flex items-center gap-2 mb-2">
        <img src="/icons/slack.png" alt="Slack" class="w-5 h-5" />
        <h1 class="text-lg font-semibold">Slack Integration</h1>
      </div>
      <p class="text-sm text-gray-500">Configure and manage Slack integration for your organization</p>
      <hr class="my-4" />
      
      <div v-if="integrated" class="mb-4">
        <p class="text-green-600 mb-4">Slack is currently connected.</p>

        <!-- Usage Notes -->
        <div class="bg-[#F6EFEA] border border-[#E8C9B5] rounded-lg p-4 mb-4">
          <h3 class="text-sm font-medium text-[#A8330F] mb-2">Usage Notes</h3>
          <ul class="text-sm text-[#A8330F] space-y-1 list-disc list-inside">
            <li>Only registered users can message or @mention the bot</li>
            <li>In channels/group chats, only <strong>public</strong> data sources are queried</li>
            <li>In private DMs, <strong>public + private</strong> data sources (that the user has access to) are queried</li>
          </ul>
        </div>

        <!-- Integration Details -->
        <div class="bg-gray-50 rounded-lg p-4 mb-4">
          <h3 class="text-sm font-medium text-gray-700 mb-3">Integration Details</h3>
          <div class="space-y-2 text-sm">
            <div class="flex justify-between">
              <span class="text-gray-600">Workspace Name:</span>
              <span class="font-medium">{{ integrationData?.platform_config?.team_name || 'N/A' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-600">Workspace ID:</span>
              <span class="font-mono text-xs">{{ integrationData?.platform_config?.team_id || 'N/A' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-600">Base URL:</span>
              <span class="font-mono text-xs">{{ integrationData?.platform_config?.base_url || 'N/A' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-600">Connected:</span>
              <span class="font-medium">{{ formatDate(integrationData?.created_at) }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-600">Last Updated:</span>
              <span class="font-medium">{{ formatDate(integrationData?.updated_at) }}</span>
            </div>
          </div>
        </div>
        
        <!-- Account Linking -->
        <div class="bg-gray-50 rounded-lg p-4 mb-4">
          <h3 class="text-sm font-medium text-gray-700 mb-3">Account Linking</h3>
          <label class="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              v-model="autoLinkByEmail"
              :disabled="savingAutoLink"
              @change="saveAutoLinkByEmail"
              class="mt-0.5"
            />
            <span class="text-sm">
              <span class="font-medium">Auto-link users by workspace email</span>
              <span class="block text-xs text-gray-500 mt-0.5">
                When enabled, Slack users are automatically linked to Dash accounts whose email matches their Slack workspace profile (no verification link required).
                Only enable if your workspace emails are managed by SSO/IdP — otherwise users could self-set an email and impersonate someone. Requires the <code>users:read.email</code> scope on the bot.
              </span>
            </span>
          </label>
        </div>

        <UButton
          color="red"
          variant="soft"
          @click="disconnect"
        >
          Disconnect
        </UButton>
      </div>
      <div v-else>
        <form @submit.prevent="connect">
          <div class="mb-4">
            <label class="block text-sm font-medium mb-1">Bot Token</label>
            <input v-model="botToken" type="text" class="w-full border rounded px-2 py-1" required />
          </div>
          <div class="mb-4">
            <label class="block text-sm font-medium mb-1">Signing Secret</label>
            <input v-model="signingSecret" type="text" class="w-full border rounded px-2 py-1" required />
          </div>
          <div class="mb-4">
            <label class="flex items-start gap-2 cursor-pointer">
              <input type="checkbox" v-model="autoLinkByEmail" class="mt-0.5" />
              <span class="text-sm">
                <span class="font-medium">Auto-link users by workspace email</span>
                <span class="block text-xs text-gray-500 mt-0.5">
                  Users messaging the bot are linked to Dash accounts whose email matches their Slack profile — no verification link required. Requires the <code>users:read.email</code> scope. Recommended for SSO-managed workspaces.
                </span>
              </span>
            </label>
          </div>

          <!-- Per-agent audience (only when scoped to a studio) -->
          <div v-if="props.studioId" class="mb-4">
            <label class="block text-sm font-medium mb-2 text-[#1f2328]">Who can use this channel</label>
            <div class="space-y-2">
              <label
                v-for="opt in audienceOptions"
                :key="opt.value"
                class="flex items-start gap-2 rounded-lg border p-2.5 cursor-pointer transition-colors"
                :class="audience === opt.value ? 'border-[#E8C9B5] bg-[#F6EFEA]' : 'border-[#E9E0D3] hover:border-[#dcd9cf]'"
              >
                <input type="radio" :value="opt.value" v-model="audience" class="mt-0.5 text-[#C2541E] focus:ring-[#C2541E]" />
                <span>
                  <span class="block text-xs font-medium text-[#1f2328]">{{ opt.label }}</span>
                  <span class="block text-[11px] text-gray-500">{{ opt.hint }}</span>
                </span>
              </label>
            </div>
          </div>
          <button type="submit" class="bg-[#C2541E] hover:bg-[#A8330F] text-white text-sm px-3 py-1.5 rounded-md">Connect</button>
        </form>
      </div>
      <button class="absolute top-2 end-2 text-gray-400 hover:text-gray-600" @click="$emit('close')">✕</button>
    </div>
  </template>
  
  <script setup lang="ts">
  import { ref, watch } from 'vue'
  const props = defineProps<{
    integrated: boolean
    integrationData?: any
    studioId?: string
  }>()
  const emit = defineEmits(['close', 'updated'])
  const toast = useToast()

  const botToken = ref('')
  const signingSecret = ref('')
  // Per-agent audience (only used when studioId is set)
  const audience = ref<'members' | 'anyone'>('members')
  const audienceOptions = [
    { value: 'members', label: 'Org members only', hint: 'Only members of your organization can use this channel.' },
    { value: 'anyone', label: 'Anyone', hint: 'Anyone who reaches the bot can chat with it.' },
  ]
  // Default ON for new connections; reflects stored config for existing ones.
  const autoLinkByEmail = ref<boolean>(
    props.integrationData?.platform_config?.auto_link_by_email ?? true
  )
  const savingAutoLink = ref(false)

  watch(() => props.integrationData?.platform_config?.auto_link_by_email, (v) => {
    if (v !== undefined) autoLinkByEmail.value = !!v
  })

  async function saveAutoLinkByEmail() {
    if (!props.integrationData?.id) return
    savingAutoLink.value = true
    const nextConfig = {
      ...(props.integrationData?.platform_config || {}),
      auto_link_by_email: autoLinkByEmail.value,
    }
    const res = await useMyFetch(`/api/settings/integrations/${props.integrationData.id}`, {
      method: 'PUT',
      body: { platform_config: nextConfig },
    })
    savingAutoLink.value = false
    if (res.status.value === 'success') {
      toast.add({
        title: autoLinkByEmail.value ? 'Auto-link enabled' : 'Auto-link disabled',
        color: 'green',
      })
      emit('updated')
    } else {
      autoLinkByEmail.value = !autoLinkByEmail.value
      toast.add({
        title: 'Failed to update setting',
        description: (res.error.value as any)?.data?.detail || (res.error.value as any)?.message,
        color: 'red',
      })
    }
  }
  
  function formatDate(dateString: string | undefined) {
    if (!dateString) return 'N/A'
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    })
  }
  
  async function connect() {
      const body: any = {
        bot_token: botToken.value,
        signing_secret: signingSecret.value,
        auto_link_by_email: autoLinkByEmail.value,
      }
      // Per-agent scope: post to the studio endpoint + include the audience.
      // Org scope (no studioId) keeps the exact original behavior.
      const url = props.studioId
        ? `/api/studios/${props.studioId}/channels/slack`
        : '/api/settings/integrations/slack'
      if (props.studioId) body.audience = audience.value
      const res = await useMyFetch(url, {
        method: 'POST',
        body,
      })
      if (res.status.value === 'success') {
        toast.add({
          title: 'Slack connected',
          description: 'Slack integration successful',
          color: 'green'
        })
        emit('updated')
        emit('close')
      } else {
        toast.add({
        title: 'Failed to connect Slack',
        description: (res.error.value as any).data?.detail || (res.error.value as any).message,
        color: 'red'
      })
    }
  }
  
  async function disconnect() {
    if (!props.integrationData?.id) return
    const res = await useMyFetch(`/api/settings/integrations/${props.integrationData.id}`, {
      method: 'DELETE'
    })
    if (res.status.value === 'success') {
      toast.add({
        title: 'Slack disconnected',
        description: 'Slack integration disconnected',
        color: 'green'
      })
      emit('updated')
      emit('close')
    } else {
      toast.add({
        title: 'Failed to disconnect Slack',
        description: (res.error.value as any).data?.detail || (res.error.value as any).message,
        color: 'red'
      })
    }
  }
  </script>