<template>
  <div v-if="pageLoaded" class="min-h-screen w-full bg-[#FBFAF6] flex flex-col">

    <!-- ============ top brand bar ============ -->
    <header class="flex items-center justify-between px-6 sm:px-10 lg:px-14 py-5">
      <div class="flex items-center gap-2.5">
        <div class="h-10 w-10 rounded-[11px] bg-white border border-[#E7E5DD] flex items-center justify-center shadow-[0_4px_12px_rgba(194,104,63,.16)]">
          <img src="/assets/logo-mark.png" alt="City Agent Insights" class="h-9 w-9 object-contain" />
        </div>
        <div class="leading-tight">
          <div class="text-[15px] font-semibold tracking-tight text-[#1f2328]">City Agent <span class="text-[#c2683f]">Insights</span></div>
          <div class="text-[10px] uppercase tracking-[2px] text-[#9a958c] mt-0.5">Data Intelligence</div>
        </div>
      </div>
      <span class="inline-flex items-center gap-2 text-[12px] font-medium text-[#6b6b6b] bg-white border border-[#E7E5DD] px-3 py-1.5 rounded-full">
        <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>v{{ hybridVersion }} · <span class="text-[#9a958c]">{{ envLabel }}</span>
      </span>
    </header>

    <!-- ============ split body ============ -->
    <div class="flex-1 grid lg:grid-cols-2 gap-8 lg:gap-12 px-6 sm:px-10 lg:px-14 pb-8 items-center max-w-[1500px] w-full mx-auto">

      <!-- ---------- LEFT: greeting + form ---------- -->
      <div class="w-full max-w-[460px] mx-auto lg:mx-0">
        <h1 class="text-[34px] sm:text-[40px] leading-[1.08] font-semibold tracking-[-0.5px] text-[#1f2328]" style="font-family: ui-serif, Georgia, 'Times New Roman', serif">
          {{ greeting }},<br>sign in to City Agent Insights
        </h1>
        <p class="mt-4 text-[15px] text-[#6b6b6b] leading-relaxed max-w-[400px]">Your data intelligence — answered with the source query.</p>

        <!-- live stat line -->
        <div class="mt-4 flex items-center gap-2 text-[13px] text-[#6b6b6b]">
          <span class="h-2 w-2 rounded-full bg-emerald-500"></span>
          <span><b class="font-semibold text-[#1f2328]">4</b> sources · <b class="font-semibold text-[#1f2328]">11</b> tables · <b class="font-semibold text-[#1f2328]">67</b> columns · data 2026-06-20</span>
        </div>

        <p v-if="error_message" v-html="error_message" class="mt-5 text-red-500 text-sm whitespace-pre-line"></p>

        <!-- form card -->
        <div class="mt-7 bg-white border border-[#E7E5DD] rounded-[18px] p-6 sm:p-7 shadow-[0_2px_10px_-6px_rgba(60,40,20,.08)]">
          <form @submit.prevent="signInWithCredentials()" v-if="authMode !== 'sso_only' || localOverride">
            <!-- email -->
            <input type="text" id="email" v-model="email" :placeholder="$t('auth.email')" autocomplete="email"
              class="w-full bg-white border border-[#E7E5DD] rounded-xl px-4 py-3.5 text-sm text-[#1f2328] placeholder:text-[#9a958c] transition focus:outline-none focus:border-[#c2683f] focus:ring-[3.5px] focus:ring-[#c2683f]/[.13]" />

            <!-- password -->
            <div class="relative mt-3">
              <input :type="showPw ? 'text' : 'password'" id="password" v-model="password" :placeholder="$t('auth.password')" autocomplete="current-password"
                class="w-full bg-white border border-[#E7E5DD] rounded-xl px-4 pr-16 py-3.5 text-sm text-[#1f2328] placeholder:text-[#9a958c] transition focus:outline-none focus:border-[#c2683f] focus:ring-[3.5px] focus:ring-[#c2683f]/[.13]" />
              <button type="button" @click="showPw = !showPw" class="absolute right-3.5 top-1/2 -translate-y-1/2 text-[13px] font-medium text-[#6b6b6b] hover:text-[#c2683f] cursor-pointer">
                {{ showPw ? 'Hide' : 'Show' }}
              </button>
            </div>

            <!-- remember + forgot -->
            <div class="flex items-center justify-between mt-4 mb-5">
              <label class="flex items-center gap-2.5 cursor-pointer select-none">
                <button type="button" role="switch" :aria-checked="rememberMe" @click="rememberMe = !rememberMe"
                  class="h-[18px] w-[18px] rounded-[5px] border flex items-center justify-center transition-colors shrink-0"
                  :class="rememberMe ? 'bg-[#c2683f] border-[#c2683f]' : 'bg-white border-[#d9d4ca]'">
                  <UIcon v-if="rememberMe" name="i-heroicons-check" class="w-3 h-3 text-white" />
                </button>
                <span class="text-[13px] text-[#46413a]">Remember me on this device</span>
              </label>
              <NuxtLink v-if="smtpEnabled" to="/users/forgot-password" class="text-[13px] font-medium text-[#c2683f] hover:text-[#a8542f]">
                {{ $t('auth.forgotPassword') }}
              </NuxtLink>
            </div>

            <!-- primary: continue with email -->
            <button type="submit" :disabled="isSubmitting"
              class="w-full bg-[#191613] hover:bg-black text-white rounded-xl py-3.5 text-[14.5px] font-semibold flex items-center justify-center gap-2 transition active:translate-y-px disabled:bg-gray-400 disabled:cursor-not-allowed cursor-pointer">
              <template v-if="isSubmitting"><Spinner class="h-5 w-5 me-1" />{{ $t('auth.loggingIn') }}</template>
              <template v-else>Continue with email</template>
            </button>
          </form>

          <!-- SSO / OIDC -->
          <div v-if="authMode !== 'local_only' && (googleSignIn || oidcProviders.length)">
            <!-- OR divider only when local form is also shown -->
            <div class="relative my-4" v-if="authMode !== 'sso_only' || localOverride">
              <div class="absolute inset-0 flex items-center"><div class="w-full border-t border-[#E7E5DD]"></div></div>
              <div class="relative flex justify-center"><span class="px-3 bg-white text-[#9a958c] text-[12px] font-medium tracking-wide">OR</span></div>
            </div>

            <!-- Microsoft / generic OIDC providers (light cream button) -->
            <div class="space-y-2.5" v-if="oidcProviders.length">
              <button v-for="p in oidcProviders" :key="p.name" @click="() => signInWithProvider(p.name)" type="button" :disabled="loadingProvider !== null"
                class="w-full flex items-center justify-center gap-2.5 px-4 py-3.5 bg-[#F4F1EA] hover:bg-[#ece7dc] border border-[#E7E5DD] rounded-xl text-[14px] font-semibold text-[#46413a] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors">
                <template v-if="loadingProvider === p.name"><Spinner class="h-5 w-5" />{{ $t('auth.redirecting') }}</template>
                <template v-else>
                  <svg v-if="/microsoft|azure|entra/i.test(p.name)" viewBox="0 0 24 24" class="w-[18px] h-[18px]"><path fill="#F25022" d="M1 1h10v10H1z"/><path fill="#7FBA00" d="M13 1h10v10H13z"/><path fill="#00A4EF" d="M1 13h10v10H1z"/><path fill="#FFB900" d="M13 13h10v10H13z"/></svg>
                  {{ /microsoft|azure|entra/i.test(p.name) ? 'Continue with Microsoft' : $t('auth.signInWithProvider', { provider: p.name }) }}
                </template>
              </button>
            </div>

            <!-- Google (light cream button) -->
            <div class="mt-2.5" v-if="googleSignIn">
              <button @click="signInWithGoogle" type="button" :disabled="loadingProvider !== null"
                class="w-full flex items-center justify-center gap-2.5 px-4 py-3.5 bg-[#F4F1EA] hover:bg-[#ece7dc] border border-[#E7E5DD] rounded-xl text-[14px] font-semibold text-[#46413a] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors">
                <template v-if="loadingProvider === 'google'"><Spinner class="h-5 w-5" />{{ $t('auth.redirecting') }}</template>
                <template v-else><img src="/llm_providers_icons/google-icon.png" alt="Google logo" class="h-5 w-5" />Continue with Google</template>
              </button>
            </div>
          </div>

          <!-- Admin sign-in (reveal local form when SSO-only) -->
          <div class="mt-5 text-center" v-if="authMode === 'sso_only' && !localOverride">
            <NuxtLink to="/users/sign-in?local=true" class="text-[13px] font-medium text-[#6b6b6b] hover:text-[#1f2328] inline-flex items-center gap-1">
              Admin sign-in <UIcon name="i-heroicons-arrow-right" class="w-3.5 h-3.5" />
            </NuxtLink>
          </div>
        </div>

      </div>

      <!-- ---------- RIGHT: dark animated agent panel (desktop only) ---------- -->
      <div class="hidden lg:block">
        <div class="dark-panel a-float relative w-full max-w-[620px] rounded-[24px] overflow-hidden border border-[#2a2622] p-7"
          style="background:#1b1816">
          <!-- grid texture -->
          <div class="pointer-events-none absolute inset-0 opacity-[0.5]"
            style="background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);background-size:34px 34px"></div>
          <!-- coral glow -->
          <div class="pointer-events-none absolute -top-24 -left-24 w-72 h-72 rounded-full"
            style="background:radial-gradient(circle,rgba(194,104,63,.28),transparent 70%)"></div>

          <div class="relative">
            <!-- status -->
            <div class="flex items-center gap-2 text-[12.5px] text-[#b8b0a6] mb-6">
              <span class="live-dot h-2 w-2 rounded-full bg-[#c2683f] block"></span>
              live · answering from your data
            </div>

            <!-- question bubble (dark) -->
            <div class="a-bubble inline-flex max-w-[80%] bg-[#2a2622] text-[#e7e2da] text-[13.5px] px-4 py-2.5 rounded-2xl rounded-bl-[6px] mb-4">
              Top 5 artists by revenue this quarter?
            </div>

            <!-- answer bubble (coral, right) -->
            <div class="a-answer flex justify-end mb-4">
              <div class="max-w-[86%] bg-[#c2683f] text-white text-[13.5px] leading-relaxed px-4 py-3 rounded-2xl rounded-br-[6px] shadow-[0_10px_30px_-12px_rgba(194,104,63,.6)]">
                Rock leads → <b>+$11.2K</b>. Top 5 charted from
                <span class="inline-flex items-center px-1.5 py-0.5 rounded-md bg-white/20 text-[12px] font-semibold mx-0.5">invoice_line</span> ⋈ track.
              </div>
            </div>

            <!-- typing dots -->
            <div class="a-typing flex items-center gap-1.5 bg-[#232019] w-fit px-3.5 py-2.5 rounded-xl mb-6">
              <span class="dot h-1.5 w-1.5 rounded-full bg-[#7a736a] block"></span>
              <span class="dot h-1.5 w-1.5 rounded-full bg-[#7a736a] block"></span>
              <span class="dot h-1.5 w-1.5 rounded-full bg-[#7a736a] block"></span>
            </div>

            <!-- capability tiles (2-col) -->
            <div class="grid grid-cols-2 gap-3 mb-6">
              <div v-for="(tile, i) in tiles" :key="tile.l"
                class="a-tile flex items-center gap-3 px-4 py-3.5 rounded-xl transition-colors"
                :style="{ animationDelay: (0.9 + i * 0.08) + 's' }"
                :class="i === 0 ? 'bg-[#2a211b] ring-1 ring-[#c2683f] shadow-[0_8px_24px_-14px_rgba(194,104,63,.7)]' : 'bg-[#232019] border border-[#2f2b26] hover:border-[#46413a]'">
                <span class="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                  :class="i === 0 ? 'bg-[#c2683f]/20 text-[#e9a07a]' : 'bg-[#2c2823] text-[#b8b0a6]'">
                  <UIcon :name="tile.icon" class="w-4 h-4" />
                </span>
                <span class="text-[13px] font-medium" :class="i === 0 ? 'text-[#f0e9e2]' : 'text-[#c9c1b7]'">{{ tile.l }}</span>
              </div>
            </div>

            <!-- stat footer -->
            <div class="flex items-center gap-5 text-[12.5px] text-[#8a8278] border-t border-[#2a2622] pt-4">
              <span><b class="text-[#e7e2da] font-semibold">4</b> sources</span>
              <span><b class="text-[#e7e2da] font-semibold">11</b> tables</span>
              <span><b class="text-[#e7e2da] font-semibold">SSO</b> ready</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- footer -->
    <footer class="text-center text-[12px] text-[#9a958c] py-5">© 2026 City Agent Insights · Data Intelligence &amp; Analytics</footer>
  </div>
  <div v-else class="flex h-screen items-center justify-center bg-[#FBFAF6]"><Spinner class="h-6 w-6" /></div>
