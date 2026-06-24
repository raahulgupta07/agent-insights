<template>
    <UModal v-model="isOpen" :ui="{ width: 'sm:max-w-3xl' }">
        <div class="p-6">
            <!-- Header -->
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-2 min-w-0">
                    <Icon name="heroicons:sparkles" class="w-5 h-5 text-amber-500 shrink-0" />
                    <h2 class="text-lg font-medium text-gray-900 truncate">
                        {{ detail?.name || skill?.name || 'Skill' }}
                    </h2>
                </div>
                <button @click="close" class="text-gray-400 hover:text-gray-600">
                    <Icon name="heroicons:x-mark" class="w-5 h-5" />
                </button>
            </div>

            <!-- Loading -->
            <div v-if="loading" class="flex items-center justify-center py-12 text-gray-400">
                <Icon name="heroicons:arrow-path" class="w-5 h-5 animate-spin me-2" />
                <span class="text-sm">Loading skill…</span>
            </div>

            <!-- Error -->
            <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
                {{ error }}
            </div>

            <!-- Content -->
            <div v-else-if="detail || skill" class="space-y-4">
                <!-- Description -->
                <div v-if="description" class="text-gray-600 text-sm leading-relaxed">
                    {{ description }}
                </div>

                <!-- Metadata row -->
                <div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500">
                    <!-- Scope -->
                    <div class="flex items-center gap-1">
                        <span :class="scopeBadgeClass" class="px-2 py-0.5 rounded text-xs font-medium">
                            {{ scopeLabel }}
                        </span>
                    </div>
                    <!-- Category -->
                    <div v-if="category" class="flex items-center gap-1">
                        <Icon name="heroicons:tag" class="w-3 h-3" />
                        <span>{{ category }}</span>
                    </div>
                </div>

                <!-- SKILL.md body -->
                <div class="markdown-wrapper bg-gray-50 rounded-lg p-4 border max-h-[55vh] overflow-y-auto">
                    <MDC v-if="skillMd" :value="skillMd" class="markdown-content" />
                    <div v-else class="text-xs text-gray-400">
                        No SKILL.md body available.
                    </div>
                </div>

                <!-- ── Skill Optimizer ─────────────────────────────────────── -->
                <div class="rounded-xl border border-[#E7E5DD] bg-[#FBFAF6] p-4">
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <div class="flex items-center gap-1.5 text-[13px] font-medium text-[#1f2328]">
                                <Icon name="heroicons:beaker" class="w-4 h-4 text-[#C2683F] shrink-0" />
                                Skill Optimizer
                            </div>
                            <p class="mt-1 text-xs text-[#6b6b6b] leading-relaxed">
                                Run held-out evals and let the agent propose textual edits to this
                                SKILL.md. Accepted only if the eval pass-rate improves; the result is
                                saved as a new draft version for review below.
                            </p>
                        </div>
                        <UButton
                            color="orange"
                            variant="outline"
                            size="sm"
                            icon="i-heroicons-sparkles"
                            :loading="optimizing"
                            :disabled="optimizing"
                            @click="handleOptimize"
                        >
                            {{ optimizing ? 'Optimizing…' : 'Optimize' }}
                        </UButton>
                    </div>

                    <!-- Inputs -->
                    <div class="mt-3 flex flex-wrap items-end gap-3">
                        <label class="flex flex-col gap-1">
                            <span class="text-[11px] font-medium text-[#6b6b6b]">Epochs</span>
                            <input
                                v-model.number="optEpochs"
                                type="number"
                                min="1"
                                max="10"
                                class="w-20 rounded-lg border border-[#E7E5DD] bg-white px-2 py-1 text-xs outline-none focus:border-[#C2683F]"
                                :disabled="optimizing"
                            />
                        </label>
                        <label class="flex flex-col gap-1">
                            <span class="text-[11px] font-medium text-[#6b6b6b]">Eval suite ID (optional)</span>
                            <input
                                v-model.trim="optEvalSuiteId"
                                type="text"
                                placeholder="leave blank to use default"
                                class="w-56 rounded-lg border border-[#E7E5DD] bg-white px-2 py-1 text-xs outline-none focus:border-[#C2683F] placeholder:text-[#9a958c]"
                                :disabled="optimizing"
                            />
                        </label>
                    </div>

                    <!-- Optimizer result / note -->
                    <div v-if="optNote" class="mt-3 rounded-lg border border-[#E7E5DD] bg-[#F3E7DF] p-3 text-xs text-[#A8542F]">
                        {{ optNote }}
                    </div>

                    <div
                        v-if="optResult"
                        class="mt-3 rounded-lg border border-[#E7E5DD] bg-white p-3 text-xs text-[#1f2328]"
                    >
                        <div class="flex flex-wrap items-center gap-x-4 gap-y-1">
                            <span class="inline-flex items-center gap-1.5">
                                <span class="text-[#6b6b6b]">Score</span>
                                <span class="font-medium">{{ fmtScore(optResult.baseline_score) }}</span>
                                <Icon name="heroicons:arrow-right" class="w-3 h-3 text-[#9a958c]" />
                                <span class="font-semibold text-[#C2683F]">{{ fmtScore(optResult.best_score) }}</span>
                            </span>
                            <span
                                class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
                                :class="optResult.improved ? 'bg-[#eef6f0] text-[#3f9e6a] border border-[#d7ebde]' : 'bg-[#F4F1EA] text-[#6b6b6b] border border-[#E7E5DD]'"
                            >
                                {{ optResult.improved ? 'Improved' : 'No improvement' }}
                            </span>
                            <span v-if="optResult.epochs_run != null" class="text-[#6b6b6b]">
                                {{ optResult.epochs_run }} epoch(s) run
                            </span>
                            <span v-if="optResult.accepted_edits != null" class="text-[#6b6b6b]">
                                {{ optResult.accepted_edits }} edit(s) accepted
                            </span>
                        </div>
                        <p
                            v-if="optResult.improved && optResult.new_version_id"
                            class="mt-2 text-[#3f9e6a]"
                        >
                            New draft version created — review &amp; activate below.
                        </p>
                    </div>
                </div>

                <!-- ── Versions ────────────────────────────────────────────── -->
                <div v-if="otherVersions.length" class="rounded-xl border border-[#E7E5DD] bg-white p-4">
                    <div class="flex items-center gap-1.5 text-[13px] font-medium text-[#1f2328]">
                        <Icon name="heroicons:clock" class="w-4 h-4 text-[#C2683F] shrink-0" />
                        Versions
                        <span class="text-xs font-normal text-[#9a958c]">({{ otherVersions.length }})</span>
                    </div>
                    <p class="mt-1 text-xs text-[#6b6b6b]">
                        Other candidate / archived versions of this skill. Activate one to make it live
                        (the current active version is superseded).
                    </p>

                    <div class="mt-3 space-y-3">
                        <div
                            v-for="v in otherVersions"
                            :key="v.id"
                            class="rounded-lg border border-[#E7E5DD] bg-[#FBFAF6] p-3"
                        >
                            <div class="flex items-center justify-between gap-2">
                                <div class="flex items-center gap-2 min-w-0">
                                    <span
                                        class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border"
                                        :class="versionPillClass(v.status)"
                                    >{{ (v.status || 'draft') }}</span>
                                    <span v-if="v.valid_at" class="text-[11px] text-[#9a958c]" style="font-family: ui-monospace, monospace">
                                        {{ fmtDate(v.valid_at) }}
                                    </span>
                                </div>
                                <UButton
                                    color="orange"
                                    variant="soft"
                                    size="2xs"
                                    icon="i-heroicons-arrow-up-circle"
                                    :loading="activatingId === v.id"
                                    :disabled="!!activatingId"
                                    @click="handleActivate(v)"
                                >
                                    Activate
                                </UButton>
                            </div>

                            <!-- before / after diff (active vs this candidate) -->
                            <div class="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
                                <div class="min-w-0">
                                    <div class="text-[10px] uppercase tracking-wide text-[#9a958c] mb-1">Active</div>
                                    <pre class="max-h-40 overflow-auto rounded border border-[#E7E5DD] bg-white p-2 text-[11px] leading-relaxed whitespace-pre-wrap text-[#6b6b6b]">{{ activeBodyPreview }}</pre>
                                </div>
                                <div class="min-w-0">
                                    <div class="text-[10px] uppercase tracking-wide text-[#9a958c] mb-1">This version</div>
                                    <pre class="max-h-40 overflow-auto rounded border border-[#E7E5DD] bg-white p-2 text-[11px] leading-relaxed whitespace-pre-wrap text-[#1f2328]">{{ bodyPreview(v.skill_md) }}</pre>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Footer -->
            <div class="mt-6 flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <UButton
                        v-if="canPromote"
                        color="primary"
                        variant="soft"
                        size="sm"
                        icon="i-heroicons-arrow-up-circle"
                        :loading="promoting"
                        @click="handlePromote"
                    >
                        Promote to Org
                    </UButton>
                    <UButton
                        color="red"
                        variant="outline"
                        size="sm"
                        icon="i-heroicons-trash"
                        :loading="deleting"
                        @click="handleDelete"
                    >
                        Delete
                    </UButton>
                </div>
                <UButton color="gray" variant="outline" size="sm" @click="close">
                    Close
                </UButton>
            </div>
        </div>
    </UModal>
