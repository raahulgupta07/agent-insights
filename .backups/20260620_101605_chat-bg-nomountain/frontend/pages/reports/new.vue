<template>
  <div class="flex flex-col h-full bg-[#F5F4EE]">
    <!-- Scrollable empty-state area -->
    <div class="flex-1 overflow-y-auto">
      <div class="flex flex-col items-center text-center min-h-[58vh] justify-center px-4">
        <img
          src="/assets/empty-states/empty-integrations.png"
          alt=""
          class="w-64 max-w-full mb-6 select-none pointer-events-none"
        />
        <h1
          class="text-lg font-semibold"
          style="font-family: ui-serif, Georgia, 'Times New Roman', serif"
        >{{ emptyTitle }}</h1>

        <!-- Optional suggestion chips (corpus-agnostic, static) -->
        <div v-if="starters.length > 0" class="mt-5 flex flex-wrap justify-center gap-2">
          <button
            v-for="s in starters"
            :key="s"
            class="px-3 py-1.5 text-xs rounded-full border border-gray-200 bg-gray-50 text-gray-700 hover:bg-[#F3E7DF] hover:border-[#C2683F] transition-colors"
            @click="textareaContent = s"
          >
            {{ s }}
          </button>
        </div>
      </div>
    </div>

    <!-- Composer (lazy-create: no report_id → PromptBoxV2.createReport() handles POST + redirect) -->
    <div class="shrink-0 bg-[#F5F4EE] pt-2 pb-6">
      <div class="mx-auto w-full px-4 max-w-2xl">
        <PromptBoxV2
          :initialSelectedDataSources="selectedDataSources"
          :initialSelectedStudioId="selectedStudioId"
          :initialMode="'chat'"
          :textareaContent="textareaContent"
          @update:modelValue="handlePromptUpdate"
        />
      </div>
      <p class="text-center text-[11px] text-gray-400 mt-2">City Agent can make mistakes - double-check results.</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import PromptBoxV2 from '~/components/prompt/PromptBoxV2.vue';

definePageMeta({
  layout: 'default',
  auth: true,
  permissions: ['view_reports'],
});

const { t } = useI18n();

// Selected agents from the AgentSelector are the data sources (mirror pages/index.vue)
const { selectedAgentObjects, selectedStudioId } = useAgent();
const selectedDataSources = computed(() => selectedAgentObjects.value);

// Heading: prefer the i18n key, fall back to a literal if it doesn't resolve
const emptyTitle = computed(() => {
  const key = 'reports.emptyTitle';
  const resolved = t(key);
  return resolved === key ? 'Ask a question to get started.' : resolved;
});

// Bound to the composer textarea; chips just prefill it
const textareaContent = ref('');
const handlePromptUpdate = (value: string) => {
  textareaContent.value = value;
};

// A few generic starter chips (no corpus dependency)
const starters: string[] = [];
</script>
