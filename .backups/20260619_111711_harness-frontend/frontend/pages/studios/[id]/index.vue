<template>
    <div class="flex justify-center ps-2 md:ps-4 text-sm h-full">
        <div class="w-full max-w-7xl px-4 ps-0 py-2 h-full">
            <!-- Loading -->
            <div v-if="loading" class="flex flex-col items-center justify-center py-20">
                <Spinner class="h-4 w-4 text-gray-400" />
                <p class="text-sm text-gray-500 mt-2">{{ $t('common.loading') }}</p>
            </div>

            <!-- Not found / no access -->
            <div v-else-if="notFound" class="flex flex-col items-center justify-center py-20 text-center">
                <UIcon name="i-heroicons-film" class="w-10 h-10 text-gray-300 mb-3" />
                <h3 class="text-sm font-medium text-gray-700">{{ $t('studio.notFound') }}</h3>
                <p class="mt-1 text-xs text-gray-500 max-w-md">{{ $t('studio.notFoundHint') }}</p>
                <UButton color="gray" variant="outline" size="xs" class="mt-4" @click="router.push('/studios')">
                    {{ $t('studio.backToStudios') }}
                </UButton>
            </div>

            <template v-else-if="studio">
                <!-- Header -->
                <div class="flex items-start justify-between mb-4">
                    <div class="flex items-start gap-3 min-w-0">
                        <button class="text-gray-400 hover:text-gray-700 mt-1" @click="router.push('/studios')" :title="$t('studio.backToStudios')">
                            <UIcon name="i-heroicons-arrow-left" class="w-4 h-4" />
                        </button>
                        <div class="shrink-0 flex items-center justify-center w-9 h-9 rounded-md bg-gray-100 text-lg overflow-hidden">
                            <img v-if="isImageAvatar" :src="studio.avatar || ''" alt="" class="w-full h-full object-cover" />
                            <span v-else-if="studio.avatar">{{ studio.avatar }}</span>
                            <UIcon v-else name="i-heroicons-film" class="w-5 h-5 text-gray-400" />
                        </div>
                        <div class="min-w-0">
                            <div class="flex items-center gap-2">
                                <h1 class="text-lg font-semibold truncate">{{ studio.name }}</h1>
                                <span :class="scopeBadgeClass" class="text-[9px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded">{{ scopeLabel }}</span>
                            </div>
                            <p v-if="studio.description" class="text-xs text-gray-500 line-clamp-1">{{ studio.description }}</p>
                        </div>
                    </div>
                    <div class="flex items-center gap-2 shrink-0">
                        <UButton color="gray" variant="outline" size="xs" icon="i-heroicons-share" @click="showShare = true">
                            {{ $t('studio.tabMembers') }}
                        </UButton>
                    </div>
                </div>

                <!-- Read-only banner -->
                <div v-if="role === 'viewer'" class="mb-3 flex items-center gap-2 text-[11px] text-gray-500 bg-gray-50 border border-gray-200 rounded-md px-3 py-1.5">
                    <UIcon name="i-heroicons-eye" class="w-3.5 h-3.5" />
                    {{ $t('studio.readOnly') }}
                </div>

                <!-- Tabs -->
                <div class="flex items-center gap-1 mb-4 border-b border-gray-200">
                    <button
                        v-for="tab in tabs"
                        :key="tab.value"
                        type="button"
                        class="px-3 py-2 text-xs font-medium -mb-px border-b-2 transition-colors inline-flex items-center gap-1.5"
                        :class="activeTab === tab.value
                            ? 'border-blue-500 text-blue-600'
                            : 'border-transparent text-gray-500 hover:text-gray-800'"
                        @click="activeTab = tab.value"
                    >
                        <UIcon :name="tab.icon" class="w-3.5 h-3.5" />
                        {{ tab.label }}
                    </button>
                </div>

                <!-- Tab content -->
                <div class="grid grid-cols-1 lg:grid-cols-[200px_minmax(0,1fr)] gap-6">
                    <!-- Sources rail (always visible on lg) -->
                    <aside class="hidden lg:block">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-[11px] font-medium text-gray-400 uppercase tracking-wider">{{ $t('studio.sourcesTitle') }}</span>
                        </div>
                        <ul v-if="sources.length" class="space-y-1 mb-2">
                            <li
                                v-for="s in sources"
                                :key="s.id"
                                class="group flex items-center gap-1.5 text-xs text-gray-600 rounded px-2 py-1 hover:bg-gray-50"
                            >
                                <DataSourceIcon v-if="s.type" class="h-3.5 shrink-0" :type="s.type" />
                                <UIcon v-else name="i-heroicons-circle-stack" class="w-3.5 h-3.5 shrink-0 text-gray-400" />
                                <span class="truncate flex-1">{{ s.name || s.agent_id }}</span>
                                <button
                                    v-if="canEdit"
                                    class="text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100"
                                    :title="$t('studio.unpin')"
                                    @click="unpinSource(s.agent_id)"
                                >
                                    <UIcon name="i-heroicons-x-mark" class="w-3.5 h-3.5" />
                                </button>
                            </li>
                        </ul>
                        <p v-else class="text-[11px] text-gray-400 mb-2">{{ $t('studio.noSources') }}</p>
                        <UButton
                            v-if="canEdit"
                            color="gray"
                            variant="outline"
                            size="2xs"
                            icon="i-heroicons-plus"
                            block
                            @click="openAddSource"
                        >
                            {{ $t('studio.addConnection') }}
                        </UButton>
                    </aside>

                    <!-- Main panel -->
                    <div class="min-w-0">
                        <!-- CHAT -->
                        <section v-if="activeTab === 'chat'">
                            <div class="flex items-start justify-between mb-4">
                                <div>
                                    <h2 class="text-sm font-semibold text-gray-900">{{ $t('studio.chatTitle') }}</h2>
                                    <p class="text-xs text-gray-500 mt-0.5">{{ $t('studio.chatHint') }}</p>
                                </div>
                                <UTooltip :text="sources.length === 0 ? $t('studio.needSourcesForChat') : $t('studio.newChat')">
                                    <UButton
                                        color="blue"
                                        size="xs"
                                        icon="i-heroicons-plus"
                                        :loading="creatingChat"
                                        :disabled="sources.length === 0"
                                        @click="startChat"
                                    >
                                        {{ $t('studio.newChat') }}
                                    </UButton>
                                </UTooltip>
                            </div>

                            <div v-if="loadingChats" class="flex items-center justify-center py-10 text-gray-400">
                                <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
                            </div>
                            <div v-else-if="chats.length === 0" class="py-10 text-center border border-dashed border-gray-200 rounded-lg">
                                <UIcon name="i-heroicons-chat-bubble-left-right" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
                                <p class="text-xs text-gray-500">{{ $t('studio.noChats') }}</p>
                            </div>
                            <ul v-else class="divide-y divide-gray-100 border border-gray-100 rounded-lg overflow-hidden">
                                <li
                                    v-for="c in chats"
                                    :key="c.id"
                                    class="flex items-center justify-between px-3 py-2.5 bg-white hover:bg-gray-50 cursor-pointer"
                                    @click="openChat(c.id)"
                                >
                                    <div class="flex items-center gap-2 min-w-0">
                                        <UIcon name="i-heroicons-chat-bubble-left-right" class="w-4 h-4 text-gray-400 shrink-0" />
                                        <span class="text-xs text-gray-800 truncate">{{ c.title || 'untitled report' }}</span>
                                    </div>
                                    <UIcon name="i-heroicons-arrow-top-right-on-square" class="w-3.5 h-3.5 text-gray-300 shrink-0" />
                                </li>
                            </ul>
                        </section>

                        <!-- SOURCES -->
                        <section v-else-if="activeTab === 'sources'">
                            <div class="flex items-start justify-between mb-4">
                                <div>
                                    <h2 class="text-sm font-semibold text-gray-900">{{ $t('studio.sourcesTitle') }}</h2>
                                    <p class="text-xs text-gray-500 mt-0.5">{{ $t('studio.sourcesHint') }}</p>
                                </div>
                                <UButton v-if="canEdit" color="blue" size="xs" icon="i-heroicons-plus" @click="openAddSource">
                                    {{ $t('studio.addConnection') }}
                                </UButton>
                            </div>

                            <div v-if="sources.length === 0" class="py-10 text-center border border-dashed border-gray-200 rounded-lg">
                                <UIcon name="i-heroicons-circle-stack" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
                                <p class="text-xs text-gray-500">{{ $t('studio.noSources') }}</p>
                            </div>
                            <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
                                <div
                                    v-for="s in sources"
                                    :key="s.id"
                                    class="flex items-center justify-between p-3 rounded-lg border border-gray-100 bg-white"
                                >
                                    <div class="flex items-center gap-2 min-w-0">
                                        <DataSourceIcon v-if="s.type" class="h-4 shrink-0" :type="s.type" />
                                        <UIcon v-else name="i-heroicons-circle-stack" class="w-4 h-4 shrink-0 text-gray-400" />
                                        <span class="text-xs font-medium text-gray-800 truncate">{{ s.name || s.agent_id }}</span>
                                    </div>
                                    <UButton
                                        v-if="canEdit"
                                        color="gray"
                                        variant="ghost"
                                        size="2xs"
                                        icon="i-heroicons-x-mark"
                                        @click="unpinSource(s.agent_id)"
                                    >
                                        {{ $t('studio.unpin') }}
                                    </UButton>
                                </div>
                            </div>
                        </section>

                        <!-- SKILLS -->
                        <section v-else-if="activeTab === 'skills'">
                            <div class="flex items-start justify-between mb-4">
                                <div>
                                    <h2 class="text-sm font-semibold text-gray-900">{{ $t('studio.skillsTitle') }}</h2>
                                    <p class="text-xs text-gray-500 mt-0.5">{{ $t('studio.skillsHint') }}</p>
                                </div>
                                <UButton v-if="canEdit" color="blue" size="xs" icon="i-heroicons-plus" @click="openAddSkill">
                                    {{ $t('studio.pinSkill') }}
                                </UButton>
                            </div>

                            <div v-if="loadingSkills" class="flex items-center justify-center py-10 text-gray-400">
                                <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
                            </div>
                            <div v-else-if="pinnedSkills.length === 0" class="py-10 text-center border border-dashed border-gray-200 rounded-lg">
                                <UIcon name="i-heroicons-sparkles" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
                                <p class="text-xs text-gray-500">{{ $t('studio.noSkillsPinned') }}</p>
                            </div>
                            <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3">
                                <div
                                    v-for="sk in pinnedSkills"
                                    :key="sk.id"
                                    class="flex items-start justify-between p-3 rounded-lg border border-gray-100 bg-white"
                                >
                                    <div class="min-w-0">
                                        <div class="flex items-center gap-1.5">
                                            <UIcon name="i-heroicons-sparkles" class="w-3.5 h-3.5 text-amber-500 shrink-0" />
                                            <span class="text-xs font-medium text-gray-800 truncate">{{ sk.name }}</span>
                                        </div>
                                        <p v-if="sk.description" class="text-[11px] text-gray-500 line-clamp-2 mt-0.5">{{ sk.description }}</p>
                                    </div>
                                    <UButton
                                        v-if="canEdit"
                                        color="gray"
                                        variant="ghost"
                                        size="2xs"
                                        icon="i-heroicons-x-mark"
                                        @click="unpinSkill(sk.id)"
                                    >
                                        {{ $t('studio.unpinSkill') }}
                                    </UButton>
                                </div>
                            </div>
                        </section>

                        <!-- ARTIFACTS -->
                        <section v-else-if="activeTab === 'artifacts'">
                            <ArtifactsPanel :studio-id="studioId" :can-edit="canEdit" />
                        </section>

                        <!-- MEMBERS / SHARE -->
                        <section v-else-if="activeTab === 'members'">
                            <div class="flex items-start justify-between mb-4">
                                <div>
                                    <h2 class="text-sm font-semibold text-gray-900">{{ $t('studio.membersTitle') }}</h2>
                                    <p class="text-xs text-gray-500 mt-0.5">{{ $t('studio.membersHint') }}</p>
                                </div>
                                <UButton color="blue" size="xs" icon="i-heroicons-share" @click="showShare = true">
                                    {{ $t('studio.shareTitle') }}
                                </UButton>
                            </div>
                            <p class="text-xs text-gray-500">
                                {{ $t('studio.shareScope') }}: <span class="font-medium text-gray-700">{{ scopeLabel }}</span>
                            </p>
                            <UButton class="mt-3" color="gray" variant="soft" size="xs" icon="i-heroicons-users" @click="showShare = true">
                                {{ $t('studio.tabMembers') }}
                            </UButton>

                            <div v-if="role === 'owner'" class="mt-8 pt-4 border-t border-gray-100">
                                <UButton color="red" variant="outline" size="xs" icon="i-heroicons-trash" :loading="deleting" @click="deleteStudio">
                                    {{ $t('studio.deleteStudio') }}
                                </UButton>
                            </div>
                        </section>
                    </div>
                </div>
            </template>

            <!-- Share modal -->
            <ShareModal
                v-if="studio"
                v-model="showShare"
                :studio-id="studioId"
                :owner-user-id="String(studio.owner_user_id)"
                :can-manage="role === 'owner'"
                :share-scope="studio.share_scope"
                :share-token="studio.share_token"
                @updated="onShareUpdated"
            />

            <!-- Add source modal -->
            <UModal v-model="showAddSource" :ui="{ width: 'sm:max-w-md' }">
                <div class="p-6">
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-lg font-medium text-gray-900">{{ $t('studio.pickSource') }}</h2>
                        <button @click="showAddSource = false" class="text-gray-400 hover:text-gray-600">
                            <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
                        </button>
                    </div>
                    <div v-if="loadingAgents" class="flex items-center justify-center py-8 text-gray-400">
                        <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
                    </div>
                    <div v-else-if="pinnableAgents.length === 0" class="py-8 text-center text-xs text-gray-500">
                        {{ $t('studio.noAgentsToPin') }}
                    </div>
                    <ul v-else class="space-y-1 max-h-80 overflow-y-auto">
                        <li
                            v-for="a in pinnableAgents"
                            :key="a.id"
                            class="flex items-center justify-between gap-2 rounded-md px-2 py-2 hover:bg-gray-50 cursor-pointer"
                            @click="pinSource(a)"
                        >
                            <div class="flex items-center gap-2 min-w-0">
                                <DataSourceIcon v-if="(a.connections || [])[0]?.type" class="h-4 shrink-0" :type="(a.connections || [])[0]?.type" />
                                <UIcon v-else name="i-heroicons-circle-stack" class="w-4 h-4 shrink-0 text-gray-400" />
                                <span class="text-xs text-gray-800 truncate">{{ a.name }}</span>
                            </div>
                            <UIcon name="i-heroicons-plus" class="w-3.5 h-3.5 text-gray-400 shrink-0" />
                        </li>
                    </ul>
                </div>
            </UModal>

            <!-- Add skill modal -->
            <UModal v-model="showAddSkill" :ui="{ width: 'sm:max-w-md' }">
                <div class="p-6">
                    <div class="flex items-center justify-between mb-4">
                        <h2 class="text-lg font-medium text-gray-900">{{ $t('studio.pinSkill') }}</h2>
                        <button @click="showAddSkill = false" class="text-gray-400 hover:text-gray-600">
                            <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
                        </button>
                    </div>
                    <div v-if="loadingAllSkills" class="flex items-center justify-center py-8 text-gray-400">
                        <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
                    </div>
                    <div v-else-if="pinnableSkills.length === 0" class="py-8 text-center text-xs text-gray-500">
                        {{ $t('studio.noSkillsToPin') }}
                    </div>
                    <ul v-else class="space-y-1 max-h-80 overflow-y-auto">
                        <li
                            v-for="sk in pinnableSkills"
                            :key="sk.id"
                            class="flex items-center justify-between gap-2 rounded-md px-2 py-2 hover:bg-gray-50 cursor-pointer"
                            @click="pinSkill(sk)"
                        >
                            <div class="min-w-0">
                                <div class="flex items-center gap-1.5">
                                    <UIcon name="i-heroicons-sparkles" class="w-3.5 h-3.5 text-amber-500 shrink-0" />
                                    <span class="text-xs text-gray-800 truncate">{{ sk.name }}</span>
                                </div>
                                <p v-if="sk.description" class="text-[11px] text-gray-400 line-clamp-1">{{ sk.description }}</p>
                            </div>
                            <UIcon name="i-heroicons-plus" class="w-3.5 h-3.5 text-gray-400 shrink-0" />
                        </li>
                    </ul>
                </div>
            </UModal>
        </div>
    </div>
