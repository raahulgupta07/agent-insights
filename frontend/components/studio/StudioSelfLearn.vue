<template>
  <!-- Per-agent self-learning cadence. Master switch is the org daemon flag;
       when off the card stays informational. Owner/editor can change. -->
  <div class="rounded-2xl border border-[#E9E0D3] bg-[#FBFAF6] p-4 mb-4">
    <div class="flex items-center justify-between gap-2 mb-1">
      <h3 class="text-sm font-semibold text-[#1f2328] flex items-center gap-1.5" style="font-family: ui-serif, Georgia, serif">
        <UIcon name="i-heroicons-sparkles" class="w-4 h-4 text-[#5A4FCF]" /> Self-learning
      </h3>
      <span v-if="cfg.enabled" class="text-[10px] font-medium text-[#2F6F4F] bg-[#E7F1EA] rounded-full px-2 py-0.5">ON</span>
      <span v-else class="text-[10px] font-medium text-[#9a958c] bg-[#F0ECE3] rounded-full px-2 py-0.5">OFF</span>
    </div>
    <p class="text-[11.5px] text-[#6b6b6b] mb-3 max-w-[520px]">
      Let this agent quietly learn from its own usage on a schedule — it <b>proposes</b> examples &amp; rules
      for your review (nothing auto-applies). You pick how often.
    </p>

    <!-- master off note -->
    <div v-if="!cfg.master_enabled" class="text-[11px] text-[#8a7333] bg-[#F6EFE0] rounded-lg px-3 py-2 mb-3">
      Self-learning is currently disabled org-wide by an admin. Your setting is saved and will take effect once it's turned on.
    </div>

    <div v-if="loading" class="text-[11px] text-[#9a958c] py-2">Loading…</div>

    <template v-else>
      <!-- enable toggle -->
      <label class="flex items-center gap-2.5 mb-3 cursor-pointer select-none" :class="{ 'opacity-60 cursor-not-allowed': !canEdit }">
        <button type="button" role="switch" :aria-checked="cfg.enabled" :disabled="!canEdit"
          class="relative inline-flex h-5 w-9 items-center rounded-full transition-colors"
          :class="cfg.enabled ? 'bg-[#5A4FCF]' : 'bg-[#D8D2C6]'"
          @click="canEdit && (cfg.enabled = !cfg.enabled)">
          <span class="inline-block h-4 w-4 transform rounded-full bg-white transition-transform" :class="cfg.enabled ? 'translate-x-4' : 'translate-x-0.5'"></span>
        </button>
        <span class="text-[12.5px] font-medium text-[#1f2328]">Auto-improve this agent</span>
      </label>

      <!-- cadence -->
      <div v-if="cfg.enabled" class="space-y-3">
        <div>
          <div class="text-[10px] uppercase tracking-wide text-[#9a958c] mb-1">Frequency</div>
          <div class="inline-flex rounded-lg border border-[#E9E0D3] bg-white p-0.5">
            <button v-for="opt in cadenceOptions" :key="opt.v" type="button" :disabled="!canEdit"
              class="text-[11.5px] font-medium rounded-md px-2.5 py-1 transition-colors disabled:opacity-50"
              :class="cfg.cadence === opt.v ? 'bg-[#5A4FCF] text-white' : 'text-[#6b6b6b] hover:bg-[#F4EEE5]'"
              @click="cfg.cadence = opt.v">{{ opt.label }}</button>
          </div>
        </div>

        <!-- run-at hour for daily/weekly/monthly -->
        <div v-if="cfg.cadence !== '6h'">
          <div class="text-[10px] uppercase tracking-wide text-[#9a958c] mb-1">Run at (UTC)</div>
          <select v-model.number="cfg.hour_utc" :disabled="!canEdit"
            class="text-[12px] border border-[#E9E0D3] rounded-lg px-2.5 py-1.5 bg-white text-[#1f2328] disabled:opacity-50">
            <option v-for="h in 24" :key="h-1" :value="h-1">{{ String(h-1).padStart(2,'0') }}:00{{ (h-1)===0 ? ' (midnight)' : '' }}</option>
          </select>
        </div>

        <div class="flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-[#9a958c] pt-0.5">
          <span>Last run: <span class="text-[#6b6b6b]">{{ fmt(cfg.last_run_at) || 'never' }}</span></span>
          <span>Next: <span class="text-[#6b6b6b]">{{ fmt(cfg.next_run_at) || '—' }}</span></span>
        </div>
      </div>

      <!-- save -->
      <div v-if="canEdit" class="flex items-center gap-2 mt-3.5 pt-3 border-t border-[#E9E0D3]">
        <span v-if="savedMsg" class="text-[10.5px] text-[#2F6F4F] font-medium">{{ savedMsg }}</span>
        <span v-if="errMsg" class="text-[10.5px] text-[#C0392B] font-medium">{{ errMsg }}</span>
        <button type="button" :disabled="saving" class="ml-auto inline-flex items-center gap-1.5 text-[11.5px] font-semibold text-white bg-[#5A4FCF] hover:bg-[#473dad] rounded-lg px-3.5 py-1.5 transition-colors disabled:opacity-50" @click="save">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
      <div v-else class="text-[10.5px] text-[#9a958c] mt-3 pt-3 border-t border-[#E9E0D3]">Owner or editor can change this.</div>
    </template>
  </div>
</template>

<script setup lang="ts">
const props = defineProps<{ studioId: string; canEdit?: boolean }>()

const cadenceOptions = [
  { v: '6h', label: 'Every 6h' },
  { v: 'daily', label: 'Daily' },
  { v: 'weekly', label: 'Weekly' },
  { v: 'monthly', label: 'Monthly' },
]

const loading = ref(true)
const saving = ref(false)
const savedMsg = ref('')
const errMsg = ref('')
const cfg = reactive<any>({
  enabled: false, cadence: 'daily', hour_utc: 0,
  last_run_at: null, next_run_at: null, master_enabled: false, role: null,
})

const fmt = (s: string | null) => {
  if (!s) return ''
  try { return new Date(s).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) } catch { return s }
}

const load = async () => {
  loading.value = true
  try {
    const { data } = await useMyFetch<any>(`/api/studios/${props.studioId}/self-learn`)
    const d = data.value as any
    if (d) Object.assign(cfg, d)
  } catch (e) { /* fail-soft: leave defaults */ }
  loading.value = false
}

const save = async () => {
  saving.value = true; savedMsg.value = ''; errMsg.value = ''
  try {
    const { data, error } = await useMyFetch<any>(`/api/studios/${props.studioId}/self-learn`, {
      method: 'PUT',
      body: { enabled: cfg.enabled, cadence: cfg.cadence, hour_utc: cfg.hour_utc },
    })
    if (error?.value) throw error.value
    if (data.value) Object.assign(cfg, data.value)
    savedMsg.value = 'Saved'
    setTimeout(() => { savedMsg.value = '' }, 2500)
  } catch (e: any) {
    errMsg.value = e?.data?.detail || 'Save failed'
  }
  saving.value = false
}

onMounted(load)
</script>
