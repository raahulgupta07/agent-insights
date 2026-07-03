<template>
    <div>
        <!-- Flag OFF → disabled explainer, no token fields -->
        <div v-if="flagLoaded && !flagEnabled" class="md:w-2/3">
            <div class="rounded-xl border border-[#E9E0D3] bg-[#F4EEE5] p-5 text-sm text-[#6b6b6b] leading-relaxed">
                Knowledge sources are turned off. Enable
                <span class="font-medium text-[#1f2328]">“Notion / Slack knowledge sources”</span>
                in <span class="font-medium text-[#1f2328]">Settings → Features</span> to sync pages and channels.
            </div>
        </div>

        <div v-else class="space-y-6">
            <p class="md:w-2/3 text-sm text-[#6b6b6b] leading-relaxed">
                Paste a workspace token and sync. Imported pages and channels land in
                <span class="font-medium text-[#1f2328]">Knowledge → Review</span> as pending —
                they only ground answers after you approve them.
            </p>

            <!-- Notion -->
            <div class="md:w-2/3 rounded-2xl border border-[#E9E0D3] bg-[#FBFAF6] p-5 space-y-4">
                <div class="flex items-center gap-2">
                    <Icon name="heroicons:document-text" class="w-5 h-5 text-[#C2541E]" />
                    <h2 class="text-base font-semibold text-[#1f2328]">Notion</h2>
                </div>

                <div class="space-y-1.5">
                    <div class="text-sm font-medium text-[#1f2328]">Integration token</div>
                    <UInput
                        v-model="notion.token"
                        type="password"
                        autocomplete="off"
                        placeholder="secret_…"
                        :ui="inputUi"
                    />
                </div>

                <div class="space-y-1.5">
                    <div class="text-sm font-medium text-[#1f2328]">Page IDs <span class="text-[#9a958c] font-normal">(optional, comma-separated)</span></div>
                    <UInput v-model="notion.ids" placeholder="page-id-1, page-id-2" :ui="inputUi" />
                </div>

                <label class="flex items-center gap-2 text-sm text-[#6b6b6b] cursor-pointer select-none">
                    <input type="checkbox" v-model="notion.autoApprove" class="rounded border-[#E9E0D3] text-[#C2541E] focus:ring-0" />
                    Approve immediately (skip Review)
                </label>

                <div class="flex items-center gap-3">
                    <UButton
                        class="rounded-xl px-4 py-2.5 bg-[#C2541E] hover:bg-[#A8330F] text-white border-0 transition-colors cursor-pointer"
                        :loading="notion.running"
                        :disabled="!notion.token || notion.running"
                        @click="sync('notion')"
                    >Sync now</UButton>
                    <span v-if="notion.result" class="text-sm" :class="resultClass(notion.result)">{{ resultText(notion.result, notion.autoApprove) }}</span>
                </div>
            </div>

            <!-- Slack -->
            <div class="md:w-2/3 rounded-2xl border border-[#E9E0D3] bg-[#FBFAF6] p-5 space-y-4">
                <div class="flex items-center gap-2">
                    <Icon name="heroicons:chat-bubble-left-right" class="w-5 h-5 text-[#C2541E]" />
                    <h2 class="text-base font-semibold text-[#1f2328]">Slack</h2>
                </div>

                <div class="space-y-1.5">
                    <div class="text-sm font-medium text-[#1f2328]">Bot token</div>
                    <UInput
                        v-model="slack.token"
                        type="password"
                        autocomplete="off"
                        placeholder="xoxb-…"
                        :ui="inputUi"
                    />
                </div>

                <div class="space-y-1.5">
                    <div class="text-sm font-medium text-[#1f2328]">Channel IDs <span class="text-[#9a958c] font-normal">(optional, comma-separated)</span></div>
                    <UInput v-model="slack.ids" placeholder="C0123ABC, C0456DEF" :ui="inputUi" />
                </div>

                <label class="flex items-center gap-2 text-sm text-[#6b6b6b] cursor-pointer select-none">
                    <input type="checkbox" v-model="slack.autoApprove" class="rounded border-[#E9E0D3] text-[#C2541E] focus:ring-0" />
                    Approve immediately (skip Review)
                </label>

                <div class="flex items-center gap-3">
                    <UButton
                        class="rounded-xl px-4 py-2.5 bg-[#C2541E] hover:bg-[#A8330F] text-white border-0 transition-colors cursor-pointer"
                        :loading="slack.running"
                        :disabled="!slack.token || slack.running"
                        @click="sync('slack')"
                    >Sync now</UButton>
                    <span v-if="slack.result" class="text-sm" :class="resultClass(slack.result)">{{ resultText(slack.result, slack.autoApprove) }}</span>
                </div>
            </div>

            <p class="md:w-2/3 text-xs text-[#9a958c] leading-relaxed">
                Synced docs land in Knowledge → Review for approval before they ground answers. Tokens are
                sent once over the sync request and are never stored in your browser.
            </p>
        </div>
    </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'

