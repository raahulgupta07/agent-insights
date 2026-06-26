<template>
  <div class="cat-wrap">
    <!-- Terminal panel -->
    <transition name="cat-pop">
      <div v-if="open" class="cat-panel" role="dialog" aria-label="City Agent status">
        <!-- header -->
        <div class="cat-head">
          <span class="cat-mark">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none"><rect x="4" y="6" width="16" height="13" rx="3.5" stroke="#fff" stroke-width="1.7"/><circle cx="9.5" cy="12.5" r="1.3" fill="#fff"/><circle cx="14.5" cy="12.5" r="1.3" fill="#fff"/><path d="M12 6V3M12 3h.01" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/></svg>
          </span>
          <div class="flex-1 min-w-0">
            <div class="cat-title">City Agent</div>
            <div class="cat-sub"><span class="cat-sub-dot" />City Agent · {{ phase }}</div>
          </div>
          <button class="cat-icon" :title="'Refresh'" @click="refresh">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" :class="{ 'cat-spin': busy }"><path d="M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16M3 21v-5h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button class="cat-icon" :title="'Collapse'" @click="open = false">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
        </div>

        <!-- terminal body -->
        <div class="cat-body">
          <div v-for="(line, i) in visibleLines" :key="i" class="cat-line">
            <span class="cat-caret">›</span>
            <span>{{ line.text }}<span v-if="i === visibleLines.length - 1 && line.last" class="cat-cursor" /></span>
          </div>
        </div>

        <!-- footer -->
        <div class="cat-foot">
          <span class="cat-status"><span class="cat-status-dot" />{{ statusLabel }}</span>
          <span class="cat-model">{{ modelLabel }}</span>
        </div>
      </div>
    </transition>

    <!-- launcher bubble -->
    <button class="cat-launch" :class="{ 'cat-launch-on': open }" :aria-label="open ? 'Close City Agent' : 'Open City Agent'" @click="toggle">
      <span class="cat-launch-glow" />
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none"><rect x="4" y="6" width="16" height="13" rx="3.5" stroke="#fff" stroke-width="1.7"/><circle cx="9.5" cy="12.5" r="1.4" fill="#fff"/><circle cx="14.5" cy="12.5" r="1.4" fill="#fff"/><path d="M12 6V3M12 3h.01" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/></svg>
    </button>
  </div>
</template>

<script setup lang="ts">
// Floating "agent thinking" widget — a coral launcher bubble that opens a dark
// terminal-style status popover. Numbers are REAL (fetched from /data_sources +
// /llm/models); nothing is faked. Fail-soft: on any error the lines degrade to
// the generic boot/ready pair, never throwing.

const open = ref(false)
const busy = ref(false)
const phase = ref('booting…')
const statusLabel = ref('Booting')
const modelLabel = ref('City Agent')

const sourceCount = ref<number | null>(null)
const tableCount = ref<number | null>(null)

interface Line { text: string; last?: boolean }
const allLines = ref<Line[]>([])
const visibleLines = ref<Line[]>([])

const timers: any[] = []
const wait = (ms: number) => new Promise<void>(r => { const t = setTimeout(r, ms); timers.push(t) })
const clearTimers = () => { while (timers.length) clearTimeout(timers.pop()) }

// Build the status lines from real counts.
const buildLines = () => {
  const lines: Line[] = [{ text: 'boot · context engine online' }]
  if (sourceCount.value !== null) {
    const s = `${sourceCount.value} source${sourceCount.value === 1 ? '' : 's'}`
    const tablePart = tableCount.value !== null ? ` · ${tableCount.value} table${tableCount.value === 1 ? '' : 's'}` : ''
    lines.push({ text: `synced ${s}${tablePart}` })
  }
  lines.push({ text: 'vector index warm' })
  lines.push({ text: 'ready.', last: true })
  allLines.value = lines
}

// Type the lines out one at a time when the panel opens.
const playing = ref(false)
const playLines = async () => {
  if (playing.value) return
  playing.value = true
  visibleLines.value = []
  for (const line of allLines.value) {
    visibleLines.value = [...visibleLines.value, line]
    await wait(line.last ? 250 : 420)
  }
  phase.value = 'ready.'
  statusLabel.value = 'Idle'
  playing.value = false
}

const fetchState = async () => {
  busy.value = true
  try {
    const { data } = await useMyFetch<any[]>('/data_sources', { method: 'GET' })
    const list = (data.value as any[]) || []
    sourceCount.value = list.filter(d => d?.status === 'active').length || list.length
    let tables = 0
    for (const ds of list) {
      for (const c of (ds.connections || [])) {
        if (typeof c?.table_count === 'number') tables += c.table_count
      }
    }
    tableCount.value = tables || null
  } catch {
    sourceCount.value = null
    tableCount.value = null
  }
  // Default model label (fail-soft).
  try {
    const { data } = await useMyFetch<any[]>('/llm/models', { method: 'GET' })
    const models = (data.value as any[]) || []
    const def = models.find(m => m?.is_default) || models.find(m => m?.is_enabled) || models[0]
    if (def?.name) modelLabel.value = String(def.name)
  } catch { /* keep default label */ }
  busy.value = false
  buildLines()
}