</template>

<script setup lang="ts">
import ShareModal from '~/components/studio/ShareModal.vue'
import ArtifactsPanel from '~/components/studio/ArtifactsPanel.vue'
import DataSourceIcon from '~/components/DataSourceIcon.vue'
import Spinner from '~/components/Spinner.vue'

definePageMeta({ auth: true, layout: 'default' })

interface Studio {
    id: string
    name: string
    description?: string | null
    persona?: string | null
    avatar?: string | null
    owner_user_id: string
    share_scope: string
    share_token?: string | null
    config?: Record<string, any>
}
interface Source { id: string; studio_id: string; agent_id: string; name?: string | null; type?: string | null }
interface SkillItem { id: string; name: string; description?: string | null; scope?: string; status?: string }
interface ChatItem { id: string; title?: string; studio_id?: string }

const { t } = useI18n()
const toast = useToast()
const route = useRoute()
const router = useRouter()
const { data: currentUser } = useAuth()

const studioId = computed(() => String(route.params.id))

const studio = ref<Studio | null>(null)
const role = ref<string>('viewer')
const loading = ref(true)
const notFound = ref(false)

const sources = ref<Source[]>([])
const pinnedSkills = ref<SkillItem[]>([])
const loadingSkills = ref(false)
const chats = ref<ChatItem[]>([])
const loadingChats = ref(false)