definePageMeta({ auth: true, permissions: ['manage_settings'], layout: 'settings' })

const inputUi = { base: 'w-full', rounded: 'rounded-lg', color: { white: { outline: 'bg-white border border-[#E9E0D3] focus:border-[#C2541E] focus:ring-0' } } }

// HYBRID_NOTION_KB gate — read the flag the same way PromptBoxV2.vue does.
const flagLoaded = ref(false)
const flagEnabled = ref(false)
async function loadFlag() {
    try {
        const { data } = await useMyFetch<any[]>('/api/organization/hybrid-flags')
        const rows = (data.value as any[]) || []
        flagEnabled.value = !!rows.find(r => r?.env_name === 'HYBRID_NOTION_KB')?.effective
    } catch {
        flagEnabled.value = false
    } finally {
        flagLoaded.value = true
    }
}

interface SyncResult { enabled: boolean; ok: boolean; ingested?: number; skipped?: number; errors?: number; reason?: string }

const notion = reactive<{ token: string; ids: string; autoApprove: boolean; running: boolean; result: SyncResult | null }>({ token: '', ids: '', autoApprove: false, running: false, result: null })
const slack = reactive<{ token: string; ids: string; autoApprove: boolean; running: boolean; result: SyncResult | null }>({ token: '', ids: '', autoApprove: false, running: false, result: null })

function parseIds(raw: string): string[] {
    return raw.split(',').map(s => s.trim()).filter(Boolean)
}

async function sync(kind: 'notion' | 'slack') {
    const state = kind === 'notion' ? notion : slack
    if (!state.token || state.running) return
    state.running = true
    state.result = null
    // Token travels only in the POST body — never in the URL, never logged, never persisted.
    const body: Record<string, any> = { token: state.token, auto_approve: state.autoApprove }
    const ids = parseIds(state.ids)
    if (ids.length) body[kind === 'notion' ? 'page_ids' : 'channel_ids'] = ids
    try {
        const { data, error } = await useMyFetch<SyncResult>(`/kb-sources/${kind}/sync`, { method: 'POST', body })
        if (error?.value) throw error.value
        state.result = (data.value as SyncResult) || { enabled: true, ok: false, reason: 'no_response' }
    } catch {
        state.result = { enabled: true, ok: false, reason: 'request_failed' }
    } finally {
        state.running = false
    }
}

function resultText(r: SyncResult, approved = false): string {
    if (r.reason) return `Nothing synced (${r.reason.replace(/_/g, ' ')}).`
    const counts = `Ingested ${r.ingested ?? 0} · skipped ${r.skipped ?? 0} · errors ${r.errors ?? 0}.`
    const okApproved = approved && r.ok !== false && (r.errors ?? 0) === 0
    return okApproved
        ? `${counts} Synced + approved — grounding answers now.`
        : `${counts} Review them in Knowledge → Review.`
}
function resultClass(r: SyncResult): string {
    if (r.reason || r.ok === false) return 'text-[#A8330F]'
    if ((r.errors ?? 0) > 0) return 'text-[#A8330F]'
    return 'text-[#3f7d4e]'
}

onMounted(loadFlag)
</script>