</template>


<script setup lang="ts">

import qs from 'qs';

import { ref, computed, onMounted } from 'vue';
import Spinner from '~/components/Spinner.vue';

const { t } = useI18n()
const { rawToken } = useAuthState()
const { fetchOrganization } = useOrganization()
const route = useRoute()
const googleSignIn = ref(false)
const signupEnabled = ref(false)
const oidcProviders = ref<{ name: string; enabled: boolean }[]>([])
const loadingProvider = ref<string | null>(null)
const authMode = ref<'hybrid'|'local_only'|'sso_only'>('hybrid')
const smtpEnabled = ref(false)
const isSubmitting = ref(false)
const rememberMe = ref(true)
const localOverride = computed(() => route.query.local === 'true')

// Version chip: real product version (VERSION_HYBRID) from /api/settings,
// with an env label derived from the host (localhost -> local, else prod).
const hybridVersion = ref('…')
const envLabel = computed(() => {
  if (import.meta.client) {
    const h = window.location.hostname
    if (h === 'localhost' || h === '127.0.0.1') return 'local'
  }
  return 'prod'
})

// Time-of-day greeting (client-only page, so local hour is correct).
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
})

definePageMeta({
  auth: {
    unauthenticatedOnly: true,
  },
  layout: 'users'
})

