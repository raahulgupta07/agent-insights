<template>
    <div>
        <div class="flex items-start justify-between mb-4">
            <div>
                <h2 class="text-sm font-semibold text-gray-900">{{ $t('studio.artifactsTitle') }}</h2>
                <p class="text-xs text-gray-500 mt-0.5">{{ $t('studio.artifactsHint') }}</p>
            </div>
        </div>

        <!-- Kind tabs -->
        <div class="flex items-center gap-1 mb-4 border-b border-gray-200">
            <button
                v-for="k in kinds"
                :key="k.value"
                type="button"
                class="px-3 py-1.5 text-xs font-medium -mb-px border-b-2 transition-colors"
                :class="activeKind === k.value
                    ? 'border-[#C2683F] text-[#C2683F]'
                    : 'border-transparent text-gray-500 hover:text-gray-800'"
                @click="activeKind = k.value"
            >
                {{ k.label }}
            </button>
        </div>

        <!-- Generated artifacts (summary / faq / briefing) -->
        <div v-if="activeKind !== 'note'">
            <div class="flex items-center gap-2 mb-3">
                <UButton
                    v-if="canEdit"
                    color="primary"
                    variant="soft"
                    size="xs"
                    icon="i-heroicons-sparkles"
                    :loading="generating"
                    @click="generate(activeKind)"
                >
                    {{ activeArtifacts.length ? $t('studio.regenerate') : $t('studio.generate') }}
                </UButton>
                <span class="text-[11px] text-gray-400">
                    {{ $t('studio.generateHint', { kind: activeLabel.toLowerCase() }) }}
                </span>
            </div>

            <div v-if="loading" class="flex items-center justify-center py-10 text-gray-400">
                <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
            </div>

            <div v-else-if="activeArtifacts.length === 0" class="py-10 text-center border border-dashed border-gray-200 rounded-lg">
                <UIcon name="i-heroicons-document-text" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
                <p class="text-xs text-gray-500">{{ $t('studio.noArtifacts') }}</p>
            </div>

            <div v-else class="space-y-3">
                <div
                    v-for="a in activeArtifacts"
                    :key="a.id"
                    class="rounded-lg border border-gray-200 bg-white p-4"
                >
                    <div class="flex items-start justify-between mb-2">
                        <span class="text-[11px] text-gray-400">{{ formatDate(a.created_at) }}</span>
                        <button
                            v-if="canEdit"
                            class="text-gray-300 hover:text-red-500"
                            :title="$t('studio.deleteArtifact')"
                            @click="remove(a.id)"
                        >
                            <UIcon name="i-heroicons-trash" class="w-3.5 h-3.5" />
                        </button>
                    </div>
                    <MDC v-if="a.content" :value="a.content" class="markdown-content text-sm text-gray-700" />
                    <p v-else class="text-xs text-gray-400 italic">—</p>
                </div>
            </div>
        </div>

        <!-- Notes -->
        <div v-else>
            <div v-if="canEdit" class="mb-3">
                <UTextarea v-model="noteDraft" :placeholder="$t('studio.notePlaceholder')" :rows="3" size="sm" />
                <div class="mt-2 flex justify-end">
                    <UButton
                        color="primary"
                        variant="soft"
                        size="xs"
                        icon="i-heroicons-plus"
                        :loading="savingNote"
                        :disabled="!noteDraft.trim()"
                        @click="saveNote"
                    >
                        {{ $t('studio.saveNote') }}
                    </UButton>
                </div>
            </div>

            <div v-if="loading" class="flex items-center justify-center py-10 text-gray-400">
                <Spinner class="h-4 w-4" /><span class="ms-2 text-xs">{{ $t('common.loading') }}</span>
            </div>

            <div v-else-if="activeArtifacts.length === 0" class="py-10 text-center border border-dashed border-gray-200 rounded-lg">
                <UIcon name="i-heroicons-pencil-square" class="w-7 h-7 mx-auto text-gray-300 mb-1.5" />
                <p class="text-xs text-gray-500">{{ $t('studio.noArtifacts') }}</p>
            </div>

            <div v-else class="space-y-3">
                <div
                    v-for="a in activeArtifacts"
                    :key="a.id"
                    class="rounded-lg border border-gray-200 bg-white p-4"
                >
                    <div class="flex items-start justify-between mb-1.5">
                        <span class="text-[11px] text-gray-400">{{ formatDate(a.created_at) }}</span>
                        <button
                            v-if="canEdit"
                            class="text-gray-300 hover:text-red-500"
                            :title="$t('studio.deleteArtifact')"
                            @click="remove(a.id)"
                        >
                            <UIcon name="i-heroicons-trash" class="w-3.5 h-3.5" />
                        </button>
                    </div>
                    <p class="text-sm text-gray-700 whitespace-pre-wrap">{{ a.content }}</p>
                </div>
            </div>
        </div>

        <div v-if="errorMsg" class="mt-3 bg-red-50 border border-red-200 rounded-lg p-2.5 text-xs text-red-700">
            {{ errorMsg }}
        </div>
    </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'

