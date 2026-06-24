<template>
    <div class="flex justify-center ps-2 md:ps-4 text-sm h-full">
        <div class="w-full max-w-7xl px-4 ps-0 py-2 h-full">
            <div class="flex flex-col h-[calc(100vh-100px)]">
                <!-- Header -->
                <div class="flex items-start justify-between mb-6 shrink-0">
                    <div>
                        <h1 class="text-lg font-semibold">Skills</h1>
                        <p class="mt-2 text-gray-500">
                            Reusable SKILL.md playbooks the agent can load on demand. Authored from a
                            solved chat via "Save as skill", scoped personal, org, or global.
                        </p>
                    </div>
                </div>

                <!-- Author from completion -->
                <div class="flex items-center gap-2 mb-4 shrink-0">
                    <UInput
                        v-model="completionId"
                        placeholder="Completion ID"
                        size="sm"
                        class="w-64"
                        :disabled="authoring"
                        @keyup.enter="authorFromCompletion"
                    />
                    <UButton
                        icon="i-heroicons-sparkles"
                        color="blue"
                        size="xs"
                        :loading="authoring"
                        :disabled="!completionId.trim()"
                        @click="authorFromCompletion"
                    >
                        Author from completion
                    </UButton>
                    <span class="text-xs text-gray-400">
                        Drafts a personal skill from a solved completion.
                    </span>
                </div>

                <!-- Author error -->
                <div v-if="authorError" class="mb-4 shrink-0 bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">
                    {{ authorError }}
                </div>

                <!-- List -->
                <div class="flex-1 min-h-0 overflow-y-auto">
                    <!-- Loading -->
                    <div v-if="loading" class="flex items-center justify-center py-16 text-gray-400">
                        <Icon name="heroicons:arrow-path" class="w-5 h-5 animate-spin me-2" />
                        <span class="text-sm">Loading skills…</span>
                    </div>

                    <!-- Error -->
                    <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
                        {{ error }}
                        <UButton color="red" variant="ghost" size="xs" class="ms-2" @click="fetchSkills">
                            Retry
                        </UButton>
                    </div>

                    <!-- Empty state -->
                    <div v-else-if="skills.length === 0" class="flex flex-col items-center justify-center py-16 text-center">
                        <Icon name="heroicons:sparkles" class="w-10 h-10 text-gray-300 mb-3" />
                        <h3 class="text-sm font-medium text-gray-700">No skills yet</h3>
                        <p class="mt-1 text-xs text-gray-500 max-w-md">
                            Skills are authored from a solved chat using the "Save as skill" action on
                            a completion. Once authored, they appear here as personal drafts you can
                            review and promote to your organization.
                        </p>
                    </div>

                    <!-- Skills table -->
                    <div v-else class="border border-gray-200 rounded-lg overflow-hidden">
                        <table class="min-w-full divide-y divide-gray-200">
                            <thead class="bg-gray-50">
                                <tr>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">Name</th>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">Description</th>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">Scope</th>
                                    <th class="px-4 py-2 text-left text-xs font-medium text-gray-500">Status</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-gray-100 bg-white">
                                <tr
                                    v-for="skill in skills"
                                    :key="skill.id"
                                    class="hover:bg-gray-50 cursor-pointer"
                                    @click="openSkill(skill)"
                                >
                                    <td class="px-4 py-2">
                                        <div class="flex items-center gap-2">
                                            <Icon name="heroicons:sparkles" class="w-4 h-4 text-amber-500 shrink-0" />
                                            <span class="font-medium text-gray-900">{{ skill.name }}</span>
                                        </div>
                                    </td>
                                    <td class="px-4 py-2 text-gray-600 max-w-md">
                                        <span class="line-clamp-2">{{ skill.description || '—' }}</span>
                                    </td>
                                    <td class="px-4 py-2">
                                        <span :class="scopeBadgeClass(skill.scope)" class="px-2 py-0.5 rounded text-xs font-medium">
                                            {{ scopeLabel(skill.scope) }}
                                        </span>
                                    </td>
                                    <td class="px-4 py-2 text-gray-500">
                                        <span v-if="skill.status" class="text-xs">{{ skill.status }}</span>
                                        <span v-else class="text-xs text-gray-400">—</span>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- Details modal -->
                <SkillDetailsModal
                    v-model="showDetailsModal"
                    :skill="selectedSkill"
                    @promoted="handleChanged"
                    @deleted="handleChanged"
                />
            </div>
        </div>
    </div>
</template>

<script setup lang="ts">
import SkillDetailsModal from '~/components/SkillDetailsModal.vue'

definePageMeta({
    auth: true,
    layout: 'default'
})

interface Skill {
    id: string
    name: string
    description?: string
    scope?: string
    status?: string
}

const skills = ref<Skill[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const completionId = ref('')
const authoring = ref(false)
const authorError = ref<string | null>(null)

const showDetailsModal = ref(false)
const selectedSkill = ref<Skill | null>(null)

const scopeLabel = (scope?: string) => {
    const s = (scope || '').toLowerCase()
    if (s === 'org' || s === 'organization') return 'Organization'
    if (s === 'global') return 'Global'
    return 'Personal'
}

const scopeBadgeClass = (scope?: string) => {
    const s = (scope || '').toLowerCase()
    if (s === 'org' || s === 'organization') return 'bg-blue-100 text-blue-700'
    if (s === 'global') return 'bg-purple-100 text-purple-700'
    return 'bg-gray-100 text-gray-700'
}

const fetchSkills = async () => {
    loading.value = true
    error.value = null
    try {
        const { data, error: fetchErr } = await useMyFetch<Skill[]>('/api/skills', { method: 'GET' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        skills.value = data.value || []
    } catch (e: any) {
        console.error('Failed to fetch skills:', e)
        error.value = 'Failed to load skills.'
    } finally {
        loading.value = false
    }
}

const openSkill = (skill: Skill) => {
    selectedSkill.value = skill
    showDetailsModal.value = true
}

const authorFromCompletion = async () => {
    const id = completionId.value.trim()
    if (!id) return
    authoring.value = true
    authorError.value = null
    try {
        const { error: fetchErr } = await useMyFetch(`/api/skills/from-completion/${id}`, { method: 'POST' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        completionId.value = ''
        await fetchSkills()
    } catch (e: any) {
        console.error('Failed to author skill from completion:', e)
        authorError.value = 'Failed to author skill from that completion. Check the completion ID.'
    } finally {
        authoring.value = false
    }
}

const handleChanged = () => {
    fetchSkills()
}

onMounted(() => {
    fetchSkills()
})
</script>