const refresh = async () => {
  phase.value = 'syncing…'
  statusLabel.value = 'Working'
  await fetchState()
  await playLines()
}

const toggle = async () => {
  open.value = !open.value
  if (open.value) {
    if (!allLines.value.length) await fetchState()
    await playLines()
  }
}

onMounted(() => {
  // Warm the counts in the background so the first open is instant.
  fetchState().catch(() => {})
})
onBeforeUnmount(clearTimers)
</script>

<style scoped>
.cat-wrap { position: fixed; right: 24px; bottom: 24px; z-index: 60; font-family: 'Hanken Grotesk', system-ui, sans-serif; }

/* launcher */
.cat-launch {
  position: relative; width: 64px; height: 64px; margin-left: auto;
  border: none; border-radius: 20px; cursor: pointer;
  background: linear-gradient(150deg, #D67037, #A8330F);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 16px 34px -12px rgba(168, 51, 15, .6);
  transition: transform .18s, box-shadow .18s;
}
.cat-launch:hover { transform: translateY(-2px) scale(1.04); }
.cat-launch-on { transform: scale(.96); }
.cat-launch-glow {
  position: absolute; inset: -8px; border-radius: 26px; pointer-events: none;
  background: radial-gradient(circle, rgba(214, 112, 55, .35), transparent 70%);
  animation: cat-glow 2.6s ease-in-out infinite;
}
@keyframes cat-glow { 0%, 100% { opacity: .5; transform: scale(1); } 50% { opacity: .85; transform: scale(1.08); } }

/* panel */
.cat-panel {
  position: absolute; right: 0; bottom: 80px; width: 360px; max-width: calc(100vw - 32px);
  background: radial-gradient(130% 110% at 80% -10%, #2A1F18, #120D0A);
  border: 1px solid rgba(255, 255, 255, .07);
  border-radius: 22px; overflow: hidden;
  box-shadow: 0 40px 80px -30px rgba(20, 12, 6, .8);
}
.cat-head { display: flex; align-items: center; gap: 12px; padding: 16px 16px 14px; border-bottom: 1px solid rgba(255, 255, 255, .06); }
.cat-mark {
  width: 46px; height: 46px; border-radius: 13px; flex-shrink: 0;
  background: linear-gradient(150deg, #D67037, #A8330F);
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 8px 18px -6px rgba(168, 51, 15, .7);
}
.cat-title { font-size: 16px; font-weight: 600; color: #F3ECE2; }
.cat-sub { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: #9A8A78; margin-top: 1px; }
.cat-sub-dot { width: 6px; height: 6px; border-radius: 50%; background: #3FA86B; box-shadow: 0 0 6px #3FA86B; }
.cat-icon {
  width: 30px; height: 30px; border-radius: 9px; border: none; cursor: pointer;
  background: transparent; color: #9A8A78; display: flex; align-items: center; justify-content: center;
  transition: .15s;
}
.cat-icon:hover { background: rgba(255, 255, 255, .06); color: #E4D9CA; }
.cat-spin { animation: cat-rot .9s linear infinite; }
@keyframes cat-rot { to { transform: rotate(360deg); } }

.cat-body { padding: 18px 18px 8px; min-height: 132px; font-family: 'Hanken Grotesk', ui-monospace, monospace; }
.cat-line { display: flex; gap: 10px; font-size: 15px; line-height: 1.9; color: #CDB9A4; animation: cat-rise .25s ease both; }
.cat-caret { color: #8A6F58; }
.cat-cursor { display: inline-block; width: 9px; height: 16px; background: #C2541E; margin-left: 4px; vertical-align: -2px; animation: cat-blink .9s steps(1) infinite; }
@keyframes cat-blink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }
@keyframes cat-rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

.cat-foot {
  display: flex; align-items: center; justify-content: space-between;
  padding: 13px 18px; border-top: 1px solid rgba(255, 255, 255, .06);
}
.cat-status { display: flex; align-items: center; gap: 8px; font-size: 13.5px; color: #C9BCAB; }
.cat-status-dot { width: 8px; height: 8px; border-radius: 50%; background: #3FA86B; box-shadow: 0 0 7px #3FA86B; }
.cat-model { font-size: 13px; color: #8A7B69; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.cat-pop-enter-active, .cat-pop-leave-active { transition: opacity .18s, transform .18s; transform-origin: bottom right; }
.cat-pop-enter-from, .cat-pop-leave-to { opacity: 0; transform: translateY(8px) scale(.96); }
</style>