</template>

<script setup lang="ts">
interface SkillSummary {
    id: string
    name: string
    description?: string
    scope?: string
    status?: string
    skill_md?: string
    valid_at?: string | null
    invalid_at?: string | null
    superseded_by?: string | null
}

interface SkillDetail {
    id: string
    name: string
    description?: string
    skill_md?: string
    category?: string
    scope?: string
}

interface OptimizeResult {
    skill_id?: string
    epochs_run?: number
    baseline_score?: number
    best_score?: number
    improved?: boolean
    accepted_edits?: number
    new_version_id?: string
}

interface Props {
    modelValue: boolean
    skill: SkillSummary | null
    // Full visible skills list (from /skills) so we can compute the version group client-side.
    allSkills?: SkillSummary[]
}

const props = defineProps<Props>()

const emit = defineEmits<{
    'update:modelValue': [value: boolean]
    'promoted': [id: string]
    'deleted': [id: string]
    'changed': []
}>()

const isOpen = computed({
    get: () => props.modelValue,
    set: (value) => emit('update:modelValue', value)
})

const detail = ref<SkillDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const promoting = ref(false)
const deleting = ref(false)

const description = computed(() => detail.value?.description || props.skill?.description || '')
const skillMd = computed(() => detail.value?.skill_md || '')
const category = computed(() => detail.value?.category || '')
const scope = computed(() => detail.value?.scope || props.skill?.scope || 'personal')

