// /composables/useActivity.ts
// Global singleton activity store for the floating Robot Assistant.
// Dependency-free, SSR-safe, shared across the whole app via useState
// (same idiom as useOrganization / useUsageQuota).

export type ActivityState = 'idle' | 'thinking' | 'processing' | 'success' | 'error'
export type ActivityLevel = 'info' | 'ok' | 'warn' | 'err'

export interface ActivityLog {
  id: number
  ts: string // HH:MM:SS (client) or '' on server
  msg: string
  level: ActivityLevel
}

const MAX_LOGS = 50
const SUCCESS_REVERT_MS = 4000

// module-scoped, survives across composable calls in the same process
let _seq = 0
let _revertTimer: ReturnType<typeof setTimeout> | null = null

function nextId(): number {
  _seq += 1
  return _seq
}

function nowTs(): string {
  // SSR-safe: never touch Date on the server (avoids hydration drift)
  if (!process.client) return ''
  try {
    return new Date().toTimeString().slice(0, 8)
  } catch {
    return ''
  }
}

export const useActivity = () => {
  const state = useState<ActivityState>('cityagent-activity', () => 'idle')
  const title = useState<string>('cityagent-activity:title', () => '')
  const logs = useState<ActivityLog[]>('cityagent-activity:logs', () => [])
  const open = useState<boolean>('cityagent-activity:open', () => false)

  const busy = computed(() => state.value === 'thinking' || state.value === 'processing')

  function _push(msg: string, level: ActivityLevel) {
    logs.value = [...logs.value, { id: nextId(), ts: nowTs(), msg, level }].slice(-MAX_LOGS)
  }

  function _clearRevert() {
    if (_revertTimer) {
      clearTimeout(_revertTimer)
      _revertTimer = null
    }
  }

  function start(t: string) {
    _clearRevert()
    title.value = t || ''
    state.value = 'thinking'
    // title divider line
    if (t) _push(t, 'info')
  }

  function setState(s: ActivityState) {
    _clearRevert()
    state.value = s
  }

  function log(msg: string, level: ActivityLevel = 'info') {
    _push(msg, level)
  }

  function done(msg?: string) {
    _clearRevert()
    if (msg) _push(msg, 'ok')
    state.value = 'success'
    if (process.client) {
      _revertTimer = setTimeout(() => {
        // only revert if nothing new took over
        if (state.value === 'success') state.value = 'idle'
        _revertTimer = null
      }, SUCCESS_REVERT_MS)
    }
  }

  function fail(msg: string) {
    _clearRevert()
    if (msg) _push(msg, 'err')
    state.value = 'error'
  }

  function toggle() {
    open.value = !open.value
  }
  function openPanel() {
    open.value = true
  }
  function closePanel() {
    open.value = false
  }

  function clear() {
    _clearRevert()
    logs.value = []
    title.value = ''
    state.value = 'idle'
  }

  return {
    // reactive refs
    state,
    title,
    logs,
    open,
    busy,
    // methods
    start,
    setState,
    log,
    done,
    fail,
    toggle,
    openPanel,
    closePanel,
    clear,
  }
}