interface Artifact {
    id: string
    kind: string
    content?: string | null
    created_at?: string
}

const props = defineProps<{
    studioId: string
    canEdit: boolean
}>()

const { t } = useI18n()
const toast = useToast()

const artifacts = ref<Artifact[]>([])
const loading = ref(false)
const generating = ref(false)
const savingNote = ref(false)
const errorMsg = ref<string | null>(null)
const noteDraft = ref('')

const kinds = computed(() => [
    { value: 'summary', label: t('studio.artifactSummary') },
    { value: 'faq', label: t('studio.artifactFaq') },
    { value: 'briefing', label: t('studio.artifactBriefing') },
    { value: 'note', label: t('studio.artifactNote') },
])
const activeKind = ref('summary')
const activeLabel = computed(() => kinds.value.find(k => k.value === activeKind.value)?.label || '')
const activeArtifacts = computed(() => artifacts.value.filter(a => a.kind === activeKind.value))

const formatDate = (d?: string) => {
    if (!d) return ''
    try { return new Date(d).toLocaleString() } catch { return d }
}

const fetchArtifacts = async () => {
    loading.value = true
    errorMsg.value = null
    try {
        const { data, error } = await useMyFetch<Artifact[]>(`/studios/${props.studioId}/artifacts`, { method: 'GET' })
        if (error?.value) throw error.value
        artifacts.value = data.value || []
    } catch (e: any) {
        // 404 = artifacts route not available (flag off / not built) → empty, don't crash.
        if (e?.statusCode === 404 || e?.status === 404) {
            artifacts.value = []
        } else {
            console.error('Failed to load artifacts:', e)
            errorMsg.value = t('studio.actionFailed')
        }
    } finally {
        loading.value = false
    }
}

const generate = async (kind: string) => {
    generating.value = true
    errorMsg.value = null
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/artifacts/generate`, {
            method: 'POST',
            body: { kind },
        })
        if (error?.value) throw error.value
        await fetchArtifacts()
    } catch (e: any) {
        console.error('Failed to generate artifact:', e)
        errorMsg.value = t('studio.actionFailed')
    } finally {
        generating.value = false
    }
}

const saveNote = async () => {
    if (!noteDraft.value.trim()) return
    savingNote.value = true
    errorMsg.value = null
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/artifacts`, {
            method: 'POST',
            body: { kind: 'note', content: noteDraft.value.trim() },
        })
        if (error?.value) throw error.value
        noteDraft.value = ''
        await fetchArtifacts()
    } catch (e: any) {
        console.error('Failed to save note:', e)
        errorMsg.value = t('studio.actionFailed')
    } finally {
        savingNote.value = false
    }
}

const remove = async (artifactId: string) => {
    if (!window.confirm(t('studio.deleteArtifact') + '?')) return
    try {
        const { error } = await useMyFetch(`/studios/${props.studioId}/artifacts/${artifactId}`, { method: 'DELETE' })
        if (error?.value) throw error.value
        await fetchArtifacts()
    } catch (e: any) {
        console.error('Failed to delete artifact:', e)
        toast.add({ title: t('studio.actionFailed'), color: 'red' })
    }
}

onMounted(fetchArtifacts)
</script>