const activeTab = ref('chat')
const showShare = ref(false)
const showAddSource = ref(false)
const showAddSkill = ref(false)
const deleting = ref(false)
const creatingChat = ref(false)

const tabs = computed(() => [
    { value: 'chat', label: t('studio.tabChat'), icon: 'i-heroicons-chat-bubble-left-right' },
    { value: 'sources', label: t('studio.tabSources'), icon: 'i-heroicons-circle-stack' },
    { value: 'skills', label: t('studio.tabSkills'), icon: 'i-heroicons-sparkles' },
    { value: 'artifacts', label: t('studio.tabArtifacts'), icon: 'i-heroicons-document-text' },
    { value: 'members', label: t('studio.tabMembers'), icon: 'i-heroicons-users' },
])

// Owner derives editor+viewer; the page reads `role` returned from the studio
// access path. The backend GET doesn't return the caller role, so we infer it:
// owner_user_id match → owner; otherwise default viewer (editor actions still
// enforced server-side, which gives the authoritative answer on write).
const canEdit = computed(() => role.value === 'owner' || role.value === 'editor')

const isImageAvatar = computed(() => {
    const a = studio.value?.avatar || ''
    return /^https?:\/\//.test(a) || a.startsWith('/')
})
const scopeLabel = computed(() => {
    const s = (studio.value?.share_scope || 'private').toLowerCase()
    if (s === 'org') return t('studio.scopeOrg')
    if (s === 'link') return t('studio.scopeLink')
    return t('studio.scopePrivate')
})
const scopeBadgeClass = computed(() => {
    const s = (studio.value?.share_scope || 'private').toLowerCase()
    if (s === 'org') return 'bg-blue-100 text-blue-700'
    if (s === 'link') return 'bg-purple-100 text-purple-700'
    return 'bg-gray-100 text-gray-600'
})

