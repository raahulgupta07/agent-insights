<template>
  <!-- Auto-pilot v2 — reordered ADD → QUEUE → TRAIN → RESULT. Flag-gated by the parent
       (HYBRID_AUTOPILOT_V2). Self-contained, fail-soft on every fetch. Warm clay theme. -->
  <div>
    <!-- HEADER -->
    <div class="flex items-start justify-between gap-4 mb-1">
      <div>
        <h2 class="text-lg font-semibold text-[#1f2328]" style="font-family: 'Spectral', ui-serif, Georgia, serif">AI Auto-pilot</h2>
        <p class="text-xs text-[#6b6b6b] mt-0.5 max-w-[460px]">Drop anything in — queue it, train once, and the router sorts each input into Data &middot; Knowledge &middot; Skill &middot; Rule. No per-dataset code.</p>
      </div>
      <div class="shrink-0 text-center">
        <div class="relative w-[54px] h-[54px] mx-auto">
          <svg width="54" height="54" style="transform:rotate(-90deg)">
            <circle cx="27" cy="27" r="22" stroke="#ECE7E0" stroke-width="6" fill="none" />
            <circle cx="27" cy="27" r="22" stroke="#C2541E" stroke-width="6" fill="none" stroke-linecap="round" stroke-dasharray="138" :stroke-dashoffset="Math.round(138 - 138 * (readiness?.score || 0) / 100)" style="transition:stroke-dashoffset .5s" />
          </svg>
          <div class="absolute inset-0 flex items-center justify-center text-[15px] font-semibold text-[#C2541E]" style="font-family: ui-serif, Georgia, serif">{{ readiness?.score || 0 }}</div>
        </div>
        <div class="text-[9px] uppercase tracking-wide text-[#9a958c] mt-0.5">readiness</div>
      </div>
    </div>

    <!-- MODEL (compact — pick the LLM this agent uses for analysis + file routing) -->
    <div class="mt-4 border border-[#E9E0D3] rounded-xl bg-white px-3 py-2.5">
      <div class="flex items-center gap-3 flex-wrap">
        <span class="text-[12.5px] font-semibold text-[#1f2328] shrink-0">Model</span>
        <div class="relative">
          <select
            v-model="selectedModelId"
            :disabled="modelSaving"
            class="appearance-none text-[12px] text-[#1f2328] bg-[#fdfcf9] border border-[#E9E0D3] rounded-lg pl-2.5 pr-7 py-1.5 focus:outline-none focus:border-[#C2541E] disabled:opacity-60"
            @change="saveModel">
            <option :value="null">Default (org)</option>
            <option v-for="m in models" :key="m.id" :value="m.id">{{ m.name }}</option>
          </select>
          <UIcon name="i-heroicons-chevron-down" class="w-3.5 h-3.5 text-[#9a958c] absolute right-2 top-1/2 -translate-y-1/2 pointer-events-none" />
        </div>
        <Spinner v-if="modelSaving" class="h-3.5 w-3.5 text-[#C2541E]" />
        <span v-else-if="modelSaved" class="inline-flex items-center gap-1 text-[11px] font-semibold text-[#2F6F4F]">
          <UIcon name="i-heroicons-check-circle" class="w-4 h-4" /> Saved
        </span>
        <span v-else-if="modelError" class="text-[11px] text-[#A8330F]">{{ modelError }}</span>
        <span class="text-[10.5px] text-[#9a958c] ms-auto">Used for analysis and file routing.</span>
      </div>
    </div>

    <!-- LLM-key gate notice (shown only when the org has no model key) -->
    <div v-if="llmConfigured === false" class="mt-4 flex items-center gap-2 text-[11.5px] text-[#9A6A12] bg-[#FBF1DD] border border-[#EBD9AE] rounded-xl px-3 py-2">
      <UIcon name="i-heroicons-key" class="w-4 h-4 shrink-0" />
      <span>Add your model key in
        <NuxtLink to="/settings/models" class="font-semibold underline hover:text-[#C2541E]">Settings &rarr; Models</NuxtLink>
        to start adding data.</span>
    </div>

    <!-- 1 · ADD (compact) -->
    <div class="relative mt-4 border border-[#E9E0D3] rounded-2xl bg-white p-3">
      <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">1 &middot; ADD</span>
      <!-- One row of source buttons: Database · Upload · OneDrive · SharePoint · Folder.
           Each opens its existing connect flow via @add. Scrolls horizontally if narrow. -->
      <div class="flex gap-2 mt-1.5 overflow-x-auto pb-1">
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#2F6F4F] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','database')">
          <span class="w-7 h-7 rounded-lg bg-[#E7F1EB] flex items-center justify-center shrink-0"><UIcon name="i-heroicons-circle-stack" class="w-4 h-4 text-[#2F6F4F]" /></span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">Database</span><span class="block text-[10.5px] text-[#9a958c] truncate">Postgres · MySQL · Snowflake</span></span>
        </button>
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#C2541E] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','upload')">
          <span class="w-7 h-7 rounded-lg bg-[#F6EBE3] flex items-center justify-center shrink-0"><UIcon name="i-heroicons-arrow-up-tray" class="w-4 h-4 text-[#C2541E]" /></span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">Upload file</span><span class="block text-[10.5px] text-[#9a958c] truncate">.csv .xlsx .pdf .docx</span></span>
        </button>
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#2C6EB5] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','onedrive')">
          <span class="w-7 h-7 rounded-lg bg-[#E6F0FA] flex items-center justify-center shrink-0"><UIcon name="i-heroicons-cloud" class="w-4 h-4 text-[#2C6EB5]" /></span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">OneDrive</span><span class="block text-[10.5px] text-[#9a958c] truncate">personal files</span></span>
        </button>
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#2C6EB5] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','sharepoint')">
          <span class="w-7 h-7 rounded-lg bg-[#E6F0FA] flex items-center justify-center shrink-0"><UIcon name="i-heroicons-building-office-2" class="w-4 h-4 text-[#2C6EB5]" /></span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">SharePoint</span><span class="block text-[10.5px] text-[#9a958c] truncate">team library</span></span>
        </button>
        <button type="button" :disabled="!canEdit || !llmConfigured" class="flex-1 min-w-[150px] flex items-center gap-2 text-left border border-[#E9E0D3] rounded-xl px-3 py-2.5 bg-gradient-to-b from-white to-[#fdfcf9] hover:border-[#C2541E] transition-colors disabled:opacity-50 disabled:cursor-not-allowed" @click="$emit('add','folder')">
          <span class="w-7 h-7 rounded-lg bg-[#F4E5DA] flex items-center justify-center shrink-0 text-[#C2541E] text-base">⟳</span>
          <span class="min-w-0"><span class="block text-[12.5px] font-semibold text-[#1f2328] truncate">Folder</span><span class="block text-[10.5px] text-[#9a958c] truncate">desktop auto-sync</span></span>
        </button>
      </div>
    </div>

    <!-- 2 · QUEUE (the heart) -->
    <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4">
      <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">2 &middot; QUEUE</span>
      <p class="text-[11px] text-[#6b6b6b] mt-1 mb-3">Everything you add waits here with an instant type-guess. Re-route anything the router got wrong before you train.</p>
      <StudioInbox v-if="studioId" :studio-id="studioId" :v2="true" ref="inboxRef" />
      <div v-else class="text-[11.5px] text-[#9a958c]">Loading agent…</div>
    </div>

    <!-- 3 · TRAIN (button + segregation receipt) -->
    <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4">
      <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">3 &middot; TRAIN</span>
      <div class="flex items-center justify-between gap-3 mt-1 flex-wrap">
        <div class="text-[11.5px] text-[#6b6b6b]"><b class="text-[#1f2328]">{{ (sources || []).length }} source{{ (sources || []).length === 1 ? '' : 's' }} &middot; {{ (docs || []).length }} doc{{ (docs || []).length === 1 ? '' : 's' }} &middot; queued</b> → one pass</div>
        <div class="flex gap-2 shrink-0">
          <button type="button" class="text-[11.5px] border border-[#E9E0D3] rounded-lg px-3 py-2 text-[#6b6b6b] hover:bg-[#faf8f3] font-medium" @click="$emit('openTab','sources')">Review routing</button>
          <button type="button" :disabled="trainingAll || !canTrain" class="inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-white bg-[#C2541E] hover:bg-[#A8330F] rounded-lg px-3.5 py-2 transition-colors disabled:opacity-50" @click="$emit('train')">
            <Spinner v-if="trainingAll" class="h-3.5 w-3.5 text-white" />
            <UIcon v-else name="i-heroicons-bolt" class="w-3.5 h-3.5" />
            {{ trainingAll ? 'Training…' : '⚡ Auto-train everything' }}
          </button>
        </div>
      </div>
      <p class="text-[11px] text-[#9a958c] mt-2">One pass: classify → segregate → ingest → write goldens → reconcile → coverage. Needs ≥1 pinned source or a file queued above.</p>

      <!-- RECEIPT (only once a train status exists) -->
      <div v-if="hasTrainStatus" class="mt-3 border-t border-[#E9E0D3] pt-3">
        <!-- LIVE PROCESS DIAGRAM — BPMN spine: ROUTE group → decision diamond
             (held branch) → every train stage left→right → ✓ agent-ready.
             Driven by the same trainFlow node states; scrolls horizontally. -->
        <div class="bpmn mb-2.5">
          <!-- thin clay progress bar -->
          <div class="flow-bar-row">
            <div class="flow-bar"><div class="flow-bar-fill" :style="{ width: flowPct + '%' }"></div></div>
            <span v-if="trainingAll" class="flow-status flow-status-run">running &middot; {{ flowPct }}%</span>
            <span v-else-if="flowReady" class="flow-status flow-status-done">✓ agent ready &middot; 100%</span>
            <span v-else class="flow-status">{{ flowPct }}%</span>
          </div>

          <div class="bpmn-canvas">
            <div class="bpmn-spine">
              <!-- ROUTE group (pre-diamond) -->
              <template v-for="(n, i) in routeNodes" :key="'r-' + n.key">
                <div v-if="i > 0" class="bpmn-arrow" :class="{ done: routeNodes[i - 1].state === 'done' }" aria-hidden="true">
                  <svg viewBox="0 0 34 16"><path d="M1 8h28M24 3l6 5-6 5" /></svg>
                </div>
                <div class="bpmn-node" :class="'st-' + n.state">
                  <div class="bpmn-box">
                    <svg class="bpmn-icon" viewBox="0 0 24 24" v-html="iconFor(n.key)" />
                    <svg class="ring" viewBox="0 0 70 70"><circle class="track" cx="35" cy="35" r="32" /><circle class="fill" cx="35" cy="35" r="32" stroke-dasharray="201" :stroke-dashoffset="n.state === 'running' ? 110 : 201" /></svg>
                    <span class="bpmn-badge">{{ n.state === 'done' ? '✓' : n.state === 'skipped' ? '✓' : n.state === 'held' ? '◌' : '' }}</span>
                  </div>
                  <span class="bpmn-lbl">{{ nodeLabel(n.key) }}</span>
                </div>
              </template>

              <!-- arrow → DECISION diamond (+ held branch) → arrow -->
              <div class="bpmn-arrow" :class="{ done: routerDone }" aria-hidden="true"><svg viewBox="0 0 34 16"><path d="M1 8h28M24 3l6 5-6 5" /></svg></div>
              <div class="bpmn-diamond-wrap">
                <div class="bpmn-diamond" :class="{ done: routerDone }">
                  <svg viewBox="0 0 24 24" v-html="iconFor('__router')" />
                </div>
                <span class="bpmn-dlbl">router sure?</span>
                <div class="bpmn-branch" :class="{ faint: heldCount === 0 }">
                  <span class="bpmn-drop" />
                  <div class="bpmn-terminal">
                    <div class="tcircle held">◌</div>
                    <span class="tlbl">Held &middot; review<br><span class="tsub">{{ heldCount }} item{{ heldCount === 1 ? '' : 's' }}</span></span>
                  </div>
                </div>
              </div>
              <div class="bpmn-arrow" :class="{ done: routerDone }" aria-hidden="true"><svg viewBox="0 0 34 16"><path d="M1 8h28M24 3l6 5-6 5" /></svg></div>

              <!-- main spine — every remaining stage -->
              <template v-for="(n, i) in spineNodes" :key="'s-' + n.key">
                <div v-if="i > 0" class="bpmn-arrow" :class="{ done: spineNodes[i - 1].state === 'done' }" aria-hidden="true">
                  <svg viewBox="0 0 34 16"><path d="M1 8h28M24 3l6 5-6 5" /></svg>
                </div>
                <div class="bpmn-node" :class="'st-' + n.state">
                  <div class="bpmn-box">
                    <svg class="bpmn-icon" viewBox="0 0 24 24" v-html="iconFor(n.key)" />
                    <svg class="ring" viewBox="0 0 70 70"><circle class="track" cx="35" cy="35" r="32" /><circle class="fill" cx="35" cy="35" r="32" stroke-dasharray="201" :stroke-dashoffset="n.state === 'running' ? 110 : 201" /></svg>
                    <span class="bpmn-badge">{{ n.state === 'done' ? '✓' : n.state === 'skipped' ? '✓' : n.state === 'held' ? '◌' : '' }}</span>
                  </div>
                  <span class="bpmn-lbl">{{ nodeLabel(n.key) }}</span>
                </div>
              </template>

              <!-- final arrow → terminal ✓ -->
              <div class="bpmn-arrow" :class="{ done: flowReady }" aria-hidden="true"><svg viewBox="0 0 34 16"><path d="M1 8h28M24 3l6 5-6 5" /></svg></div>
              <div class="bpmn-terminal-final">
                <div class="tcircle" :class="{ ok: flowReady }">✓</div>
                <span class="tlbl">Agent ready</span>
              </div>
            </div>

            <div class="bpmn-legend">
              <span><i class="dot d" />done</span>
              <span><i class="dot r" />working</span>
              <span><i class="dot q" />queued</span>
              <span><i class="dot s" />skipped &middot; nothing to do</span>
              <span><i class="dot h" />held</span>
            </div>
          </div>
        </div>

        <!-- RECONCILE + COVERAGE pills -->
        <div class="flex flex-wrap items-center gap-2 mb-2.5">
          <span v-if="routeInbox"
            class="inline-flex items-center gap-1 text-[10.5px] font-semibold rounded-full px-2.5 py-1"
            :class="(routeInbox.held || 0) === 0 ? 'bg-[#E7F2EC] text-[#2f7a52]' : 'bg-[#FBF1DD] text-[#9A6A12]'">
            {{ routeInbox.files_in || 0 }} in → {{ routeInbox.placed || 0 }} placed &middot; {{ routeInbox.held || 0 }} held
          </span>
          <span v-if="coverageTotalPeriods != null"
            class="inline-flex items-center gap-1 text-[10.5px] font-semibold rounded-full px-2.5 py-1 bg-[#E4F0F4] text-[#1F6F8B]">
            coverage {{ coverageTotalPeriods }} period{{ coverageTotalPeriods === 1 ? '' : 's' }}
          </span>
        </div>

        <!-- per-dest breakdown (compact) -->
        <div v-if="byDestEntries.length" class="flex flex-wrap gap-1.5 mb-2.5">
          <span v-for="[dest, n] in byDestEntries" :key="dest"
            class="inline-flex items-center gap-1 text-[10px] rounded-md px-2 py-0.5 border border-[#ECE7E0] bg-white text-[#6b6b6b]">
            {{ destEmoji(dest) }} {{ destShort(dest) }} <b class="text-[#1f2328]">{{ n }}</b>
          </span>
        </div>

      </div>
    </div>

    <!-- 4 · RESULT (4 lanes) -->
    <div class="relative mt-5 border border-[#E9E0D3] rounded-2xl bg-white p-4 mb-4">
      <span class="absolute -top-2.5 left-4 bg-[#2B2A26] text-white text-[9.5px] font-semibold px-2.5 py-0.5 rounded-full tracking-wide">4 &middot; RESULT</span>
      <p class="text-[10px] uppercase tracking-wide text-[#9a958c] mt-1 mb-3 flex items-center gap-2"><span class="h-px bg-[#EFEDE6] flex-1"></span>each input lands in one of 4 lanes · all born pending (review gate)<span class="h-px bg-[#EFEDE6] flex-1"></span></p>
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2.5">
        <!-- DATA -->
        <div class="rounded-xl border border-[#E9E0D3] bg-[#E7F1EB] p-3 flex flex-col min-h-[164px]">
          <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#2F6F4F]"></span><h4 class="text-xs font-semibold text-[#2F6F4F]">Data</h4><span class="ms-auto text-[10px] text-[#2F6F4F] font-semibold">{{ (sources || []).length }}</span></div>
          <p class="text-[9.5px] text-[#5f7d6c] mb-1">tables → profiled &amp; queryable</p>
          <div v-for="s in (sources || []).slice(0,4)" :key="s.id" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <div class="flex items-center gap-1.5"><DataSourceIcon v-if="s.type" class="h-3.5 shrink-0" :type="s.type" /><UIcon v-else name="i-heroicons-circle-stack" class="w-3.5 h-3.5 text-[#9a958c] shrink-0" /><span class="text-[11px] font-medium text-[#1f2328] truncate">{{ s.name || s.agent_id }}</span></div>
          </div>
          <div v-if="!(sources || []).length" class="text-[10.5px] text-[#5f7d6c] mt-1.5">Add a sheet or connect a source above.</div>
          <div class="mt-auto pt-2 flex items-center gap-3">
            <button type="button" class="text-[10px] text-[#2F6F4F] font-medium text-left hover:underline" @click="$emit('openTab','sources')">Manage in Sources →</button>
            <button v-if="(sources || []).length" type="button" :disabled="repairing" class="text-[10px] text-[#9A6A12] font-medium hover:underline disabled:opacity-50" title="Stitch same-schema tables that were uploaded in separate sessions back into one table" @click="repairData">{{ repairing ? 'Repairing…' : 'Repair data' }}</button>
          </div>
        </div>
        <!-- KNOWLEDGE -->
        <div class="rounded-xl border border-[#E9E0D3] bg-[#E4F0F4] p-3 flex flex-col min-h-[164px]">
          <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#1F6F8B]"></span><h4 class="text-xs font-semibold text-[#1F6F8B]">Knowledge</h4><span class="ms-auto text-[10px] text-[#1F6F8B] font-semibold">{{ (docs || []).length }}</span></div>
          <p class="text-[9.5px] text-[#5a7d89] mb-1">docs → definitions extracted</p>
          <div v-for="d in (docs || []).slice(0,4)" :key="d.id" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <div class="flex items-center gap-1.5"><UIcon name="i-heroicons-document-text" class="w-3.5 h-3.5 text-[#1F6F8B] shrink-0" /><span class="text-[11px] font-medium text-[#1f2328] truncate">{{ d.title || d.name || d.filename || 'Knowledge doc' }}</span></div>
          </div>
          <div v-if="!(docs || []).length" class="text-[10.5px] text-[#5a7d89] mt-1.5">Upload a PDF / deck, or extract from a source.</div>
          <button type="button" class="mt-auto pt-2 text-[10px] text-[#1F6F8B] font-medium text-left hover:underline" @click="$emit('openTab','sources')">Manage in Knowledge →</button>
        </div>
        <!-- SKILL -->
        <div class="rounded-xl border border-[#E9E0D3] bg-[#ECEAFB] p-3 flex flex-col min-h-[164px]">
          <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#5A4FCF]"></span><h4 class="text-xs font-semibold text-[#5A4FCF]">Skill</h4></div>
          <p class="text-[9.5px] text-[#6f67b0] mb-1">a method/recipe → pack</p>
          <div class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <span class="text-[11px] text-[#1f2328]">Paste an analysis method — the router classifies it and binds it to your columns.</span>
          </div>
          <button type="button" class="mt-auto pt-2 text-[10px] text-[#5A4FCF] font-medium text-left hover:underline" @click="$emit('openTab','skills')">Open Skills →</button>
        </div>
        <!-- RULE / INSTRUCTION -->
        <div class="rounded-xl border border-[#E9E0D3] bg-[#F6EEDD] p-3 flex flex-col min-h-[164px]">
          <div class="flex items-center gap-1.5"><span class="w-2 h-2 rounded-full bg-[#9A6A12]"></span><h4 class="text-xs font-semibold text-[#9A6A12]">Rule / Instruction</h4><span class="ms-auto text-[10px] text-[#9A6A12] font-semibold">{{ (activeInstr || 0) + (activeExamples || 0) }}</span></div>
          <p class="text-[9.5px] text-[#8a7333] mb-1">a constraint you type</p>
          <div v-if="activeInstr" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <span class="text-[11px] text-[#1f2328]">{{ activeInstr }} instruction{{ activeInstr === 1 ? '' : 's' }} applied to every answer</span>
          </div>
          <div v-if="activeExamples" class="bg-white border border-black/5 rounded-lg p-2 mt-1.5">
            <span class="text-[11px] text-[#1f2328]">{{ activeExamples }} example{{ activeExamples === 1 ? '' : 's' }} grounding the agent</span>
          </div>
          <div v-if="!activeInstr && !activeExamples" class="text-[10.5px] text-[#8a7333] mt-1.5">Type a rule like “FY starts in April”.</div>
          <button type="button" class="mt-auto pt-2 text-[10px] text-[#9A6A12] font-medium text-left hover:underline" @click="$emit('openTab','instructions')">Manage in Instructions →</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useLlmConfigured } from '~/composables/useLlmConfigured'

const props = defineProps<{
  studioId: string
  sources: any[]
  docs: any[]
  readiness: { score: number }
  canEdit: boolean
  trainingAll: boolean
  canTrain: boolean
  trainLog: any
  trainStages: any[]
  trainLogLines: any[]
  activeInstr: number
  activeExamples: number
  showTrainLogPanel: boolean
}>()

defineEmits<{
  (e: 'add', payload: 'connector' | 'database' | 'upload' | 'onedrive' | 'sharepoint' | 'folder'): void
  (e: 'train'): void
  (e: 'openTab', payload: string): void
}>()

const inboxRef = ref<any>(null)

// Repair data: stitch same-schema orphan tables (files uploaded in separate
// sessions) back into each pinned source's ONE bound table. POSTs the generic
// self-heal route for every pinned source and surfaces a single result toast.
const toast = useToast()
const repairing = ref(false)
async function repairData() {
  if (repairing.value) return
  repairing.value = true
  let stitched = 0
  let rows = 0
  let failed = 0
  try {
    for (const s of (props.sources || [])) {
      const dsId = s.agent_id || s.data_source_id || s.id
      if (!dsId) continue
      try {
        const { data, error } = await useMyFetch<any>(`/data_sources/${dsId}/repair`, { method: 'POST' })
        if (error.value) { failed++; continue }
        const rep = (data.value as any)?.report
        if (rep && rep.ok) { stitched += (rep.tables_stitched || 0); rows += (rep.rows_added || 0) }
        else if (rep && rep.ok === false) { failed++ }
      } catch { failed++ }
    }
    if (failed && !stitched) {
      toast.add({ title: 'Repair failed', description: 'Could not repair this agent’s data.', color: 'red', icon: 'i-heroicons-exclamation-triangle' })
    } else if (stitched) {
      toast.add({ title: 'Data repaired', description: `Stitched ${stitched} orphaned table(s), added ${rows} row(s).`, color: 'green', icon: 'i-heroicons-check-circle' })
    } else {
      toast.add({ title: 'Nothing to repair', description: 'No split tables found — data is already unified.', color: 'green', icon: 'i-heroicons-check-circle' })
    }
  } finally {
    repairing.value = false
  }
}

// LLM-key gate (fail-open: llmConfigured defaults true, flips false only on explicit no-key).
const { llmConfigured } = useLlmConfigured()

// ─── Model selection card ───────────────────────────────────────────────────
// Lists the org's enabled models (same endpoint/shape as PromptBoxV2.loadModels).
// Value = model slug/id; null = org default. Reads/writes studio.config.model_id.
const models = ref<any[]>([])
const studioConfig = ref<Record<string, any>>({})   // full existing config (backend REPLACES it wholesale)
const selectedModelId = ref<string | null>(null)
const modelSaving = ref(false)
const modelSaved = ref(false)
const modelError = ref('')
let savedTimer: any = null

async function loadModelList() {
  try {
    const { data } = await useMyFetch<any>('/llm/models?is_enabled=true')
    if (Array.isArray(data.value)) models.value = data.value
  } catch { /* fail-soft — dropdown just shows Default (org) */ }
}

async function loadStudioModel() {
  if (!props.studioId) return
  try {
    const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}`)
    if (error?.value) return
    const cfg = ((data.value as any)?.config) || {}
    studioConfig.value = cfg
    selectedModelId.value = cfg.model_id != null ? cfg.model_id : null
  } catch { /* fail-soft */ }
}

async function saveModel() {
  modelError.value = ''
  modelSaved.value = false
  modelSaving.value = true
  // Spread the FULL existing config (backend replaces it wholesale), set/omit model_id.
  const nextConfig: Record<string, any> = { ...studioConfig.value }
  if (selectedModelId.value) nextConfig.model_id = selectedModelId.value
  else delete nextConfig.model_id
  try {
    const { error } = await useMyFetch<any>(`/studios/${props.studioId}`, {
      method: 'PATCH',
      body: { config: nextConfig },
    })
    if (error?.value) throw error.value
    studioConfig.value = nextConfig
    modelSaved.value = true
    if (savedTimer) clearTimeout(savedTimer)
    savedTimer = setTimeout(() => { modelSaved.value = false }, 2000)
  } catch {
    modelError.value = 'Save failed'
  } finally {
    modelSaving.value = false
  }
}

// Own train-status fetch (parent already polls for the log lines we render as a prop,
// but the segregation receipt — detail.route_inbox — we resolve here, fail-soft).
const status = ref<any>(null)
const routeInbox = computed<any>(() => (status.value && status.value.detail && status.value.detail.route_inbox) || null)
const hasTrainStatus = computed(() => !!(status.value && (status.value.status || status.value.step || status.value.detail)) || !!(props.trainLog && (props.trainLog.status || props.trainLog.step)))

const RECEIPT_STAGES = [
  { key: 'classify', label: 'classify' },
  { key: 'segregate', label: 'segregate' },
  { key: 'ingest', label: 'ingest' },
  { key: 'goldens', label: 'goldens' },
  { key: 'reconcile', label: 'reconcile' },
  { key: 'coverage', label: 'coverage' },
]
const receiptStages = computed(() => {
  const detail = (status.value && status.value.detail) || (props.trainLog && props.trainLog.detail) || {}
  const ri = routeInbox.value
  return RECEIPT_STAGES.map(s => {
    let done = false
    if (s.key === 'classify' || s.key === 'segregate') done = !!ri
    else if (s.key === 'ingest') done = !!(ri && (ri.placed || 0) >= 0 && (ri.files_in != null))
    else if (s.key === 'goldens') done = !!detail.goldens || !!detail.golden_queries
    else if (s.key === 'reconcile') done = !!ri
    else if (s.key === 'coverage') done = coverageTotalPeriods.value != null
    if (detail[s.key]) done = true
    return { ...s, done }
  })
})

// ─── LIVE PROCESS FLOW ──────────────────────────────────────────────────────
// 6 phases, each with real sub-stage nodes. State derived fail-soft from the
// same signals in scope: receiptStages done-flags (classify/segregate/ingest/
// goldens/reconcile/coverage), the train-status detail map (other nodes, via
// aliases), coverage=0 → held, and the newest `▸ <stage>` train-log marker →
// running. Missing data → 'queued'. Never throws.
// Ordered to mirror the LIVE pipeline log. The 'route' phase is the pre-diamond
// group (classify → segregate → ingest); every other phase flows the BPMN spine
// left→right, one icon box per stage. flowPct/flowAllDone flatten ALL of these.
const FLOW_PHASES: { id: string; label: string; keys: string[] }[] = [
  { id: 'route',   label: 'ROUTE',   keys: ['classify', 'segregate', 'ingest'] },
  { id: 'prep',    label: 'PREP',    keys: ['self-heal', 'reconcile'] },
  { id: 'profile', label: 'PROFILE', keys: ['profile', 'deep-profile'] },
  { id: 'enrich',  label: 'ENRICH',  keys: ['code-enrich', 'domain-packs'] },
  { id: 'build',   label: 'BUILD',   keys: ['queries', 'goldens', 'artifacts', 'semantic', 'mine-joins', 'verified-goldens'] },
  { id: 'index',   label: 'INDEX',   keys: ['docs', 'index', 'brain-graph'] },
  { id: 'learn',   label: 'LEARN',   keys: ['auto-eda', 'agent-kpis', 'agent-overview'] },
  { id: 'verify',  label: 'VERIFY',  keys: ['coverage'] },
]
// keys that map straight onto receiptStages done-flags
const RECEIPT_NODE_KEYS = new Set(['classify', 'segregate', 'ingest', 'goldens', 'reconcile', 'coverage'])
// detail-map + log-marker aliases for every node
const NODE_ALIASES: Record<string, string[]> = {
  classify: ['classify'],
  segregate: ['segregate', 'segregation'],
  ingest: ['ingest', 'ingestion', 'load'],
  'self-heal': ['self-heal', 'selfheal', 'self_heal', 'heal'],
  profile: ['profile', 'profiling', 'column_profile', 'column-profile'],
  'deep-profile': ['deep-profile', 'deep_profile', 'profile_v2', 'profilev2', 'deepprofile'],
  index: ['index', 'hybrid_index', 'hybridindex', 'indexer', 'indexing'],
  'code-enrich': ['code-enrich', 'code_enrich', 'codeenrich', 'enrich'],
  'domain-packs': ['domain-packs', 'domain_packs', 'domainpacks', 'packs'],
  'brain-graph': ['brain-graph', 'brain_graph', 'braingraph', 'graph'],
  'auto-eda': ['auto-eda', 'auto_eda', 'autoeda', 'eda'],
  'agent-kpis': ['agent-kpis', 'agent_kpis', 'agentkpis', 'kpis', 'kpi'],
  'agent-overview': ['agent-overview', 'agent_overview', 'agentoverview', 'overview'],
  goldens: ['goldens', 'golden', 'golden_queries', 'goldenqueries', 'goldensql', 'golden_sql'],
  reconcile: ['reconcile', 'reconciliation'],
  coverage: ['coverage'],
  // stages added for the full BPMN spine — unknown → 'queued' (fail-soft, never forced green)
  queries: ['queries', 'example_queries', 'example-queries', 'examplequeries', 'query'],
  artifacts: ['artifacts', 'generate_artifacts', 'generate-artifacts', 'generateartifacts', 'artifact'],
  semantic: ['semantic', 'semantic_metrics', 'semantic-metrics', 'semanticmetrics', 'metrics'],
  'mine-joins': ['mine-joins', 'mine_joins', 'minejoins', 'joins', 'join'],
  'verified-goldens': ['verified-goldens', 'verified_goldens', 'verifiedgoldens', 'eval_gate', 'eval-gate', 'evalgate', 'verified'],
  docs: ['docs', 'ingest_docs', 'ingest-docs', 'ingestdocs', 'attached_docs', 'attached-docs', 'attacheddocs', 'doc'],
}
const _norm = (s: string) => s.trim().toLowerCase().replace(/[ _]+/g, '-')

// Which node (if any) the newest `▸ <stage>` train-log line names. Only used
// while training. Returns a node key or null (never throws).
function runningNodeKey(): string | null {
  try {
    const raw = (props.trainLogLines && props.trainLogLines.length)
      ? props.trainLogLines
      : ((props.trainLog && Array.isArray((props.trainLog as any).log)) ? (props.trainLog as any).log : [])
    if (!Array.isArray(raw) || !raw.length) return null
    for (let i = raw.length - 1; i >= 0; i--) {
      const li = raw[i]
      const text = String((li && (li.text ?? li.message ?? li.line)) ?? li ?? '')
      const m = text.match(/▸\s*([a-z0-9 _-]+)/i)
      if (!m) continue
      const tok = _norm(m[1])
      for (const [k, aliases] of Object.entries(NODE_ALIASES)) {
        if (aliases.some(a => { const na = _norm(a); return na === tok || tok.startsWith(na) })) return k
      }
      return null   // a marker we don't map → no running node
    }
  } catch { /* fail-soft */ }
  return null
}

const trainFlow = computed(() => {
  const phases = FLOW_PHASES.map(p => ({ id: p.id, label: p.label, nodes: [] as { key: string; label: string; state: string }[] }))
  try {
    const rs: Record<string, boolean> = {}
    for (const s of receiptStages.value) rs[s.key] = s.done
    const detail = (status.value && status.value.detail) || (props.trainLog && (props.trainLog as any).detail) || {}
    const running = props.trainingAll ? runningNodeKey() : null
    const cov = coverageTotalPeriods.value

    const stateFor = (key: string): string => {
      if (running && running === key) return 'running'
      if (RECEIPT_NODE_KEYS.has(key)) {
        if (rs[key]) return 'done'
        if (key === 'coverage' && cov === 0) return 'held'
        return 'queued'
      }
      for (const a of (NODE_ALIASES[key] || [key])) {
        const entry = (detail as any)[a]
        if (entry == null) continue
        if (typeof entry === 'object') {
          const st = String(entry.state || entry.status || '').toLowerCase()
          if (['ok', 'done', 'complete', 'completed', 'success'].includes(st)) return 'done'
          if (['err', 'error', 'failed', 'skip', 'skipped', 'held'].includes(st)) return 'held'
          if (['running', 'active', 'in_progress', 'in-progress'].includes(st)) return 'running'
          return 'done'   // recorded object, no recognizable state → treat as done
        }
        if (entry) return 'done'
      }
      return 'queued'
    }

    for (const p of phases) {
      const src = FLOW_PHASES.find(x => x.id === p.id)!
      p.nodes = src.keys.map(k => ({ key: k, label: k, state: stateFor(k) }))
    }
  } catch {
    for (const p of phases) {
      const src = FLOW_PHASES.find(x => x.id === p.id)
      p.nodes = (src ? src.keys : []).map(k => ({ key: k, label: k, state: 'queued' }))
    }
  }
  return phases
})

// Raw "every node done" — read from trainFlow directly (NOT the resolved list) so it
// stays independent of runComplete (avoids a computed cycle). Used only as a signal now.
const flowAllDone = computed(() => {
  const nodes = trainFlow.value.flatMap(p => p.nodes)
  return nodes.length > 0 && nodes.every(n => n.state === 'done')
})

// runComplete — true once a train has FINISHED (and is not currently running). Fail-soft:
// any signal we can find flips it. During an active run this is always false, so queued
// nodes stay queued (never prematurely skipped).
const runComplete = computed(() => {
  try {
    if (props.trainingAll) return false
    // signal 1: a train-log line says the run is done
    const raw = (props.trainLogLines && props.trainLogLines.length)
      ? props.trainLogLines
      : ((props.trainLog && Array.isArray((props.trainLog as any).log)) ? (props.trainLog as any).log : [])
    if (Array.isArray(raw)) {
      for (const li of raw) {
        const text = String((li && (li.text ?? li.message ?? li.line)) ?? li ?? '').toLowerCase()
        if (text.includes('all stages complete') || text.includes('agent ready')) return true
      }
    }
    // signal 2: persisted train status is a terminal success state
    const st = String((status.value && status.value.status) || (props.trainLog && (props.trainLog as any).status) || '').toLowerCase()
    if (['done', 'complete', 'completed', 'ready', 'success', 'finished'].includes(st)) return true
    // signal 3: the flow is already fully done
    if (flowAllDone.value) return true
  } catch { /* fail-soft */ }
  return false
})

// Resolved flow — once the run has completed, any still-'queued' node becomes 'skipped'
// (a genuine no-op that had nothing to do). Held/done/running are untouched. During an
// active run runComplete is false → identical to the raw trainFlow.
const _resolvedFlow = computed(() => {
  const rc = runComplete.value
  if (!rc) return trainFlow.value
  return trainFlow.value.map(p => ({
    ...p,
    nodes: p.nodes.map(n => (n.state === 'queued' ? { ...n, state: 'skipped' } : n)),
  }))
})

const _flowNodes = computed(() => _resolvedFlow.value.flatMap(p => p.nodes))
// done + skipped + held all count as RESOLVED toward completion.
const _RESOLVED = new Set(['done', 'skipped', 'held'])
const flowPct = computed(() => {
  const nodes = _flowNodes.value
  if (!nodes.length) return 0
  return Math.round(100 * nodes.filter(n => _RESOLVED.has(n.state)).length / nodes.length)
})
// flowReady drives the terminal ✓ + "agent ready" label: a finished run, or every node resolved.
const flowReady = computed(() => {
  if (runComplete.value) return true
  const nodes = _flowNodes.value
  return nodes.length > 0 && nodes.every(n => _RESOLVED.has(n.state))
})

// ─── BPMN spine derivation (reuses trainFlow above — no new state) ───────────
// Split the same node set into the pre-diamond ROUTE group and the main spine.
const routeNodes = computed(() => {
  const p = _resolvedFlow.value.find(x => x.id === 'route')
  return p ? p.nodes : []
})
const spineNodes = computed(() => _resolvedFlow.value.filter(x => x.id !== 'route').flatMap(x => x.nodes))
const routerDone = computed(() => routeNodes.value.length > 0 && routeNodes.value.every(n => n.state === 'done'))
const heldCount = computed(() => Number((routeInbox.value && routeInbox.value.held) || 0))

// Inline SVG icons (stroke=currentColor, CSP-safe, no emoji) — one per stage.
const ICON_PATHS: Record<string, string> = {
  classify: '<path d="M3 5h18M6 12h12M10 19h4"/>',
  segregate: '<path d="M12 3v5M12 8L7 13M12 8l5 5M4 16a3 3 0 106 0 3 3 0 10-6 0M14 16a3 3 0 106 0 3 3 0 10-6 0"/>',
  ingest: '<path d="M12 3v10M8 9l4 4 4-4M5 20h14"/>',
  'self-heal': '<path d="M12 3v18M5 8l7-5 7 5M5 8v8l7 5 7-5V8"/>',
  reconcile: '<path d="M4 8h12M4 8l3-3M4 8l3 3M20 16H8M20 16l-3-3M20 16l-3 3"/>',
  profile: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  'deep-profile': '<path d="M4 20V12M9 20V7M14 20v-5M19 20V4M22 20H2"/>',
  'code-enrich': '<path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>',
  'domain-packs': '<path d="M12 3l8 4-8 4-8-4 8-4zM4 12l8 4 8-4M4 17l8 4 8-4"/>',
  queries: '<path d="M4 6h16M4 12h10M4 18h7"/>',
  goldens: '<path d="M12 3l2.5 6H21l-5 4 2 7-6-4-6 4 2-7-5-4h6.5z"/>',
  artifacts: '<path d="M4 4h16v12H4zM4 20h16"/>',
  semantic: '<path d="M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18"/>',
  'mine-joins': '<path d="M8 12a4 4 0 108 0 4 4 0 10-8 0M2 12h6M16 12h6"/>',
  'verified-goldens': '<path d="M12 3l2.5 6H21l-5 4 2 7-6-4-6 4 2-7-5-4h6.5zM9 9l2 2 4-4"/>',
  docs: '<path d="M6 3h9l3 3v15H6zM9 12h6M9 16h6"/>',
  index: '<path d="M4 6h16M4 12h16M4 18h16M8 3v18"/>',
  'brain-graph': '<path d="M6 6a2 2 0 104 0 2 2 0 10-4 0M14 18a2 2 0 104 0 2 2 0 10-4 0M9 8l6 8"/>',
  'auto-eda': '<path d="M12 2a7 7 0 00-4 13v3h8v-3a7 7 0 00-4-13z"/>',
  'agent-kpis': '<path d="M4 20V4M4 20h16M8 16l3-4 3 2 4-6"/>',
  'agent-overview': '<path d="M4 5h16v10H4zM8 19h8"/>',
  coverage: '<path d="M12 3a9 9 0 100 18 9 9 0 000-18zM12 7v5l4 2"/>',
  __router: '<path d="M4 6h16M4 12h10M4 18h7"/>',
}
const NODE_LABELS: Record<string, string> = {
  classify: 'classify', segregate: 'segregate', ingest: 'ingest',
  'self-heal': 'self-heal', reconcile: 'reconcile',
  profile: 'profile', 'deep-profile': 'deep profile',
  'code-enrich': 'code enrich', 'domain-packs': 'domain packs',
  queries: 'queries', goldens: 'goldens', artifacts: 'artifacts', semantic: 'semantic',
  'mine-joins': 'mine joins', 'verified-goldens': 'verified goldens',
  docs: 'docs', index: 'index', 'brain-graph': 'brain graph',
  'auto-eda': 'auto EDA', 'agent-kpis': 'agent KPIs', 'agent-overview': 'overview',
  coverage: 'coverage',
}
const iconFor = (key: string): string => ICON_PATHS[key] || ICON_PATHS.classify
const nodeLabel = (key: string): string => NODE_LABELS[key] || key

const byDestEntries = computed<[string, number][]>(() => {
  const bd = (routeInbox.value && routeInbox.value.by_dest) || {}
  return Object.entries(bd).filter(([, n]) => Number(n) > 0) as [string, number][]
})

const DEST_EMOJI: Record<string, string> = {
  database: '📊', semantic: '🔖', instructions: '📋', examples: '📋', knowledge: '📖', skip: '⏸',
}
const DEST_SHORT: Record<string, string> = {
  database: 'data', semantic: 'glossary', instructions: 'instr', examples: 'examples', knowledge: 'def', skip: '?',
}
const destEmoji = (d: string) => DEST_EMOJI[d] || '•'
const destShort = (d: string) => DEST_SHORT[d] || d

// Coverage pill — fail-soft (hide if endpoint 404s).
const coverageTotalPeriods = ref<number | null>(null)
async function loadCoverage() {
  if (!props.studioId) return
  try {
    const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/coverage`)
    if (error?.value) { coverageTotalPeriods.value = null; return }
    const srcs: any[] = Array.isArray((data.value as any)?.sources) ? (data.value as any).sources : []
    let total = 0
    for (const s of srcs) for (const t of (s.tables || [])) total += Number(t.n_periods || (Array.isArray(t.periods) ? t.periods.length : 0)) || 0
    coverageTotalPeriods.value = srcs.length ? total : null
  } catch { coverageTotalPeriods.value = null }
}

async function loadStatus() {
  if (!props.studioId) return
  try {
    const { data, error } = await useMyFetch<any>(`/studios/${props.studioId}/train/status`, { method: 'GET' })
    if (error?.value) return
    const st = (data.value as any) || {}
    if (st && (st.status || st.step || st.detail)) status.value = st
  } catch { /* fail-soft */ }
}

// Poll train status every 2s while training; refresh coverage when training ends.
let timer: any = null
watch(() => props.trainingAll, (now, prev) => {
  if (now && !timer) {
    timer = setInterval(() => { loadStatus() }, 2000)
  } else if (!now && timer) {
    clearInterval(timer); timer = null
    loadStatus(); loadCoverage()
    try { inboxRef.value?.refresh?.() } catch { /* */ }
  }
})

// Parent calls this (via ref) after an inline upload queues files → refresh the
// embedded Inbox rows + train status so the newly-queued files appear.
function refresh() {
  try { inboxRef.value?.refresh?.() } catch { /* fail-soft */ }
  loadStatus()
}
defineExpose({ refresh })

onMounted(() => { loadStatus(); loadCoverage(); loadModelList(); loadStudioModel() })
onBeforeUnmount(() => {
  if (timer) { clearInterval(timer); timer = null }
  if (savedTimer) { clearTimeout(savedTimer); savedTimer = null }
})
</script>

<style scoped>
/* LIVE PROCESS DIAGRAM — warm clay/cream BPMN spine (matches the TRAIN card) */
.flow-bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.flow-bar { flex: 1; height: 5px; border-radius: 999px; background: #EDE5D8; overflow: hidden; }
.flow-bar-fill { height: 100%; background: #C2541E; border-radius: 999px; transition: width .4s ease; }
.flow-status { font-size: 10.5px; font-weight: 600; color: #9a958c; white-space: nowrap; }
.flow-status-run { color: #C2541E; }
.flow-status-done { color: #3f9e6a; }

/* scroll spine — ~20 boxes overflow horizontally, never the page body */
.bpmn-canvas { border: 1px solid #ECE3D6; border-radius: 14px; background: #FBF8F3; padding: 16px 14px 12px; overflow-x: auto; }
.bpmn-spine { display: flex; align-items: flex-start; gap: 0; min-width: min-content; }

/* icon box */
.bpmn-node { width: 78px; display: flex; flex-direction: column; align-items: center; text-align: center; flex: 0 0 auto; }
.bpmn-box { width: 52px; height: 52px; border-radius: 14px; display: grid; place-items: center; position: relative; background: #F3EFE8; border: 1.5px solid #eae3d7; color: #b7b0a4; transition: .3s; }
.bpmn-icon { width: 24px; height: 24px; stroke-width: 1.9; fill: none; stroke: currentColor; }
.bpmn-lbl { font-size: 9.5px; margin-top: 6px; line-height: 1.2; color: #9a958c; font-weight: 600; max-width: 76px; }

/* states */
.bpmn-node.st-done .bpmn-box { background: #e4f6f3; color: #1f8878; border-color: #bde9e2; }
.bpmn-node.st-done .bpmn-lbl { color: #1f8878; }
.bpmn-node.st-running .bpmn-box { background: #fbeedd; color: #e0912f; border-color: #e0912f; animation: bpmn-pulse 1.2s ease-in-out infinite; }
.bpmn-node.st-running .bpmn-lbl { color: #c98a2e; font-weight: 700; }
.bpmn-node.st-held .bpmn-box { background: #f3efe8; color: #a89f90; border: 1.5px dashed #c9bfae; }
.bpmn-node.st-held .bpmn-lbl { color: #9a958c; }
.bpmn-node.st-queued .bpmn-box { background: #f3efe8; color: #cfc8bb; border-color: #eae3d7; }
/* skipped = a no-op that had nothing to do (resolved). Muted grey-green ✓ — clearly NOT
   the teal "done" and NOT the grey "queued". */
.bpmn-node.st-skipped .bpmn-box { background: #eef2ef; color: #9db3a9; border-color: #cdddd4; }
.bpmn-node.st-skipped .bpmn-lbl { color: #9db3a9; }
.bpmn-node.st-skipped .bpmn-badge { background: #b6c7bf; color: #f7faf8; }

/* running progress ring */
.ring { position: absolute; top: -5px; left: -5px; width: 62px; height: 62px; pointer-events: none; display: none; }
.bpmn-node.st-running .ring { display: block; }
.ring circle { fill: none; stroke-width: 3; }
.ring .track { stroke: #f0dcc0; }
.ring .fill { stroke: #e0912f; stroke-linecap: round; transform-origin: 50% 50%; transform: rotate(-90deg); animation: bpmn-ring 1.1s linear infinite; }

/* done / held badge */
.bpmn-badge { position: absolute; right: -4px; bottom: -4px; min-width: 17px; height: 17px; padding: 0 2px; border-radius: 50%; display: grid; place-items: center; font-size: 10px; color: #fff; background: #2fb8a6; border: 2px solid #FBF8F3; line-height: 1; }
.bpmn-badge:empty { display: none; }
.bpmn-node.st-held .bpmn-badge { background: #a89f90; }

/* connector arrow */
.bpmn-arrow { width: 26px; height: 52px; display: flex; align-items: center; justify-content: center; flex: 0 0 auto; }
.bpmn-arrow svg { width: 26px; height: 14px; stroke: #cbbda0; stroke-width: 1.6; fill: none; }
.bpmn-arrow.done svg { stroke: #2fb8a6; }

/* decision diamond */
.bpmn-diamond-wrap { display: flex; flex-direction: column; align-items: center; flex: 0 0 auto; width: 96px; }
.bpmn-diamond { width: 50px; height: 50px; background: #eaf0fb; border: 1.5px solid #cdd8f0; transform: rotate(45deg); border-radius: 9px; display: grid; place-items: center; color: #4f74c8; }
.bpmn-diamond svg { width: 20px; height: 20px; transform: rotate(-45deg); stroke: currentColor; fill: none; stroke-width: 1.9; }
.bpmn-diamond.done { background: #e4f6f3; border-color: #bde9e2; color: #1f8878; }
.bpmn-dlbl { font-size: 9.5px; font-weight: 600; color: #9a958c; margin-top: 8px; }

/* held branch (hangs below the diamond) */
.bpmn-branch { display: flex; flex-direction: column; align-items: center; margin-top: 8px; transition: opacity .3s; }
.bpmn-branch.faint { opacity: .35; }
.bpmn-drop { width: 2px; height: 16px; background: #cbbda0; }

/* terminal circles */
.bpmn-terminal, .bpmn-terminal-final { display: flex; flex-direction: column; align-items: center; text-align: center; flex: 0 0 auto; }
.bpmn-terminal-final { width: 86px; }
.tcircle { width: 48px; height: 48px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-size: 22px; background: #d8cfc0; }
.tcircle.ok { background: #2fb8a6; }
.tcircle.held { background: #c3bcae; }
.tlbl { font-size: 9.5px; font-weight: 600; margin-top: 6px; color: #211B14; line-height: 1.25; }
.tsub { color: #b3a48f; font-size: 8.5px; font-weight: 600; }

/* legend */
.bpmn-legend { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 12px; font-size: 10px; color: #9a958c; }
.bpmn-legend span { display: inline-flex; align-items: center; gap: 5px; }
.bpmn-legend .dot { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.bpmn-legend .dot.d { background: #2fb8a6; }
.bpmn-legend .dot.r { background: #e0912f; }
.bpmn-legend .dot.q { background: #d8cfc0; }
.bpmn-legend .dot.s { background: #b6c7bf; }
.bpmn-legend .dot.h { background: #b8afa0; }

@keyframes bpmn-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(224, 145, 47, .35); } 50% { box-shadow: 0 0 0 6px rgba(224, 145, 47, 0); } }
@keyframes bpmn-ring { to { transform: rotate(270deg); } }
@media (prefers-reduced-motion: reduce) {
  .bpmn-node.st-running .bpmn-box { animation: none; }
  .ring .fill { animation: none; }
}
</style>