const scopeLabel = computed(() => {
    const s = (scope.value || '').toLowerCase()
    if (s === 'org' || s === 'organization') return 'Organization'
    if (s === 'global') return 'Global'
    return 'Personal'
})

const scopeBadgeClass = computed(() => {
    const s = (scope.value || '').toLowerCase()
    if (s === 'org' || s === 'organization') return 'bg-[#F4E5DA] text-[#A8542F]'
    if (s === 'global') return 'bg-purple-100 text-purple-700'
    return 'bg-gray-100 text-gray-700'
})

// Only personal skills can be promoted to org.
const canPromote = computed(() => {
    const s = (scope.value || '').toLowerCase()
    return s === 'personal' || s === '' || s === 'private'
})

const close = () => {
    isOpen.value = false
}

const fetchDetail = async (id: string) => {
    loading.value = true
    error.value = null
    detail.value = null
    try {
        const { data, error: fetchErr } = await useMyFetch<SkillDetail>(`/api/skills/${id}`, { method: 'GET' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        detail.value = data.value || null
    } catch (e: any) {
        console.error('Failed to fetch skill detail:', e)
        error.value = 'Failed to load skill details.'
    } finally {
        loading.value = false
    }
}

const handlePromote = async () => {
    if (!props.skill?.id) return
    const confirmed = window.confirm('Promote this personal skill to the organization? It will be sent to the approval gate.')
    if (!confirmed) return
    promoting.value = true
    try {
        const { error: fetchErr } = await useMyFetch(`/api/skills/${props.skill.id}/promote`, { method: 'POST' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        emit('promoted', props.skill.id)
        close()
    } catch (e: any) {
        console.error('Failed to promote skill:', e)
        error.value = 'Failed to promote skill.'
    } finally {
        promoting.value = false
    }
}

const handleDelete = async () => {
    if (!props.skill?.id) return
    const confirmed = window.confirm('Delete this skill? This action removes it from your skills.')
    if (!confirmed) return
    deleting.value = true
    try {
        const { error: fetchErr } = await useMyFetch(`/api/skills/${props.skill.id}`, { method: 'DELETE' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        emit('deleted', props.skill.id)
        close()
    } catch (e: any) {
        console.error('Failed to delete skill:', e)
        error.value = 'Failed to delete skill.'
    } finally {
        deleting.value = false
    }
}

// ── Skill Optimizer state ──────────────────────────────────────────────
const optimizing = ref(false)
const optResult = ref<OptimizeResult | null>(null)
const optNote = ref<string | null>(null)
const optEpochs = ref<number>(3)
const optEvalSuiteId = ref<string>('')

const fmtScore = (n?: number) => {
    if (n == null || isNaN(n as number)) return '—'
    // Scores are pass-rates 0..1; render as a percentage when in that range.
    return (n as number) <= 1 ? `${Math.round((n as number) * 100)}%` : String(n)
}

const handleOptimize = async () => {
    if (!props.skill?.id || optimizing.value) return
    optimizing.value = true
    optResult.value = null
    optNote.value = null
    try {
        const body: Record<string, any> = {}
        if (optEpochs.value) body.epochs = optEpochs.value
        if (optEvalSuiteId.value) body.eval_suite_id = optEvalSuiteId.value
        const { data, error: fetchErr } = await useMyFetch<any>(`/api/skills/${props.skill.id}/optimize`, {
            method: 'POST',
            body,
        })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        const res = data.value || {}
        if (res.disabled) {
            optNote.value = 'Skill optimization is off (enable HYBRID_SKILL_OPTIMIZE).'
        } else if (res.skipped) {
            optNote.value = res.reason ? `Skipped: ${res.reason}` : 'Optimization skipped.'
        } else if (res.error) {
            optNote.value = typeof res.error === 'string' ? res.error : 'Optimization failed.'
        } else {
            optResult.value = res as OptimizeResult
            // A new draft version may now exist — refresh the parent list.
            emit('changed')
        }
    } catch (e: any) {
        console.error('Failed to optimize skill:', e)
        optNote.value = 'Failed to run skill optimization.'
    } finally {
        optimizing.value = false
    }
}

// ── Versions group (computed client-side from the full visible list) ───
const isActive = (s?: { status?: string }) => (s?.status || '').toLowerCase() === 'active'

// Other versions that share this skill's name + scope (drafts / archived), excluding the
// currently-open row and any active row (the open one is the active/live one).
const otherVersions = computed<SkillSummary[]>(() => {
    const cur = props.skill
    const all = props.allSkills
    if (!cur || !all || !all.length) return []
    const name = (cur.name || '').toLowerCase()
    const scope = (cur.scope || '').toLowerCase()
    return all.filter(s =>
        s.id !== cur.id &&
        (s.name || '').toLowerCase() === name &&
        (s.scope || '').toLowerCase() === scope &&
        !isActive(s)
    )
})

// The active body to diff against: prefer the loaded detail, else the prop, else the active
// row from the group.
const activeBodyPreview = computed(() => {
    const body = skillMd.value
        || props.skill?.skill_md
        || (props.allSkills || []).find(s =>
            isActive(s) &&
            (s.name || '').toLowerCase() === (props.skill?.name || '').toLowerCase() &&
            (s.scope || '').toLowerCase() === (props.skill?.scope || '').toLowerCase()
        )?.skill_md
        || ''
    return bodyPreview(body)
})

const bodyPreview = (md?: string | null) => {
    const txt = (md || '').trim()
    if (!txt) return '(no SKILL.md body)'
    return txt.length > 1500 ? txt.slice(0, 1500) + '\n…' : txt
}

const versionPillClass = (status?: string) => {
    const s = (status || 'draft').toLowerCase()
    if (s === 'archived') return 'bg-gray-100 text-gray-600 border-gray-200'
    return 'bg-[#F3E7DF] text-[#A8542F] border-[#E7E5DD]'
}

const fmtDate = (iso?: string | null) => {
    if (!iso) return ''
    try {
        return new Date(iso).toLocaleString()
    } catch {
        return iso
    }
}

const activatingId = ref<string | null>(null)
const handleActivate = async (v: SkillSummary) => {
    if (!v?.id || activatingId.value) return
    const confirmed = window.confirm('Make this version the live skill? The current active version will be superseded.')
    if (!confirmed) return
    activatingId.value = v.id
    try {
        const { error: fetchErr } = await useMyFetch(`/api/skills/${v.id}/activate`, { method: 'POST' })
        if (fetchErr?.value) {
            throw fetchErr.value
        }
        emit('changed')
        close()
    } catch (e: any) {
        console.error('Failed to activate skill version:', e)
        error.value = 'Failed to activate this version.'
    } finally {
        activatingId.value = null
    }
}

// Load the full SKILL.md body whenever the modal opens for a skill.
watch(
    () => [props.modelValue, props.skill?.id],
    ([open, id]) => {
        if (open && id) {
            // Reset optimizer state for the freshly-opened skill.
            optResult.value = null
            optNote.value = null
            fetchDetail(id as string)
        } else if (!open) {
            detail.value = null
            error.value = null
            optResult.value = null
            optNote.value = null
        }
    },
    { immediate: true }
)
</script>
