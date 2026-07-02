<template>
    <div class="py-6 relative">
        <!-- Hide content when there's a fetch error (layout shows error state) -->
        <div v-if="fetchError" />
        <div v-else>
            <!-- Live sync-log terminal (self-hides when there's no active/recent sync run) -->
            <AgentSyncLog :data-source-id="(route.params.id as string)" />

            <!-- Indexing banner: shown while any linked connection is discovering schema -->
            <div
                v-if="indexingConnections.length > 0"
                class="mb-4 flex items-start gap-3 bg-[#F4EEE5] border border-[#E9E0D3] text-[#1f2328] rounded-2xl px-4 py-3"
            >
                <UIcon name="heroicons-arrow-path" class="w-5 h-5 mt-0.5 animate-spin flex-none text-[#C2541E]" />
                <div class="flex-1 text-sm">
                    <div class="font-medium">
                        Discovering schema for
                        {{ indexingConnections.length }}
                        {{ indexingConnections.length === 1 ? 'connection' : 'connections' }}…
                    </div>
                    <div class="mt-1 text-xs text-[#6b6b6b] space-y-0.5">
                        <div v-for="conn in indexingConnections" :key="conn.id">
                            <span class="font-medium">{{ conn.name }}</span>
                            <span class="ms-1 text-[#9a958c]">· {{ connIndexingSummary(conn) }}</span>
                        </div>
                    </div>
                </div>
                <NuxtLink :to="`/agents/${route.params.id}/connection`" class="text-xs font-medium text-[#C2541E] hover:underline">
                    View progress
                </NuxtLink>
            </div>

        <div>
            <div v-if="loading" class="text-xs text-[#6b6b6b] text-center">{{ $t('common.loading') }}</div>

            <!-- Two-column: knowledge in the CENTER, thin status RIGHT rail -->
            <div v-else class="flex flex-col lg:flex-row items-start gap-4">

                <!-- CENTER column (main knowledge) -->
                <div class="flex-1 min-w-0 w-full flex flex-col gap-4">

                    <!-- 1 · Launcher card -->
                    <div class="order-1 bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl p-4">
                        <div class="flex gap-2 items-center bg-white border border-[#E9E0D3] rounded-xl pl-3.5 pr-2 py-2">
                            <input
                                v-model="launchText"
                                type="text"
                                placeholder="Ask this agent — opens a new Report…"
                                class="flex-1 min-w-0 text-sm bg-transparent outline-none text-[#1f2328] placeholder:text-[#9a958c]"
                                @keydown.enter="launchReport(launchText)"
                            />
                            <button
                                :disabled="launching || !launchText.trim()"
                                @click="launchReport(launchText)"
                                class="shrink-0 text-xs font-medium px-3 py-1.5 bg-[#C2541E] text-white rounded-lg hover:bg-[#A8330F] transition-colors disabled:opacity-50"
                            >
                                Start report →
                            </button>
                        </div>
                        <div v-if="starterList.length" class="mt-2.5 flex flex-wrap gap-2">
                            <button
                                v-for="(starter, idx) in starterList"
                                :key="idx"
                                @click="launchReport(starterPrompt(starter))"
                                class="bg-white border border-[#E9E0D3] rounded-full px-3 py-1.5 text-xs text-[#4a4034] hover:border-[#C2541E] hover:text-[#C2541E] transition-colors"
                            >
                                ↗ {{ starter.split('\n')[0] }}
                            </button>
                        </div>
                    </div>

                    <!-- 2 · What this agent knows (existing primary-instruction block) -->
                    <div class="order-4 bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl p-4">
                        <div class="text-sm font-semibold text-[#1f2328] mb-3 flex items-center gap-2" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                            <UIcon name="heroicons-book-open" class="w-4 h-4 text-[#C2541E]" />
                            What this agent knows
                        </div>

                        <!-- Inline create form -->
                        <div
                            v-if="creatingInstruction"
                            class="primary-instruction-editor flex flex-col border border-[#E9E0D3] rounded-2xl overflow-hidden bg-white"
                            style="height: min(600px, 70vh)"
                        >
                            <InstructionGlobalCreateComponent
                                default-status="published"
                                :agent-id="(route.params.id as string)"
                                :initial-title="primaryInstructionDefaultTitle"
                                :uppercase-title="false"
                                @instruction-saved="onPrimaryInstructionCreated"
                                @cancel="creatingInstruction = false"
                            />
                        </div>

                        <!-- Inline edit form -->
                        <div
                            v-else-if="editingInstruction && dataSource?.primary_instruction"
                            class="primary-instruction-editor flex flex-col border border-[#E9E0D3] rounded-2xl overflow-hidden bg-white"
                            style="height: min(600px, 70vh)"
                        >
                            <InstructionGlobalCreateComponent
                                :key="dataSource.primary_instruction.id"
                                :instruction="dataSource.primary_instruction"
                                :uppercase-title="false"
                                :start-in-edit-mode="true"
                                @instruction-saved="onPrimaryInstructionSaved"
                                @cancel="editingInstruction = false"
                            />
                        </div>

                        <!-- Existing instruction: simple read-only view -->
                        <template v-else-if="dataSource?.primary_instruction">
                            <div class="flex items-center justify-between gap-2 mb-2">
                                <span class="text-sm font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ dataSource.primary_instruction.title || 'Primary instruction' }}</span>
                                <PrimaryInstructionMenu
                                    v-if="useCan('update_data_source')"
                                    :agent-id="(route.params.id as string)"
                                    :current-instruction-id="dataSource.primary_instruction.id"
                                    :can-train="canStartTraining"
                                    @edit="editingInstruction = true"
                                    @select="onSelectExistingInstruction"
                                    @start-training="startTrainingSession"
                                />
                            </div>
                            <div :class="showFullInstruction ? '' : 'max-h-[240px] overflow-hidden relative'">
                                <InstructionText
                                    :text="dataSource.primary_instruction.text"
                                    :references="dataSource.primary_instruction.references || []"
                                    :prose="true"
                                    :markdown="true"
                                />
                                <div v-if="!showFullInstruction" class="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-[#FBFAF6] to-transparent" />
                            </div>
                            <button @click="showFullInstruction = !showFullInstruction" class="mt-1.5 text-xs font-medium text-[#C2541E] hover:underline">
                                {{ showFullInstruction ? 'Show less' : 'Show more' }}
                            </button>
                        </template>

                        <!-- Empty state -->
                        <div v-else class="border border-dashed border-[#E9E0D3] rounded-2xl px-6 py-10 text-center bg-[#F4EEE5]/50">
                            <div class="mx-auto w-10 h-10 rounded-full bg-[#F4EEE5] border border-[#E9E0D3] flex items-center justify-center mb-3">
                                <UIcon name="heroicons-document-text" class="w-5 h-5 text-[#C2541E]" />
                            </div>
                            <div class="text-sm font-medium text-[#1f2328]">No primary instruction</div>
                            <div class="text-xs text-[#6b6b6b] mt-1 max-w-md mx-auto">
                                Give this agent a guiding instruction it applies to every report — context about the data, conventions to follow, or rules to enforce.
                            </div>
                            <div v-if="useCan('update_data_source')" class="mt-4 flex items-center justify-center gap-3">
                                <button
                                    @click="creatingInstruction = true"
                                    class="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 bg-[#C2541E] text-white rounded-lg hover:bg-[#A8330F] transition-colors"
                                >
                                    <UIcon name="heroicons-plus" class="w-3.5 h-3.5" />
                                    Add Primary Instruction
                                </button>
                                <span class="text-xs text-[#9a958c]">or</span>
                                <PrimaryInstructionPicker
                                    :agent-id="(route.params.id as string)"
                                    label="select existing"
                                    @select="onSelectExistingInstruction"
                                />
                            </div>
                            <div v-if="useCan('update_data_source') && canStartTraining" class="mt-3">
                                <button @click="startTrainingSession" class="text-xs text-[#C2541E] hover:underline inline-flex items-center gap-1">
                                    <UIcon name="heroicons-academic-cap" class="w-3.5 h-3.5" />
                                    Start a training session
                                </button>
                            </div>
                        </div>
                    </div>

                    <!-- 3 · Core tables card (from overview endpoint) -->
                    <div v-if="hasOverview && overview.tables.length" class="order-2 bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl p-4">
                        <div class="text-sm font-semibold text-[#1f2328] mb-1 flex items-center gap-2" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                            <UIcon name="heroicons-table-cells" class="w-4 h-4 text-[#C2541E]" />
                            Core tables
                            <span class="text-xs font-normal text-[#6b6b6b]">· {{ overview.stats.active_tables }} active · {{ overview.stats.total_columns }} columns</span>
                        </div>
                        <div>
                            <div
                                v-for="tbl in visibleTables"
                                :key="tbl.name"
                                class="flex gap-3 py-2.5 border-b border-[#F2ECE1] last:border-0"
                            >
                                <div class="w-7 h-7 rounded-lg bg-[#F0E9DB] grid place-items-center shrink-0">
                                    <UIcon :name="tbl.entity_like ? 'heroicons-cube' : 'heroicons-table-cells'" class="w-4 h-4 text-[#C2541E]" />
                                </div>
                                <div class="flex-1 min-w-0">
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <code class="font-mono text-[11px] bg-[#F0E9DB] px-1.5 rounded text-[#211B14]">{{ tbl.name }}</code>
                                        <span class="font-mono text-[11px] bg-[#E9F1EC] text-[#2F6F4F] border border-[#d4e3d4] px-1.5 rounded">{{ tbl.entity_like ? 'entity' : 'table' }}</span>
                                    </div>
                                    <div v-if="tbl.purpose" class="text-xs text-[#6b6b6b] leading-snug mt-1">{{ tbl.purpose }}</div>
                                </div>
                                <div class="text-[11px] text-[#9a958c] whitespace-nowrap self-center text-right">
                                    <div>{{ tbl.column_count }} cols</div>
                                    <div v-if="tbl.row_count > 0">{{ tbl.row_count.toLocaleString() }} rows</div>
                                </div>
                            </div>
                        </div>
                        <div v-if="overview.tables.length > visibleTables.length" class="mt-2">
                            <NuxtLink :to="`/agents/${route.params.id}/tables`" class="text-xs font-medium text-[#C2541E] hover:underline">
                                See all {{ overview.tables.length }} tables →
                            </NuxtLink>
                        </div>
                    </div>

                    <!-- 4 · Key relationships & joins card (honest empty state when none) -->
                    <div v-if="hasOverview && overview.tables.length" class="order-3 bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl p-4">
                        <div class="text-sm font-semibold text-[#1f2328] mb-2 flex items-center gap-2" style="font-family: 'Spectral', ui-serif, Georgia, serif">
                            <UIcon name="heroicons-link" class="w-4 h-4 text-[#C2541E]" />
                            Key relationships &amp; joins
                        </div>
                        <template v-if="overview.joins.length">
                            <div
                                v-for="(j, idx) in overview.joins"
                                :key="idx"
                                class="flex items-center gap-2 py-1.5 text-xs text-[#3a332a] flex-wrap"
                            >
                                <code class="font-mono text-[11px] bg-[#ECEAE1] px-1.5 rounded">{{ j.from_table }}</code>
                                <span class="text-[#9a958c]">→</span>
                                <code class="font-mono text-[11px] bg-[#ECEAE1] px-1.5 rounded">{{ j.to_table }}</code>
                                <span class="text-[11px] text-[#9a958c]">via</span>
                                <code class="font-mono text-[11px] bg-[#ECEAE1] px-1.5 rounded">{{ j.from_column }}</code>
                            </div>
                        </template>
                        <div v-else class="text-xs text-[#9a958c] leading-relaxed">
                            No table relationships are defined in this source's schema — Power BI models don't expose foreign keys over the API, so joins are inferred at query time by the agent instead.
                        </div>
                    </div>

                    <!-- 5 · Conversation Starters (existing) -->
                    <div class="order-5 bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl p-4">
                        <div class="flex items-center gap-2">
                            <div class="text-xs uppercase tracking-wide text-[#9a958c]">{{ $t('dataSource.conversationStarters') }}</div>
                            <button v-if="useCan('update_data_source')" @click="openEditStarters" class="text-[10px] text-[#C2541E] hover:underline">{{ $t('dataSource.edit') }}</button>
                        </div>
                        <div class="mt-3 flex flex-wrap gap-2">
                            <div v-for="starter in displayDataSource?.conversation_starters" :key="starter"
                            class="bg-[#F4EEE5] border border-[#E9E0D3] text-[#1f2328] rounded-lg px-3 py-2 text-xs"
                            >
                                <span>{{ starter.split('\n')[0] }}</span>
                            </div>
                        </div>
                    </div>

                </div>

                <!-- RIGHT rail (lg only) -->
                <div v-if="hasOverview" class="w-full lg:w-[300px] lg:shrink-0 space-y-4">

                    <!-- At a glance -->
                    <div class="bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl p-3.5">
                        <div class="text-sm font-semibold text-[#1f2328] mb-2" style="font-family: 'Spectral', ui-serif, Georgia, serif">At a glance</div>
                        <div class="grid grid-cols-2 gap-2 mb-1">
                            <div class="bg-white border border-[#E9E0D3] rounded-xl px-3 py-2">
                                <div class="text-xl font-bold text-[#211B14]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ overview.stats.active_tables }}</div>
                                <div class="text-[11px] text-[#6b6b6b]">tables</div>
                            </div>
                            <div class="bg-white border border-[#E9E0D3] rounded-xl px-3 py-2">
                                <div class="text-xl font-bold text-[#211B14]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ overview.stats.total_columns }}</div>
                                <div class="text-[11px] text-[#6b6b6b]">columns</div>
                            </div>
                        </div>
                        <div class="flex justify-between items-center py-1.5 text-xs text-[#3a332a]">
                            <span>Connected</span>
                            <span class="text-[#6b6b6b]">{{ overview.stats.connections }} {{ overview.stats.connections === 1 ? 'connection' : 'connections' }}</span>
                        </div>
                    </div>

                    <!-- View-only (only if present) -->
                    <div v-if="overview.view_only.length" class="bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl p-3.5">
                        <div class="text-sm font-semibold text-[#1f2328] mb-2" style="font-family: 'Spectral', ui-serif, Georgia, serif">View-only</div>
                        <div
                            v-for="(v, idx) in overview.view_only"
                            :key="idx"
                            class="flex justify-between items-center py-1.5 text-xs text-[#3a332a] border-b border-[#F2ECE1] last:border-0"
                        >
                            <span class="truncate">{{ v.name }}</span>
                            <span class="shrink-0 ml-2 text-[10px] font-medium bg-[#FBF3E2] text-[#8a6d3b] border border-[#ECDCBB] px-1.5 py-0.5 rounded">view-only</span>
                        </div>
                    </div>

                    <!-- Guiding instruction CTA -->
                    <div class="bg-[#FBFAF6] border border-[#E9E0D3] rounded-2xl p-3.5">
                        <div class="text-sm font-semibold text-[#1f2328] mb-2" style="font-family: 'Spectral', ui-serif, Georgia, serif">Guiding instruction</div>
                        <div v-if="dataSource?.primary_instruction" class="text-xs text-[#2F6F4F] flex items-center gap-1.5">
                            <UIcon name="heroicons-check-circle" class="w-4 h-4" />
                            instruction set
                        </div>
                        <template v-else>
                            <div class="text-[11px] text-[#6b6b6b] mb-2">None yet — set rules the agent always follows.</div>
                            <button
                                v-if="useCan('update_data_source')"
                                @click="creatingInstruction = true"
                                class="w-full text-xs px-3 py-1.5 bg-white text-[#1f2328] border border-[#E9E0D3] rounded-lg hover:bg-[#ECEAE1] transition-colors inline-flex items-center justify-center gap-1.5"
                            >
                                <UIcon name="heroicons-plus" class="w-3.5 h-3.5" />
                                Add primary instruction
                            </button>
                            <div v-if="useCan('update_data_source') && canStartTraining" class="text-center mt-2">
                                <button @click="startTrainingSession" class="text-xs text-[#C2541E] hover:underline inline-flex items-center gap-1">
                                    <UIcon name="heroicons-academic-cap" class="w-3.5 h-3.5" />
                                    Start training
                                </button>
                            </div>
                        </template>
                    </div>

                </div>

            </div>
        </div>

        </div>

        <UModal v-model="showEditModal" :ui="{ width: 'sm:max-w-2xl' }">
            <div class="p-5">
                <div class="text-sm font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">{{ $t('dataSource.editStartersTitle') }}</div>
                <div class="text-xs text-[#6b6b6b] mt-1">{{ $t('dataSource.editStartersHint') }}</div>

                <div class="mt-4 space-y-2 max-h-[60vh] overflow-auto pe-1">
                    <div v-for="(item, idx) in editStarters" :key="idx" class="rounded-md border border-[#E9E0D3] p-2">
                        <div class="flex items-center justify-between mb-1">
                            <span class="text-[10px] uppercase tracking-wide text-[#9a958c]">{{ $t('dataSource.starterN', { n: idx + 1 }) }}</span>
                            <button @click="removeStarter(idx)" class="text-[11px] text-[#6b6b6b] hover:text-red-600">{{ $t('dataSource.remove') }}</button>
                        </div>
                        <div class="space-y-1">
                            <div>
                                <label class="block text-[11px] text-[#6b6b6b] mb-0.5">{{ $t('dataSource.starterTitle') }}</label>
                                <input v-model="item.title" type="text" class="w-full h-8 text-sm border border-[#E9E0D3] rounded-md px-2 focus:outline-none focus:ring-2 focus:ring-[#C2541E]/30 focus:border-[#C2541E]" :placeholder="$t('dataSource.starterTitlePlaceholder')" />
                            </div>
                            <div>
                                <label class="block text-[11px] text-[#6b6b6b] mb-0.5">{{ $t('dataSource.starterPrompt') }}</label>
                                <textarea v-model="item.prompt" rows="2" class="w-full text-sm border border-[#E9E0D3] rounded-md px-2 py-1 focus:outline-none focus:ring-2 focus:ring-[#C2541E]/30 focus:border-[#C2541E]" :placeholder="$t('dataSource.starterPromptPlaceholder')"></textarea>
                            </div>
                        </div>
                    </div>
                    <div>
                        <button @click="addStarter" class="text-xs border border-[#E9E0D3] text-[#1f2328] rounded-lg px-2 py-1 hover:bg-[#ECEAE1]">{{ $t('dataSource.addStarter') }}</button>
                    </div>
                </div>

                <div class="flex justify-end gap-2 mt-4">
                    <button @click="onCancelEdit" class="px-3 py-1.5 text-xs border border-[#E9E0D3] text-[#1f2328] rounded-lg hover:bg-[#ECEAE1]">{{ $t('dataSource.cancel') }}</button>
                    <button @click="onSaveStarters" :disabled="savingStarters" class="px-3 py-1.5 text-xs bg-[#C2541E] text-white rounded-lg hover:bg-[#A8330F] disabled:opacity-60">{{ savingStarters ? $t('dataSource.saving') : $t('dataSource.save') }}</button>
                </div>
            </div>
        </UModal>

    </div>
</template>

<script setup lang="ts">
import { ref, computed, inject, watch, onMounted } from 'vue'
import { useCan } from '~/composables/usePermissions'
import { isIndexingActive, indexingSummary } from '~/composables/useConnectionStatus'
import InstructionGlobalCreateComponent from '~/components/InstructionGlobalCreateComponent.vue'
import InstructionText from '~/components/instructions/InstructionText.vue'
import PrimaryInstructionPicker from '~/components/instructions/PrimaryInstructionPicker.vue'
import PrimaryInstructionMenu from '~/components/instructions/PrimaryInstructionMenu.vue'
import AgentSyncLog from '~/components/agents/AgentSyncLog.vue'
import { useOrgSettings } from '~/composables/useOrgSettings'
import type { Ref } from 'vue'

definePageMeta({ auth: true, layout: 'data' })

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const toast = useToast?.()

// Training mode is gated by org setting + permission (mirrors the prompt box).
const { isTrainingModeEnabled } = useOrgSettings()
const canStartTraining = computed(() => useCan('train_mode') && isTrainingModeEnabled.value)

// Inject integration data from layout (avoid duplicate API calls)
const injectedIntegration = inject<Ref<any>>('integration', ref(null))
const injectedFetchIntegration = inject<() => Promise<void>>('fetchIntegration', async () => {})
const injectedLoading = inject<Ref<boolean>>('isLoading', ref(true))
const injectedFetchError = inject<Ref<number | null>>('fetchError', ref(null))

const dataSource = injectedIntegration
const loading = injectedLoading
const fetchError = injectedFetchError

const availableMeta = ref<any | null>(null)
const showEditModal = ref(false)

// --- Overview endpoint (NEW; degrades gracefully when flag OFF → returns {}) ---
const overview = ref<{
    stats: { active_tables: number; total_columns: number; connections: number }
    tables: { name: string; column_count: number; row_count: number; entity_like: boolean; centrality?: number; purpose: string | null }[]
    joins: { from_table: string; from_column: string; to_table: string; to_column: string }[]
    view_only: { name: string }[]
}>({ stats: { active_tables: 0, total_columns: 0, connections: 0 }, tables: [], joins: [], view_only: [] })
const hasOverview = ref(false)
const TABLE_CAP = 8
const visibleTables = computed(() => overview.value.tables.slice(0, TABLE_CAP))

async function fetchOverview() {
    const id = route.params.id as string
    if (!id) return
    try {
        const { data, error } = await useMyFetch<any>(`/data_sources/${id}/overview`, { method: 'GET' })
        if (error?.value) { hasOverview.value = false; return }
        const d = data?.value as any
        if (d && d.stats) {
            overview.value = {
                stats: {
                    active_tables: d.stats.active_tables ?? 0,
                    total_columns: d.stats.total_columns ?? 0,
                    connections: d.stats.connections ?? 0,
                },
                tables: Array.isArray(d.tables) ? d.tables : [],
                joins: Array.isArray(d.joins) ? d.joins : [],
                view_only: Array.isArray(d.view_only) ? d.view_only : [],
            }
            hasOverview.value = true
        } else {
            hasOverview.value = false
        }
    } catch {
        hasOverview.value = false
    }
}

// --- Launcher: open a NEW report with the text PREFILLED (non-submitting) ---
const launchText = ref('')
const launching = ref(false)

// Starter chips reuse the same list the conversation-starters block shows.
const starterList = computed<string[]>(() => displayDataSource.value?.conversation_starters || [])
function starterPrompt(starter: string) {
    // Starters are stored "title\nprompt" — prefer the prompt body, fall back to title.
    const parts = String(starter).split('\n')
    const prompt = parts.slice(1).join('\n').trim()
    return prompt || (parts[0] || '').trim()
}

async function launchReport(text: string) {
    const t = (text || '').trim()
    if (launching.value || !t || !dataSource.value?.id) return
    launching.value = true
    try {
        const { data, error } = await useMyFetch<any>('/reports', {
            method: 'POST',
            body: { title: 'untitled report', files: [], data_sources: [dataSource.value.id] },
        })
        if (error?.value) throw new Error(String(error.value))
        const newId = (data?.value as any)?.id
        if (newId) {
            router.push(`/reports/${newId}?prompt=${encodeURIComponent(t)}`)
        }
    } catch (e: any) {
        toast?.add?.({ title: 'Error', description: String(e?.message || e), color: 'red' })
    } finally {
        launching.value = false
    }
}

onMounted(fetchOverview)
watch(() => route.params.id, () => fetchOverview())
const editStarters = ref<{ title: string; prompt: string }[]>([])
const savingStarters = ref(false)

// Primary instruction: read-only display by default; create + edit use InstructionGlobalCreateComponent inline.
const creatingInstruction = ref(false)
const editingInstruction = ref(false)
const showFullInstruction = ref(false)
const primaryInstructionDefaultTitle = computed(() => {
    const name = (dataSource.value?.name || '').trim()
    return name ? `${name} - Main` : 'Main'
})

async function onPrimaryInstructionCreated(saved: any) {
    const id = route.params.id as string
    const newId = saved?.id
    try {
        if (newId) {
            const { error } = await useMyFetch(`/data_sources/${id}`, {
                method: 'PUT',
                body: { primary_instruction_id: newId },
            })
            if (error?.value) throw new Error(String(error.value))
        }
        creatingInstruction.value = false
        await injectedFetchIntegration()
        toast?.add?.({ title: 'Saved', description: 'Primary instruction created.' })
    } catch (e: any) {
        toast?.add?.({ title: 'Error', description: String(e?.message || e), color: 'red' })
    }
}

async function onPrimaryInstructionSaved(_saved: any) {
    editingInstruction.value = false
    await injectedFetchIntegration()
}

async function startTrainingSession() {
    const agentId = route.params.id as string
    // Partial prompt the admin completes — pre-filled, not auto-submitted.
    const prompt = 'I need to update the instruction for this agent with '
    try {
        // 1. New report scoped to this agent.
        const { data, error } = await useMyFetch<any>('/reports', {
            method: 'POST',
            body: { title: 'Training session', data_sources: [agentId] },
        })
        const reportId = (data?.value as any)?.id
        if (error?.value || !reportId) throw new Error(error?.value ? String(error.value) : 'Failed to create report')
        // 2. Put it in training mode.
        const { error: modeErr } = await useMyFetch(`/reports/${reportId}`, {
            method: 'PUT',
            body: { mode: 'training' },
        })
        if (modeErr?.value) throw new Error(String(modeErr.value))
        // 3. Land on the report with the prompt pre-filled (non-submitting).
        router.push({ path: `/reports/${reportId}`, query: { prompt } })
    } catch (e: any) {
        toast?.add?.({ title: 'Error', description: String(e?.message || e), color: 'red' })
    }
}

async function onSelectExistingInstruction(instruction: any) {
    const id = route.params.id as string
    const newId = instruction?.id
    if (!newId) return
    try {
        const { error } = await useMyFetch(`/data_sources/${id}`, {
            method: 'PUT',
            body: { primary_instruction_id: newId },
        })
        if (error?.value) throw new Error(String(error.value))
        editingInstruction.value = false
        creatingInstruction.value = false
        await injectedFetchIntegration()
        toast?.add?.({ title: 'Saved', description: 'Primary instruction updated.' })
    } catch (e: any) {
        toast?.add?.({ title: 'Error', description: String(e?.message || e), color: 'red' })
    }
}

const indexingConnections = computed(() =>
    (dataSource.value?.connections || []).filter((c: any) => isIndexingActive(c?.indexing))
)

function connIndexingSummary(conn: any) {
    return indexingSummary(conn?.indexing)
}

const displayDataSource = computed(() => {
    if (!dataSource.value) return null
    const starters = (dataSource.value?.conversation_starters && dataSource.value.conversation_starters.length > 0)
        ? dataSource.value.conversation_starters
        : (availableMeta.value?.conversation_starters || [])
    return {
        ...dataSource.value,
        conversation_starters: starters,
    }
})

async function loadAvailableMeta() {
    try {
        const { data: avail, error: availErr } = await useMyFetch('/available_data_sources', { method: 'GET' })
        if (!availErr?.value && Array.isArray(avail.value)) {
            const byType = (avail.value as any[]).find((x: any) => x.type === dataSource.value?.type)
            availableMeta.value = byType || null
        }
    } catch {}
}

watch(() => dataSource.value?.type, (type) => {
    if (type) loadAvailableMeta()
}, { immediate: true })

function openEditStarters() {
    const starters = (dataSource.value?.conversation_starters && dataSource.value.conversation_starters.length > 0)
        ? dataSource.value.conversation_starters
        : (availableMeta.value?.conversation_starters || [])
    editStarters.value = (starters || []).map((s: string) => {
        const parts = String(s).split('\n')
        const title = (parts[0] || '').trim()
        const prompt = parts.slice(1).join('\n').trim()
        return { title, prompt }
    })
    if (editStarters.value.length === 0) editStarters.value = [{ title: '', prompt: '' }]
    showEditModal.value = true
}

function addStarter() {
    editStarters.value.push({ title: '', prompt: '' })
}

function removeStarter(index: number) {
    editStarters.value.splice(index, 1)
}

async function onSaveStarters() {
    if (savingStarters.value) return
    savingStarters.value = true
    const id = route.params.id as string
    const conversation_starters = editStarters.value
        .map(s => `${(s.title || '').trim()}${s.prompt?.trim() ? `\n${s.prompt.trim()}` : ''}`)
        .filter(s => s.trim().length > 0)
    const { error } = await useMyFetch(`/data_sources/${id}`, {
        method: 'PUT',
        body: { conversation_starters },
    })
    savingStarters.value = false
    if (!error?.value) {
        await injectedFetchIntegration()
        showEditModal.value = false
        toast?.add?.({ title: t('dataSource.savedTitle'), description: t('dataSource.startersUpdated') })
    } else {
        toast?.add?.({ title: t('dataSource.errorTitle'), description: String(error.value), color: 'red' })
    }
}

function onCancelEdit() {
    showEditModal.value = false
}
</script>

<style scoped>
.primary-instruction-editor :deep(.wysiwyg-content .tiptap-prose),
.primary-instruction-editor :deep(.raw-textarea) {
    font-size: 13px;
}

.markdown-wrapper :deep(.markdown-content) {
	@apply leading-relaxed;
	font-size: 14px;

	:where(h1, h2, h3, h4, h5, h6) {
		@apply font-bold mb-4 mt-6;
	}

	h1 { @apply text-3xl; }
	h2 { @apply text-2xl; }
	h3 { @apply text-xl; }

	ul, ol { @apply ps-6 mb-4; }
	ul { @apply list-disc; }
	ol { @apply list-decimal; }
	li { @apply mb-1.5; }
	li > p:only-child,
	li > p:last-child { margin-bottom: 0; }

	pre { @apply bg-gray-50 p-4 rounded-lg mb-4 overflow-x-auto; }
	code { @apply bg-gray-50 px-1 py-0.5 rounded text-sm font-mono; }
	a { @apply text-[#C2541E] hover:text-[#A8330F] underline; }
	blockquote { @apply border-l-4 border-gray-200 pl-4 italic my-4; }
	table { @apply w-full border-collapse mb-4; }
	table th, table td { @apply border border-gray-200 p-2 text-xs bg-white; }
}
</style>
