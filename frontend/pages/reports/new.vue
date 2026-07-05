<template>
  <!-- Thin redirect: /reports/new opens (or reuses) a real draft report and lands
       on /reports/{id} so the FULL chat shell renders — every panel tab, Share,
       collapse/expand, drag-resize — all real, before a single message is sent.
       A brief centered spinner shows while we resolve the draft. -->
  <div class="flex items-center justify-center h-full bg-[#FBFAF6]">
    <Spinner class="w-5 h-5 text-gray-400" />
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import Spinner from '@/components/Spinner.vue';

definePageMeta({
  layout: 'default',
  auth: true,
  permissions: ['view_reports'],
});

const { selectedAgentObjects, selectedStudioId } = useAgent();

const SCRATCH_KEY = 'scratchReportId';

// A scratch draft is reusable only if it still exists AND has never been chatted
// in (0 completions). Once a user sends a message it "graduates" to a real report
// and the next New-report click mints a fresh scratch — so at most one empty
// "untitled report" ever sits in the sidebar.
async function isReusable(id: string): Promise<boolean> {
  try {
    const rep = await useMyFetch(`/reports/${id}`);
    const repData = (rep as any)?.data?.value;
    if ((rep as any)?.error?.value || !repData) return false;
    const comps = await useMyFetch(`/reports/${id}/completions`);
    const list = (comps as any)?.data?.value;
    const arr = Array.isArray(list) ? list : (list?.completions || list?.items || []);
    if (!Array.isArray(arr) || arr.length !== 0) return false;
    // Also require the draft's data_sources to match the currently-selected agent(s).
    // Otherwise, picking a different agent then hitting "New" would reopen this empty
    // draft still scoped to the OLD agent. Compare against the SAME id-set createDraft
    // uses (selectedAgentObjects = the explicit pick, or ALL agents when none picked),
    // so an explicit single-agent pick compares by that id, not the "all" fallback.
    const wantIds = (selectedAgentObjects.value || []).map((ds: any) => ds?.id).filter(Boolean);
    const haveIds = (repData?.data_sources || []).map((ds: any) => ds?.id).filter(Boolean);
    return wantIds.length === haveIds.length && wantIds.every((x: string) => haveIds.includes(x));
  } catch {
    return false;
  }
}

async function createDraft(): Promise<string | null> {
  try {
    const resp = await useMyFetch('/reports', {
      method: 'POST',
      body: JSON.stringify({
        title: 'untitled report',
        data_sources: (selectedAgentObjects.value || []).map((ds: any) => ds.id).filter(Boolean),
        studio_id: selectedStudioId.value || null,
      }),
    });
    const data = (resp as any)?.data?.value as any;
    return data?.id || null;
  } catch {
    return null;
  }
}

onMounted(async () => {
  let id: string | null = null;
  try { id = localStorage.getItem(SCRATCH_KEY); } catch { /* ignore */ }

  if (!id || !(await isReusable(id))) {
    id = await createDraft();
    if (id) { try { localStorage.setItem(SCRATCH_KEY, id); } catch { /* ignore */ } }
  }

  if (id) {
    // replace so Back doesn't bounce through /reports/new again.
    await navigateTo(`/reports/${id}`, { replace: true });
  } else {
    // Fallback: land on Home if the draft could not be created.
    await navigateTo('/', { replace: true });
  }
});
</script>
