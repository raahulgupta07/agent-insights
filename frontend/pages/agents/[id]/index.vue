<template>
    <div class="py-6 relative">
        <!-- Hide content when there's a fetch error (layout shows error state) -->
        <div v-if="fetchError" />
        <div v-else>
            <!-- Non-blocking live-metrics indicator: subtle "refreshing…" while headline/overview
                 are in flight, or a tiny fail-soft note + retry on error. NEVER a full-page skeleton
                 — the page stays fully usable with whatever is cached/known. -->
            <div v-if="liveRefreshing || liveError" class="mb-3 flex items-center gap-1.5 text-[11.5px]">
                <template v-if="liveRefreshing">
                    <UIcon name="heroicons-arrow-path" class="w-3.5 h-3.5 animate-spin text-[#A8A29E]" />
                    <span class="text-[#A8A29E]">Refreshing live metrics…</span>
                </template>
                <template v-else>
                    <span class="w-1.5 h-1.5 rounded-full bg-[#C2841E] shrink-0"></span>
                    <span class="text-[#92610A]">Couldn't refresh live metrics.</span>
                    <button type="button" @click="retryLive" class="font-medium text-[#C2541E] hover:underline">Retry</button>
                </template>
            </div>

            <!-- Live sync-log terminal (self-hides when there's no active/recent sync run;
                 the FULL warm-dark terminal appears only while a sync is actually running) -->
            <AgentSyncLog :data-source-id="(route.params.id as string)" :agent-name="dataSource?.name" @phase="onSyncPhase" />

            <!-- Status strip — HONEST: green "ready" only when the sync has actually
                 finished AND kept at least one queryable table. While a sync is running
                 the AgentSyncLog terminal above shows live progress and NO strip shows,
                 so the user never sees a false "ready". 0 tables → amber "no data" with a
                 Build-permission hint. Sync error → red. -->
            <!-- 1) Finished + tables kept → green ready -->
            <NuxtLink
                v-if="hasOverview && !syncActive && syncPhase !== 'error' && overview.stats.active_tables > 0"
                :to="`/agents/${route.params.id}/activity`"
                class="mb-4 flex items-center gap-2.5 bg-[#E7F5EC] border border-[#CDE9D6] rounded-xl px-3.5 py-2.5 text-sm text-[#166534] hover:bg-[#DFF1E6] transition-colors"
            >
                <span class="w-2 h-2 rounded-full bg-[#15803D] shrink-0"></span>
                <span class="font-semibold">Synced &amp; ready</span>
                <span class="text-[#8AAE97]">·</span>
                <span>{{ overview.stats.active_tables }} {{ overview.stats.active_tables === 1 ? 'table' : 'tables' }} kept · {{ overview.stats.total_columns }} columns</span>
                <span class="ml-auto font-semibold text-[#15803D]">View sync log →</span>
            </NuxtLink>

            <!-- 2) Finished but NO queryable tables → honest amber (not a false "ready") -->
            <NuxtLink
                v-else-if="hasOverview && !syncActive && syncPhase === 'done' && overview.stats.active_tables === 0"
                :to="`/agents/${route.params.id}/activity`"
                class="mb-4 flex items-start gap-2.5 bg-[#FBF3E4] border border-[#F0E2C4] rounded-xl px-3.5 py-2.5 text-sm text-[#92610A] hover:bg-[#F7ECD8] transition-colors"
            >
                <span class="w-2 h-2 mt-1.5 rounded-full bg-[#C2841E] shrink-0"></span>
                <span class="flex-1">
                    <span class="font-semibold">Sync finished — no queryable tables found.</span>
                    Your Power BI account may not have <span class="font-medium">Build permission</span> on any dataset, so there's nothing to query yet.
                </span>
                <span class="ml-auto font-semibold text-[#C2841E] whitespace-nowrap">View sync log →</span>
            </NuxtLink>

            <!-- 3) Sync failed → red -->
            <NuxtLink
                v-else-if="syncPhase === 'error'"
                :to="`/agents/${route.params.id}/activity`"
                class="mb-4 flex items-center gap-2.5 bg-[#FCEBEA] border border-[#F5D0CD] rounded-xl px-3.5 py-2.5 text-sm text-[#9B2C2C] hover:bg-[#F9E0DE] transition-colors"
            >
                <span class="w-2 h-2 rounded-full bg-[#C53030] shrink-0"></span>
                <span class="font-semibold">Sync didn't finish</span>
                <span class="text-[#C99]">·</span>
                <span>Open the sync log to see what happened, then try again.</span>
                <span class="ml-auto font-semibold text-[#C53030]">View sync log →</span>
            </NuxtLink>

            <!-- Indexing banner: shown while any linked connection is discovering schema -->
            <div
                v-if="indexingConnections.length > 0 && !isSyncing"
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

                    <!-- 0 · At a glance — headline KPIs from the model's own measures,
                         pre-computed per-user (Hot Start) so real numbers show before
                         the user types. Hidden entirely when there are none. -->
                    <div v-if="headline.status === 'warming' || headlineItems.length"
                         class="order-0 flex flex-wrap gap-3">
                        <template v-if="headline.status === 'warming' && !headlineItems.length">
                            <div v-for="i in 4" :key="'hlsk'+i"
                                 class="flex-1 min-w-[130px] h-[68px] rounded-xl bg-[#F4F1EC] animate-pulse"></div>
                        </template>
                        <button v-for="(kpi, ki) in headlineItems" :key="'hl'+ki"
                             type="button"
                             @click="launchReport('Show me ' + kpi.label)"
                             :title="'Open a report about ' + kpi.label"
                             class="flex-1 min-w-[130px] text-left bg-white border border-[#EAE8E4] rounded-xl px-4 py-3 shadow-[0_1px_2px_rgba(28,25,23,.04)] hover:border-[#D9CFC2] hover:shadow-[0_2px_6px_rgba(28,25,23,.08)] transition-all cursor-pointer">
                            <div class="text-[20px] font-semibold text-[#1C1917] leading-tight tabular-nums">{{ kpi.value }}</div>
                            <div class="text-[11.5px] text-[#6b6b6b] mt-1 truncate">{{ kpi.label }}</div>
                        </button>
                    </div>

                    <!-- 1 · What this agent knows (existing primary-instruction block) -->
                    <div class="order-1 bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)]">
                        <div class="px-4 py-3 border-b border-[#F1EFEC] text-[13.5px] font-semibold text-[#1C1917] flex items-center gap-2">
                            <UIcon name="heroicons-book-open" class="w-4 h-4 text-[#C2541E]" />
                            What this agent knows
                        </div>
                        <div class="p-4">

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
                                <div v-if="!showFullInstruction" class="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-white to-transparent" />
                            </div>
                            <button @click="showFullInstruction = !showFullInstruction" class="mt-1.5 text-xs font-medium text-[#C2541E] hover:underline">
                                {{ showFullInstruction ? 'Show less' : 'Show more' }}
                            </button>
                        </template>

                        <!-- Learning state — while a sync is running and nothing is filled yet -->
                        <div v-else-if="isSyncing" class="border border-dashed border-[#E9E0D3] rounded-2xl px-6 py-8 bg-[#F4EEE5]/40">
                            <div class="flex items-center gap-2 text-[13px] font-medium text-[#8a5a3c]">
                                <UIcon name="heroicons-arrow-path" class="w-4 h-4 animate-spin text-[#C2541E]" />
                                Learning your data…
                            </div>
                            <div class="text-xs text-[#A8A29E] mt-1">Primary instruction &amp; starters will auto-fill when the sync finishes.</div>
                            <div class="mt-4 space-y-2">
                                <div class="h-3 rounded bg-[#ECE4D7] animate-pulse w-3/4"></div>
                                <div class="h-3 rounded bg-[#ECE4D7] animate-pulse w-full"></div>
                                <div class="h-3 rounded bg-[#ECE4D7] animate-pulse w-2/3"></div>
                            </div>
                        </div>

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
                    </div>

                    <!-- 2 · Core tables card (from overview endpoint) — grouped by dataset -->
                    <div v-if="hasOverview && overview.tables.length" class="order-2 bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)]">
                        <div class="px-4 py-3 border-b border-[#F1EFEC] text-[13.5px] font-semibold text-[#1C1917] flex items-center gap-2">
                            <UIcon name="heroicons-table-cells" class="w-4 h-4 text-[#C2541E]" />
                            Core tables
                            <span class="ml-auto text-[11.5px] font-medium text-[#A8A29E]">{{ overview.stats.active_tables }} active · {{ overview.stats.total_columns }} columns</span>
                        </div>
                        <div class="px-4 pb-4 pt-1">
                            <template v-for="grp in groupedTables" :key="grp.dataset || '_'">
                                <!-- dataset group header (omitted when there is no dataset prefix) -->
                                <div v-if="grp.dataset" class="flex items-center gap-2 pt-3.5 pb-1.5">
                                    <span class="text-[11px] font-semibold uppercase tracking-[0.05em] text-[#A8A29E]">{{ grp.dataset }}</span>
                                    <span class="flex-1 h-px bg-[#F1EFEC]"></span>
                                </div>
                                <div
                                    v-for="tbl in grp.tables"
                                    :key="tbl.name"
                                    class="flex items-center gap-3 py-2.5 border-b border-[#F1EFEC] last:border-0"
                                >
                                    <div class="w-7 h-7 rounded-lg bg-[#F1EFEC] grid place-items-center shrink-0">
                                        <UIcon :name="tbl.entity_like ? 'heroicons-cube' : 'heroicons-table-cells'" class="w-4 h-4 text-[#78716C]" />
                                    </div>
                                    <div class="flex-1 min-w-0">
                                        <div class="font-mono text-[13.5px] font-medium text-[#1C1917] truncate">{{ shortTableName(tbl.name) }}</div>
                                        <!-- grain sub-line, only when a purpose is present (no fabrication) -->
                                        <div v-if="tbl.purpose" class="text-[11.5px] text-[#A8A29E] leading-snug truncate">{{ tbl.purpose }}</div>
                                    </div>
                                    <!-- relevance badge from classification metadata; hidden when absent -->
                                    <span
                                        v-if="tableClassification(tbl)"
                                        class="text-[10.5px] font-semibold px-1.5 py-0.5 rounded-md whitespace-nowrap"
                                        :class="{
                                            'text-[#15803D] bg-[#E7F5EC]': badgeTone(tableClassification(tbl)!.audience) === 'biz',
                                            'text-[#B45309] bg-[#FBF0DD]': badgeTone(tableClassification(tbl)!.audience) === 'admin',
                                            'text-[#6B7280] bg-[#F1F1F0]': badgeTone(tableClassification(tbl)!.audience) === 'sys',
                                        }"
                                    >{{ tableClassification(tbl)!.audience }}<template v-if="tableClassification(tbl)!.role"> · {{ tableClassification(tbl)!.role }}</template></span>
                                    <span class="text-[12px] text-[#78716C] tabular-nums whitespace-nowrap shrink-0">{{ tbl.column_count }} cols</span>
                                </div>
                            </template>
                            <div v-if="overview.tables.length > visibleTables.length" class="pt-3 text-center">
                                <NuxtLink :to="`/agents/${route.params.id}/tables`" class="text-[12.5px] font-medium text-[#C2541E] hover:underline">
                                    See all {{ overview.tables.length }} tables →
                                </NuxtLink>
                            </div>
                        </div>
                    </div>

                    <!-- 3 · Key relationships card (honest empty state when none) -->
                    <div v-if="hasOverview && overview.tables.length" class="order-3 bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)]">
                        <div class="px-4 py-3 border-b border-[#F1EFEC] text-[13.5px] font-semibold text-[#1C1917] flex items-center gap-2">
                            <UIcon name="heroicons-link" class="w-4 h-4 text-[#C2541E]" />
                            Key relationships
                            <span v-if="!overview.joins.length" class="ml-auto text-[11.5px] font-medium text-[#A8A29E]">inferred — Power BI hides FKs over the API</span>
                        </div>
                        <div class="p-4">
                            <template v-if="overview.joins.length">
                                <div
                                    v-for="(j, idx) in overview.joins"
                                    :key="idx"
                                    class="flex items-center gap-2 py-2 text-[12.5px] flex-wrap border-b border-[#F1EFEC] last:border-0"
                                >
                                    <code class="font-mono text-[12px] text-[#1C1917] font-medium">{{ j.from_table }}.{{ j.from_column }}</code>
                                    <span class="text-[#A8A29E]">→</span>
                                    <code class="font-mono text-[12px] text-[#C2541E] font-medium">{{ j.to_table }}.{{ j.to_column }}</code>
                                </div>
                            </template>
                            <div v-else class="text-[12.5px] text-[#78716C] leading-relaxed">
                                No table relationships are defined in this source's schema — Power BI models don't expose foreign keys over the API, so joins are inferred at query time by the agent instead.
                            </div>
                        </div>
                    </div>

                </div>

                <!-- RIGHT rail (lg only) -->
                <div v-if="hasOverview" class="w-full lg:w-[300px] lg:shrink-0 space-y-4">

                    <!-- At a glance -->
                    <div class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)]">
                        <div class="px-4 py-3 border-b border-[#F1EFEC] text-[13.5px] font-semibold text-[#1C1917]">At a glance</div>
                        <div class="p-4">
                            <div class="grid grid-cols-2 gap-3">
                                <div class="border border-[#EAE8E4] rounded-[10px] px-3.5 py-3">
                                    <div class="text-[24px] font-bold tracking-[-0.02em] text-[#1C1917] tabular-nums">{{ overview.stats.active_tables }}</div>
                                    <div class="text-[11.5px] text-[#78716C] mt-0.5">active tables</div>
                                </div>
                                <div class="border border-[#EAE8E4] rounded-[10px] px-3.5 py-3">
                                    <div class="text-[24px] font-bold tracking-[-0.02em] text-[#1C1917] tabular-nums">{{ overview.stats.total_columns }}</div>
                                    <div class="text-[11.5px] text-[#78716C] mt-0.5">columns</div>
                                </div>
                            </div>

                            <!-- Agent readiness — computed only from data already fetched -->
                            <div v-if="readiness !== null" class="mt-3.5">
                                <div class="flex items-baseline justify-between mb-1.5">
                                    <span class="text-[12.5px] text-[#78716C]">Agent readiness</span>
                                    <span class="text-[15px] font-bold text-[#15803D] tabular-nums">{{ readiness }}<span class="text-[11px] font-medium text-[#A8A29E]">/100</span></span>
                                </div>
                                <div class="h-[7px] rounded bg-[#F1EFEC] overflow-hidden">
                                    <div class="h-full bg-[#C2541E]" :style="{ width: readiness + '%' }"></div>
                                </div>
                                <div class="text-[11.5px] text-[#78716C] mt-1.5">
                                    {{ readinessDescribed.described }}/{{ readinessDescribed.total }} tables described<template v-if="overview.joins.length"> · joins mapped</template><template v-if="starterList.length"> · starters ready</template>
                                </div>
                            </div>

                            <div class="flex justify-between items-center pt-3 mt-1 border-t border-[#F1EFEC] text-[13px]">
                                <span class="text-[#78716C]">Connected</span>
                                <span class="text-[#1C1917]">{{ overview.stats.connections }} {{ overview.stats.connections === 1 ? 'connection' : 'connections' }}</span>
                            </div>
                        </div>
                    </div>

                    <!-- Start a report (launcher moved here — manage-not-chat) -->
                    <div class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)]">
                        <div class="px-4 py-3 border-b border-[#F1EFEC] flex items-center gap-2 text-[13.5px] font-semibold text-[#1C1917]">
                            Start a report
                            <button v-if="useCan('update_data_source')" @click="openEditStarters" class="ml-auto text-[11px] font-medium text-[#C2541E] hover:underline">{{ $t('dataSource.edit') }}</button>
                        </div>
                        <div class="p-4">
                            <!-- syncing note — the agent isn't ready to answer yet -->
                            <div v-if="isSyncing" class="flex items-center gap-1.5 text-[12px] text-[#A8A29E] mb-2">
                                <UIcon name="heroicons-arrow-path" class="w-3.5 h-3.5 animate-spin" />
                                Ready in a moment — finishing sync
                            </div>
                            <!-- free-text launcher -->
                            <div class="flex gap-2 items-center bg-white border border-[#EAE8E4] rounded-[10px] pl-3 pr-1.5 py-1.5 mb-3" :class="{ 'opacity-60': isSyncing }">
                                <input
                                    v-model="launchText"
                                    type="text"
                                    :disabled="isSyncing"
                                    :placeholder="isSyncing ? 'Finishing sync…' : 'Ask this agent…'"
                                    class="flex-1 min-w-0 text-[13px] bg-transparent outline-none text-[#1C1917] placeholder:text-[#A8A29E] disabled:cursor-not-allowed"
                                    @keydown.enter="launchReport(launchText)"
                                />
                                <button
                                    :disabled="launching || isSyncing || !launchText.trim()"
                                    @click="launchReport(launchText)"
                                    class="shrink-0 text-[12px] font-medium px-2.5 py-1.5 bg-[#C2541E] text-white rounded-lg hover:bg-[#A8330F] transition-colors disabled:opacity-50"
                                >→</button>
                            </div>
                            <!-- starter chips -->
                            <div v-if="starterList.length" class="flex flex-col gap-2">
                                <button
                                    v-for="(starter, idx) in starterList"
                                    :key="idx"
                                    @click="launchReport(starterPrompt(starter))"
                                    class="flex items-center justify-between gap-2 text-left border border-[#EAE8E4] rounded-[10px] px-3 py-2 text-[12.5px] text-[#44403C] hover:border-[#C2541E] hover:text-[#C2541E] transition-colors"
                                >
                                    <span class="truncate">{{ starter.split('\n')[0] }}</span>
                                    <span class="text-[#C2541E] shrink-0">→</span>
                                </button>
                            </div>
                            <div class="flex items-start gap-2 mt-3 text-[12px] text-[#A8A29E] bg-[#F1EFEC] rounded-lg px-3 py-2 leading-snug">
                                <span class="shrink-0">↗</span>
                                <span>Opens a new report — this page is for managing the agent, not chatting.</span>
                            </div>
                        </div>
                    </div>

                    <!-- View-only (only if present) -->
                    <div v-if="overview.view_only.length" class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)]">
                        <div class="px-4 py-3 border-b border-[#F1EFEC] text-[13.5px] font-semibold text-[#1C1917]">View-only</div>
                        <div class="p-4 pt-1">
                            <div
                                v-for="(v, idx) in overview.view_only"
                                :key="idx"
                                class="flex justify-between items-center py-2 text-[12.5px] text-[#44403C] border-b border-[#F1EFEC] last:border-0"
                            >
                                <span class="truncate">{{ v.name }}</span>
                                <span class="shrink-0 ml-2 text-[10px] font-semibold text-[#B45309] bg-[#FBF0DD] px-1.5 py-0.5 rounded-md">view-only</span>
                            </div>
                        </div>
                    </div>

                    <!-- Guiding instruction CTA -->
                    <div class="bg-white border border-[#EAE8E4] rounded-xl shadow-[0_1px_2px_rgba(28,25,23,.04),0_1px_3px_rgba(28,25,23,.06)] p-4">
                        <div class="text-[13.5px] font-semibold text-[#1C1917] mb-2">Guiding instruction</div>
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
type OverviewTable = {
    name: string
    column_count: number
    row_count: number
    entity_like: boolean
    centrality?: number
    purpose: string | null
    metadata_json?: { classification?: { audience?: string; role?: string } | null } | null
}
const overview = ref<{
    stats: { active_tables: number; total_columns: number; connections: number }
    tables: OverviewTable[]
    joins: { from_table: string; from_column: string; to_table: string; to_column: string }[]
    view_only: { name: string }[]
}>({ stats: { active_tables: 0, total_columns: 0, connections: 0 }, tables: [], joins: [], view_only: [] })
const hasOverview = ref(false)

