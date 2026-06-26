<template>
    <div class="studios-root flex justify-center text-sm min-h-full bg-[#F6F1EA] text-[#1A1611]">
        <div class="w-full max-w-[1340px] px-8 py-9">
            <!-- Header -->
            <div class="flex items-start justify-between gap-6 mb-[30px]">
                <div class="max-w-[620px]">
                    <h1 class="studios-h1">{{ $t('studio.title') }}</h1>
                    <p class="mt-3 text-[16px] leading-relaxed text-[#6E6356]">{{ $t('studio.subtitle') }}</p>
                </div>
                <button
                    v-if="!disabled"
                    class="studios-new shrink-0"
                    @click="openCreate"
                >
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none"><path d="M12 5v14M5 12h14" stroke="#fff" stroke-width="2.2" stroke-linecap="round"/></svg>
                    {{ $t('studio.newStudio') }}
                </button>
            </div>

            <!-- Disabled (flag off) -->
            <div v-if="disabled" class="flex flex-col items-center justify-center py-20 text-center">
                <UIcon name="i-heroicons-lock-closed" class="w-10 h-10 text-[#9a958c] mb-3" />
                <h3 class="text-sm font-medium text-[#1f2328]">{{ $t('studio.disabled') }}</h3>
                <p class="mt-1 text-xs text-[#6b6b6b] max-w-md">{{ $t('studio.disabledHint') }}</p>
            </div>

            <!-- Loading -->
            <div v-else-if="loading" class="flex flex-col items-center justify-center py-20">
                <Spinner class="h-4 w-4 text-[#9a958c]" />
                <p class="text-sm text-[#6b6b6b] mt-2">{{ $t('common.loading') }}</p>
            </div>

            <!-- Error -->
            <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-2xl p-4 text-sm text-red-700">
                {{ $t('studio.loadError') }}
                <UButton color="red" variant="ghost" size="xs" class="ms-2 cursor-pointer" @click="fetchStudios">
                    {{ $t('common.retry') }}
                </UButton>
            </div>

            <template v-else>
                <!-- Your Studios -->
                <section class="mb-8">
                    <p class="text-[12px] font-bold tracking-[.1em] text-[#A89C8C] mb-4">{{ $t('studio.yourStudios').toUpperCase() }}</p>

                    <!-- Empty state: a single zero-state card with one primary action.
                         The ghost "add another" tile only appears once studios exist (v-else). -->
                    <div v-if="ownStudios.length === 0">
                        <div class="py-14 px-6 text-center bg-white border border-[#E9E0D3] rounded-2xl">
                            <span class="inline-flex w-11 h-11 mx-auto mb-3 items-center justify-center rounded-xl bg-[#F4EEE5] border border-[#E9E0D3] text-[#C2541E]">
                                <UIcon name="i-heroicons-film" class="w-6 h-6" />
                            </span>
                            <p class="text-sm text-[#1f2328] font-medium mb-1">{{ $t('studio.empty') }}</p>
                            <p class="text-xs text-[#9a958c] mb-4 max-w-md mx-auto leading-relaxed">{{ $t('studio.emptyHint') }}</p>
                            <UButton color="white" size="xs" icon="i-heroicons-plus" class="bg-[#C2541E] hover:bg-[#A8330F] text-white font-semibold border-0 cursor-pointer transition-colors" @click="openCreate">
                                {{ $t('studio.newStudio') }}
                            </UButton>
                        </div>
                    </div>

                    <!-- One add affordance only (top-right primary). Ghost dashed card removed
                         to avoid the duplicate "New Agent Studio" buttons. -->
                    <div v-else class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-[18px]">
                        <StudioCard
                            v-for="s in ownStudios"
                            :key="s.id"
                            :studio="s"
                            class="h-full transition hover:shadow-md hover:-translate-y-0.5 cursor-pointer"
                            @open="goto(s.id)"
                            @chat="startStudioChat(s)"
                        />
                    </div>
                </section>

                <!-- Shared with you -->
                <section v-if="sharedStudios.length > 0">
                    <p class="text-[12px] font-bold tracking-[.1em] text-[#A89C8C] mb-4">{{ $t('studio.sharedWithYou').toUpperCase() }}</p>
                    <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-[18px]">
                        <StudioCard
                            v-for="s in sharedStudios"
                            :key="s.id"
                            :studio="s"
                            class="h-full transition hover:shadow-md hover:-translate-y-0.5 cursor-pointer"
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
                        <h2 class="text-lg font-medium text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ $t('studio.createTitle') }}</h2>
                        <button @click="showCreate = false" class="text-[#9a958c] hover:text-[#1f2328] cursor-pointer">
                            <UIcon name="i-heroicons-x-mark" class="w-5 h-5" />
                        </button>
                    </div>
                    <p class="text-xs text-[#6b6b6b] mb-4">{{ $t('studio.createSubtitle') }}</p>

                    <div class="space-y-4">
                        <div>
                            <label class="block text-xs font-medium text-[#1f2328] mb-1">{{ $t('studio.name') }}</label>
                            <UInput v-model="form.name" :placeholder="$t('studio.namePlaceholder')" size="sm" />
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-[#1f2328] mb-1">{{ $t('studio.description') }}</label>
                            <UTextarea v-model="form.description" :placeholder="$t('studio.descriptionPlaceholder')" :rows="2" size="sm" />
                        </div>
                        <div class="flex items-start gap-2 rounded-xl bg-[#FBEFE4] border border-[#E9E0D3] px-3 py-2">
                            <UIcon name="i-heroicons-sparkles" class="w-3.5 h-3.5 text-[#C2541E] mt-0.5 shrink-0" />
                            <p class="text-[11px] text-[#C2541E] leading-snug">{{ $t('studio.autoConfigHint') }}</p>
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-[#1f2328] mb-2">{{ $t('studio.shareScope') }}</label>
                            <div class="space-y-2">
                                <label
                                    v-for="opt in scopeOptions"
                                    :key="opt.value"
                                    class="flex items-start gap-2 cursor-pointer rounded-xl border p-2.5 transition-colors"
                                    :class="form.share_scope === opt.value ? 'border-[#C2541E] bg-[#FBEFE4]/60' : 'border-[#E9E0D3] hover:border-[#d8d4ca]'"
                                >
                                    <input type="radio" :value="opt.value" v-model="form.share_scope" class="mt-0.5 text-[#C2541E] focus:ring-[#C2541E]" />
                                    <span>
                                        <span class="block text-xs font-medium text-[#1f2328]">{{ opt.label }}</span>
                                        <span class="block text-[11px] text-[#6b6b6b]">{{ opt.hint }}</span>
                                    </span>
                                </label>
                            </div>
                        </div>
                    </div>

                    <div v-if="createError" class="mt-4 bg-red-50 border border-red-200 rounded-xl p-2.5 text-xs text-red-700">
                        {{ createError }}
                    </div>

                    <div class="mt-6 flex items-center justify-end gap-2">
                        <UButton color="gray" variant="outline" size="sm" class="cursor-pointer" @click="showCreate = false">{{ $t('common.cancel') }}</UButton>
                        <UButton
                            color="white"
                            size="sm"
                            class="bg-[#C2541E] hover:bg-[#A8330F] text-white font-semibold border-0 cursor-pointer transition-colors disabled:opacity-50"
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

// Design fonts (Spectral serif headings + Hanken Grotesk body).
useHead({
    link: [
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Spectral:ital,wght@0,400;0,500;0,600;1,400;1,500&family=Hanken+Grotesk:wght@400;500;600;700&display=swap' },
    ],
})

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

<style scoped>
.studios-root { font-family: 'Hanken Grotesk', system-ui, sans-serif; }
.studios-h1 {
    font-family: 'Spectral', 'Spectral', ui-serif, Georgia, serif;
    font-weight: 500; font-size: 38px; letter-spacing: -.02em;
    margin: 0; color: #211B14; line-height: 1.1;
}
.studios-new {
    display: flex; align-items: center; gap: 9px;
    border: none; background: #C2541E; color: #fff;
    border-radius: 12px; padding: 12px 18px; cursor: pointer;
    font-family: inherit; font-size: 14.5px; font-weight: 600;
    transition: background .15s; box-shadow: 0 10px 24px -12px rgba(168, 51, 15, .7);
}
.studios-new:hover { background: #A8330F; }
</style>