const fetchStudio = async () => {
    loading.value = true
    notFound.value = false
    try {
        const { data, error } = await useMyFetch<Studio>(`/studios/${studioId.value}`, { method: 'GET' })
        if (error?.value) throw error.value
        studio.value = data.value
        // Infer caller role from ownership; editor/viewer distinction is enforced
        // server-side on write. Owner gets the management UI.
        const uid = String((currentUser.value as any)?.id ?? '')
        role.value = studio.value && String(studio.value.owner_user_id) === uid ? 'owner' : 'editor'
    } catch (e: any) {
        console.error('Failed to load studio:', e)
        notFound.value = true
    } finally {
        loading.value = false
    }
}

const fetchSources = async () => {
    try {
        const { data, error } = await useMyFetch<Source[]>(`/studios/${studioId.value}/sources`, { method: 'GET' })
        if (error?.value) throw error.value
        sources.value = data.value || []
    } catch (e: any) {
        if (e?.statusCode === 404 || e?.status === 404) sources.value = []
        else console.error('Failed to load sources:', e)
    }
}

const fetchPinnedSkills = async () => {
    loadingSkills.value = true
    try {
        const { data, error } = await useMyFetch<SkillItem[]>(`/studios/${studioId.value}/skills`, { method: 'GET' })
        if (error?.value) throw error.value
        pinnedSkills.value = data.value || []
    } catch (e: any) {
        // 404 = studio_skills route not available yet → empty, don't crash.
        if (e?.statusCode === 404 || e?.status === 404) pinnedSkills.value = []
        else console.error('Failed to load pinned skills:', e)
    } finally {
        loadingSkills.value = false
    }
}