// --- Non-blocking live-metrics state (headline + overview run against Power BI, 20-40s,
// rate-limited). The page must NEVER wait on them: we show cached/known content instantly,
// refresh in the background, and fail soft (keep the page usable + offer a retry). ---
const overviewLoading = ref(false)
const overviewError = ref(false)
const headlineLoading = ref(false)
const headlineError = ref(false)

// stale-while-revalidate cache (per data-source id) — last good values render instantly.
const LS_OV_PREFIX = 'ca_agent_overview_v1:'
const LS_HL_PREFIX = 'ca_agent_headline_v1:'
function _lsGet(key: string): any | null {
    try { const raw = localStorage.getItem(key); return raw ? JSON.parse(raw) : null } catch { return null }
}
function _lsSet(key: string, val: any) {
    try { localStorage.setItem(key, JSON.stringify(val)) } catch { /* quota/private mode — non-fatal */ }
}
function loadCachedOverview(id: string) {
    const c = _lsGet(LS_OV_PREFIX + id)
    if (c && c.stats) { overview.value = c; hasOverview.value = true }
}
function loadCachedHeadline(id: string) {
    const c = _lsGet(LS_HL_PREFIX + id)
    if (c && Array.isArray(c.items) && c.items.length) headline.value = { status: c.status || 'ready', items: c.items }
}

