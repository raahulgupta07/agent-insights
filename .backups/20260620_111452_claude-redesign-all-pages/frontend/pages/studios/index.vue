<template>
    <div class="flex justify-center ps-2 md:ps-4 text-sm h-full">
        <div class="w-full max-w-7xl px-4 ps-0 py-2 h-full">
            <!-- Header -->
            <div class="flex items-start justify-between mb-6">
                <div>
                    <h1 class="text-lg font-semibold">{{ $t('studio.title') }}</h1>
                    <p class="mt-2 text-gray-500 max-w-2xl">{{ $t('studio.subtitle') }}</p>
                </div>
                <UButton
                    v-if="!disabled"
                    color="blue"
                    size="xs"
                    icon="i-heroicons-plus"
                    @click="openCreate"
                >
                    {{ $t('studio.newStudio') }}
                </UButton>
            </div>

            <!-- Disabled (flag off) -->
            <div v-if="disabled" class="flex flex-col items-center justify-center py-20 text-center">
                <UIcon name="i-heroicons-lock-closed" class="w-10 h-10 text-gray-300 mb-3" />
                <h3 class="text-sm font-medium text-gray-700">{{ $t('studio.disabled') }}</h3>
                <p class="mt-1 text-xs text-gray-500 max-w-md">{{ $t('studio.disabledHint') }}</p>
            </div>

            <!-- Loading -->
            <div v-else-if="loading" class="flex flex-col items-center justify-center py-20">
                <Spinner class="h-4 w-4 text-gray-400" />
                <p class="text-sm text-gray-500 mt-2">{{ $t('common.loading') }}</p>
            </div>

            <!-- Error -->
            <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
                {{ $t('studio.loadError') }}
                <UButton color="red" variant="ghost" size="xs" class="ms-2" @click="fetchStudios">
                    {{ $t('common.retry') }}
                </UButton>
            </div>

            <template v-else>
                <!-- Your Studios -->
                <section class="mb-8">
                    <h2 class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">{{ $t('studio.yourStudios') }}</h2>

                    <div v-if="ownStudios.length === 0" class="py-12 text-center border border-dashed border-gray-200 rounded-lg">
                        <UIcon name="i-heroicons-film" class="w-8 h-8 mx-auto text-gray-300 mb-2" />
                        <p class="text-sm text-gray-500 mb-1">{{ $t('studio.empty') }}</p>
                        <p class="text-xs text-gray-400 mb-4 max-w-md mx-auto">{{ $t('studio.emptyHint') }}</p>
                        <UButton color="blue" size="xs" icon="i-heroicons-plus" @click="openCreate">
                            {{ $t('studio.newStudio') }}
                        </UButton>
                    </div>

                    <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        <StudioCard
                            v-for="s in ownStudios"
                            :key="s.id"
                            :studio="s"
                            @open="goto(s.id)"
                            @chat="startStudioChat(s)"
                        />
                    </div>
                </section>

                <!-- Shared with you -->
                <section v-if="sharedStudios.length > 0">
                    <h2 class="text-xs font-medium text-gray-400 uppercase tracking-wider mb-3">{{ $t('studio.sharedWithYou') }}</h2>
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                        <StudioCard
                            v-for="s in sharedStudios"
                            :key="s.id"
                            :studio="s"
                            @open="goto(s.id)"
                            @chat="startStudioChat(s)"
                        />
                    </div>
                </section>
            </template>

            <!-- Create modal -->
            <UModal v-model="showCreate" :ui="{ width: 'sm:max-w-lg' }">
                <div class="p-6">
                    <div class="flex items-center justify-between mb-1">
                        <h2 class="text-lg font-medium text-gray-900">{{ $t('studio.createTitle') }}</h2>
                        <button @click="showCreate = false" class="text-gray-400 hover:text-gray-600">
                            <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
                        </button>
                    </div>
                    <p class="text-xs text-gray-500 mb-4">{{ $t('studio.createSubtitle') }}</p>

                    <div class="space-y-4">
                        <div>
                            <label class="block text-xs font-medium text-gray-700 mb-1">{{ $t('studio.name') }}</label>
                            <UInput v-model="form.name" :placeholder="$t('studio.namePlaceholder')" size="sm" />
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-gray-700 mb-1">{{ $t('studio.description') }}</label>
                            <UTextarea v-model="form.description" :placeholder="$t('studio.descriptionPlaceholder')" :rows="2" size="sm" />
                        </div>
                        <div class="flex items-start gap-2 rounded-md bg-blue-50/60 border border-blue-100 px-3 py-2">
                            <UIcon name="i-heroicons-sparkles" class="w-3.5 h-3.5 text-blue-500 mt-0.5 shrink-0" />
                            <p class="text-[11px] text-blue-700 leading-snug">{{ $t('studio.autoConfigHint') }}</p>
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-gray-700 mb-2">{{ $t('studio.shareScope') }}</label>
                            <div class="space-y-2">
                                <label
                                    v-for="opt in scopeOptions"
                                    :key="opt.value"
                                    class="flex items-start gap-2 cursor-pointer rounded-md border p-2.5 transition-colors"
                                    :class="form.share_scope === opt.value ? 'border-blue-300 bg-blue-50/50' : 'border-gray-200 hover:border-gray-300'"
                                >
                                    <input type="radio" :value="opt.value" v-model="form.share_scope" class="mt-0.5 text-blue-500 focus:ring-blue-500" />
                                    <span>
                                        <span class="block text-xs font-medium text-gray-800">{{ opt.label }}</span>
                                        <span class="block text-[11px] text-gray-500">{{ opt.hint }}</span>
                                    </span>
                                </label>
                            </div>
                        </div>
                    </div>

                    <div v-if="createError" class="mt-4 bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">
                        {{ createError }}
                    </div>

                    <div class="mt-6 flex items-center justify-end gap-2">
                        <UButton color="gray" variant="outline" size="sm" @click="showCreate = false">{{ $t('common.cancel') }}</UButton>
                        <UButton
                            color="blue"
                            size="sm"
                            :loading="creating"
                            :disabled="!form.name.trim()"
                            @click="createStudio"
                        >
                            {{ $t('studio.createStudio') }}
                        </UButton>
                    </div>
                </div>
            </UModal>
        </div>
    </div>