// Define reactive references for email and password
const email = ref('');
const password = ref('');
const showPw = ref(false);

// Static decorative data for the right-side agent panel
const tiles = [
  { l: 'Ask your data', icon: 'i-heroicons-magnifying-glass' },
  { l: 'Build a chart', icon: 'i-heroicons-chart-bar' },
  { l: 'Connect source', icon: 'i-heroicons-circle-stack' },
  { l: 'Run SQL', icon: 'i-heroicons-command-line' },
  { l: 'Teach a metric', icon: 'i-heroicons-academic-cap' },
  { l: 'Schedule report', icon: 'i-heroicons-clock' },
];

const error_message = ref('')
// Extract the signIn function from useAuth
const { signIn, getSession } = useAuth();

// Only honor redirects to same-origin paths to avoid open-redirect bugs
function safeRedirectTarget(value: unknown): string | null {
  if (typeof value !== 'string' || !value) return null
  if (!value.startsWith('/') || value.startsWith('//')) return null
  return value
}

const OAUTH_REDIRECT_STORAGE_NAME = 'dash:postSignInRedirect'

// Helper to extract error message from server response
function extractErrorMessage(error: any, fallback: string): string {
  const data = error?.data
  if (!data) return fallback

  // Handle FastAPI validation errors (detail array)
  if (Array.isArray(data.detail)) {
    return data.detail.map((d: any) => d.msg || d.message || JSON.stringify(d)).join('\n')
  }
  // Handle simple detail string
  if (typeof data.detail === 'string') {
    return data.detail
  }
  // Handle message field
  if (data.message) {
    return data.message
  }
  return fallback
}
const pageLoaded = ref(false)