// subtle, non-blocking indicators (never a full-page skeleton)
const liveRefreshing = computed(() => overviewLoading.value || headlineLoading.value)
const liveError = computed(() => overviewError.value || headlineError.value)
function retryLive() {
    _headlinePolls = 0
    try { fetchOverview() } catch (_e) {}
    try { fetchHeadline() } catch (_e) {}
}

// Live sync phase from AgentSyncLog, so the status strip is HONEST: never show a
// green "ready" while a sync is still running or when 0 tables were kept.
const syncPhase = ref<string>('')
const syncActive = computed(
    () => !!syncPhase.value && !['done', 'error', 'idle'].includes(syncPhase.value),
)
// Alias for the syncing-state page treatment (skeletons, launcher gate, hidden indexing banner).
const isSyncing = syncActive
// Guard: act on the 'done' transition exactly ONCE. AgentSyncLog lives inside the
// layout's page slot, which is `v-else` of the full-page skeleton — so any toggle of
// the layout `isLoading` unmounts+remounts AgentSyncLog, and a fresh AgentSyncLog
// re-emits 'done'. Without this guard (and with a NON-silent integration refetch
// below) that formed an infinite unmount/remount loop (skeleton blinked forever).
let _syncDoneHandled = false
function onSyncPhase(p: string) {
    syncPhase.value = p || ''
    // A finished sync changed the kept-table set → refresh the overview + headline
    // once so the strip + cards reflect the real result instead of the pre-sync snapshot.
    // Also refetch the agent detail so the auto-filled primary instruction + starters appear.
    if (p === 'done') {
        if (_syncDoneHandled) return
        _syncDoneHandled = true
        try { fetchOverview() } catch (_e) {}
        try { fetchHeadline() } catch (_e) {}
        // SILENT refetch — must NOT toggle the layout `isLoading` (that unmounts this
        // page + AgentSyncLog and restarts the whole cycle).
        try { injectedFetchIntegration(true) } catch (_e) {}
    } else {
        // A new run started (e.g. re-sync) → allow the next 'done' to be handled again.
        _syncDoneHandled = false
    }
}

