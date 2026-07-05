<template>
  <!-- Shared agent detail body: Connect card (locked) OR the tabbed
       Overview / Tables / Instructions / Queries view for a data agent
       (data_source). Header/positioning is owned by the parent (AgentFlyout,
       StudioFlyout, …) so this is just the body and can be embedded anywhere.
       Everything is driven by `agentId`; `reportGrounding` lets a studio start
       reports grounded on the studio + all its sources instead of one agent. -->
  <div class="flex-1 min-h-0 flex flex-col overflow-hidden">
    <!-- Locked state: agent requires per-user auth and this user hasn't
         connected. Show a slim Connect card instead of tabs/content. -->
    <div v-if="locked" class="px-4 py-4 flex-shrink-0">
      <p class="text-xs text-gray-500 mb-3">{{ $t('agentFlyout.connectToPreview') }}</p>
      <button
        @click.stop="emit('connect', agentDetails)"
        class="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs text-[#C2541E] bg-[#F6EFEA] border border-[#E8C9B5] rounded-lg hover:bg-[#F4E5DA] transition-colors"
      >
        <Icon name="heroicons-key" class="w-3.5 h-3.5" />
        {{ $t('data.connect') }}
      </button>
    </div>

    <!-- Tabs (underline / border-bottom style like Settings) -->
    <div v-else class="border-b border-gray-200 px-4 flex-shrink-0">
      <nav class="-mb-px flex space-x-4">
        <button
          @click="flyoutTab = 'overview'"
          :class="[
            flyoutTab === 'overview'
              ? 'border-indigo-500 text-indigo-600'
              : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700',
            'whitespace-nowrap border-b-2 py-2 text-xs font-medium'
          ]"
        >
          {{ $t('agentFlyout.overview') }}
        </button>
        <button
          @click="flyoutTab = 'tables'"
          :class="[
            flyoutTab === 'tables'
              ? 'border-indigo-500 text-indigo-600'
              : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700',
            'whitespace-nowrap border-b-2 py-2 text-xs font-medium'
          ]"
        >
          {{ $t('agentFlyout.tables') }}
          <span v-if="tablesCount > 0" class="ms-1 text-[10px] text-gray-400">({{ tablesCount }})</span>
        </button>
        <button
          @click="flyoutTab = 'instructions'"
          :class="[
            flyoutTab === 'instructions'
              ? 'border-indigo-500 text-indigo-600'
              : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700',
            'whitespace-nowrap border-b-2 py-2 text-xs font-medium'
          ]"
        >
          {{ $t('agentFlyout.instructions') }}
          <span v-if="instructionsCount > 0" class="ms-1 text-[10px] text-gray-400">({{ instructionsCount }})</span>
        </button>
        <button
          @click="flyoutTab = 'queries'"
          :class="[
            flyoutTab === 'queries'
              ? 'border-indigo-500 text-indigo-600'
              : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700',
            'whitespace-nowrap border-b-2 py-2 text-xs font-medium'
          ]"
        >
          {{ $t('agentFlyout.queries') }}
          <span v-if="queriesCount > 0" class="ms-1 text-[10px] text-gray-400">({{ queriesCount }})</span>
        </button>
      </nav>
    </div>

    <div v-if="!locked" class="p-4 flex-1 min-h-0 overflow-y-auto">
      <div v-if="loadingDetails" class="flex items-center justify-center py-8">
        <Spinner class="w-5 h-5 text-gray-400 animate-spin" />
      </div>

      <template v-else>
        <!-- Overview tab -->
        <div v-if="flyoutTab === 'overview'" class="space-y-4">
          <!-- Optional lead-in slot (e.g. a studio's own summary above the agent overview) -->
          <slot name="overview-lead" />

          <!-- Primary Instruction -->
          <div v-if="agentDetails?.primary_instruction" class="max-h-[40vh] overflow-y-auto pe-1">
            <InstructionText
              :text="agentDetails.primary_instruction.text"
              :references="agentDetails.primary_instruction.references || []"
              :prose="true"
            />
          </div>

          <!-- Description rendered as Markdown -->
          <div
            v-if="agentDetails?.description"
            class="agent-flyout-markdown hidden text-xs text-gray-600 leading-relaxed max-h-[320px] overflow-auto pe-1"
          >
            <MDC :value="agentDetails.description" class="markdown-content" />
          </div>

          <!-- Sample Questions (hidden when the parent supplies its own, e.g. a
               studio's suggested questions via the overview-lead slot). -->
          <div v-if="showStarters && agentDetails?.conversation_starters?.length">
            <div class="text-[10px] uppercase tracking-wider text-gray-400 font-semibold mb-2">{{ $t('agentFlyout.sampleQuestions') }}</div>
            <div class="space-y-1.5">
              <button
                v-for="(starter, idx) in agentDetails.conversation_starters.slice(0, 6)"
                :key="idx"
                @click.stop.prevent="startReportWithQuestion(starter, Number(idx))"
                :disabled="creatingReport"
                :class="[
                  'w-full text-start text-xs px-3 py-2 rounded-lg transition-colors flex items-center gap-2',
                  creatingReport && creatingQuestionIdx === idx
                    ? 'bg-indigo-100 border border-indigo-300 text-indigo-700'
                    : 'bg-gray-50 border border-gray-100 text-gray-700 hover:bg-indigo-50 hover:border-indigo-200 hover:text-indigo-700 cursor-pointer',
                  creatingReport && creatingQuestionIdx !== idx ? 'opacity-50 cursor-not-allowed' : ''
                ]"
              >
                <Spinner v-if="creatingReport && creatingQuestionIdx === idx" class="w-3 h-3 flex-shrink-0 animate-spin" />
                <span class="flex-1">{{ starter.split('\n')[0] }}</span>
              </button>
              <div
                v-if="agentDetails.conversation_starters.length > 6"
                class="text-[11px] text-gray-400"
              >
                {{ $t('agentFlyout.moreCount', { n: agentDetails.conversation_starters.length - 6 }) }}
              </div>
            </div>
          </div>

          <!-- Auto-EDA (BI-uplift Phase 6): per-agent first-look, saved on the
               agent only. Shown when eda_profile is present. -->
          <div v-if="eda" class="rounded-xl border border-[#E9E0D3] bg-[#FBF4EF] p-3">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-[10px] uppercase tracking-wider text-[#9a958c] font-semibold">Data at a glance</span>
              <span class="text-[10px] text-[#b7ab9b]">{{ edaProfile?.n_rows?.toLocaleString?.() || edaProfile?.n_rows }} rows · {{ edaProfile?.n_cols }} cols</span>
              <button
                @click.stop.prevent="refreshEda"
                :disabled="edaRefreshing"
                class="ms-auto text-[10px] px-2 py-0.5 rounded-md border border-[#e6d6c8] text-[#8B4427] hover:bg-[#F4EEE5] transition-colors cursor-pointer disabled:opacity-50"
              >
                <Spinner v-if="edaRefreshing" class="w-3 h-3 inline animate-spin" />
                <span v-else>Refresh</span>
              </button>
            </div>

            <!-- data-prep banner (Phase 5 summary if present) -->
            <div v-if="eda.prep && eda.prep.rows_droppable > 0" class="text-[10.5px] text-[#7a6f60] mb-2">
              <b class="text-[#8B4427]">Prep:</b> {{ eda.prep.rows_clean?.toLocaleString?.() }} of {{ eda.prep.total_rows?.toLocaleString?.() }} rows clean · {{ eda.prep.rows_droppable }} dropped (missing critical values)
            </div>

            <!-- insights -->
            <ul v-if="eda.insights?.length" class="space-y-1 mb-2.5">
              <li v-for="(ins, i) in eda.insights.slice(0,5)" :key="i" class="flex items-start gap-2 text-[12px] text-[#4b4b4b] leading-snug">
                <span class="mt-1.5 w-1 h-1 rounded-full flex-none bg-[#C2541E]"></span>
                <span>{{ ins }}</span>
              </li>
            </ul>

            <!-- category shares as labelled bars -->
            <div v-if="edaProfile?.category_shares?.rows?.length" class="mb-2.5">
              <div class="text-[9.5px] uppercase tracking-wide text-[#9a958c] font-semibold mb-1">{{ edaProfile.category_shares.dim }}</div>
              <div v-for="(r, i) in edaProfile.category_shares.rows.slice(0,5)" :key="i" class="mb-1">
                <div class="flex justify-between text-[10.5px] text-[#6b6b6b]"><span class="truncate">{{ r.label }}</span><span>{{ r.pct }}%</span></div>
                <div class="h-1.5 rounded-full bg-[#eaded1]"><div class="h-1.5 rounded-full bg-[#C2541E]" :style="{ width: Math.max(2, r.pct) + '%' }"></div></div>
              </div>
            </div>

            <!-- time-series peak / ranking chips -->
            <div class="flex flex-wrap gap-1.5 mb-1">
              <span v-if="edaProfile?.time_series?.peak_period" class="text-[10px] px-2 py-0.5 rounded-full bg-white border border-[#e6d6c8] text-[#6b6b6b]">
                Peak {{ edaProfile.time_series.peak_period }}<template v-if="edaProfile.time_series.growth_pct != null"> · {{ edaProfile.time_series.growth_pct }}% overall</template>
              </span>
              <span v-if="edaProfile?.distribution?.outlier_count" class="text-[10px] px-2 py-0.5 rounded-full bg-white border border-[#e6d6c8] text-[#6b6b6b]">
                {{ edaProfile.distribution.outlier_count }} outliers in {{ edaProfile.distribution.column }}
              </span>
            </div>

            <!-- suggested first questions -->
            <div v-if="eda.suggested_questions?.length" class="mt-2">
              <div class="text-[9.5px] uppercase tracking-wide text-[#9a958c] font-semibold mb-1.5">Ask to get started</div>
              <div class="space-y-1.5">
                <button
                  v-for="(q, qi) in eda.suggested_questions.slice(0,4)"
                  :key="qi"
                  @click.stop.prevent="startReportWithQuestion(q, 1000 + Number(qi))"
                  :disabled="creatingReport"
                  class="w-full text-start text-xs px-3 py-2 rounded-lg bg-white border border-[#eadfd2] text-gray-700 hover:bg-[#F4EEE5] hover:border-[#e0cbbb] transition-colors cursor-pointer flex items-center gap-2"
                >
                  <Spinner v-if="creatingReport && creatingQuestionIdx === (1000 + Number(qi))" class="w-3 h-3 flex-shrink-0 animate-spin" />
                  <span class="flex-1">{{ q }}</span>
                </button>
              </div>
            </div>
          </div>

          <!-- KPI layer (BI-uplift Phase 3, HYBRID_KPI_LAYER): governed KPIs —
               outcome-first, leading/lagging, target/action. Shown when present. -->
          <div v-if="kpis.length" class="rounded-xl border border-[#E9E0D3] bg-white p-3">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-[10px] uppercase tracking-wider text-[#9a958c] font-semibold">Key metrics</span>
              <button
                @click.stop.prevent="refreshKpis"
                :disabled="kpiRefreshing"
                class="ms-auto text-[10px] px-2 py-0.5 rounded-md border border-[#e6d6c8] text-[#8B4427] hover:bg-[#F4EEE5] transition-colors cursor-pointer disabled:opacity-50"
              >
                <Spinner v-if="kpiRefreshing" class="w-3 h-3 inline animate-spin" />
                <span v-else>Refresh</span>
              </button>
            </div>
            <div class="space-y-2">
              <div v-for="(k, i) in kpis" :key="i" class="rounded-lg border border-[#eee3d6] p-2.5">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-[13px] font-semibold text-[#211B14]">{{ k.name }}</span>
                  <span class="text-[8.5px] font-bold px-1.5 py-0.5 rounded uppercase" :class="k.leading_lagging === 'leading' ? 'bg-[#fff3cd] text-[#b45309]' : 'bg-[#e7edfb] text-[#2C53A8]'">{{ k.leading_lagging }}</span>
                  <span v-if="k.kind === 'activity'" class="text-[8.5px] font-bold px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 uppercase">activity</span>
                  <span v-else class="text-[8.5px] font-bold px-1.5 py-0.5 rounded bg-[#EEFAF1] text-[#157A43] uppercase">outcome</span>
                  <span v-if="k.target" class="ms-auto text-[10px] text-[#6b6b6b]">target {{ k.target }}</span>
                </div>
                <div class="text-[11.5px] text-[#6b6b6b] mt-0.5 leading-snug">{{ k.definition }}</div>
                <div v-if="k.better" class="text-[10.5px] text-[#8B4427] mt-0.5">→ better: {{ k.better }}</div>
                <div v-if="k.depends_on" class="text-[10px] text-[#9a958c] mt-0.5">leads to <b>{{ k.depends_on }}</b></div>
                <div v-if="k.action" class="text-[10.5px] text-[#6b6b6b] mt-0.5">if off-track: {{ k.action }}</div>
              </div>
            </div>
          </div>

          <!-- Forecast (BI-uplift P7): LLM-reasoned projection of the agent's
               primary time series. On-demand, transient, labelled AI estimate. -->
          <div v-if="edaProfile?.time_series || forecast" class="rounded-xl border border-[#E9E0D3] bg-white p-3">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-[10px] uppercase tracking-wider text-[#9a958c] font-semibold">Forecast</span>
              <span class="text-[8.5px] font-bold px-1.5 py-0.5 rounded bg-[#F1ECE3] text-[#8B4427] uppercase">AI estimate</span>
              <button
                @click.stop.prevent="refreshForecast"
                :disabled="forecastRefreshing"
                class="ms-auto text-[10px] px-2 py-0.5 rounded-md border border-[#e6d6c8] text-[#8B4427] hover:bg-[#F4EEE5] transition-colors cursor-pointer disabled:opacity-50"
              >
                <Spinner v-if="forecastRefreshing" class="w-3 h-3 inline animate-spin" />
                <span v-else>{{ forecast ? 'Refresh' : 'Predict' }}</span>
              </button>
            </div>

            <div v-if="forecastRefreshing && !forecast" class="text-[11px] text-[#9a958c] py-2">
              Reasoning over your history…
            </div>

            <div v-else-if="forecast && forecast.success === false" class="text-[11px] text-[#9a958c] py-1">
              {{ forecast.message }}
            </div>

            <div v-else-if="forecast && forecast.success">
              <div class="flex items-center gap-2 flex-wrap mb-1.5">
                <span class="text-[12px] font-semibold text-[#211B14]">{{ forecast.measure }}</span>
                <span class="text-[8.5px] font-bold px-1.5 py-0.5 rounded uppercase"
                      :class="forecast.direction === 'up' ? 'bg-[#EEFAF1] text-[#157A43]' : forecast.direction === 'down' ? 'bg-[#FBEAEA] text-[#B4453A]' : 'bg-gray-100 text-gray-500'">{{ forecast.direction || 'trend' }}</span>
                <span class="text-[8.5px] font-bold px-1.5 py-0.5 rounded bg-[#e7edfb] text-[#2C53A8] uppercase">conf {{ forecast.confidence }}</span>
              </div>
              <div class="space-y-1">
                <div v-for="(f, i) in forecast.forecast" :key="i" class="flex items-center gap-2 text-[11.5px]">
                  <span class="text-[#9a958c] w-16 flex-shrink-0">{{ f.period }}</span>
                  <span class="font-semibold text-[#211B14] tabular-nums">{{ Number(f.yhat).toLocaleString() }}</span>
                  <span class="text-[10px] text-[#9a958c] tabular-nums">[{{ Number(f.yhat_lower).toLocaleString() }} – {{ Number(f.yhat_upper).toLocaleString() }}]</span>
                </div>
              </div>
              <div v-if="forecast.assumptions" class="text-[10.5px] text-[#6b6b6b] mt-1.5 leading-snug italic">{{ forecast.assumptions }}</div>
              <div class="text-[9.5px] text-[#b3aea4] mt-1">{{ forecast.disclaimer }}</div>
            </div>

            <div v-else class="text-[11px] text-[#9a958c] py-1">
              Predict the next few months from this agent's history — AI reasoning, not a trained model.
            </div>
          </div>

          <div
            v-if="!agentDetails?.primary_instruction && !agentDetails?.description && !(showStarters && agentDetails?.conversation_starters?.length) && !eda && !kpis.length && !forecast && !$slots['overview-lead']"
            class="text-xs text-gray-400 italic py-6 text-center"
          >
            {{ $t('agentFlyout.noDetails') }}
          </div>
        </div>

        <!-- Tables tab -->
        <div v-else-if="flyoutTab === 'tables'">
          <div v-if="tablesLoading" class="flex items-center justify-center py-10">
            <Spinner class="w-5 h-5 text-gray-400 animate-spin" />
          </div>

          <div v-else-if="tablesError" class="text-xs text-gray-500">
            {{ tablesError }}
          </div>

          <div v-else>
            <div v-if="tablesCount === 0" class="text-xs text-gray-400 italic py-6 text-center">
              {{ $t('agentFlyout.noTables') }}
            </div>

            <div v-else>
              <!-- List view -->
              <div v-if="!selectedTable" class="border border-gray-200 rounded-lg overflow-hidden">
                <div class="max-h-[320px] overflow-auto">
                  <button
                    v-for="t in tablesResources"
                    :key="t.id || t.name"
                    @click="selectTable(t)"
                    class="w-full px-3 py-2 text-start text-xs flex items-center gap-2 hover:bg-gray-50 border-b border-gray-100 last:border-b-0"
                  >
                    <DataSourceIcon v-if="hasMultipleConnections" :type="t.connection_type" class="h-3.5 flex-shrink-0" />
                    <span class="truncate flex-1 text-gray-800 font-medium">{{ t.name }}</span>
                    <span v-if="t.columns?.length" class="text-[11px] text-gray-400 flex-shrink-0">{{ $t('agentFlyout.colsAbbr', { n: t.columns.length }) }}</span>
                  </button>
                </div>
                <div v-if="tablesResources.length === 0" class="px-3 py-3 text-xs text-gray-400">{{ $t('agentFlyout.noTablesShort') }}</div>
              </div>

              <!-- Detail view (columns) -->
              <div v-else class="space-y-2">
                <div class="flex items-center justify-between">
                  <button
                    @click="selectedTable = null"
                    class="text-[11px] text-gray-500 hover:text-gray-700"
                  >
                    {{ $t('agentFlyout.back') }}
                  </button>
                  <div class="text-[11px] text-gray-400">{{ $t('agentFlyout.columns') }}</div>
                </div>

                <div class="text-sm font-semibold text-gray-900 truncate">{{ selectedTable.name }}</div>

                <div class="flex flex-wrap gap-1 max-h-[240px] overflow-auto border border-gray-200 rounded-lg p-2">
                  <span
                    v-for="(col, idx) in (selectedTable.columns || [])"
                    :key="idx"
                    class="px-1.5 py-0.5 bg-white rounded border text-[11px] text-gray-700"
                  >
                    {{ typeof col === 'string' ? col : (col as any).name }}
                    <span v-if="typeof col === 'object' && (col as any).dtype" class="text-gray-400 ms-1">({{ (col as any).dtype }})</span>
                  </span>
                  <span v-if="!(selectedTable.columns || []).length" class="text-[12px] text-gray-400">{{ $t('agentFlyout.noColumns') }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Instructions tab -->
        <div v-else-if="flyoutTab === 'instructions'">
          <div v-if="instructionsLoading" class="flex items-center justify-center py-10">
            <Spinner class="w-5 h-5 text-gray-400 animate-spin" />
          </div>

          <div v-else-if="instructionsError" class="text-xs text-gray-500">
            {{ instructionsError }}
          </div>

          <div v-else>
            <div v-if="instructionsCount === 0" class="text-xs text-gray-400 italic py-6 text-center">
              {{ $t('agentFlyout.noInstructions') }}
            </div>

            <div v-else class="border border-gray-200 rounded-lg overflow-hidden">
              <div class="max-h-[320px] overflow-auto">
                <NuxtLink
                  v-for="inst in instructionsResources"
                  :key="inst.id"
                  :to="`/instructions?search=${encodeURIComponent(inst.title || '')}`"
                  class="w-full px-3 py-2 text-start text-xs flex items-start gap-2 hover:bg-gray-50 border-b border-gray-100 last:border-b-0 block"
                >
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-1.5">
                      <span class="truncate text-gray-800 font-medium">{{ inst.title || $t('agentFlyout.untitled') }}</span>
                      <span
                        v-if="!inst.data_sources?.length"
                        class="px-1 py-0.5 text-[9px] rounded bg-purple-50 text-purple-600 flex-shrink-0"
                      >
                        {{ $t('agentFlyout.global') }}
                      </span>
                    </div>
                    <div class="text-[11px] text-gray-400 truncate mt-0.5">
                      {{ inst.category || 'general' }} · {{ inst.source_type || 'user' }}
                    </div>
                  </div>
                </NuxtLink>
              </div>
            </div>
          </div>
        </div>

        <!-- Queries tab -->
        <div v-else-if="flyoutTab === 'queries'">
          <div v-if="queriesLoading" class="flex items-center justify-center py-10">
            <Spinner class="w-5 h-5 text-gray-400 animate-spin" />
          </div>

          <div v-else-if="queriesError" class="text-xs text-gray-500">
            {{ queriesError }}
          </div>

          <div v-else>
            <div v-if="queriesCount === 0" class="text-xs text-gray-400 italic py-6 text-center">
              {{ $t('agentFlyout.noQueries') }}
            </div>

            <div v-else class="border border-gray-200 rounded-lg overflow-hidden">
              <div class="max-h-[320px] overflow-auto">
                <NuxtLink
                  v-for="entity in queriesResources"
                  :key="entity.id"
                  :to="`/queries/${entity.id}`"
                  class="w-full px-3 py-2 text-start text-xs flex items-start gap-2 hover:bg-gray-50 border-b border-gray-100 last:border-b-0 block"
                >
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-1.5">
                      <span
                        class="px-1 py-0.5 text-[9px] rounded border flex-shrink-0"
                        :class="entity.type === 'metric' ? 'text-emerald-700 border-emerald-200 bg-emerald-50' : 'text-[#A8330F] border-[#E8C9B5] bg-[#F6EFEA]'"
                      >{{ (entity.type || 'entity').toUpperCase() }}</span>
                      <span class="truncate text-gray-800 font-medium">{{ entity.title || entity.slug }}</span>
                    </div>
                    <div v-if="entity.description" class="text-[11px] text-gray-400 truncate mt-0.5">
                      {{ entity.description }}
                    </div>
                  </div>
                </NuxtLink>
              </div>
            </div>
          </div>
        </div>

      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import Spinner from '~/components/Spinner.vue'
import DataSourceIcon from '~/components/DataSourceIcon.vue'
import InstructionText from '~/components/instructions/InstructionText.vue'

const router = useRouter()
const { t } = useI18n()

const props = defineProps<{
  agentId: string | null
  // Optional report grounding. When a studio embeds this, it passes the studio
  // id + all its sources so sample-question reports ground on the whole studio;
  // a plain agent leaves this unset and grounds on [agentId].
  reportGrounding?: { dataSources?: string[]; studioId?: string }
  // Show the agent's own conversation starters in Overview. A studio hides these
  // because it supplies its own (richer, studio-grounded) suggested questions.
  showStarters?: boolean
}>()

const showStarters = computed(() => props.showStarters !== false)

const emit = defineEmits<{
  // Fired with the fetched agent details when the user clicks Connect (locked).
  connect: [agent: any]
  // Fired when details finish loading so a parent header can show name/etc.
  loaded: [agent: any]
}>()

const { needsUserConnection } = useDataSourceConnect()

const locked = computed(() => !!agentDetails.value && needsUserConnection(agentDetails.value))

function refreshDetails() {
  const id = props.agentId
  if (!id) return
  delete detailsCache.value[id]
  fetchAgentDetails(id)
}
defineExpose({ refreshDetails })

// Internal state
const agentDetails = ref<any>(null)
const loadingDetails = ref(false)
const detailsCache = ref<Record<string, any>>({})
const flyoutTab = ref<'overview' | 'tables' | 'instructions' | 'queries'>('overview')

// BI-uplift Phase 6: per-agent Auto-EDA (present only when eda_profile is set).
const eda = computed<any>(() => agentDetails.value?.eda_profile || null)
const edaProfile = computed<any>(() => eda.value?.profile || null)
const edaRefreshing = ref(false)
async function refreshEda() {
  const id = props.agentId
  if (!id || edaRefreshing.value) return
  edaRefreshing.value = true
  try {
    const { data } = await useMyFetch(`/data_sources/${id}/auto-eda`, { method: 'POST' })
    const payload = (data.value as any)?.eda
    if (payload && !payload.error && agentDetails.value) {
      agentDetails.value = { ...agentDetails.value, eda_profile: payload }
      if (detailsCache.value[id]) detailsCache.value[id] = agentDetails.value
    }
  } catch (e) {
    /* fail-soft */
  } finally {
    edaRefreshing.value = false
  }
}

// BI-uplift Phase 3: per-agent governed KPIs (present only when kpi_defs is set).
const kpis = computed<any[]>(() => agentDetails.value?.kpi_defs?.kpis || [])
const kpiRefreshing = ref(false)
async function refreshKpis() {
  const id = props.agentId
  if (!id || kpiRefreshing.value) return
  kpiRefreshing.value = true
  try {
    const { data } = await useMyFetch(`/data_sources/${id}/kpis`, { method: 'POST' })
    const payload = (data.value as any)?.kpis
    if (payload && !payload.error && agentDetails.value) {
      agentDetails.value = { ...agentDetails.value, kpi_defs: payload }
      if (detailsCache.value[id]) detailsCache.value[id] = agentDetails.value
    }
  } catch (e) {
    /* fail-soft */
  } finally {
    kpiRefreshing.value = false
  }
}

// Forecast (BI-uplift P7 — LLM reasoning over the agent's time series, transient)
const forecast = ref<any>(null)
const forecastRefreshing = ref(false)
async function refreshForecast() {
  const id = props.agentId
  if (!id || forecastRefreshing.value) return
  forecastRefreshing.value = true
  try {
    const { data } = await useMyFetch(`/data_sources/${id}/forecast`, { method: 'POST' })
    const payload = (data.value as any)?.forecast
    if (payload) forecast.value = payload
  } catch (e) {
    /* fail-soft */
  } finally {
    forecastRefreshing.value = false
  }
}

// Tables tab state
const tablesCache = ref<Record<string, any[]>>({})
const tablesLoading = ref(false)
const tablesError = ref<string | null>(null)
const selectedTable = ref<any | null>(null)

// Instructions tab state
const instructionsCache = ref<Record<string, any[]>>({})
const instructionsLoading = ref(false)
const instructionsError = ref<string | null>(null)

// Queries tab state
const queriesCache = ref<Record<string, any[]>>({})
const queriesLoading = ref(false)
const queriesError = ref<string | null>(null)

// Report creation state
const creatingReport = ref(false)
const creatingQuestionIdx = ref<number | null>(null)

// Computed
const tablesResources = computed<any[]>(() => {
  if (!props.agentId) return []
  return tablesCache.value[props.agentId] || []
})
const tablesCount = computed(() => tablesResources.value.length)

const instructionsResources = computed<any[]>(() => {
  if (!props.agentId) return []
  return instructionsCache.value[props.agentId] || []
})
const instructionsCount = computed(() => instructionsResources.value.length)

const queriesResources = computed<any[]>(() => {
  if (!props.agentId) return []
  return queriesCache.value[props.agentId] || []
})
const queriesCount = computed(() => queriesResources.value.length)

const hasMultipleConnections = computed(() => {
  const connections = agentDetails.value?.connections || []
  return connections.length > 1
})

// Fetch functions
const fetchAgentDetails = async (agentId: string) => {
  if (detailsCache.value[agentId]) {
    agentDetails.value = detailsCache.value[agentId]
    emit('loaded', agentDetails.value)
    return
  }

  loadingDetails.value = true
  try {
    const { data, error } = await useMyFetch(`/data_sources/${agentId}`, { method: 'GET' })
    if (!error?.value && data?.value) {
      detailsCache.value[agentId] = data.value
      if (props.agentId === agentId) {
        agentDetails.value = data.value
        emit('loaded', data.value)
      }
    }
  } catch (e) {
    console.error('Failed to load agent details:', e)
  } finally {
    loadingDetails.value = false
  }
}

const fetchTablesForAgent = async (agentId: string) => {
  if (!agentId || tablesCache.value[agentId]) return
  tablesLoading.value = true
  tablesError.value = null
  try {
    const { data, error } = await useMyFetch(`/data_sources/${agentId}/schema`, { method: 'GET' })
    if (error?.value) {
      tablesError.value = t('agentFlyout.tablesLoadFailed')
      return
    }
    const payload: any = (data as any)?.value
    const tables = Array.isArray(payload) ? payload : []
    const filtered = tables.filter((t: any) => t?.is_active !== false)
    tablesCache.value[agentId] = filtered
  } catch (e) {
    tablesError.value = t('agentFlyout.tablesLoadFailed')
  } finally {
    tablesLoading.value = false
  }
}

const fetchInstructionsForAgent = async (agentId: string) => {
  if (!agentId || instructionsCache.value[agentId]) return
  instructionsLoading.value = true
  instructionsError.value = null
  try {
    const { data, error } = await useMyFetch('/api/instructions', {
      method: 'GET',
      query: {
        data_source_ids: agentId,
        include_global: true,
        limit: 50,
        include_own: true,
        include_drafts: false
      }
    })
    if (error?.value) {
      instructionsError.value = t('agentFlyout.instructionsLoadFailed')
      return
    }
    const payload: any = (data as any)?.value
    const items = payload?.items || payload || []
    instructionsCache.value[agentId] = items
  } catch (e) {
    instructionsError.value = t('agentFlyout.instructionsLoadFailed')
  } finally {
    instructionsLoading.value = false
  }
}

const fetchQueriesForAgent = async (agentId: string) => {
  if (!agentId || queriesCache.value[agentId]) return
  queriesLoading.value = true
  queriesError.value = null
  try {
    const { data, error } = await useMyFetch('/api/entities', {
      method: 'GET',
      query: {
        data_source_ids: agentId
      }
    })
    if (error?.value) {
      queriesError.value = t('agentFlyout.queriesLoadFailed')
      return
    }
    const payload: any = (data as any)?.value
    const entities = Array.isArray(payload) ? payload : []
    const filtered = entities.filter((e: any) =>
      e.status === 'published' && e.global_status === 'approved'
    )
    queriesCache.value[agentId] = filtered
  } catch (e) {
    queriesError.value = t('agentFlyout.queriesLoadFailed')
  } finally {
    queriesLoading.value = false
  }
}

const selectTable = (tbl: any) => {
  selectedTable.value = tbl
}

const startReportWithQuestion = async (question: string, idx: number) => {
  if (creatingReport.value) return
  creatingReport.value = true
  creatingQuestionIdx.value = idx

  try {
    // Grounding: a studio passes its own sources + studio_id; a plain agent
    // grounds on just [agentId].
    const grounded = props.reportGrounding?.dataSources?.length
      ? props.reportGrounding.dataSources
      : (props.agentId ? [props.agentId] : [])
    const body: any = {
      title: 'untitled report',
      files: [],
      new_message: question,
      data_sources: grounded
    }
    if (props.reportGrounding?.studioId) body.studio_id = props.reportGrounding.studioId

    const response = await useMyFetch('/reports', {
      method: 'POST',
      body: JSON.stringify(body)
    })

    if ((response as any)?.error?.value) {
      throw new Error('Report creation failed')
    }

    const data = (response as any)?.data?.value as any
    if (data?.id) {
      await router.push({
        path: `/reports/${data.id}`,
        query: {
          new_message: question
        }
      })
    }
  } catch (error) {
    console.error('Failed to create report:', error)
  } finally {
    creatingReport.value = false
    creatingQuestionIdx.value = null
  }
}

// Watch for agentId changes to fetch data
watch(() => props.agentId, async (newId, oldId) => {
  if (newId && newId !== oldId) {
    // Reset state
    flyoutTab.value = 'overview'
    tablesError.value = null
    selectedTable.value = null
    instructionsError.value = null
    queriesError.value = null
    agentDetails.value = null

    await fetchAgentDetails(newId)
  }
}, { immediate: true })

// Watch tab changes to ensure data is loaded
watch(flyoutTab, async (tab) => {
  const id = props.agentId
  if (!id) return

  if (tab === 'tables') {
    await fetchTablesForAgent(id)
  } else if (tab === 'instructions') {
    await fetchInstructionsForAgent(id)
  } else if (tab === 'queries') {
    await fetchQueriesForAgent(id)
  }
})
</script>

<style lang="postcss">
/* Not scoped: may be teleported by the parent flyout */
.agent-flyout-markdown .markdown-content {
  @apply leading-relaxed;
  font-size: 12px;

  :where(h1, h2, h3, h4, h5, h6) {
    @apply font-bold mb-2 mt-3;
  }

  h1 { @apply text-base; }
  h2 { @apply text-sm; }
  h3 { @apply text-xs; }

  ul, ol { @apply ps-4 mb-2; }
  ul { @apply list-disc; }
  ol { @apply list-decimal; }
  li { @apply mb-1; }

  pre { @apply bg-gray-50 p-2 rounded-lg mb-2 overflow-x-auto text-[11px]; }
  code { @apply bg-gray-50 px-1 py-0.5 rounded text-[11px] font-mono; }
  a { @apply text-[#C2541E] hover:text-[#A8330F] underline; }
  blockquote { @apply border-l-4 border-gray-200 pl-3 italic my-2; }
  table { @apply w-full border-collapse mb-2; }
  table th, table td { @apply border border-gray-200 p-1 text-[11px] bg-white; }
  p { @apply mb-2; }
}
</style>