const fetchChats = async () => {
    loadingChats.value = true
    try {
        // No studio_id filter on /reports, so fetch the user's reports and filter
        // client-side by studio_id. Bounded by limit.
        const { data, error } = await useMyFetch<any>('/reports?filter=my&limit=50', { method: 'GET' })
        if (error?.value) throw error.value
        const items = (data.value?.reports || data.value?.items || data.value || []) as any[]
        chats.value = items.filter((r: any) => String(r.studio_id || '') === studioId.value)
    } catch (e: any) {
        console.error('Failed to load studio chats:', e)
        chats.value = []
    } finally {
        loadingChats.value = false
    }
}

// ---- sources ----
const allAgents = ref<any[]>([])
const loadingAgents = ref(false)
const pinnableAgents = computed(() => {
    const pinnedIds = new Set(sources.value.map(s => String(s.agent_id)))
    return allAgents.value.filter(a => !pinnedIds.has(String(a.id)))
})

const openAddSource = async () => {
    showAddSource.value = true
    loadingAgents.value = true
    try {
        const { data, error } = await useMyFetch<any[]>('/data_sources', { method: 'GET' })
        if (error?.value) throw error.value
        allAgents.value = data.value || []
    } catch (e: any) {
        console.error('Failed to load data sources:', e)
        allAgents.value = []
    } finally {
        loadingAgents.value = false
    }
}