</template>

<script setup lang="ts">
import StudioCard from '~/components/studio/StudioCard.vue'
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
    source_count?: number
    member_count?: number
    role?: string
    // Concept-1 advanced card fields (server-enriched; optional/degrade-safe).
    chat_count?: number
    last_active_at?: string | null
    eval_pass_rate?: number | null
    activity_7d?: number[]
    sources_preview?: { name: string; type?: string | null }[]
}

const { t } = useI18n()
const toast = useToast()
const router = useRouter()
const { data: currentUser } = useAuth()

const studios = ref<Studio[]>([])
const counts = ref<Record<string, { sources: number; members: number }>>({})
const loading = ref(true)
const error = ref(false)
// `disabled` = the Studios feature flag is off. The backend returns [] for the
// list (never 404) when off, so we detect it via the GET-one / create 404 path.
const disabled = ref(false)

const currentUserId = computed(() => String((currentUser.value as any)?.id ?? ''))

// Owned vs shared. The backend list returns owned ∪ member ∪ org-scope; we split
// on owner_user_id so "Your Studios" and "Shared with you" read naturally.
const ownStudios = computed(() =>
    studios.value.filter(s => String(s.owner_user_id) === currentUserId.value)
)
const sharedStudios = computed(() =>
    studios.value.filter(s => String(s.owner_user_id) !== currentUserId.value)
)

const scopeOptions = computed(() => [
    { value: 'private', label: t('studio.scopePrivate'), hint: t('studio.scopePrivateHint') },
    { value: 'org', label: t('studio.scopeOrg'), hint: t('studio.scopeOrgHint') },
    { value: 'link', label: t('studio.scopeLink'), hint: t('studio.scopeLinkHint') },
])

const fetchStudios = async () => {
    loading.value = true
    error.value = false
    try {
        const { data, error: fetchErr } = await useMyFetch<Studio[]>('/studios', { method: 'GET' })
        if (fetchErr?.value) throw fetchErr.value
        studios.value = data.value || []
        // Best-effort enrich each card with source/member counts. These run in
        // parallel and never block the list; failures leave counts at 0.
        await enrichCounts()
    } catch (e: any) {
        console.error('Failed to fetch studios:', e)
        error.value = true
    } finally {
        loading.value = false
    }
}

