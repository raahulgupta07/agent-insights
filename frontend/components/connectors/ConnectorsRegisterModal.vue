<template>
  <div
    v-if="modelValue && template"
    class="fixed inset-0 z-[80] flex items-center justify-center bg-black/40 p-4"
    @click.self="close"
  >
    <div class="w-full max-w-md rounded-xl border border-[#E9E0D3] bg-white shadow-xl">
      <!-- Header -->
      <div class="flex items-start justify-between gap-3 border-b border-[#E9E0D3] px-5 py-4">
        <div class="min-w-0">
          <h2
            class="text-lg font-semibold text-[#211B14] truncate"
            style="font-family: 'Spectral', ui-serif, Georgia, serif"
          >Connect “{{ template.name }}”</h2>
          <p class="mt-0.5 text-[11px] text-[#6b6b6b] leading-relaxed">
            Sign in with your own account. Only the data your account can access is synced — privately to you.
          </p>
        </div>
        <button
          type="button"
          class="shrink-0 text-[#9a958c] hover:text-[#211B14]"
          :disabled="submitting"
          @click="close"
        >
          <UIcon name="heroicons-x-mark" class="h-5 w-5" />
        </button>
      </div>

      <!-- Body: CONNECTED — confirm identity + consent + explicit sync (journey v2) -->
      <div v-if="connectedStep" class="px-5 py-5 space-y-3.5">
        <template v-if="!syncing">
          <div class="flex items-center gap-3 rounded-xl border border-[#d4e3d4] bg-[#ECF1EC] px-3.5 py-3">
            <span class="w-9 h-9 rounded-full bg-[#2F6F4F] text-white grid place-items-center text-sm font-semibold shrink-0">{{ (connectedEmail[0] || 'U').toUpperCase() }}</span>
            <div class="min-w-0">
              <div class="text-[13px] font-semibold text-[#211B14]">Connected as</div>
              <div class="text-[12px] text-[#4a4034] truncate">{{ connectedEmail || 'your account' }}</div>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <span class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[#ECF1EC] text-[#2F6F4F] border border-[#d4e3d4]">● Sign-in verified</span>
            <span v-if="!wasMfa" class="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded-full bg-[#E4F0F4] text-[#1F6F8B] border border-[#cfe2e8]">⚡ instant</span>
          </div>
          <p class="text-[11px] text-[#9a958c] leading-relaxed">We'll import only the reports &amp; datasets your account can query. Confirm to continue:</p>
          <label class="flex items-start gap-2.5 rounded-xl border border-[#E9E0D3] bg-white px-3 py-2.5 cursor-pointer hover:border-[#D8CFC0]">
            <input type="checkbox" v-model="consent" class="mt-0.5 h-4 w-4 accent-[#C2541E]" />
            <span class="text-[12px] text-[#4a4034] leading-relaxed"><b>I agree</b> to sync the Power BI reports &amp; datasets <b>my account has access to</b>. Only data I can query is imported.</span>
          </label>
          <div class="flex items-center justify-end gap-2 pt-0.5">
            <button type="button" class="rounded-lg px-3 py-1.5 text-sm text-[#6b6b6b] hover:text-[#211B14]" @click="forceClose">Later</button>
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-lg bg-[#C2541E] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#A8330F] transition-colors disabled:opacity-50"
              :disabled="!consent"
              @click="startSync"
            >Sync my data →</button>
          </div>
        </template>
        <div v-else class="flex items-center gap-2.5 py-4 text-sm text-[#211B14]">
          <Spinner class="h-4 w-4 animate-spin text-[#C2541E]" /> Starting your sync…
        </div>
      </div>

      <!-- Body: PROGRESS checklist (while connecting/syncing) -->
      <div v-else-if="submitting && !mfaStep" class="px-5 py-5 space-y-4">
        <p class="text-sm font-medium text-[#211B14]">Setting up your data agent…</p>
        <ul class="space-y-2.5">
          <li v-for="(s, i) in steps" :key="s.key" class="flex items-center gap-2.5 text-sm">
            <span class="w-4 h-4 flex items-center justify-center shrink-0">
              <UIcon v-if="i < stepIdx" name="heroicons-check-circle-solid" class="h-4 w-4 text-[#3f9e6a]" />
              <Spinner v-else-if="i === stepIdx" class="h-3.5 w-3.5 animate-spin text-[#C2541E]" />
              <span v-else class="h-2 w-2 rounded-full bg-[#D8CFC0]"></span>
            </span>
            <span
              :class="i < stepIdx
                ? 'text-[#6b6b6b]'
                : i === stepIdx ? 'text-[#211B14] font-medium cai-shimmer' : 'text-[#B3AB9E]'"
            >{{ s.label }}</span>
          </li>
        </ul>
        <div class="flex items-center gap-2.5 pt-0.5">
          <div class="flex-1 h-1 rounded-full bg-[#EDE7DC] overflow-hidden">
            <div class="h-full w-1/3 rounded-full bg-[#C2541E]/70 cai-indeterminate"></div>
          </div>
          <span class="text-[11px] tabular-nums text-[#9a958c]">{{ mmss }}</span>
        </div>
        <p class="text-[11px] text-[#9a958c] leading-relaxed">This can take a moment while we sync every table your account can see.</p>
        <div class="flex justify-end">
          <button type="button" class="text-xs text-[#9a958c] hover:text-[#211B14]" @click="forceClose">Cancel</button>
        </div>
      </div>

      <!-- Body: password form -->
      <form v-else-if="!mfaStep" class="px-5 py-4 space-y-3" @submit.prevent="submit">
        <div>
          <label class="mb-1 block text-xs font-medium text-gray-700">Email</label>
          <input
            v-model="email"
            type="email"
            autocomplete="username"
            placeholder="you@company.com"
            class="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-[#C2541E] focus:outline-none"
          />
        </div>
        <div>
          <label class="mb-1 block text-xs font-medium text-gray-700">Password</label>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            placeholder="••••••••"
            class="block w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-[#C2541E] focus:outline-none"
          />
        </div>

        <p v-if="isPowerBiUser" class="text-[11px] text-[#8a6d3b] bg-[#FBF3E2] border border-[#ECDCBB] rounded-md px-2.5 py-2 leading-relaxed">
          If your Power BI account uses multi-factor authentication, email + password may not be enough — a device-code sign-in option is available after connecting.
        </p>

        <!-- Error -->
        <p v-if="errorMessage" class="text-[12px] text-red-600 bg-red-50 border border-red-200 rounded-md px-2.5 py-2">
          {{ errorMessage }}
        </p>

        <!-- Actions -->
        <div class="flex items-center justify-end gap-2 pt-1">
          <button
            type="button"
            class="rounded-lg px-3 py-1.5 text-sm text-[#6b6b6b] hover:text-[#211B14]"
            @click="close"
          >Cancel</button>
          <button
            type="submit"
            class="inline-flex items-center gap-2 rounded-lg bg-[#C2541E] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#A8330F] transition-colors disabled:opacity-60"
            :disabled="!canSubmit"
          >Connect with my account</button>
        </div>
      </form>

      <!-- Body: device-code (MFA) view -->
      <div v-else class="px-5 py-4 space-y-3">
        <p class="text-[12px] text-[#6b6b6b] leading-relaxed">
          Your account uses multi-factor sign-in. Finish in your browser:
        </p>

        <!-- Error in device view -->
        <template v-if="deviceError">
          <p class="text-[12px] text-red-600 bg-red-50 border border-red-200 rounded-md px-2.5 py-2">
            {{ deviceError }}
          </p>
          <div class="flex items-center justify-end pt-1">
            <button
              type="button"
              class="rounded-lg bg-[#C2541E] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#A8330F] transition-colors"
              @click="startOver"
            >Start over</button>
          </div>
        </template>

        <template v-else>
          <ol class="text-sm text-[#211B14] space-y-2">
            <li>
              1. Open
              <a :href="verificationUri" target="_blank" class="text-[#A8330F] font-semibold underline">{{ verificationUri }}</a>
            </li>
            <li>2. Enter this code:</li>
          </ol>
          <div class="font-mono text-2xl font-bold tracking-widest text-center text-[#A8330F] bg-[#FBF3EB] border border-dashed border-[#C2541E] rounded-xl py-4 select-all">
            {{ userCode }}
          </div>
          <div class="flex items-center gap-2 text-xs text-[#6b6b6b] bg-[#F6F1EA] rounded-lg p-2.5">
            <Spinner class="h-3.5 w-3.5 animate-spin" /> Waiting for you to approve…
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
import Spinner from '~/components/Spinner.vue'

const props = defineProps<{
  modelValue: boolean
  template: any | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'registered', dataSource: any): void
}>()

const email = ref('')
const password = ref('')
const submitting = ref(false)
const errorMessage = ref('')

// ---- journey v2: connected → consent → explicit sync ----
const connectedStep = ref(false)
const connectedEmail = ref('')
const connectedDsId = ref('')
const consent = ref(false)
const syncing = ref(false)
const wasMfa = ref(false)

function enterConnected(r: any, viaMfa: boolean) {
  stopProgress()
  stopPoll()
  submitting.value = false
  mfaStep.value = false
  wasMfa.value = viaMfa
  connectedEmail.value = r?.ms_account_email || email.value.trim()
  connectedDsId.value = r?.data_source_id || ''
  consent.value = false
  syncing.value = false
  connectedStep.value = true
}

async function startSync() {
  if (!consent.value || !connectedDsId.value) return
  syncing.value = true
  try {
    await useMyFetch(`/connectors/${connectedDsId.value}/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    })
  } catch (e) { /* fire-and-forget; the agent page shows the live sync log */ }
  emit('registered', { id: connectedDsId.value })
  connectedStep.value = false
  emit('update:modelValue', false)
}

// ---- progress checklist (while /connect is in flight) ----
// One POST can't stream sub-steps, so these are time-paced to the real phases:
// sign-in returns fast (~1-2s), then the server seeds every table (slow). We flip
// sign-in to done after a short delay and leave "sync" spinning until the call
// resolves. "Learn" stays pending (auto-learn runs in the background after connect).
const steps = computed(() => [
  { key: 'signin', label: `Signing in as ${email.value.trim() || 'your account'}` },
  { key: 'sync', label: 'Syncing your tables' },
  { key: 'learn', label: 'Learning your data' },
])
const stepIdx = ref(0)
const elapsed = ref(0)
const mmss = computed(() => {
  const m = Math.floor(elapsed.value / 60)
  const s = elapsed.value % 60
  return `${m}:${s.toString().padStart(2, '0')}`
})
let elapsedTimer: ReturnType<typeof setInterval> | null = null
let signinTimer: ReturnType<typeof setTimeout> | null = null

function startProgress() {
  stepIdx.value = 0
  elapsed.value = 0
  elapsedTimer = setInterval(() => { elapsed.value += 1 }, 1000)
  // sign-in usually done within ~1.6s → advance to the (slow) sync step
  signinTimer = setTimeout(() => { if (stepIdx.value < 1) stepIdx.value = 1 }, 1600)
}
function stopProgress() {
  if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null }
  if (signinTimer) { clearTimeout(signinTimer); signinTimer = null }
}
function forceClose() {
  // Leaving mid-connect: the server may finish the clone anyway; just release the UI.
  stopProgress()
  submitting.value = false
  stopPoll()
  emit('update:modelValue', false)
}

// device-code (MFA) state
const mfaStep = ref(false)
const userCode = ref('')
const verificationUri = ref('')
const deviceCode = ref('')
const deviceError = ref('')
let pollHandle: ReturnType<typeof setTimeout> | null = null
let pollInterval = 5000

const isPowerBiUser = computed(() => props.template?.type === 'powerbi_user')

// auth_mode: powerbi_user signs in with userpass; otherwise fall back to the
// template's first allowed user auth mode. (used only in the 404 fallback path)
const authMode = computed<string>(() => {
  if (isPowerBiUser.value) return 'userpass'
  return props.template?.allowed_user_auth_modes?.[0] || 'userpass'
})

const canSubmit = computed(() => !!email.value.trim() && !!password.value)

function stopPoll() {
  if (pollHandle) {
    clearTimeout(pollHandle)
    pollHandle = null
  }
}

function resetDevice() {
  mfaStep.value = false
  userCode.value = ''
  verificationUri.value = ''
  deviceCode.value = ''
  deviceError.value = ''
  stopPoll()
}

// Reset the form whenever a new template is opened (or the modal closes).
watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      email.value = ''
      password.value = ''
      errorMessage.value = ''
      submitting.value = false
      connectedStep.value = false
      connectedEmail.value = ''
      connectedDsId.value = ''
      consent.value = false
      syncing.value = false
      resetDevice()
    } else {
      stopPoll()
    }
  }
)

function close() {
  if (submitting.value) return
  stopPoll()
  emit('update:modelValue', false)
}

function startOver() {
  resetDevice()
  errorMessage.value = ''
}

async function submit() {
  if (submitting.value || !canSubmit.value || !props.template?.id) return
  submitting.value = true
  errorMessage.value = ''
  startProgress()
  try {
    const res = await useMyFetch(`/connectors/${props.template.id}/connect`, {
      method: 'POST',
      body: JSON.stringify({ email: email.value.trim(), password: password.value }),
      headers: { 'Content-Type': 'application/json' },
    })

    const err = (res.error as any)?.value
    if (err) {
      // Graceful fallback: adaptive-connect flag off on the server → old /register path.
      const code = err?.statusCode ?? err?.status
      if (code === 404) {
        await legacyRegister()
        return
      }
      errorMessage.value = err?.data?.detail || 'Failed to connect. Please check your credentials.'
      return
    }

    const r = (res.data as any)?.value || {}
    if (r.status === 'connected') {
      if (r.needs_sync) { enterConnected(r, false); return }   // journey v2: consent gate
      emit('registered', { id: r.data_source_id })
      close()
      return
    }
    if (r.status === 'mfa_required') {
      // Switch to the device-code view and start polling.
      userCode.value = r.user_code || ''
      verificationUri.value = r.verification_uri || ''
      deviceCode.value = r.device_code || ''
      deviceError.value = ''
      pollInterval = (r.interval || 5) * 1000
      mfaStep.value = true
      schedulePoll()
      return
    }
    if (r.status === 'error') {
      errorMessage.value = r.error || 'Failed to connect. Please check your credentials.'
      return
    }
    errorMessage.value = 'Unexpected response from server.'
  } catch (e: any) {
    errorMessage.value = e?.data?.detail || e?.message || 'Failed to connect. Please check your credentials.'
  } finally {
    stopProgress()
    submitting.value = false
  }
}

// Fallback (server has no /connect endpoint): original /register behavior.
async function legacyRegister() {
  const body = {
    auth_mode: authMode.value,
    credentials: {
      username: email.value.trim(),
      password: password.value,
    } as Record<string, string>,
  }
  const res = await useMyFetch(`/connectors/${props.template.id}/register`, {
    method: 'POST',
    body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json' },
  })
  if ((res.error as any)?.value) {
    errorMessage.value =
      (res.error as any).value?.data?.detail || 'Failed to connect. Please check your credentials.'
    return
  }
  const dataSource = (res.data as any)?.value
  emit('registered', dataSource)
}

function schedulePoll() {
  pollHandle = setTimeout(poll, pollInterval)
}

async function poll() {
  if (!mfaStep.value) return
  try {
    const res = await useMyFetch(`/connectors/${props.template?.id}/device-code/poll`, {
      method: 'POST',
      body: JSON.stringify({ device_code: deviceCode.value }),
      headers: { 'Content-Type': 'application/json' },
    })
    if ((res.error as any)?.value) throw (res.error as any).value
    const r = (res.data as any)?.value || {}
    if (r.status === 'pending') {
      if (r.slow_down) pollInterval += 5000
      schedulePoll()
      return
    }
    if (r.status === 'success') {
      stopPoll()
      if (r.needs_sync) { enterConnected(r, true); return }   // journey v2: consent gate
      emit('registered', { id: r.data_source_id })
      close()
      return
    }
    deviceError.value = r.error || 'Sign-in failed. Please start over.'
    stopPoll()
  } catch (e: any) {
    deviceError.value = e?.data?.detail || e?.message || 'Sign-in failed. Please start over.'
    stopPoll()
  }
}

onBeforeUnmount(() => { stopPoll(); stopProgress() })
</script>

<style scoped>
/* active-step text shimmer */
.cai-shimmer {
  background: linear-gradient(90deg, #211B14 0%, #211B14 35%, #C2541E 50%, #211B14 65%, #211B14 100%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: cai-shimmer 1.8s linear infinite;
}
@keyframes cai-shimmer { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }

/* indeterminate progress sweep */
.cai-indeterminate { animation: cai-sweep 1.3s ease-in-out infinite; }
@keyframes cai-sweep {
  0% { transform: translateX(-120%) }
  100% { transform: translateX(320%) }
}
</style>
