<template>
    <div>
        <div class="mb-4">
            <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">Email / SMTP</h2>
            <p class="text-xs text-[#6b6b6b] mt-0.5">
                Outbound email for <span class="font-medium text-[#1f2328]">this agent</span> — report shares, scheduled results, channel and mailbox replies. Choose where its mail sends from.
            </p>
        </div>

        <div v-if="unavailable" class="rounded-2xl border border-[#E9E0D3] bg-white p-6 text-[12px] text-[#9a958c] flex items-center gap-2">
            <UIcon name="i-heroicons-information-circle" class="w-4 h-4" /> Per-agent email isn't enabled for this org yet.
        </div>

        <div v-else class="rounded-2xl border border-[#E9E0D3] bg-white p-4">
            <div v-if="loading" class="flex items-center justify-center py-10 text-[#9a958c]">
                <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
            </div>

            <template v-else>
                <!-- delivery mode -->
                <h3 class="text-sm font-semibold text-[#1f2328] mb-2" style="font-family: 'Spectral', ui-serif, Georgia, serif">Delivery mode</h3>
                <div class="space-y-2 mb-4">
                    <label
                        v-for="opt in modeOptions"
                        :key="opt.value"
                        class="flex items-start gap-2 rounded-xl border p-2.5 transition-colors"
                        :class="[
                            form.mode === opt.value ? 'border-[#E8C9B5] bg-[#F6EFEA]' : 'border-[#E9E0D3]',
                            canEdit ? 'cursor-pointer hover:border-[#dcd9cf]' : 'opacity-70 cursor-default',
                        ]"
                    >
                        <input type="radio" :value="opt.value" v-model="form.mode" :disabled="!canEdit" class="mt-0.5 text-[#C2541E] focus:ring-[#C2541E]" />
                        <span>
                            <span class="block text-xs font-medium text-[#1f2328]">{{ opt.label }}</span>
                            <span class="block text-[11px] text-[#9a958c]">{{ opt.hint }}</span>
                        </span>
                    </label>
                </div>

                <!-- custom SMTP fields -->
                <div v-if="form.mode === 'custom'" class="rounded-xl border border-[#F0EEE6] bg-[#F9F6F0] p-4">
                    <div class="text-[11px] text-[#8A4527] bg-[#FBF4EF] border border-[#f0ddd0] rounded-lg px-3 py-2 mb-4 flex items-start gap-1.5">
                        <UIcon name="i-heroicons-exclamation-triangle" class="w-3.5 h-3.5 shrink-0 mt-0.5" />
                        <span>Agent SMTP sends only <span class="font-medium">this agent's</span> mail. Overrides global for this agent. Falls back to global if host left blank.</span>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-[11px] font-medium text-[#1f2328] mb-1">From name</label>
                            <UInput v-model="form.from_name" size="sm" placeholder="CRM Sales Agent" :disabled="!canEdit" />
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-[#1f2328] mb-1">From address</label>
                            <UInput v-model="form.from_address" size="sm" placeholder="crm@acme.com" :disabled="!canEdit" />
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Host</label>
                            <UInput v-model="form.host" size="sm" placeholder="smtp.acme.com" :disabled="!canEdit" />
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Port</label>
                            <UInput v-model.number="form.port" type="number" size="sm" placeholder="587" :disabled="!canEdit" />
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Username <span class="text-[#9a958c]">(optional)</span></label>
                            <UInput v-model="form.username" size="sm" :disabled="!canEdit" />
                        </div>
                        <div>
                            <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Password <span class="text-[#9a958c]">(optional)</span></label>
                            <UInput v-model="form.password" type="password" size="sm" :placeholder="passwordSet ? '•••••••• (saved)' : ''" :disabled="!canEdit" />
                        </div>
                    </div>
                    <p class="text-[11px] text-[#9a958c] mt-1.5">Leave username &amp; password empty for an open relay that doesn't require authentication.</p>

                    <div class="mt-3">
                        <label class="block text-[11px] font-medium text-[#1f2328] mb-1">Security</label>
                        <select
                            v-model="form.security"
                            :disabled="!canEdit"
                            class="w-full text-xs text-[#1f2328] bg-white border border-[#E9E0D3] rounded-lg px-3 py-2 focus:outline-none focus:border-[#C2541E] disabled:opacity-60"
                        >
                            <option value="starttls">STARTTLS (587)</option>
                            <option value="ssl">SSL/TLS (465)</option>
                            <option value="none">None (25)</option>
                        </select>
                    </div>

                    <label class="flex items-center gap-2 mt-3 cursor-pointer">
                        <UToggle v-model="form.validate_certs" :disabled="!canEdit" />
                        <span class="text-[11px] text-[#1f2328]">Validate TLS certificates <span class="text-[#9a958c]">— turn off for self-signed / internal-CA relays</span></span>
                    </label>
                </div>

                <div v-if="canEdit" class="flex items-center gap-2 mt-4">
                    <UButton color="orange" size="sm" :loading="saving" @click="save">Save</UButton>
                    <UButton v-if="form.mode === 'custom'" color="gray" variant="outline" size="sm" :loading="testing" @click="test">Send test connection</UButton>
                    <span v-if="testResult" class="text-[11px]" :class="testOk ? 'text-[#2f7a52]' : 'text-red-600'">{{ testResult }}</span>
                </div>
            </template>
        </div>
    </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{
    studioId: string
    canEdit: boolean
}>()

const { t } = useI18n()
const toast = useToast()

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const unavailable = ref(false)
const passwordSet = ref(false)
const testResult = ref('')
const testOk = ref(false)

const modeOptions = [
    { value: 'global', label: 'Use global default', hint: 'Inherit the org / dash-config SMTP. No setup needed.' },
    { value: 'custom', label: 'Custom SMTP for this agent', hint: 'Send this agent\'s mail from your own server.' },
]

const form = reactive({
    mode: 'global',
    host: '',
    port: 587,
    security: 'starttls',
    username: '',
    password: '',
    from_address: '',
    from_name: '',
    validate_certs: true,
})

const load = async () => {
    loading.value = true
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/smtp`, { method: 'GET' })
        if (error?.value) throw error.value
        const d = data.value || {}
        form.mode = d.mode || 'global'
        form.host = d.host || ''
        form.port = d.port || 587
        form.security = d.security || 'starttls'
        form.username = d.username || ''
        form.from_address = d.from_address || ''
        form.from_name = d.from_name || ''
        form.validate_certs = d.validate_certs !== false
        passwordSet.value = !!d.password_set
        unavailable.value = false
    } catch (e: any) {
        if (e?.statusCode === 404 || e?.status === 404) unavailable.value = true
        else console.error('Failed to load agent SMTP:', e)
    } finally {
        loading.value = false
    }
}

const save = async () => {
    saving.value = true
    testResult.value = ''
    try {
        const body: any = {
            mode: form.mode,
            host: form.host || null,
            port: form.port || 587,
            security: form.security,
            username: form.username || null,
            from_address: form.from_address || null,
            from_name: form.from_name || null,
            validate_certs: form.validate_certs,
        }
        // Only send password when the user typed a new one.
        if (form.password) body.password = form.password
        const { error } = await useMyFetch(`/studios/${props.studioId}/smtp`, { method: 'PUT', body })
        if (error?.value) throw error.value
        form.password = ''
        await load()
        toast.add({ title: 'Email settings saved', color: 'green', icon: 'i-heroicons-check-circle' })
    } catch (e: any) {
        console.error('Failed to save agent SMTP:', e)
        toast.add({ title: e?.data?.detail || t('studio.actionFailed') || 'Action failed', color: 'red' })
    } finally {
        saving.value = false
    }
}

const test = async () => {
    testing.value = true
    testResult.value = ''
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/smtp/test`, { method: 'POST' })
        if (error?.value) throw error.value
        const r = data.value || {}
        testOk.value = !!r.success
        testResult.value = r.success ? 'Connection OK' : (r.smtp || 'Failed')
    } catch (e: any) {
        testOk.value = false
        testResult.value = 'Test failed'
    } finally {
        testing.value = false
    }
}

onMounted(load)
</script>
