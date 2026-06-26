<template>
    <section>
        <!-- Header -->
        <div class="flex items-start justify-between mb-4">
            <div>
                <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                    Teach the agent
                </h2>
                <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-2xl">
                    Paste an existing analysis, SOP or note. The agent reads it and proposes what to
                    learn — a reusable skill, guardrails, data rules or background knowledge. Nothing
                    is saved until you approve.
                </p>
            </div>
        </div>

        <!-- Paste box -->
        <div class="rounded-2xl border border-[#E9E0D3] bg-white p-4 mb-4">
            <UTextarea
                v-model="pasteText"
                :rows="9"
                size="sm"
                :disabled="!canEdit || classifying"
                placeholder="Paste your analysis here — e.g. an EBITDA review with how you compute it, the >10% driver rule, how you present it, plus any background facts…"
                :ui="{ base: 'font-mono text-[12px] leading-relaxed' }"
            />
            <div class="mt-3 flex items-center justify-between">
                <span class="text-[11px] text-[#9a958c] tabular-nums">{{ pasteText.length }} / 20000 chars</span>
                <button
                    v-if="canEdit"
                    type="button"
                    :disabled="classifying || pasteText.trim().length < 12"
                    class="inline-flex items-center gap-1.5 text-xs font-semibold text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-lg px-3.5 py-1.5 transition-colors disabled:opacity-50"
                    @click="teach"
                >
                    <Spinner v-if="classifying" class="h-3.5 w-3.5" />
                    <UIcon v-else name="i-heroicons-sparkles" class="w-3.5 h-3.5" />
                    {{ classifying ? 'Reading…' : '✦ Teach AI' }}
                </button>
            </div>
        </div>

        <!-- Empty / no-spans note -->
        <div v-if="ran && !spans.length" class="py-10 text-center border border-dashed border-[#E9E0D3] rounded-2xl">
            <UIcon name="i-heroicons-light-bulb" class="w-7 h-7 mx-auto text-[#9a958c] mb-1.5" />
            <p class="text-xs text-[#6b6b6b]">Nothing teachable detected. Try pasting more detail — a method, a rule, or a fact.</p>
        </div>

        <!-- Review cards -->
        <div v-if="spans.length" class="space-y-3">
            <div class="flex items-center justify-between">
                <h3 class="text-xs font-semibold uppercase tracking-wide text-[#6b6b6b]">
                    Detected · {{ includedCount }} selected
                </h3>
                <span class="text-[11px] text-[#9a958c]">Edit titles &amp; text inline. Untick to skip.</span>
            </div>

            <div
                v-for="(sp, i) in spans"
                :key="i"
                class="rounded-2xl border bg-white p-4 transition-colors"
                :class="sp._include === false ? 'border-[#EFE7DF] opacity-55' : 'border-[#E9E0D3]'"
            >
                <div class="flex items-start gap-3">
                    <!-- include toggle -->
                    <input
                        type="checkbox"
                        v-model="sp._include"
                        :disabled="!canEdit"
                        class="mt-1 h-4 w-4 rounded border-[#d8d4c8] text-[#C2541E] focus:ring-[#C2541E] shrink-0"
                    />
                    <div class="min-w-0 flex-1">
                        <!-- type badge + becomes -->
                        <div class="flex items-center gap-2 flex-wrap mb-2">
                            <span
                                class="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full border"
                                :class="badge(sp.type).cls"
                            >
                                <UIcon :name="badge(sp.type).icon" class="w-3 h-3" />
                                {{ badge(sp.type).label }}
                            </span>
                            <span class="text-[11px] text-[#9a958c]">→ {{ sp.will_be }}</span>
                            <!-- bind status for skills -->
                            <span
                                v-if="sp.type === 'SKILL'"
                                class="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                                :class="sp.bind && sp.bind.bound ? 'bg-[#E4F1EA] text-[#2f7d53]' : 'bg-[#FBEFE4] text-[#A8330F]'"
                            >
                                {{ sp.bind && sp.bind.bound
                                    ? `binds ${Math.round((sp.bind.overall_conf || 0) * 100)}%`
                                    : 'dormant — columns missing' }}
                            </span>
                        </div>

                        <!-- editable title -->
                        <input
                            v-model="sp.title"
                            :disabled="!canEdit"
                            class="w-full text-sm font-medium text-[#1f2328] bg-transparent border-0 border-b border-transparent focus:border-[#E9E0D3] focus:ring-0 px-0 py-0.5 mb-1.5"
                            placeholder="Title"
                        />
                        <!-- editable content -->
                        <UTextarea
                            v-model="sp.content"
                            :rows="textRows(sp.content)"
                            size="sm"
                            :disabled="!canEdit"
                            :ui="{ base: 'text-[12px] leading-relaxed' }"
                        />

                        <!-- skill bind detail -->
                        <div v-if="sp.type === 'SKILL' && sp.bind" class="mt-2 text-[11px] text-[#6b6b6b]">
                            <template v-if="sp.bind.binding && Object.keys(sp.bind.binding).length">
                                <span class="text-[#9a958c]">maps:</span>
                                <code
                                    v-for="(col, key) in sp.bind.binding"
                                    :key="key"
                                    class="inline-block ms-1 mb-1 bg-[#F4EEE5] border border-[#E9E0D3] rounded px-1.5 py-0.5"
                                >{{ key }} → {{ col }}</code>
                            </template>
                            <span v-if="sp.bind.missing && sp.bind.missing.length" class="text-[#A8330F]">
                                · needs: {{ sp.bind.missing.join(', ') }}
                            </span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Footer: train toggle + approve -->
            <div v-if="canEdit" class="flex items-center justify-end gap-3 pt-1">
                <label class="inline-flex items-center gap-1.5 text-[11px] text-[#6b6b6b] cursor-pointer select-none">
                    <input type="checkbox" v-model="trainAfter" class="h-3.5 w-3.5 rounded border-[#d8d4c8] text-[#C2541E] focus:ring-[#C2541E]" />
                    Re-train studio after saving
                </label>
                <button
                    type="button"
                    :disabled="approving || includedCount === 0"
                    class="inline-flex items-center gap-1.5 text-xs font-semibold text-white bg-[#3f9e6a] hover:bg-[#357f57] rounded-lg px-3.5 py-1.5 transition-colors disabled:opacity-50"
                    @click="approve"
                >
                    <Spinner v-if="approving" class="h-3.5 w-3.5" />
                    <UIcon v-else name="i-heroicons-check-circle" class="w-3.5 h-3.5" />
                    {{ approving ? 'Saving…' : `Approve &amp; save (${includedCount})` }}
                </button>
            </div>
        </div>
    </section>
