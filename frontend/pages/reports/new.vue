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
    // Reusable = exists + never chatted in (0 completions). We do NOT require the
    // draft's data_sources to match the picked agent — instead we RE-SCOPE the same
    // scratch row to the current selection (see rescopeDraft below). This keeps at
    // most ONE empty draft in existence instead of minting a fresh orphan on every
    // agent switch.
    return true;
  } catch {
    return false;
  }
}

// Point the reused scratch draft at the currently-selected agent(s) so its grounding
// follows the picker (mirrors the v1.122 report-lock). Fail-soft.
async function rescopeDraft(id: string): Promise<void> {
  try {
    const ids = (selectedAgentObjects.value || []).map((ds: any) => ds?.id).filter(Boolean);
    await useMyFetch(`/reports/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data_sources: ids, studio_id: selectedStudioId.value || null }),
    });
  } catch { /* ignore — draft still opens, just keeps prior scope */ }
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
  } else {
    // Reusing the existing empty scratch — re-point it at the picked agent(s).
    await rescopeDraft(id);
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