// Add this code to handle URL parameters
onMounted(async () => {
  try {
    const settings = await $fetch('/api/settings')
    if (settings?.oidc_providers?.length) {
      oidcProviders.value = settings.oidc_providers.filter((p: any) => p.enabled)
    }
    if (settings?.auth?.mode) {
      authMode.value = settings.auth.mode
    }
    smtpEnabled.value = settings?.smtp_enabled ?? false
    googleSignIn.value = !!(settings as any)?.google_oauth?.enabled
    signupEnabled.value = !!(settings as any)?.signup_enabled
    const hv = (settings as any)?.hybrid_version
    if (hv) hybridVersion.value = hv
  } catch (_) {}
  const inviteError = route.query.error as string
  if (inviteError) {
    error_message.value = inviteError
  }
  const access_token = route.query.access_token as string
  const userEmail = route.query.email as string
  if (access_token) {
    rawToken.value = access_token
    await getSession({ force: true })
    // Check if the user has an organization (same as credentials login)
    const org = await fetchOrganization()
    if (!org || !org.id) {
      navigateTo('/organizations/new')
    } else {
      let pendingRedirect: string | null = null
      try {
        pendingRedirect = safeRedirectTarget(sessionStorage.getItem(OAUTH_REDIRECT_STORAGE_NAME))
        sessionStorage.removeItem(OAUTH_REDIRECT_STORAGE_NAME)
      } catch (_) {}
      navigateTo(pendingRedirect || '/')
    }
    return
  }
  pageLoaded.value = true
})