// Fallback enrichment: the list now serves source_count/member_count/sources_preview
// (and the advanced stats) directly, so only fetch per-studio when the server
// didn't already inline them. Keeps old backends working; skips N calls on new ones.
const enrichCounts = async () => {
    const needsEnrich = studios.value.filter(s => s.source_count === undefined || s.sources_preview === undefined)
    if (needsEnrich.length === 0) return
    await Promise.all(
        needsEnrich.map(async (s) => {
            try {
                const [src, mem] = await Promise.all([
                    useMyFetch<any[]>(`/studios/${s.id}/sources`, { method: 'GET' }),
                    useMyFetch<any[]>(`/studios/${s.id}/members`, { method: 'GET' }),
                ])
                const srcList = (src.data.value as any[] | null) || []
                s.source_count = s.source_count ?? srcList.length
                s.member_count = s.member_count ?? ((mem.data.value as any[] | null)?.length ?? 0)
                s.sources_preview = s.sources_preview ?? srcList.slice(0, 3).map((x: any) => ({ name: x.name || x.agent_id, type: x.type ?? null }))
            } catch {
                s.source_count = s.source_count ?? 0
                s.member_count = s.member_count ?? 0
            }
        })
    )
}

const goto = (id: string) => router.push(`/studios/${id}`)

// Card "Chat" action: start a fresh studio-grounded conversation (not the
// workspace). Mirrors studios/[id]/index.vue startChat — create a report bound
// to the studio + its pinned sources, then land on the report chat screen.
const startingChat = ref<string | null>(null)
const startStudioChat = async (s: Studio) => {
    if (startingChat.value) return
    startingChat.value = s.id
    try {
        // Resolve the studio's pinned source agent ids (the list payload only
        // carries a preview), so the new report is grounded on all of them.
        const { data: srcData } = await useMyFetch<any[]>(`/studios/${s.id}/sources`, { method: 'GET' })
        const dataSources = ((srcData.value as any[] | null) || []).map((x: any) => String(x.agent_id))
        const { data, error: fetchErr } = await useMyFetch<any>('/reports', {
            method: 'POST',
            body: {
                title: `${s.name || 'Studio'} chat`,
                files: [],
                data_sources: dataSources,
                studio_id: s.id,
            },
        })
        if (fetchErr?.value) throw fetchErr.value
        const created = data.value
        if (created?.id) router.push(`/reports/${created.id}`)
        else goto(s.id)
    } catch (e: any) {
        console.error('Failed to start studio chat:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    } finally {
        startingChat.value = null
    }
}

// ---- create ----
const showCreate = ref(false)
const creating = ref(false)
const createError = ref<string | null>(null)
const form = reactive({
    name: '',
    description: '',
    share_scope: 'private',
})

const openCreate = () => {
    form.name = ''
    form.description = ''
    form.share_scope = 'private'
    createError.value = null
    showCreate.value = true
}

const createStudio = async () => {
    if (!form.name.trim()) return
    creating.value = true
    createError.value = null
    try {
        const { data, error: fetchErr } = await useMyFetch<Studio>('/studios', {
            method: 'POST',
            body: {
                name: form.name.trim(),
                description: form.description.trim() || null,
                share_scope: form.share_scope,
            },
        })
        if (fetchErr?.value) throw fetchErr.value
        const created = data.value
        toast.add({ title: t('studio.studioCreated'), color: 'green', icon: 'i-heroicons-check-circle' })
        showCreate.value = false
        if (created?.id) router.push(`/studios/${created.id}`)
        else await fetchStudios()
    } catch (e: any) {
        console.error('Failed to create studio:', e)
        // A 404 here means the feature flag is off.
        if (e?.statusCode === 404 || e?.status === 404) {
            disabled.value = true
            showCreate.value = false
        } else {
            createError.value = t('studio.actionFailed')
        }
    } finally {
        creating.value = false
    }
}

onMounted(fetchStudios)
</script>