// Hot Start — headline KPIs (the model's own measures), pre-computed per-user.
const headline = ref<{ status: string; items: { label: string; value: string }[] }>({ status: '', items: [] })
const headlineItems = computed(() => headline.value.items || [])
let _headlinePolls = 0
async function fetchHeadline() {
    const id = route.params.id as string
    headlineLoading.value = true
    try {
        const { data } = await useMyFetch<any>(`/data_sources/${id}/headline`, { method: 'GET' })
        const r = (data.value as any) || { status: 'error', items: [] }
        headline.value = { status: r.status || 'error', items: Array.isArray(r.items) ? r.items : [] }
        headlineError.value = false
        // persist good KPIs so the next visit shows them instantly (stale-while-revalidate)
        if (headline.value.items.length) _lsSet(LS_HL_PREFIX + id, headline.value)
        // still warming + nothing yet → poll a few times (measures compute in the background)
        if (headline.value.status !== 'ready' && !headline.value.items.length && _headlinePolls < 6) {
            _headlinePolls++
            setTimeout(fetchHeadline, 4000)
        }
    } catch (_e) {
        // fail soft: keep any cached/prior KPIs on screen; only blank if we have nothing
        headlineError.value = true
        if (!headlineItems.value.length) headline.value = { status: 'error', items: [] }
    } finally {
        headlineLoading.value = false
    }
}

