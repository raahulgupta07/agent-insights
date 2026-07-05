// /composables/useLlmConfigured.ts
//
// Shared, org-wide "does this org have an LLM key configured?" signal so the UI
// can disable create/upload/connect buttons when it's missing. FAIL-OPEN: default
// true; only flips false when GET /settings explicitly returns llm_configured:false.
// A transient/absent-field error must NEVER lock the user out.
//
// Module-level singleton refs (mirrors composables/useAppNav.ts) so every consumer
// shares one fetch. Fetch once on first use; refresh() re-fetches (e.g. after a key save).
import { useMyFetch } from '~/composables/useMyFetch'

const llmConfigured = ref(true)
const loading = ref(false)
let loaded = false

async function fetchSettings() {
  loading.value = true
  try {
    const { data } = await useMyFetch<any>('/settings')
    const settings = data.value as any
    // Only lock out on an EXPLICIT false; absent/undefined field stays fail-open.
    llmConfigured.value = settings?.llm_configured === false ? false : true
  } catch {
    // Transient error → never lock the user out.
    llmConfigured.value = true
  } finally {
    loading.value = false
  }
}

export function useLlmConfigured() {
  if (!loaded) {
    loaded = true
    fetchSettings()
  }
  const refresh = async () => { await fetchSettings() }
  return { llmConfigured, loading, refresh }
}