</template>

<script setup lang="ts">
const props = defineProps<{ studioId: string; sources?: any[]; canEdit: boolean }>()
const toast = useToast()

const pasteText = ref('')
const classifying = ref(false)
const approving = ref(false)
const ran = ref(false)
const trainAfter = ref(false)
const spans = ref<any[]>([])

const includedCount = computed(() => spans.value.filter(s => s._include !== false).length)

function textRows(s?: string) {
    const n = String(s || '').length
    return Math.min(8, Math.max(2, Math.ceil(n / 80)))
}

function badge(type: string) {
    switch (type) {
        case 'SKILL':
            return { label: 'Skill', icon: 'i-heroicons-sparkles', cls: 'border-[#E8C9B5] bg-[#F6EFEA] text-[#A8330F]' }
        case 'INSTRUCTION':
            return { label: 'Instruction', icon: 'i-heroicons-clipboard-document-list', cls: 'border-[#C9D8E8] bg-[#EEF4FA] text-[#37618A]' }
        case 'DATA_RULE':
            return { label: 'Data rule', icon: 'i-heroicons-variable', cls: 'border-[#D8CDE8] bg-[#F2EEFA] text-[#6A4FA8]' }
        case 'KNOWLEDGE':
            return { label: 'Knowledge', icon: 'i-heroicons-book-open', cls: 'border-[#CFE0CF] bg-[#EEF5EE] text-[#3f7d53]' }
        default:
            return { label: type, icon: 'i-heroicons-tag', cls: 'border-[#E9E0D3] bg-[#F4EEE5] text-[#6b6b6b]' }
    }
}

async function teach() {
    if (classifying.value) return
    classifying.value = true
    spans.value = []
    ran.value = false
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/teach`, {
            method: 'POST',
            body: { text: pasteText.value.slice(0, 20000) },
        })
        if (error.value) throw error.value
        const list: any[] = ((data.value as any)?.spans) || []
        spans.value = list.map(s => ({ ...s, _include: true }))
        ran.value = true
        if (!spans.value.length) {
            toast.add({ title: 'Nothing teachable detected', color: 'orange', icon: 'i-heroicons-light-bulb' })
        }
    } catch (e: any) {
        toast.add({ title: 'Teach failed', description: String(e?.data?.detail || e?.message || e), color: 'red', icon: 'i-heroicons-exclamation-triangle' })
    } finally {
        classifying.value = false
    }
}

async function approve() {
    if (approving.value) return
    const payload = spans.value
        .filter(s => s._include !== false)
        .map(({ _include, ...rest }) => rest)
    if (!payload.length) return
    approving.value = true
    try {
        const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/teach/approve`, {
            method: 'POST',
            body: { spans: payload, train: trainAfter.value },
        })
        if (error.value) throw error.value
        const created = (data.value as any)?.created || {}
        const kicked = (data.value as any)?.train_kicked
        const skills = (created.skills_active || 0) + (created.skills_dormant || 0)
        const instr = (created.instructions || 0) + (created.data_rules || 0)
        const parts: string[] = []
        if (skills) parts.push(`${skills} skill${skills > 1 ? 's' : ''}${created.skills_dormant ? ` (${created.skills_dormant} dormant)` : ''}`)
        if (instr) parts.push(`${instr} instruction${instr > 1 ? 's' : ''}`)
        if (created.knowledge) parts.push(`${created.knowledge} knowledge doc${created.knowledge > 1 ? 's' : ''}`)
        toast.add({
            title: 'Saved to review queue',
            description: (parts.join(' · ') || 'Spans saved') + (kicked ? ' · re-training started' : ''),
            color: 'green',
            icon: 'i-heroicons-check-circle',
        })
        spans.value = []
        pasteText.value = ''
        ran.value = false
    } catch (e: any) {
        toast.add({ title: 'Approve failed', description: String(e?.data?.detail || e?.message || e), color: 'red', icon: 'i-heroicons-exclamation-triangle' })
    } finally {
        approving.value = false
    }
}
</script>