const TABLE_CAP = 8
const visibleTables = computed(() => overview.value.tables.slice(0, TABLE_CAP))

// --- Restyle helpers (grouping + readiness) — use ONLY data already fetched ---

// A relevance badge from the table's classification metadata; null when absent (no badge).
function tableClassification(tbl: OverviewTable): { audience: string; role: string } | null {
    const c = tbl?.metadata_json?.classification
    if (!c || !c.audience) return null
    return { audience: String(c.audience), role: String(c.role || '') }
}
// audience → badge colour bucket (business green / admin amber / system gray)
function badgeTone(audience: string): 'biz' | 'admin' | 'sys' {
    const a = (audience || '').toLowerCase()
    if (a === 'business') return 'biz'
    if (a === 'admin') return 'admin'
    return 'sys'
}

// The overview table name is "<dataset>/<table>" — group the capped visible tables by dataset.
const groupedTables = computed(() => {
    const groups: { dataset: string; tables: OverviewTable[] }[] = []
    const byName: Record<string, OverviewTable[]> = {}
    for (const tbl of visibleTables.value) {
        const slash = tbl.name.indexOf('/')
        const dataset = slash > 0 ? tbl.name.slice(0, slash) : ''
        if (!byName[dataset]) { byName[dataset] = []; groups.push({ dataset, tables: byName[dataset] }) }
        byName[dataset].push(tbl)
    }
    return groups
})
// Show just the table part ("<dataset>/<table>" → "<table>") in grouped rows.
function shortTableName(name: string): string {
    const slash = name.indexOf('/')
    return slash > 0 ? name.slice(slash + 1) : name
}

