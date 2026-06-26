<template>
    <div class="mt-6">
        <!-- Inner tabs -->
        <div class="border-b border-[#E9E0D3] dark:border-gray-700 mb-4">
            <nav class="-mb-px flex space-x-6">
                <button
                    v-for="tab in visibleTabs"
                    :key="tab.key"
                    @click="activeTab = tab.key"
                    :class="[
                        activeTab === tab.key
                            ? 'border-[#C2541E] text-[#C2541E]'
                            : 'border-transparent text-[#6b6b6b] hover:border-[#E9E0D3] hover:text-[#1f2328] dark:hover:text-gray-300',
                    ]"
                    class="whitespace-nowrap border-b-2 py-2 px-1 text-sm font-medium transition-colors"
                >
                    {{ tab.label }}
                </button>
            </nav>
        </div>

        <MembersComponent v-if="activeTab === 'members'" :organization="organization" />
        <RolesManager v-if="activeTab === 'roles'" :organization="organization" />
        <GroupsManager v-if="activeTab === 'groups'" :organization="organization" />
        <QuotaPoliciesManager v-if="activeTab === 'quotas'" :organization="organization" />
        <SignupPolicyManager v-if="activeTab === 'signup'" :organization="organization" />
    </div>
</template>

<script setup lang="ts">
import { useCan } from '~/composables/usePermissions'
import { useEnterprise } from '~/ee/composables/useEnterprise'

const { t } = useI18n()
const { organization } = useOrganization()
const activeTab = ref('members')
const { hasFeature } = useEnterprise()

const tabs = computed(() => [
    { key: 'members', label: t('settings.membersTabs.members') },
    { key: 'roles', label: t('settings.membersTabs.roles'), permission: 'manage_roles', feature: 'custom_roles' },
    { key: 'groups', label: t('settings.membersTabs.groups'), permission: 'manage_groups', feature: 'custom_roles' },
    { key: 'quotas', label: t('settings.membersTabs.quotas'), permission: 'manage_settings', feature: 'usage_limits' },
    { key: 'signup', label: t('settings.membersTabs.signup'), permission: 'full_admin_access', feature: 'domain_signup' },
])

const visibleTabs = computed(() =>
    tabs.value.filter((tab) => {
        if (tab.feature && !hasFeature(tab.feature)) return false
        if (tab.permission && !useCan(tab.permission)) return false
        return true
    })
)

definePageMeta({
    layout: 'settings',
    permissions: ['view_members'],
})
</script>
