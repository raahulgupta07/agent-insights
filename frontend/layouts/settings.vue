<template>
    <NuxtLayout name="default">
        <!-- Canonical Build/Manage page shell: centered, cream, no left rail.
             Each /settings/* tab is its own standalone page (nav lives in the
             top-bar "Settings ▾" dropdown). Title + subtitle come from the
             active tab so every page reads like Monitoring/Queries/etc. -->
        <div class="text-sm bg-[#F1ECE3] h-full overflow-hidden flex flex-col text-[#1f2328]">
                <!-- Overview-matched card shell: 8px gutter + #FBFAF6 card, flush to the rail like every other page -->
                <div class="my-2 me-2 px-6 md:px-8 py-6 bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl flex-1 overflow-y-auto">
                    <!-- Page heading (per-tab) -->
                    <div class="mb-6">
                        <h1
                            class="text-2xl font-semibold text-[#1f2328] tracking-tight"
                            style="font-family: 'Spectral', ui-serif, Georgia, serif"
                        >{{ currentTab ? $t(currentTab.label) : $t('settings.title') }}</h1>
                        <p v-if="currentTab?.description" class="mt-2 text-[#6b6b6b] leading-relaxed max-w-2xl">
                            {{ currentTab.description }}
                        </p>
                    </div>

                    <!-- Page content -->
                    <div class="bg-white border border-[#E9E0D3] rounded-2xl p-6 md:p-8">
                        <slot />
                    </div>
                </div>
        </div>
    </NuxtLayout>
</template>

<script setup lang="ts">
const route = useRoute()

// All available tabs with their required permissions + one-line descriptions.
const allTabs = [
    { name: 'members', label: 'settings.membersTab', requiredPermission: "view_members", description: 'Manage members, roles, and groups.' },
    { name: 'models', label: 'settings.llm', requiredPermission: "manage_llm", description: 'Configure language-model providers and API keys.' },
    { name: 'ai_settings', label: 'settings.aiSettings', requiredPermission: "manage_settings", description: 'Tune agent behaviour and AI defaults.' },
    { name: 'general', label: 'settings.general', requiredPermission: "manage_settings", description: 'Workspace name, branding, and general preferences.' },
    { name: "integrations", label: "settings.integrations.title", requiredPermission: "manage_settings", description: 'Connect external channels and integrations.' },
    { name: 'connectors', label: 'Connectors', requiredPermission: "manage_connections", description: 'Configure Microsoft connector templates (tenant, SQL endpoint) once. Members then sign in with their own account from the Data Agents page.' },
    { name: 'folder-sync', label: 'Folder Sync', requiredPermission: "manage_settings", description: 'Auto-ingest a local folder into an agent via the desktop sync app — like Claude Code.' },
    { name: 'kb-sources', label: 'Knowledge Sources', requiredPermission: "manage_settings", description: 'Sync Notion pages and Slack channels into the knowledge base. Synced docs land in Knowledge → Review for approval before they ground answers.' },
    { name: 'audit', label: 'settings.auditLogs', requiredPermission: "view_audit_logs", description: 'Review activity and security events across the workspace.' },
    { name: 'identity-provider', label: 'settings.identityProviderTab', requiredPermission: "manage_identity_providers", description: 'Configure SSO, SCIM provisioning, and LDAP.' },
    { name: 'smtp', label: 'settings.smtpTab', requiredPermission: "manage_settings", description: 'Configure outbound email delivery.' },
    { name: 'features', label: 'Feature Flags', requiredPermission: "manage_settings", description: 'Toggle hybrid feature flags and experimental capabilities.' },
    { name: 'pack-analytics', label: 'Pack Analytics', requiredPermission: "manage_settings", description: 'Org-wide observability for Domain Packs (Skills) — binding, fires, and win-rate.' },
]

// The tab whose route is active (drives the page title + subtitle).
const currentTab = computed(() =>
    allTabs.find(tab => route.path === `/settings/${tab.name}`) || null
)
</script>
