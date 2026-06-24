<template>
  <div v-if="pageLoaded" class="h-screen w-full grid lg:grid-cols-[minmax(0,0.95fr)_1.05fr] bg-white">

    <!-- ============ LEFT — form ============ -->
    <div class="flex flex-col px-6 py-8 sm:px-12 lg:px-16">
      <!-- brand -->
      <div class="flex items-center gap-3">
        <div class="h-9 w-9 rounded-[10px] bg-gradient-to-br from-[#c2683f] to-[#dd9269] flex items-center justify-center shadow-[0_4px_12px_rgba(194,104,63,.28)]">
          <img src="/assets/logo-128.png" alt="CityAgent Analytics" class="h-6 w-6 rounded-md" />
        </div>
        <div class="leading-tight">
          <div class="text-[15px] font-semibold tracking-tight">CityAgent <span class="text-[#c2683f]">Analytics</span></div>
          <div class="text-[10px] uppercase tracking-[1.8px] text-gray-400 mt-0.5">Data Intelligence</div>
        </div>
        <span class="ml-auto inline-flex items-center gap-1.5 text-[11.5px] font-medium text-gray-500 bg-[#f7ede7] px-2.5 py-1 rounded-full">
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-500 ring-2 ring-emerald-500/15"></span>v2.4.0
        </span>
      </div>

      <!-- center -->
      <div class="flex-1 flex flex-col justify-center max-w-[392px] w-full mx-auto lg:mx-0">
        <h1 class="text-[32px] leading-[1.12] font-semibold tracking-[-1px] mb-3">Welcome back,<br>sign in to CityAgent</h1>
        <p class="text-[14.5px] text-gray-500 leading-relaxed mb-5 max-w-[340px]">Ask your data in plain language. Dashboards, metrics, and SQL — answered in seconds.</p>

        <!-- capability chips -->
        <div class="flex flex-wrap gap-2 mb-7">
          <span class="inline-flex items-center gap-1.5 text-[12px] text-[#5c574f] bg-[#faf8f5] border border-[#eae6df] px-2.5 py-1.5 rounded-lg">
            <UIcon name="i-heroicons-circle-stack" class="w-3.5 h-3.5 text-[#c2683f]" />4 sources
          </span>
          <span class="inline-flex items-center gap-1.5 text-[12px] text-[#5c574f] bg-[#faf8f5] border border-[#eae6df] px-2.5 py-1.5 rounded-lg">
            <UIcon name="i-heroicons-table-cells" class="w-3.5 h-3.5 text-[#c2683f]" />11 tables grounded
          </span>
          <span class="inline-flex items-center gap-1.5 text-[12px] text-[#5c574f] bg-[#faf8f5] border border-[#eae6df] px-2.5 py-1.5 rounded-lg">
            <UIcon name="i-heroicons-sparkles" class="w-3.5 h-3.5 text-[#c2683f]" />Dash Pro online
          </span>
        </div>

        <p v-if="error_message" v-html="error_message" class="mb-4 text-red-500 text-sm whitespace-pre-line"></p>

        <form @submit.prevent="signInWithCredentials()" v-if="authMode !== 'sso_only' || localOverride">
          <label for="email" class="block text-[12.5px] font-medium text-[#46413a] mb-1.5 ml-0.5">{{ $t('auth.email') }}</label>
          <div class="relative mb-4">
            <UIcon name="i-heroicons-envelope" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-[17px] h-[17px] text-gray-400" />
            <input type="text" id="email" v-model="email" :placeholder="$t('auth.email')" autocomplete="email"
              class="w-full bg-white border border-[#eae6df] rounded-xl pl-[42px] pr-3.5 py-3 text-sm text-[#191613] placeholder:text-gray-400 transition focus:outline-none focus:border-[#c2683f] focus:ring-[3.5px] focus:ring-[#c2683f]/[.13]" />
          </div>

          <label for="password" class="block text-[12.5px] font-medium text-[#46413a] mb-1.5 ml-0.5">{{ $t('auth.password') }}</label>
          <div class="relative mb-3">
            <UIcon name="i-heroicons-lock-closed" class="absolute left-3.5 top-1/2 -translate-y-1/2 w-[17px] h-[17px] text-gray-400" />
            <input :type="showPw ? 'text' : 'password'" id="password" v-model="password" :placeholder="$t('auth.password')" autocomplete="current-password"
              class="w-full bg-white border border-[#eae6df] rounded-xl pl-[42px] pr-16 py-3 text-sm text-[#191613] placeholder:text-gray-400 transition focus:outline-none focus:border-[#c2683f] focus:ring-[3.5px] focus:ring-[#c2683f]/[.13]" />
            <button type="button" @click="showPw = !showPw" class="absolute right-3 top-1/2 -translate-y-1/2 text-[12.5px] font-medium text-gray-500 hover:text-[#c2683f] cursor-pointer">
              {{ showPw ? 'Hide' : 'Show' }}
            </button>
          </div>

          <div class="flex items-center justify-between mt-0.5 mb-5">
            <span class="text-[12px] text-gray-400">Use your work account to continue</span>
            <NuxtLink v-if="smtpEnabled" to="/users/forgot-password" class="text-[13px] font-medium text-[#c2683f] hover:text-[#a8542f]">
              {{ $t('auth.forgotPassword') }}
            </NuxtLink>
          </div>

          <button type="submit" :disabled="isSubmitting"
            class="w-full bg-[#191613] hover:bg-black text-white rounded-xl py-3.5 text-[14.5px] font-medium flex items-center justify-center gap-2 transition active:translate-y-px disabled:bg-gray-400 disabled:cursor-not-allowed cursor-pointer">
            <template v-if="isSubmitting"><Spinner class="h-5 w-5 me-1" />{{ $t('auth.loggingIn') }}</template>
            <template v-else>
              {{ $t('auth.signIn') }}
              <UIcon name="i-heroicons-arrow-right" class="w-4 h-4" />
            </template>
          </button>
        </form>

        <!-- SSO / OIDC -->
        <div class="mt-4" v-if="authMode !== 'local_only' && (googleSignIn || oidcProviders.length)">
          <div class="relative my-3" v-if="authMode === 'hybrid'">
            <div class="absolute inset-0 flex items-center"><div class="w-full border-t border-[#eae6df]"></div></div>
            <div class="relative flex justify-center text-sm"><span class="px-2 bg-white text-gray-400 text-[12.5px]">{{ $t('auth.orContinueWith') }}</span></div>
          </div>
          <div class="mt-3" v-if="googleSignIn">
            <button @click="signInWithGoogle" type="button" :disabled="loadingProvider !== null"
              class="w-full flex items-center justify-center px-4 py-3 border border-[#eae6df] rounded-xl text-sm font-medium text-[#46413a] bg-white hover:bg-[#faf8f5] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors">
              <template v-if="loadingProvider === 'google'"><Spinner class="h-5 w-5 me-2" />{{ $t('auth.redirecting') }}</template>
              <template v-else><img src="/llm_providers_icons/google-icon.png" alt="Google logo" class="h-5 w-5 me-2" />{{ $t('auth.signInWithGoogle') }}</template>
            </button>
          </div>
          <div class="mt-3 space-y-2" v-if="oidcProviders.length">
            <button v-for="p in oidcProviders" :key="p.name" @click="() => signInWithProvider(p.name)" type="button" :disabled="loadingProvider !== null"
              class="w-full flex items-center justify-center px-4 py-3 border border-[#eae6df] rounded-xl text-sm font-medium text-[#46413a] bg-white hover:bg-[#faf8f5] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer transition-colors">
              <template v-if="loadingProvider === p.name"><Spinner class="h-5 w-5 me-2" />{{ $t('auth.redirecting') }}</template>
              <template v-else>{{ $t('auth.signInWithProvider', { provider: p.name }) }}</template>
            </button>
          </div>
        </div>

        <div class="mt-4 text-[13px] text-gray-500" v-if="authMode !== 'sso_only'">
          New to CityAgent?
          <NuxtLink to="/users/sign-up" class="text-[#c2683f] hover:text-[#a8542f] font-medium">{{ $t('auth.signUp') }}</NuxtLink>
        </div>
      </div>

      <!-- footer -->
      <div class="flex items-center gap-3.5 text-[11px] text-gray-400 max-w-[392px] w-full mx-auto lg:mx-0">
        <span>© 2026 CityAgent Analytics · v2.4.0</span>
      </div>
    </div>

    <!-- ============ RIGHT — analytics preview (desktop only) ============ -->
    <div class="hidden lg:flex items-center justify-center p-8" style="background:radial-gradient(120% 120% at 80% 0%,#fbf3ee 0%,#faf8f5 42%,#f7f5f1 100%)">
      <div class="w-full max-w-[600px] bg-white border border-[#eae6df] rounded-[20px] overflow-hidden shadow-[0_24px_60px_-28px_rgba(60,40,20,.25),0_2px_8px_rgba(0,0,0,.03)]">
        <!-- panel top bar -->
        <div class="flex items-center gap-2.5 px-4 py-3 border-b border-[#f1ede6]">
          <div class="flex gap-1.5"><i class="w-2.5 h-2.5 rounded-full bg-[#e7e2da] block"></i><i class="w-2.5 h-2.5 rounded-full bg-[#e7e2da] block"></i><i class="w-2.5 h-2.5 rounded-full bg-[#e7e2da] block"></i></div>
          <span class="text-[12.5px] text-gray-500 font-medium">City Agent Analyst · Music Store</span>
          <span class="ml-auto inline-flex items-center gap-1.5 text-[11px] font-semibold text-emerald-600"><i class="w-1.5 h-1.5 rounded-full bg-emerald-500 block"></i>Live</span>
        </div>

        <div class="p-5">
          <!-- question -->
          <div class="flex justify-end mb-3.5">
            <div class="bg-[#c2683f] text-white text-[13px] px-3.5 py-2.5 rounded-2xl rounded-br-[5px] shadow-[0_6px_16px_-6px_rgba(194,104,63,.5)]">Top 5 artists by revenue this quarter?</div>
          </div>

          <!-- answer -->
          <div class="flex gap-3 mb-4">
            <div class="w-[30px] h-[30px] rounded-lg bg-gradient-to-br from-[#c2683f] to-[#dd9269] flex items-center justify-center shrink-0">
              <UIcon name="i-heroicons-presentation-chart-line" class="w-4 h-4 text-white" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-[11px] text-gray-400 mb-2 flex items-center gap-2">
                <b class="text-[#5c574f] font-semibold">Dash Pro</b> · 2.1s · 412 tok
                <span class="inline-flex items-center gap-1 text-emerald-600 font-medium"><i class="w-[5px] h-[5px] rounded-full bg-emerald-500 block"></i>Grounded on 11 of 11 tables</span>
              </div>

              <!-- KPIs -->
              <div class="grid grid-cols-3 gap-2.5 mb-3.5">
                <div class="bg-[#faf8f5] border border-[#f1ede6] rounded-xl px-3 py-2.5">
                  <div class="text-[10.5px] uppercase tracking-wide text-gray-400 font-medium">Revenue</div>
                  <div class="text-[18px] font-semibold tracking-tight mt-0.5">$48.2K</div>
                  <div class="text-[10.5px] font-semibold mt-0.5 flex items-center gap-1 text-emerald-600"><UIcon name="i-heroicons-arrow-trending-up" class="w-3 h-3" />+12.4%</div>
                </div>
                <div class="bg-[#faf8f5] border border-[#f1ede6] rounded-xl px-3 py-2.5">
                  <div class="text-[10.5px] uppercase tracking-wide text-gray-400 font-medium">Invoices</div>
                  <div class="text-[18px] font-semibold tracking-tight mt-0.5">1,094</div>
                  <div class="text-[10.5px] font-semibold mt-0.5 flex items-center gap-1 text-emerald-600"><UIcon name="i-heroicons-arrow-trending-up" class="w-3 h-3" />+5.1%</div>
                </div>
                <div class="bg-[#faf8f5] border border-[#f1ede6] rounded-xl px-3 py-2.5">
                  <div class="text-[10.5px] uppercase tracking-wide text-gray-400 font-medium">Avg order</div>
                  <div class="text-[18px] font-semibold tracking-tight mt-0.5">$44.1</div>
                  <div class="text-[10.5px] font-semibold mt-0.5 flex items-center gap-1 text-[#c2683f]"><UIcon name="i-heroicons-arrow-trending-down" class="w-3 h-3" />-1.8%</div>
                </div>
              </div>

              <!-- bar chart -->
              <div class="bg-[#faf8f5] border border-[#f1ede6] rounded-xl px-3.5 pt-3 pb-2">
                <div class="flex items-center justify-between mb-3">
                  <span class="text-[12px] font-semibold text-[#46413a]">Revenue by artist</span>
                  <span class="text-[10.5px] text-gray-400">Q2 2026 · USD</span>
                </div>
                <div class="flex items-end gap-3.5 h-24 pt-1">
                  <div v-for="b in bars" :key="b.l" class="flex-1 flex flex-col items-center gap-1.5 h-full justify-end">
                    <div class="w-full max-w-[34px] rounded-t-md bg-gradient-to-b from-[#e2a883] to-[#c2683f]" :style="{ height: b.h }"></div>
                    <span class="text-[10px] text-gray-400">{{ b.l }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- quick tiles -->
          <div class="grid grid-cols-4 gap-2.5">
            <div v-for="(tile, i) in tiles" :key="tile.l"
              class="bg-white border rounded-xl px-2.5 py-2.5 flex flex-col gap-2 transition-colors"
              :class="i === 0 ? 'border-[#c2683f] shadow-[0_0_0_1px_#c2683f,0_6px_16px_-10px_rgba(194,104,63,.5)]' : 'border-[#eae6df] hover:border-[#d9b9a6]'">
              <div class="w-[30px] h-[30px] rounded-lg bg-[#f7ede7] flex items-center justify-center text-[#c2683f]"><UIcon :name="tile.icon" class="w-4 h-4" /></div>
              <span class="text-[11.5px] font-medium text-[#46413a]">{{ tile.l }}</span>
            </div>
          </div>

          <!-- composer -->
          <div class="mt-4 flex items-center gap-3 bg-white border border-[#eae6df] rounded-[13px] px-3 py-3 shadow-[0_4px_14px_-10px_rgba(0,0,0,.2)]">
            <div class="w-[30px] h-[30px] rounded-lg bg-[#faf8f5] border border-[#f1ede6] flex items-center justify-center text-gray-500"><UIcon name="i-heroicons-beaker" class="w-[15px] h-[15px]" /></div>
            <div class="flex-1 leading-tight">
              <div class="text-[12.5px] text-[#191613] font-medium">Ask anything about your data…</div>
              <div class="text-[11px] text-gray-400">City Agent Analyst · Dash Pro · Grounded mode</div>
            </div>
            <div class="bg-[#c2683f] text-white text-[12.5px] font-semibold px-3.5 py-2 rounded-lg flex items-center gap-1.5">Let's go<UIcon name="i-heroicons-arrow-right" class="w-3.5 h-3.5" /></div>
          </div>
        </div>
      </div>
    </div>

  </div>
  <div v-else class="flex h-screen items-center justify-center"><Spinner class="h-6 w-6" /></div>
  </template>


  <script setup lang="ts">

  import qs from 'qs';

  import { ref, computed, onMounted } from 'vue';
  import Spinner from '~/components/Spinner.vue';

  const { t } = useI18n()
  const { rawToken } = useAuthState()
  const { fetchOrganization } = useOrganization()
  const route = useRoute()
  const config = useRuntimeConfig();
  const googleSignIn = ref(config.public.googleSignIn);
  const oidcProviders = ref<{ name: string; enabled: boolean }[]>([])
  const loadingProvider = ref<string | null>(null)
  const authMode = ref<'hybrid'|'local_only'|'sso_only'>('hybrid')
  const smtpEnabled = ref(false)
  const isSubmitting = ref(false)
  const localOverride = computed(() => route.query.local === 'true')

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

  // Static decorative data for the right-side analytics preview
  const bars = [
    { l: 'Iron M.', h: '88%' },
    { l: 'U2', h: '71%' },
    { l: 'Metallica', h: '58%' },
    { l: 'Led Z.', h: '44%' },
    { l: 'Lost', h: '33%' },
  ];
  const tiles = [
    { l: 'Run query', icon: 'i-heroicons-circle-stack' },
    { l: 'Build chart', icon: 'i-heroicons-chart-bar' },
    { l: 'Ask brain', icon: 'i-heroicons-sparkles' },
    { l: 'Metrics', icon: 'i-heroicons-cube' },
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

  const OAUTH_REDIRECT_STORAGE_NAME = 'bow:postSignInRedirect'

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