// Agent readiness — real fraction of curated tables that carry a purpose/description,
// nudged by whether joins + conversation starters exist. All inputs already fetched.
const readiness = computed<number | null>(() => {
    const tables = overview.value.tables
    if (!tables.length) return null
    const described = tables.filter(t => (t.purpose || '').trim().length > 0).length
    const describedFrac = described / tables.length            // 0..1
    const hasJoins = overview.value.joins.length > 0 ? 1 : 0
    const hasStarters = (starterList.value?.length || 0) > 0 ? 1 : 0
    // weighted: 70% described, 15% joins present, 15% starters present
    const score = describedFrac * 0.7 + hasJoins * 0.15 + hasStarters * 0.15
    return Math.round(score * 100)
})
const readinessDescribed = computed(() => {
    const tables = overview.value.tables
    return {
        described: tables.filter(t => (t.purpose || '').trim().length > 0).length,
        total: tables.length,
    }
})

async function fetchOverview() {
    const id = route.params.id as string
    if (!id) return
    overviewLoading.value = true
    try {
        const { data, error } = await useMyFetch<any>(`/data_sources/${id}/overview`, { method: 'GET' })
        // fail soft: on error/empty, KEEP any cached/prior overview (do NOT blank hasOverview)
        if (error?.value) { overviewError.value = true; return }
        const d = data?.value as any
        if (d && d.stats) {
            overview.value = {
                stats: {
                    active_tables: d.stats.active_tables ?? 0,
                    total_columns: d.stats.total_columns ?? 0,
                    connections: d.stats.connections ?? 0,
                },
                tables: Array.isArray(d.tables) ? (d.tables as OverviewTable[]) : [],
                joins: Array.isArray(d.joins) ? d.joins : [],
                view_only: Array.isArray(d.view_only) ? d.view_only : [],
            }
            hasOverview.value = true
            overviewError.value = false
            _lsSet(LS_OV_PREFIX + id, overview.value)  // stale-while-revalidate
        } else {
            overviewError.value = true
        }
    } catch {
        overviewError.value = true
    } finally {
        overviewLoading.value = false
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

onMounted(() => {
    const id = route.params.id as string
    // paint last-known values instantly, then revalidate live in the background
    loadCachedOverview(id); loadCachedHeadline(id)
    fetchOverview(); fetchHeadline()
})
watch(() => route.params.id, (id) => {
    _headlinePolls = 0
    overviewError.value = false; headlineError.value = false
    loadCachedOverview(id as string); loadCachedHeadline(id as string)
    fetchOverview(); fetchHeadline()
})
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
