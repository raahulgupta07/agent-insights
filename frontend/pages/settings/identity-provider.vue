<template>
  <div class="mt-4 space-y-8">

    <!-- ================================================================== -->
    <!-- Single Sign-On & Directories — one unified, add-driven list         -->
    <!-- ================================================================== -->
    <div>
      <!-- Section header: title/subtitle left · dirty + Add + Save right -->
      <div class="flex items-start justify-between gap-3 mb-4">
        <div>
          <h2 class="text-sm font-medium text-[#1f2328]">Single Sign-On &amp; Directories</h2>
          <p class="text-xs text-[#6b6b6b] mt-0.5">Everything is added, configured, enabled and removed from one place. Nothing is on until you add it.</p>
        </div>
        <div class="flex items-center gap-2.5 flex-shrink-0">
          <span v-if="dirty" class="text-[11px] font-medium text-[#9A5A12] whitespace-nowrap">● Unsaved changes</span>
          <button
            type="button"
            class="px-3 py-2 text-xs font-medium rounded-lg border border-[#E9E0D3] bg-white text-[#1f2328] hover:bg-[#F4EEE5] transition-colors cursor-pointer whitespace-nowrap"
            @click="showLibrary = true"
          >+ Add provider</button>
          <button
            type="button"
            class="px-3 py-2 text-xs font-semibold rounded-lg border transition-colors whitespace-nowrap"
            :class="dirty
              ? 'bg-[#C2541E] border-[#C2541E] text-white hover:bg-[#A8330F] cursor-pointer'
              : 'bg-[#C2541E] border-[#C2541E] text-white opacity-50 cursor-default'"
            :disabled="!dirty || saving"
            @click="save"
          >{{ saving ? 'Saving…' : 'Save changes' }}</button>
        </div>
      </div>

      <!-- EMPTY STATE -->
      <div
        v-if="methods.length === 0"
        class="border border-[#E9E0D3] rounded-2xl overflow-hidden bg-white"
      >
        <div class="text-center px-5 py-10">
          <div class="w-12 h-12 rounded-xl border border-dashed border-[#E9E0D3] bg-[#FBF7F1] flex items-center justify-center mx-auto mb-3 p-2.5 [&_svg]:w-full [&_svg]:h-full" v-html="idpLogoSvg('shield')"></div>
          <h3 class="text-sm font-medium text-[#1f2328]" style="font-family:'Spectral',ui-serif,Georgia,serif">No sign-in methods yet</h3>
          <p class="text-xs text-[#9a958c] max-w-sm mx-auto mt-1 mb-4">Add Google, Microsoft, Okta, Keycloak, a generic OIDC provider, an LDAP / AD directory, or SCIM provisioning.</p>
          <button
            type="button"
            class="inline-flex items-center gap-2 text-xs font-medium text-[#C2541E] border border-dashed border-[#E9E0D3] rounded-xl px-4 py-2.5 hover:border-[#C2541E] hover:bg-[#FBEFE4] transition-colors"
            @click="showLibrary = true"
          ><span>+</span> Add provider</button>
        </div>
      </div>

      <!-- POPULATED LIST -->
      <div v-else class="border border-[#E9E0D3] rounded-2xl overflow-hidden bg-white">
        <div
          v-for="m in methods"
          :key="m.id"
          class="flex items-center gap-3 px-5 py-3.5 border-b border-[#E9E0D3] last:border-b-0"
        >
          <span class="w-8 h-8 rounded-md border border-[#E9E0D3] bg-white flex items-center justify-center flex-shrink-0 p-1.5 [&_svg]:w-full [&_svg]:h-full [&_img]:w-full [&_img]:h-full" v-html="idpLogoSvg(m.logo)"></span>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-medium text-[#1f2328] truncate">{{ m.name }}</div>
            <div v-if="m.meta" class="text-[11px] text-[#9a958c] truncate">{{ m.meta }}</div>
          </div>
          <span class="text-[11px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap" :class="pillClass(m.enabled, m.configured)">{{ pillText(m.enabled, m.configured) }}</span>
          <button
            type="button"
            class="px-3 py-2 text-xs rounded-lg transition-colors cursor-pointer whitespace-nowrap"
            :class="(m.enabled && !m.configured) ? 'border border-[#e7c79a] text-[#9A5A12] bg-[#FBEEDD] hover:bg-[#f6e3c8]' : 'border border-[#E9E0D3] text-[#1f2328] bg-white hover:bg-[#F4EEE5]'"
            @click="m.configure()"
          >{{ (m.enabled && !m.configured) ? 'Set up →' : 'Configure' }}</button>
          <button
            v-if="m.toggle"
            type="button"
            class="relative w-9 h-5 rounded-full transition-colors focus:outline-none flex-shrink-0"
            :class="m.enabled ? 'bg-[#C2541E]' : 'bg-[#E9E0D3]'"
            :title="m.enabled ? 'Enabled — click to disable' : 'Disabled — click to enable'"
            @click="m.toggle()"
          >
            <span class="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all" :class="m.enabled ? 'left-[18px]' : 'left-0.5'"></span>
          </button>
          <button
            type="button"
            class="text-sm text-[#9a958c] hover:text-red-600 hover:bg-red-50 rounded-md px-1.5 py-1 flex-shrink-0"
            title="Remove provider"
            @click="askRemove(m)"
          >&#x2715;</button>
        </div>
      </div>

      <!-- Auth mode (staged, applied by Save) -->
      <div class="mt-5 pt-5 border-t border-[#E9E0D3]">
        <div class="flex items-center gap-6 flex-wrap">
          <span class="text-xs text-[#6b6b6b] w-28 flex-shrink-0">Auth mode</span>
          <label
            v-for="opt in authModeOptions"
            :key="opt.value"
            class="flex items-center gap-2 cursor-pointer text-xs text-[#6b6b6b]"
          >
            <span
              class="w-3.5 h-3.5 rounded-full border flex-shrink-0 relative"
              :class="ssoAuthMode === opt.value ? 'border-[#C2541E]' : 'border-[#E9E0D3]'"
            >
              <span
                v-if="ssoAuthMode === opt.value"
                class="absolute inset-[3px] rounded-full bg-[#C2541E]"
              ></span>
            </span>
            <input
              type="radio"
              :value="opt.value"
              v-model="ssoAuthMode"
              class="sr-only"
              @change="stageAuthMode"
            />
            {{ opt.label }}
          </label>
        </div>
      </div>
    </div>

    <!-- ================================================================== -->
    <!-- PROVIDER CONFIG MODALS (immediate persist — NOT staged)            -->
    <!-- ================================================================== -->

    <!-- Google Modal -->
    <SettingsProviderConfigModal :model-value="activeModal === 'google'" title="Configure Google SSO" @close="closeModal">
      <IdpLogoPicker v-model="ssoGoogle.logo" />
      <!-- Redirect URI -->
      <div class="mb-4 rounded-xl border border-[#E9E0D3] bg-[#faf8f3] px-3 py-2.5">
        <div class="flex items-center justify-between mb-1">
          <span class="text-xs font-medium text-[#6b6b6b]">Redirect URI</span>
          <button type="button" class="text-[11px] text-[#C2541E] hover:text-[#A8330F] font-medium" @click="copyToClipboard(googleRedirectUri, 'google-redirect')">
            {{ copied === 'google-redirect' ? 'Copied!' : 'Copy' }}
          </button>
        </div>
        <code class="text-[11px] font-mono text-[#6b6b6b] break-all">{{ googleRedirectUri }}</code>
        <p class="text-[11px] text-[#9a958c] mt-1">Paste this into the Google Cloud Console OAuth 2.0 authorized redirect URIs.</p>
      </div>

      <div class="flex items-center justify-between mb-4">
        <span class="text-xs font-semibold text-[#6b6b6b]">Enable Google SSO</span>
        <label class="flex items-center gap-2 cursor-pointer">
          <button
            type="button"
            class="relative w-9 h-5 rounded-full transition-colors focus:outline-none flex-shrink-0"
            :class="ssoGoogle.enabled ? 'bg-[#C2541E]' : 'bg-[#E9E0D3]'"
            @click="ssoGoogle.enabled = !ssoGoogle.enabled"
          >
            <span
              class="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all"
              :class="ssoGoogle.enabled ? 'left-[18px]' : 'left-0.5'"
            ></span>
          </button>
          <span class="text-xs text-[#6b6b6b]">{{ ssoGoogle.enabled ? 'Enabled' : 'Disabled' }}</span>
        </label>
      </div>

      <div class="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2.5 items-center">
        <span class="text-xs text-[#6b6b6b]">Client ID</span>
        <input
          v-model="ssoGoogle.client_id"
          type="text"
          placeholder="1234-abc.apps.googleusercontent.com"
          class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
        />
        <span class="text-xs text-[#6b6b6b]">Client secret</span>
        <input
          v-model="ssoGoogle.client_secret"
          type="password"
          :placeholder="ssoGoogle.client_secret_set ? 'configured' : 'paste secret…'"
          class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
        />
        <span class="col-start-2 text-[11px] text-[#9a958c]">Encrypted at rest (Fernet). Write-only — never echoed back.</span>
      </div>

      <div v-if="ssoGoogleTestResult" class="mt-3 text-xs" :class="ssoGoogleTestResult.ok ? 'text-green-600' : 'text-red-500'">
        {{ ssoGoogleTestResult.text }}
      </div>

      <!-- Modal footer -->
      <div class="flex items-center gap-2 mt-5 pt-4 border-t border-[#E9E0D3]">
        <button
          type="button"
          class="px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer disabled:opacity-65"
          :disabled="ssoGoogleTesting"
          @click="handleTestGoogle"
        >{{ ssoGoogleTesting ? 'Testing…' : 'Test' }}</button>
        <button
          type="button"
          class="px-4 py-2.5 text-xs bg-[#C2541E] hover:bg-[#A8330F] text-white rounded-xl font-semibold transition-colors cursor-pointer disabled:opacity-65"
          :disabled="ssoGoogleSaving"
          @click="handleSaveGoogleAndClose"
        >{{ ssoGoogleSaving ? 'Saving…' : 'Save' }}</button>
        <button type="button" class="ms-auto px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer" @click="closeModal">Cancel</button>
      </div>
    </SettingsProviderConfigModal>

    <!-- Microsoft Modal -->
    <SettingsProviderConfigModal :model-value="activeModal === 'microsoft'" title="Configure Microsoft / Entra SSO" @close="closeModal">
      <IdpLogoPicker v-model="ssoMicrosoft.logo" />
      <!-- Redirect URI -->
      <div class="mb-4 rounded-xl border border-[#E9E0D3] bg-[#faf8f3] px-3 py-2.5">
        <div class="flex items-center justify-between mb-1">
          <span class="text-xs font-medium text-[#6b6b6b]">Redirect URI</span>
          <button type="button" class="text-[11px] text-[#C2541E] hover:text-[#A8330F] font-medium" @click="copyToClipboard(microsoftRedirectUri, 'ms-redirect')">
            {{ copied === 'ms-redirect' ? 'Copied!' : 'Copy' }}
          </button>
        </div>
        <code class="text-[11px] font-mono text-[#6b6b6b] break-all">{{ microsoftRedirectUri }}</code>
        <p class="text-[11px] text-[#9a958c] mt-1">Paste this into the Azure app registration redirect URIs.</p>
      </div>

      <div class="flex items-center justify-between mb-4">
        <span class="text-xs font-semibold text-[#6b6b6b]">Enable Microsoft SSO</span>
        <label class="flex items-center gap-2 cursor-pointer">
          <button
            type="button"
            class="relative w-9 h-5 rounded-full transition-colors focus:outline-none flex-shrink-0"
            :class="ssoMicrosoft.enabled ? 'bg-[#C2541E]' : 'bg-[#E9E0D3]'"
            @click="ssoMicrosoft.enabled = !ssoMicrosoft.enabled"
          >
            <span
              class="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all"
              :class="ssoMicrosoft.enabled ? 'left-[18px]' : 'left-0.5'"
            ></span>
          </button>
          <span class="text-xs text-[#6b6b6b]">{{ ssoMicrosoft.enabled ? 'Enabled' : 'Disabled' }}</span>
        </label>
      </div>

      <div class="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2.5 items-center">
        <span class="text-xs text-[#6b6b6b]">Tenant ID</span>
        <input
          v-model="ssoMicrosoft.tenant_id"
          type="text"
          placeholder="00000000-0000-0000-0000-000000000000"
          class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
        />
        <span class="text-xs text-[#6b6b6b]">Client ID</span>
        <input
          v-model="ssoMicrosoft.client_id"
          type="text"
          placeholder="application (client) id"
          class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
        />
        <span class="text-xs text-[#6b6b6b]">Client secret</span>
        <input
          v-model="ssoMicrosoft.client_secret"
          type="password"
          :placeholder="ssoMicrosoft.client_secret_set ? 'configured' : 'paste secret…'"
          class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
        />
        <span class="col-start-2 text-[11px] text-[#9a958c]">Encrypted at rest (Fernet). Write-only — never echoed back.</span>
        <label class="col-span-2 flex items-center gap-2 cursor-pointer mt-1">
          <input v-model="ssoMicrosoft.sync_groups" type="checkbox" class="accent-[#C2541E] w-3.5 h-3.5" />
          <span class="text-xs text-[#6b6b6b]">Sync groups from Entra (Microsoft Graph) — maps Entra groups to Dash Groups</span>
        </label>
      </div>
      <p class="text-[11px] text-[#9a958c] mt-2">
        Issuer auto-built:
        <code class="font-mono">https://login.microsoftonline.com/{{ ssoMicrosoft.tenant_id || '&lt;tenant&gt;' }}/v2.0</code>
      </p>

      <div v-if="ssoMicrosoftTestResult" class="mt-3 text-xs" :class="ssoMicrosoftTestResult.ok ? 'text-green-600' : 'text-red-500'">
        {{ ssoMicrosoftTestResult.text }}
      </div>

      <!-- Modal footer -->
      <div class="flex items-center gap-2 mt-5 pt-4 border-t border-[#E9E0D3]">
        <button
          type="button"
          class="px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer disabled:opacity-65"
          :disabled="ssoMicrosoftTesting"
          @click="handleTestMicrosoft"
        >{{ ssoMicrosoftTesting ? 'Testing…' : 'Test' }}</button>
        <button
          type="button"
          class="px-4 py-2.5 text-xs bg-[#C2541E] hover:bg-[#A8330F] text-white rounded-xl font-semibold transition-colors cursor-pointer disabled:opacity-65"
          :disabled="ssoMicrosoftSaving"
          @click="handleSaveMicrosoftAndClose"
        >{{ ssoMicrosoftSaving ? 'Saving…' : 'Save' }}</button>
        <button type="button" class="ms-auto px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer" @click="closeModal">Cancel</button>
      </div>
    </SettingsProviderConfigModal>

    <!-- Custom OIDC Modal -->
    <SettingsProviderConfigModal :model-value="activeModal === 'oidc'" :title="activeOidcIdx !== null && oidcProviders[activeOidcIdx] ? `Configure ${oidcProviders[activeOidcIdx].label || oidcProviders[activeOidcIdx].name || 'OIDC Provider'}` : 'Configure OIDC Provider'" @close="closeModal">
      <template v-if="activeOidcIdx !== null && oidcProviders[activeOidcIdx]">
        <IdpLogoPicker v-model="oidcProviders[activeOidcIdx].logo" />
        <!-- Redirect URI -->
        <div class="mb-4 rounded-xl border border-[#E9E0D3] bg-[#faf8f3] px-3 py-2.5">
          <div class="flex items-center justify-between mb-1">
            <span class="text-xs font-medium text-[#6b6b6b]">Redirect URI</span>
            <button type="button" class="text-[11px] text-[#C2541E] hover:text-[#A8330F] font-medium" @click="copyToClipboard(oidcRedirectUri(oidcProviders[activeOidcIdx].name), 'oidc-redirect')">
              {{ copied === 'oidc-redirect' ? 'Copied!' : 'Copy' }}
            </button>
          </div>
          <code class="text-[11px] font-mono text-[#6b6b6b] break-all">{{ oidcRedirectUri(oidcProviders[activeOidcIdx].name) }}</code>
          <p class="text-[11px] text-[#9a958c] mt-1">Paste this into your identity provider's authorized redirect URIs.</p>
        </div>

        <div class="flex items-center justify-between mb-4">
          <span class="text-xs font-semibold text-[#6b6b6b]">Enable this provider</span>
          <label class="flex items-center gap-2 cursor-pointer">
            <button
              type="button"
              class="relative w-9 h-5 rounded-full transition-colors focus:outline-none flex-shrink-0"
              :class="oidcProviders[activeOidcIdx].enabled ? 'bg-[#C2541E]' : 'bg-[#E9E0D3]'"
              @click="oidcProviders[activeOidcIdx].enabled = !oidcProviders[activeOidcIdx].enabled"
            >
              <span
                class="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all"
                :class="oidcProviders[activeOidcIdx].enabled ? 'left-[18px]' : 'left-0.5'"
              ></span>
            </button>
            <span class="text-xs text-[#6b6b6b]">{{ oidcProviders[activeOidcIdx].enabled ? 'Enabled' : 'Disabled' }}</span>
          </label>
        </div>

        <div class="grid grid-cols-[140px_1fr] gap-x-4 gap-y-2.5 items-center">
          <span class="text-xs text-[#6b6b6b]">Name (slug)</span>
          <input
            v-model="oidcProviders[activeOidcIdx].name"
            type="text"
            placeholder="e.g. okta"
            class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
          />
          <span class="text-xs text-[#6b6b6b]">Label</span>
          <input
            v-model="oidcProviders[activeOidcIdx].label"
            type="text"
            placeholder="e.g. Okta"
            class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs focus:outline-none focus:border-[#C2541E]"
          />
          <span class="text-xs text-[#6b6b6b]">Issuer URL</span>
          <input
            v-model="oidcProviders[activeOidcIdx].issuer"
            type="text"
            :placeholder="oidcProviders[activeOidcIdx].issuerPattern || 'https://your-idp.example.com'"
            class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
          />
          <span class="text-xs text-[#6b6b6b]">Client ID</span>
          <input
            v-model="oidcProviders[activeOidcIdx].client_id"
            type="text"
            class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
          />
          <span class="text-xs text-[#6b6b6b]">Client secret</span>
          <input
            v-model="oidcProviders[activeOidcIdx].client_secret"
            type="password"
            :placeholder="oidcProviders[activeOidcIdx].client_secret_set ? 'configured' : 'paste secret…'"
            class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
          />
          <span class="text-xs text-[#6b6b6b]">Scopes (csv)</span>
          <input
            v-model="oidcProviders[activeOidcIdx].scopesCsv"
            type="text"
            placeholder="openid,profile,email"
            class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
          />
          <span class="text-xs text-[#6b6b6b]">Group claim</span>
          <input
            v-model="oidcProviders[activeOidcIdx].group_claim"
            type="text"
            placeholder="groups"
            class="w-full border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:border-[#C2541E]"
          />
          <label class="col-span-2 flex items-center gap-2 cursor-pointer mt-1">
            <input v-model="oidcProviders[activeOidcIdx].sync_groups" type="checkbox" class="accent-[#C2541E] w-3.5 h-3.5" />
            <span class="text-xs text-[#6b6b6b]">Sync groups from this provider</span>
          </label>
        </div>

        <!-- Modal footer -->
        <div class="flex items-center gap-2 mt-5 pt-4 border-t border-[#E9E0D3]">
          <button
            type="button"
            class="px-4 py-2.5 text-xs bg-[#C2541E] hover:bg-[#A8330F] text-white rounded-xl font-semibold transition-colors cursor-pointer disabled:opacity-65"
            :disabled="ssoOidcSaving"
            @click="handleSaveOidcAndClose"
          >{{ ssoOidcSaving ? 'Saving…' : 'Save' }}</button>
          <button type="button" class="ms-auto px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer" @click="closeModal">Cancel</button>
        </div>
      </template>
    </SettingsProviderConfigModal>

    <!-- SCIM Modal -->
    <SettingsProviderConfigModal :model-value="activeModal === 'scim'" title="Configure SCIM Provisioning" @close="closeModal">
      <!-- SCIM Endpoint URL -->
      <div class="mb-4 rounded-lg border border-[#E9E0D3] p-3">
        <label class="block text-xs font-medium text-[#6b6b6b] mb-1">{{ $t('settings.identityProvider.scimBaseUrl') }}</label>
        <div class="flex items-center gap-2">
          <code class="flex-1 text-xs bg-[#F4EEE5] px-2 py-1.5 rounded-lg border border-[#E9E0D3] text-[#6b6b6b] font-mono">
            {{ scimBaseUrl }}
          </code>
          <button
            class="px-3 py-2 text-xs text-[#1f2328] bg-white border border-[#E9E0D3] rounded-lg hover:bg-[#F4EEE5] transition-colors cursor-pointer"
            @click="copyToClipboard(scimBaseUrl)"
          >
            {{ copied === 'url' ? $t('settings.identityProvider.copied') : $t('settings.identityProvider.copy') }}
          </button>
        </div>
        <p class="text-[11px] text-[#9a958c] mt-1">{{ $t('settings.identityProvider.scimBaseUrlHint') }}</p>
      </div>

      <!-- Token Management -->
      <div class="mb-3 flex items-center justify-between">
        <label class="text-xs font-medium text-[#6b6b6b]">{{ $t('settings.identityProvider.bearerTokens') }}</label>
        <button
          class="px-3 py-2.5 text-xs text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-xl transition-colors cursor-pointer"
          @click="showCreateModal = true"
        >
          {{ $t('settings.identityProvider.generateToken') }}
        </button>
      </div>

      <!-- Loading State -->
      <div v-if="scimLoading" class="py-8 text-center">
        <div class="inline-block w-4 h-4 border-2 border-[#E9E0D3] border-t-[#9a958c] rounded-full animate-spin"></div>
      </div>

      <!-- Error State -->
      <div v-else-if="scimError" class="py-6 text-center text-xs text-red-500">
        {{ scimError }}
      </div>

      <!-- Tokens List -->
      <div v-else class="border border-[#E9E0D3] rounded-lg overflow-hidden">
        <template v-if="tokens.length > 0">
          <div
            v-for="(token, idx) in tokens"
            :key="token.id"
            class="flex items-center px-3 py-2.5 text-xs"
            :class="{ 'border-t border-[#E9E0D3]': idx > 0 }"
          >
            <span class="w-36 flex-shrink-0 text-[#6b6b6b] font-medium truncate">{{ token.name }}</span>
            <span class="w-36 flex-shrink-0 text-[#9a958c] font-mono text-[11px]">{{ token.token_prefix }}...</span>
            <span class="flex-1 text-[#9a958c] text-[11px]">
              <template v-if="token.last_used_at">
                {{ $t('settings.identityProvider.lastUsed', { when: formatRelativeTime(token.last_used_at) }) }}
              </template>
              <template v-else>
                {{ $t('settings.identityProvider.neverUsed') }}
              </template>
            </span>
            <span class="w-24 flex-shrink-0 text-[#9a958c] text-[11px]">
              {{ formatRelativeTime(token.created_at) }}
            </span>
            <button
              class="text-[11px] text-red-500 hover:text-red-700 ms-2"
              @click="confirmRevoke(token)"
            >
              {{ $t('settings.identityProvider.revoke') }}
            </button>
          </div>
        </template>

        <!-- Empty State -->
        <div v-else class="py-8 text-center">
          <p class="text-xs text-[#9a958c]">{{ $t('settings.identityProvider.noTokens') }}</p>
          <p class="text-[11px] text-[#9a958c] mt-1">{{ $t('settings.identityProvider.noTokensHint') }}</p>
        </div>
      </div>

      <!-- Modal footer -->
      <div class="flex justify-end mt-5 pt-4 border-t border-[#E9E0D3]">
        <button type="button" class="px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer" @click="closeModal">Close</button>
      </div>
    </SettingsProviderConfigModal>


    <!-- ================================================================== -->
    <!-- SCIM Modals (Create + Revoke)                                       -->
    <!-- ================================================================== -->

    <!-- Create Token Modal -->
    <div v-if="showCreateModal" class="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]" @click.self="dismissCreateModal">
      <div class="bg-white rounded-lg shadow-lg w-full max-w-sm p-4">
        <h3 class="text-sm font-medium text-[#1f2328] mb-3">{{ $t('settings.identityProvider.generateTokenTitle') }}</h3>

        <template v-if="!createdToken">
          <div class="mb-3">
            <label class="block text-xs text-[#6b6b6b] mb-1">{{ $t('settings.identityProvider.nameLabel') }}</label>
            <input
              v-model="newTokenName"
              type="text"
              :placeholder="$t('settings.identityProvider.namePlaceholder')"
              class="w-full px-2 py-1.5 text-xs border border-[#E9E0D3] rounded-lg focus:outline-none focus:border-[#C2541E]"
              @keydown.enter="handleCreateToken"
            />
          </div>
          <div class="flex justify-end gap-2">
            <button class="px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer" @click="dismissCreateModal">{{ $t('settings.identityProvider.cancel') }}</button>
            <button
              class="px-4 py-2.5 text-xs text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-xl transition-colors cursor-pointer disabled:opacity-65"
              :disabled="!newTokenName.trim() || creating"
              @click="handleCreateToken"
            >
              {{ creating ? $t('settings.identityProvider.generating') : $t('settings.identityProvider.generate') }}
            </button>
          </div>
        </template>

        <template v-else>
          <div class="rounded-lg border border-amber-200 bg-amber-50 p-3 mb-3">
            <div class="flex items-start gap-2">
              <svg class="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
              </svg>
              <p class="text-xs font-medium text-amber-800">{{ $t('settings.identityProvider.copyWarning') }}</p>
            </div>
          </div>
          <div class="flex items-center gap-2 mb-3">
            <code class="flex-1 text-[11px] bg-[#F4EEE5] px-2 py-1.5 rounded-lg border border-[#E9E0D3] text-[#6b6b6b] font-mono truncate">
              {{ createdToken }}
            </code>
            <button
              class="px-3 py-2 text-xs text-[#1f2328] bg-white border border-[#E9E0D3] rounded-lg hover:bg-[#F4EEE5] transition-colors cursor-pointer flex-shrink-0"
              @click="copyToClipboard(createdToken!, 'token')"
            >
              {{ copied === 'token' ? $t('settings.identityProvider.copied') : $t('settings.identityProvider.copy') }}
            </button>
          </div>
          <div class="flex justify-end">
            <button class="px-4 py-2.5 text-xs text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-xl transition-colors cursor-pointer" @click="dismissCreateModal">{{ $t('settings.identityProvider.done') }}</button>
          </div>
        </template>
      </div>
    </div>

    <!-- Revoke Confirmation Modal -->
    <div v-if="tokenToRevoke" class="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]" @click.self="tokenToRevoke = null">
      <div class="bg-white rounded-lg shadow-lg w-full max-w-sm p-4">
        <h3 class="text-sm font-medium text-[#1f2328] mb-2">{{ $t('settings.identityProvider.revokeTitle') }}</h3>
        <p class="text-xs text-[#6b6b6b] mb-3">
          {{ $t('settings.identityProvider.revokeWarning', { name: tokenToRevoke.name }) }}
        </p>
        <div class="flex justify-end gap-2">
          <button class="px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer" @click="tokenToRevoke = null">{{ $t('settings.identityProvider.cancel') }}</button>
          <button class="px-3 py-2 text-xs text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors cursor-pointer" @click="handleRevoke">{{ $t('settings.identityProvider.revoke') }}</button>
        </div>
      </div>
    </div>

    <!-- LDAP directory config modal (create / edit) -->
    <LdapDirectoryModal
      :open="ldapModalOpen"
      :directory="ldapEditing"
      @close="ldapModalOpen = false"
      @saved="onLdapSaved"
    />

    <!-- Provider library (Add provider) -->
    <IdpProviderLibraryModal :open="showLibrary" @close="showLibrary = false" @select="onLibrarySelect" />

    <!-- DELETE — double-confirm modal -->
    <div v-if="removeTarget" class="fixed inset-0 bg-black/50 flex items-center justify-center z-[60]" @click.self="cancelRemove">
      <div class="bg-white rounded-2xl shadow-xl w-full max-w-md overflow-hidden border border-[#E9E0D3]">
        <div class="flex items-center justify-between px-5 py-4 border-b border-[#E9E0D3]">
          <h3 class="text-sm font-medium text-[#1f2328]" style="font-family:'Spectral',ui-serif,Georgia,serif">Remove provider</h3>
          <button type="button" class="text-[#9a958c] hover:text-[#1f2328]" @click="cancelRemove">&#x2715;</button>
        </div>
        <div class="px-5 py-4">
          <p class="text-xs text-[#1f2328] mb-3">
            Remove <b>{{ removeTarget.name }}</b>? This permanently deletes its configuration and members can no longer sign in through it.
          </p>
          <label class="flex items-center gap-2 text-xs text-[#6b6b6b] cursor-pointer">
            <input type="checkbox" v-model="removeAck" class="accent-[#C2541E] w-3.5 h-3.5" />
            I understand this cannot be undone.
          </label>
        </div>
        <div class="flex justify-end gap-2 px-5 py-4 border-t border-[#E9E0D3]">
          <button type="button" class="px-3 py-2 text-xs border border-[#E9E0D3] rounded-lg text-[#1f2328] bg-white hover:bg-[#F4EEE5] transition-colors cursor-pointer" @click="cancelRemove">Cancel</button>
          <button
            type="button"
            class="px-3 py-2 text-xs rounded-lg text-white transition-colors"
            :class="(removeAck && !removing) ? 'bg-red-600 hover:bg-red-700 cursor-pointer' : 'bg-red-600 opacity-50 cursor-default'"
            :disabled="!removeAck || removing"
            @click="confirmRemove"
          >{{ removing ? 'Removing…' : 'Remove' }}</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { useScimTokens, type ScimToken } from '~/ee/composables/useScimTokens'
import { idpLogoSvg } from '~/utils/idpLogos'
import { IDP_TEMPLATES, type IdpTemplate } from '~/utils/idpTemplates'
import IdpProviderLibraryModal from '~/components/idp/IdpProviderLibraryModal.vue'
import IdpLogoPicker from '~/components/idp/IdpLogoPicker.vue'
import LdapDirectoryModal from '~/components/idp/LdapDirectoryModal.vue'

definePageMeta({
  auth: true,
  permissions: ['manage_identity_providers'],
  layout: 'settings'
})

const { hasFeature, license } = useEnterprise()
const toast = useToast()

// ── Dirty / staged-save tracking ────────────────────────────────────────────
const dirty = ref(false)
const saving = ref(false)
function markDirty() { dirty.value = true }

// ── Modal state ───────────────────────────────────────────────────────────
type ModalKey = 'google' | 'microsoft' | 'oidc' | 'scim' | null
const activeModal = ref<ModalKey>(null)
const activeOidcIdx = ref<number | null>(null)

function openModal(key: Exclude<ModalKey, null>, oidcIdx?: number) {
  activeModal.value = key
  if (key === 'oidc' && oidcIdx !== undefined) {
    activeOidcIdx.value = oidcIdx
  }
}

function closeModal() {
  activeModal.value = null
  activeOidcIdx.value = null
  // clear transient test results
  ssoGoogleTestResult.value = null
  ssoMicrosoftTestResult.value = null
}

// ── SSO state ──────────────────────────────────────────────────────────────

const ssoAuthMode = ref<'local_only' | 'hybrid' | 'sso_only'>('hybrid')
const authModeOptions = [
  { value: 'local_only', label: 'Local only' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'sso_only', label: 'SSO only' },
]
let authModeBaseline: string = 'hybrid'
function stageAuthMode() { markDirty() }

const ssoGoogle = reactive({
  enabled: false,
  logo: 'google',
  client_id: '',
  client_secret: '',
  client_secret_set: false,
})
const ssoGoogleSaving = ref(false)
const ssoGoogleTesting = ref(false)
const ssoGoogleTestResult = ref<{ ok: boolean; text: string } | null>(null)
// "Added this session" flags — let a freshly-added Google/SCIM appear before configure.
const googleAdded = ref(false)
const scimAdded = ref(false)

const ssoMicrosoft = reactive({
  enabled: false,
  logo: 'microsoft',
  tenant_id: '',
  client_id: '',
  client_secret: '',
  client_secret_set: false,
  sync_groups: false,
})
const ssoMicrosoftSaving = ref(false)
const ssoMicrosoftTesting = ref(false)
const ssoMicrosoftTestResult = ref<{ ok: boolean; text: string } | null>(null)
const microsoftAdded = ref(false)

interface OidcProvider {
  name: string
  label: string
  enabled: boolean
  logo: string
  issuer: string
  issuerPattern?: string
  client_id: string
  client_secret: string
  client_secret_set: boolean
  scopesCsv: string
  sync_groups: boolean
  group_claim: string
}

const oidcProviders = ref<OidcProvider[]>([])
const ssoOidcSaving = ref(false)

// ── Redirect URI helpers ──────────────────────────────────────────────────
const googleRedirectUri = computed(() => {
  if (process.client) return `${window.location.origin}/api/auth/google/callback`
  return '/api/auth/google/callback'
})
const microsoftRedirectUri = computed(() => {
  if (process.client) return `${window.location.origin}/api/auth/microsoft/callback`
  return '/api/auth/microsoft/callback'
})
function oidcRedirectUri(name: string) {
  if (process.client) return `${window.location.origin}/api/auth/${name || '<name>'}/callback`
  return `/api/auth/${name || '<name>'}/callback`
}

async function loadSso() {
  try {
    const res = await useMyFetch('/api/organization/sso')
    const data = res.data.value as any
    if (!data) return
    ssoAuthMode.value = data.auth_mode || 'hybrid'
    authModeBaseline = ssoAuthMode.value
    if (data.google) {
      ssoGoogle.enabled = data.google.enabled ?? false
      ssoGoogle.logo = data.google.logo || 'google'
      ssoGoogle.client_id = data.google.client_id || ''
      ssoGoogle.client_secret_set = data.google.client_secret_set ?? false
    }
    const providers: OidcProvider[] = []
    for (const p of (data.oidc || [])) {
      if (p.name === 'microsoft') {
        // Parse tenant from issuer: https://login.microsoftonline.com/<tenant>/v2.0
        const m = (p.issuer || '').match(/microsoftonline\.com\/([^/]+)\/v2\.0/)
        ssoMicrosoft.enabled = p.enabled ?? false
        ssoMicrosoft.logo = p.logo || 'microsoft'
        ssoMicrosoft.tenant_id = m ? m[1] : ''
        ssoMicrosoft.client_id = p.client_id || ''
        ssoMicrosoft.client_secret_set = p.client_secret_set ?? false
        ssoMicrosoft.sync_groups = p.sync_groups ?? false
        microsoftAdded.value = true
      } else {
        providers.push({
          name: p.name || '',
          label: p.label || '',
          enabled: p.enabled ?? false,
          logo: p.logo || p.name || 'oidc',
          issuer: p.issuer || '',
          issuerPattern: '',
          client_id: p.client_id || '',
          client_secret: '',
          client_secret_set: p.client_secret_set ?? false,
          scopesCsv: (p.scopes || []).join(','),
          sync_groups: p.sync_groups ?? false,
          group_claim: p.group_claim || 'groups',
        })
      }
    }
    oidcProviders.value = providers
  } catch {
    // ignore — SSO not yet configured
  }
}

// ── Per-config-modal save (immediate persist — NOT staged) ──────────────────
async function handleSaveGoogle() {
  ssoGoogleSaving.value = true
  try {
    const body: any = { enabled: ssoGoogle.enabled, logo: ssoGoogle.logo, client_id: ssoGoogle.client_id }
    if (ssoGoogle.client_secret) body.client_secret = ssoGoogle.client_secret
    const res = await useMyFetch('/api/organization/sso/google', { method: 'PUT', body })
    if (res.status.value === 'success') {
      toast.add({ title: 'Google SSO saved', color: 'green' })
      googleAdded.value = true
      ssoGoogle.client_secret_set = ssoGoogle.client_secret_set || !!ssoGoogle.client_secret
      ssoGoogle.client_secret = ''
    } else {
      toast.add({ title: 'Failed to save Google SSO', description: (res.error.value as any)?.data?.detail || 'Error', color: 'red' })
    }
  } finally {
    ssoGoogleSaving.value = false
  }
}

async function handleSaveGoogleAndClose() {
  await handleSaveGoogle()
  if (!ssoGoogleSaving.value) closeModal()
}

async function handleTestGoogle() {
  ssoGoogleTesting.value = true
  ssoGoogleTestResult.value = null
  try {
    const res = await useMyFetch('/api/organization/sso/google/test', { method: 'POST' })
    const data = res.data.value as any
    if (res.status.value === 'success' && data?.success) {
      ssoGoogleTestResult.value = { ok: true, text: 'Connection OK — redirect URI is reachable.' }
    } else {
      ssoGoogleTestResult.value = { ok: false, text: data?.detail || 'Test failed — check Client ID and secret.' }
    }
  } catch {
    ssoGoogleTestResult.value = { ok: false, text: 'Test failed — check Client ID and secret.' }
  } finally {
    ssoGoogleTesting.value = false
  }
}

function buildMicrosoftOidcPayload() {
  const tenantId = ssoMicrosoft.tenant_id.trim()
  const p: any = {
    name: 'microsoft',
    label: 'Microsoft',
    enabled: ssoMicrosoft.enabled,
    logo: ssoMicrosoft.logo || 'microsoft',
    issuer: `https://login.microsoftonline.com/${tenantId}/v2.0`,
    client_id: ssoMicrosoft.client_id,
    sync_groups: ssoMicrosoft.sync_groups,
    group_claim: 'groups',
    scopes: ['openid', 'profile', 'email'],
  }
  if (ssoMicrosoft.client_secret) p.client_secret = ssoMicrosoft.client_secret
  return p
}

// Build the full oidc list to PUT (microsoft only when added/configured).
function buildAllOidcPayload() {
  const list: any[] = oidcProviders.value.map(buildOidcPayload)
  if (microsoftAdded.value) list.unshift(buildMicrosoftOidcPayload())
  return list
}

async function handleSaveMicrosoft() {
  ssoMicrosoftSaving.value = true
  try {
    microsoftAdded.value = true
    const res = await useMyFetch('/api/organization/sso/oidc', {
      method: 'PUT',
      body: { providers: buildAllOidcPayload() },
    })
    if (res.status.value === 'success') {
      toast.add({ title: 'Microsoft SSO saved', color: 'green' })
      ssoMicrosoft.client_secret_set = ssoMicrosoft.client_secret_set || !!ssoMicrosoft.client_secret
      ssoMicrosoft.client_secret = ''
    } else {
      toast.add({ title: 'Failed to save Microsoft SSO', description: (res.error.value as any)?.data?.detail || 'Error', color: 'red' })
    }
  } finally {
    ssoMicrosoftSaving.value = false
  }
}

async function handleSaveMicrosoftAndClose() {
  await handleSaveMicrosoft()
  if (!ssoMicrosoftSaving.value) closeModal()
}

async function handleTestMicrosoft() {
  ssoMicrosoftTesting.value = true
  ssoMicrosoftTestResult.value = null
  try {
    const res = await useMyFetch('/api/organization/sso/oidc/microsoft/test', { method: 'POST' })
    const data = res.data.value as any
    if (res.status.value === 'success' && data?.success) {
      ssoMicrosoftTestResult.value = { ok: true, text: 'Connection OK — OIDC discovery endpoint reachable.' }
    } else {
      ssoMicrosoftTestResult.value = { ok: false, text: data?.detail || 'Test failed — check Tenant ID, Client ID and secret.' }
    }
  } catch {
    ssoMicrosoftTestResult.value = { ok: false, text: 'Test failed — check Tenant ID, Client ID and secret.' }
  } finally {
    ssoMicrosoftTesting.value = false
  }
}

function buildOidcPayload(p: OidcProvider) {
  const out: any = {
    name: p.name,
    label: p.label,
    enabled: p.enabled,
    logo: p.logo || p.name || 'oidc',
    issuer: p.issuer,
    client_id: p.client_id,
    sync_groups: p.sync_groups,
    group_claim: p.group_claim,
    scopes: p.scopesCsv.split(',').map((s) => s.trim()).filter(Boolean),
  }
  if (p.client_secret) out.client_secret = p.client_secret
  return out
}

async function handleSaveOidc() {
  ssoOidcSaving.value = true
  try {
    const res = await useMyFetch('/api/organization/sso/oidc', {
      method: 'PUT',
      body: { providers: buildAllOidcPayload() },
    })
    if (res.status.value === 'success') {
      toast.add({ title: 'OIDC providers saved', color: 'green' })
      // Clear secrets
      for (const p of oidcProviders.value) {
        if (p.client_secret) {
          p.client_secret_set = true
          p.client_secret = ''
        }
      }
    } else {
      toast.add({ title: 'Failed to save OIDC providers', description: (res.error.value as any)?.data?.detail || 'Error', color: 'red' })
    }
  } finally {
    ssoOidcSaving.value = false
  }
}

async function handleSaveOidcAndClose() {
  await handleSaveOidc()
  if (!ssoOidcSaving.value) closeModal()
}

// ── SCIM ──────────────────────────────────────────────────────────────────
const { tokens, loading: scimLoading, error: scimError, fetchTokens, createToken, revokeToken } = useScimTokens()

const showCreateModal = ref(false)
const newTokenName = ref('SCIM Token')
const creating = ref(false)
const createdToken = ref<string | null>(null)
const tokenToRevoke = ref<ScimToken | null>(null)
const copied = ref<string | null>(null)
const hasFetchedScim = ref(false)

const scimBaseUrl = computed(() => {
  if (process.client) {
    return `${window.location.origin}/scim/v2`
  }
  return '/scim/v2'
})

const dismissCreateModal = () => {
  showCreateModal.value = false
  createdToken.value = null
  newTokenName.value = 'SCIM Token'
}

const handleCreateToken = async () => {
  if (!newTokenName.value.trim() || creating.value) return
  creating.value = true
  const result = await createToken(newTokenName.value.trim())
  creating.value = false
  if (result) {
    createdToken.value = result.token
    scimAdded.value = true
  }
}

const confirmRevoke = (token: ScimToken) => {
  tokenToRevoke.value = token
}

const handleRevoke = async () => {
  if (!tokenToRevoke.value) return
  await revokeToken(tokenToRevoke.value.id)
  tokenToRevoke.value = null
  createdToken.value = null
}

// ── LDAP directories ────────────────────────────────────────────────────────
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

const ldapDirectories = ref<LdapDirectory[]>([])
const ldapModalOpen = ref(false)
const ldapEditing = ref<LdapDirectory | null>(null)
// Staged enable/disable per directory id (applied on Save).
const ldapStagedEnabled = reactive<Record<string, boolean>>({})

async function loadLdapDirectories() {
  if (!hasFeature('ldap')) return
  try {
    const { data, error } = await useMyFetch<{ directories: LdapDirectory[] } | LdapDirectory[]>(
      '/enterprise/ldap/directories',
      { method: 'GET' }
    )
    if (error?.value) throw error.value
    const raw = data.value
    ldapDirectories.value = Array.isArray(raw) ? raw : (raw?.directories ?? [])
    // reset staged enable map to live state
    for (const k of Object.keys(ldapStagedEnabled)) delete ldapStagedEnabled[k]
  } catch {
    // not yet configured / no permission — leave empty
  }
}

function ldapEnabledState(dir: LdapDirectory): boolean {
  return dir.id in ldapStagedEnabled ? ldapStagedEnabled[dir.id] : !!dir.enabled
}
function stageLdapToggle(dir: LdapDirectory) {
  ldapStagedEnabled[dir.id] = !ldapEnabledState(dir)
  markDirty()
}
function openLdapConfig(dir: LdapDirectory) {
  ldapEditing.value = dir
  ldapModalOpen.value = true
}
function openLdapCreate() {
  ldapEditing.value = null
  ldapModalOpen.value = true
}
async function onLdapSaved() {
  ldapModalOpen.value = false
  ldapEditing.value = null
  await loadLdapDirectories()
}

// ── Shared ────────────────────────────────────────────────────────────────
const copyToClipboard = async (text: string, key: string = 'url') => {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = key
    setTimeout(() => { copied.value = null }, 2000)
  } catch {
    // Fallback
  }
}

const formatRelativeTime = (timestamp: string | null) => {
  if (!timestamp) return ''
  const isoTimestamp = timestamp.endsWith('Z') ? timestamp : timestamp + 'Z'
  const date = new Date(isoTimestamp)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`

  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// ── Smart-status pill helpers ───────────────────────────────────────────────
function pillText(enabled: boolean, configured: boolean) {
  if (enabled && configured) return '● On · Ready'
  if (enabled && !configured) return '⚠ On · Needs setup'
  if (!enabled && configured) return '○ Off · Configured'
  return '○ Disabled'
}
function pillClass(enabled: boolean, configured: boolean) {
  if (enabled && configured) return 'bg-[#E7F2EC] text-[#2f7a52] border border-[#cfe6da]'
  if (enabled && !configured) return 'bg-[#FBEEDD] text-[#9A5A12] border border-[#eed6b3]'
  return 'bg-[#F4EEE5] text-[#6b6b6b] border border-[#E9E0D3]'
}

// ── Add provider (library) ──────────────────────────────────────────────────
const showLibrary = ref(false)

function findOidcIdx(name: string) {
  return oidcProviders.value.findIndex(p => (p.name || '').toLowerCase() === name)
}
function oidcConfigured(p: OidcProvider) {
  return !!(p.client_secret_set || (p.client_id && p.issuer))
}

// Push a new oidc provider prefilled from a template + open its config modal.
function createFromTemplate(tpl: IdpTemplate) {
  const isGeneric = tpl.key === 'oidc'
  oidcProviders.value.push({
    name: isGeneric ? '' : tpl.key,
    label: tpl.name,
    enabled: true,
    logo: tpl.logo,
    issuer: '',
    issuerPattern: tpl.issuerPattern,
    client_id: '',
    client_secret: '',
    client_secret_set: false,
    scopesCsv: tpl.scopes.join(','),
    sync_groups: false,
    group_claim: tpl.groupClaim || 'groups',
  })
  openModal('oidc', oidcProviders.value.length - 1)
}

function onLibrarySelect(tpl: IdpTemplate) {
  showLibrary.value = false
  if (tpl.key === 'google') {
    googleAdded.value = true
    ssoGoogle.enabled = true
    openModal('google')
    return
  }
  if (tpl.key === 'microsoft') {
    microsoftAdded.value = true
    ssoMicrosoft.enabled = true
    openModal('microsoft')
    return
  }
  if (tpl.key === 'ldap') {
    openLdapCreate()
    return
  }
  if (tpl.key === 'scim') {
    scimAdded.value = true
    if (!hasFetchedScim.value) { hasFetchedScim.value = true; fetchTokens() }
    openModal('scim')
    return
  }
  // OIDC family — reuse an existing entry of the same name (non-generic) if present.
  const existing = findOidcIdx(tpl.key)
  if (existing >= 0 && tpl.key !== 'oidc') {
    openModal('oidc', existing)
    return
  }
  createFromTemplate(tpl)
}

// ── Unified row model ────────────────────────────────────────────────────────
interface MethodRow {
  id: string
  name: string
  logo: string
  meta?: string
  enabled: boolean
  configured: boolean
  configure: () => void
  toggle?: () => void
  remove: () => void | Promise<void>
}

const methods = computed<MethodRow[]>(() => {
  const rows: MethodRow[] = []

  // Google — only if configured or just added this session.
  const googleConfigured = !!(ssoGoogle.client_secret_set || ssoGoogle.client_id)
  if (googleConfigured || googleAdded.value) {
    rows.push({
      id: 'google',
      name: 'Google',
      logo: ssoGoogle.logo || 'google',
      enabled: ssoGoogle.enabled,
      configured: googleConfigured,
      configure: () => openModal('google'),
      toggle: () => { ssoGoogle.enabled = !ssoGoogle.enabled; markDirty() },
      remove: removeGoogle,
    })
  }

  // OIDC entries (Microsoft is an ordinary oidc entry by name).
  oidcProviders.value.forEach((p, idx) => {
    rows.push({
      id: 'oidc-' + idx,
      name: p.label || p.name || 'Unnamed provider',
      logo: p.logo || p.name || 'oidc',
      enabled: p.enabled,
      configured: oidcConfigured(p),
      configure: () => openModal('oidc', idx),
      toggle: () => { p.enabled = !p.enabled; markDirty() },
      remove: () => removeOidc(idx),
    })
  })

  // Microsoft (stored separately as a reactive object; one row when added/configured).
  const msConfigured = !!(ssoMicrosoft.client_secret_set || ssoMicrosoft.client_id)
  if (msConfigured || microsoftAdded.value) {
    rows.push({
      id: 'microsoft',
      name: 'Microsoft / Entra',
      logo: ssoMicrosoft.logo || 'microsoft',
      enabled: ssoMicrosoft.enabled,
      configured: msConfigured,
      configure: () => openModal('microsoft'),
      toggle: () => { ssoMicrosoft.enabled = !ssoMicrosoft.enabled; markDirty() },
      remove: removeMicrosoft,
    })
  }

  // LDAP directories.
  ldapDirectories.value.forEach((dir) => {
    rows.push({
      id: 'ldap-' + dir.id,
      name: dir.name,
      logo: dir.logo || 'ldap',
      meta: `LDAP · ${dir.host}:${dir.port}`,
      enabled: ldapEnabledState(dir),
      configured: !!(dir.host && dir.bind_dn),
      configure: () => openLdapConfig(dir),
      toggle: () => stageLdapToggle(dir),
      remove: () => removeLdap(dir),
    })
  })

  // SCIM — only if tokens exist or added this session. No enable flag → no toggle.
  if (tokens.value.length > 0 || scimAdded.value) {
    rows.push({
      id: 'scim',
      name: 'SCIM Provisioning',
      logo: 'scim',
      meta: 'Provisioning · /scim/v2',
      enabled: tokens.value.length > 0,
      configured: tokens.value.length > 0,
      configure: () => {
        if (!hasFetchedScim.value) { hasFetchedScim.value = true; fetchTokens() }
        openModal('scim')
      },
      // SCIM has no backend enable flag — toggle omitted (status derived from tokens).
      remove: removeScim,
    })
  }

  return rows
})

// ── Page-level Save: commit staged toggles + auth-mode in one batch ──────────
async function save() {
  if (!dirty.value || saving.value) return
  saving.value = true
  let anyError = false

  try {
    // OIDC list (carries microsoft + all oidc enabled states).
    if (oidcProviders.value.length > 0 || microsoftAdded.value) {
      try {
        const res = await useMyFetch('/api/organization/sso/oidc', {
          method: 'PUT',
          body: { providers: buildAllOidcPayload() },
        })
        if (res.status.value !== 'success') anyError = true
        else {
          for (const p of oidcProviders.value) {
            if (p.client_secret) { p.client_secret_set = true; p.client_secret = '' }
          }
        }
      } catch { anyError = true }
    }

    // Google enabled state.
    if (methods.value.some(m => m.id === 'google')) {
      try {
        const body: any = { enabled: ssoGoogle.enabled, logo: ssoGoogle.logo, client_id: ssoGoogle.client_id }
        if (ssoGoogle.client_secret) body.client_secret = ssoGoogle.client_secret
        const res = await useMyFetch('/api/organization/sso/google', { method: 'PUT', body })
        if (res.status.value !== 'success') anyError = true
        else if (ssoGoogle.client_secret) { ssoGoogle.client_secret_set = true; ssoGoogle.client_secret = '' }
      } catch { anyError = true }
    }

    // LDAP directories whose enabled changed.
    for (const dir of ldapDirectories.value) {
      if (!(dir.id in ldapStagedEnabled)) continue
      const newEnabled = ldapStagedEnabled[dir.id]
      if (newEnabled === !!dir.enabled) continue
      try {
        const res = await useMyFetch(`/enterprise/ldap/directories/${dir.id}`, {
          method: 'PUT',
          body: { enabled: newEnabled },
        })
        if (res.status.value !== 'success' && (res.error?.value)) anyError = true
        else dir.enabled = newEnabled
      } catch { anyError = true }
    }

    // Auth mode.
    if (ssoAuthMode.value !== authModeBaseline) {
      try {
        const res = await useMyFetch('/api/organization/sso/auth-mode', { method: 'PUT', body: { mode: ssoAuthMode.value } })
        if (res.status.value !== 'success') anyError = true
        else authModeBaseline = ssoAuthMode.value
      } catch { anyError = true }
    }

    if (anyError) {
      toast.add({ title: 'Some changes could not be saved', color: 'red' })
    } else {
      toast.add({ title: 'Changes saved', color: 'green' })
    }
  } finally {
    // Reload truth from server + clear dirty.
    await loadSso()
    await loadLdapDirectories()
    dirty.value = false
    saving.value = false
  }
}

// ── DELETE — double-confirm ──────────────────────────────────────────────────
const removeTarget = ref<MethodRow | null>(null)
const removeAck = ref(false)
const removing = ref(false)

function askRemove(m: MethodRow) {
  removeTarget.value = m
  removeAck.value = false
}
function cancelRemove() {
  removeTarget.value = null
  removeAck.value = false
}
async function confirmRemove() {
  if (!removeTarget.value || !removeAck.value || removing.value) return
  removing.value = true
  try {
    await removeTarget.value.remove()
  } finally {
    removing.value = false
    cancelRemove()
  }
}

async function removeGoogle() {
  try {
    const res = await useMyFetch('/api/organization/sso/google', {
      method: 'PUT',
      body: { enabled: false, logo: 'google', client_id: '' },
    })
    if (res.status.value === 'success') {
      googleAdded.value = false
      ssoGoogle.enabled = false
      ssoGoogle.client_id = ''
      ssoGoogle.client_secret = ''
      ssoGoogle.client_secret_set = false
      toast.add({ title: 'Google removed', color: 'green' })
    } else {
      toast.add({ title: 'Failed to remove Google', color: 'red' })
    }
  } catch {
    toast.add({ title: 'Failed to remove Google', color: 'red' })
  }
}

async function removeMicrosoft() {
  microsoftAdded.value = false
  ssoMicrosoft.enabled = false
  ssoMicrosoft.tenant_id = ''
  ssoMicrosoft.client_id = ''
  ssoMicrosoft.client_secret = ''
  ssoMicrosoft.client_secret_set = false
  // Persist the remaining providers (microsoft now excluded by buildAllOidcPayload).
  try {
    const res = await useMyFetch('/api/organization/sso/oidc', {
      method: 'PUT',
      body: { providers: buildAllOidcPayload() },
    })
    if (res.status.value === 'success') toast.add({ title: 'Microsoft removed', color: 'green' })
    else toast.add({ title: 'Failed to remove Microsoft', color: 'red' })
  } catch {
    toast.add({ title: 'Failed to remove Microsoft', color: 'red' })
  }
}

async function removeOidc(idx: number) {
  oidcProviders.value.splice(idx, 1)
  try {
    const res = await useMyFetch('/api/organization/sso/oidc', {
      method: 'PUT',
      body: { providers: buildAllOidcPayload() },
    })
    if (res.status.value === 'success') toast.add({ title: 'Provider removed', color: 'green' })
    else toast.add({ title: 'Failed to remove provider', color: 'red' })
  } catch {
    toast.add({ title: 'Failed to remove provider', color: 'red' })
  }
}

async function removeLdap(dir: LdapDirectory) {
  try {
    const { error } = await useMyFetch(`/enterprise/ldap/directories/${dir.id}`, { method: 'DELETE' })
    if (error?.value) throw error.value
    delete ldapStagedEnabled[dir.id]
    toast.add({ title: 'Directory removed', color: 'green' })
    await loadLdapDirectories()
  } catch {
    toast.add({ title: 'Failed to remove directory', color: 'red' })
  }
}

async function removeScim() {
  try {
    const ids = tokens.value.map(t => t.id)
    for (const id of ids) {
      await revokeToken(id)
    }
    scimAdded.value = false
    toast.add({ title: 'SCIM provisioning removed', color: 'green' })
  } catch {
    toast.add({ title: 'Failed to remove SCIM provisioning', color: 'red' })
  }
}

// ── Init ──────────────────────────────────────────────────────────────────
watch(
  () => license.value,
  (newLicense) => {
    if (newLicense && hasFeature('scim') && !hasFetchedScim.value) {
      hasFetchedScim.value = true
      fetchTokens()
    }
    if (newLicense && hasFeature('ldap')) {
      loadLdapDirectories()
    }
  },
  { immediate: true }
)

onMounted(() => {
  loadSso()
})
</script>