function persistRedirectForOAuth() {
  const target = safeRedirectTarget(route.query.redirect)
  try {
    if (target) {
      sessionStorage.setItem(OAUTH_REDIRECT_STORAGE_NAME, target)
    } else {
      sessionStorage.removeItem(OAUTH_REDIRECT_STORAGE_NAME)
    }
  } catch (_) {}
}

async function signInWithCredentials() {
  isSubmitting.value = true
  error_message.value = ''
  const route = useRoute();
  const redirectedFrom = safeRedirectTarget(route.query.redirect)

  const credentials = {
    username: email.value,
    password: password.value,
  };

  try {
    const response = await $fetch('/api/auth/jwt/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: qs.stringify(credentials),
    });


    if (response) {
      rawToken.value = response.access_token
      await getSession({ force: true })

      // Check if the user has an organization
      const org = await fetchOrganization();
      if (!org || !org.id) {
        navigateTo('/organizations/new');
      } else {
        if (redirectedFrom) {
          navigateTo(redirectedFrom);
        } else {
          navigateTo('/');
        }
      }
    }
    else {
      error_message.value = t('auth.invalidCredentials')
      isSubmitting.value = false
    }
  } catch (error: any) {
    error_message.value = extractErrorMessage(error, t('auth.invalidCredentials'))
    isSubmitting.value = false
  }
}

// Add new function for Google sign-in
async function signInWithGoogle() {
  try {
    loadingProvider.value = 'google'
    persistRedirectForOAuth()
    const response = await $fetch('/api/auth/google/authorize', {
      method: 'GET',
    });

    if (response.authorization_url) {
      window.location.href = response.authorization_url;
    }
  } catch (error) {
    error_message.value = t('auth.googleInitError')
    loadingProvider.value = null
  }
}

async function signInWithProvider(name: string) {
  try {
    loadingProvider.value = name
    persistRedirectForOAuth()
    const response = await $fetch(`/api/auth/${name}/authorize`, { method: 'GET' })
    if ((response as any)?.authorization_url) {
      window.location.href = (response as any).authorization_url
    }
  } catch (error) {
    error_message.value = t('auth.providerInitError', { provider: name })
    loadingProvider.value = null
  }
}
</script>

<style scoped>
/* ===== entrance (staged, once on mount) ===== */
@keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@keyframes pop  { from { opacity: 0; transform: translateY(8px) scale(.97); } to { opacity: 1; transform: translateY(0) scale(1); } }

.a-bubble { animation: pop  .5s cubic-bezier(.21,1,.32,1) .2s both; }
.a-answer { animation: rise .6s cubic-bezier(.21,1,.32,1) .55s both; }
.a-typing { animation: pop  .4s cubic-bezier(.21,1,.32,1) .85s both; }
.a-tile   { animation: pop  .45s cubic-bezier(.21,1,.32,1) both; }

/* ===== ambient loops ===== */
@keyframes float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }
.a-float { animation: float 7s ease-in-out 1.4s infinite; }

/* live dot pulse */
@keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(194,104,63,.5); } 70% { box-shadow: 0 0 0 7px rgba(194,104,63,0); } 100% { box-shadow: 0 0 0 0 rgba(194,104,63,0); } }
.live-dot { animation: pulse 2.2s ease-out infinite; }

/* typing dots bounce */
@keyframes dotb { 0%,60%,100% { transform: translateY(0); opacity: .5; } 30% { transform: translateY(-4px); opacity: 1; } }
.a-typing .dot { animation: dotb 1.3s ease-in-out infinite; }
.a-typing .dot:nth-child(2) { animation-delay: .18s; }
.a-typing .dot:nth-child(3) { animation-delay: .36s; }

@media (prefers-reduced-motion: reduce) {
  .a-bubble, .a-answer, .a-typing, .a-tile, .a-float, .live-dot, .a-typing .dot { animation: none !important; }
}
</style>