const pinSource = async (agent: any) => {
    try {
        const { error } = await useMyFetch(`/studios/${studioId.value}/sources`, {
            method: 'POST',
            body: { agent_id: String(agent.id) },
        })
        if (error?.value) throw error.value
        showAddSource.value = false
        await fetchSources()
    } catch (e: any) {
        console.error('Failed to pin source:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    }
}

const unpinSource = async (agentId: string) => {
    try {
        const { error } = await useMyFetch(`/studios/${studioId.value}/sources/${agentId}`, { method: 'DELETE' })
        if (error?.value) throw error.value
        await fetchSources()
    } catch (e: any) {
        console.error('Failed to unpin source:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    }
}

// ---- skills ----
const allSkills = ref<SkillItem[]>([])
const loadingAllSkills = ref(false)
const pinnableSkills = computed(() => {
    const pinnedIds = new Set(pinnedSkills.value.map(s => String(s.id)))
    return allSkills.value.filter(s => !pinnedIds.has(String(s.id)))
})

const openAddSkill = async () => {
    showAddSkill.value = true
    loadingAllSkills.value = true
    try {
        const { data, error } = await useMyFetch<SkillItem[]>('/skills', { method: 'GET' })
        if (error?.value) throw error.value
        allSkills.value = data.value || []
    } catch (e: any) {
        console.error('Failed to load skills:', e)
        allSkills.value = []
    } finally {
        loadingAllSkills.value = false
    }
}

const pinSkill = async (skill: SkillItem) => {
    try {
        const { error } = await useMyFetch(`/studios/${studioId.value}/skills`, {
            method: 'POST',
            body: { skill_id: String(skill.id) },
        })
        if (error?.value) throw error.value
        showAddSkill.value = false
        await fetchPinnedSkills()
    } catch (e: any) {
        console.error('Failed to pin skill:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    }
}

const unpinSkill = async (skillId: string) => {
    try {
        const { error } = await useMyFetch(`/studios/${studioId.value}/skills/${skillId}`, { method: 'DELETE' })
        if (error?.value) throw error.value
        await fetchPinnedSkills()
    } catch (e: any) {
        console.error('Failed to unpin skill:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    }
}

// ---- chat ----
// Lightest integration: create a report carrying studio_id + the studio's pinned
// sources, then navigate to the existing report chat UI (/reports/{id}).
const startChat = async () => {
    if (sources.value.length === 0) return
    creatingChat.value = true
    try {
        const { data, error } = await useMyFetch<any>('/reports', {
            method: 'POST',
            body: {
                title: `${studio.value?.name || 'Studio'} chat`,
                files: [],
                data_sources: sources.value.map(s => String(s.agent_id)),
                studio_id: studioId.value,
            },
        })
        if (error?.value) throw error.value
        const created = data.value
        if (created?.id) router.push(`/reports/${created.id}`)
    } catch (e: any) {
        console.error('Failed to start studio chat:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    } finally {
        creatingChat.value = false
    }
}

const openChat = (reportId: string) => router.push(`/reports/${reportId}`)

// ---- share / delete ----
const onShareUpdated = (payload: { share_scope: string; share_token: string | null }) => {
    if (studio.value) {
        studio.value.share_scope = payload.share_scope
        studio.value.share_token = payload.share_token
    }
}

const deleteStudio = async () => {
    if (!window.confirm(t('studio.deleteConfirm'))) return
    deleting.value = true
    try {
        const { error } = await useMyFetch(`/studios/${studioId.value}`, { method: 'DELETE' })
        if (error?.value) throw error.value
        toast.add({ title: t('studio.studioDeleted'), color: 'green', icon: 'i-heroicons-check-circle' })
        router.push('/studios')
    } catch (e: any) {
        console.error('Failed to delete studio:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    } finally {
        deleting.value = false
    }
}

onMounted(async () => {
    await fetchStudio()
    if (!notFound.value) {
        await Promise.all([fetchSources(), fetchPinnedSkills(), fetchChats()])
    }
})
</script>

<style scoped>
.line-clamp-1 {
    display: -webkit-box;
    -webkit-line-clamp: 1;
    line-clamp: 1;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
</style>
