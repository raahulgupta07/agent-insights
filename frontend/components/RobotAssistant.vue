<template>
  <ClientOnly>
   <template v-if="visible">
    <!-- LAUNCHER -->
    <div class="ra-launcher">
      <button
        class="ra-bot-btn"
        :class="{ busy: busy }"
        :title="`City Agent · ${stateMeta.label}`"
        aria-label="City Agent assistant"
        @click="onLauncherClick"
      >
        <!-- mini pixel robot reflecting state -->
        <div class="ra-mini">
          <div class="ra-stage-mini" :class="{ 'proc-on': state === 'processing', 'think-on': state === 'thinking' }">
            <div class="ring2"></div><div class="ring"></div>
            <div class="robot" :class="robotClasses">
              <div class="thought"><i></i><i></i><i></i></div>
              <div class="antenna" :class="{ live: stateMeta.ant }"></div>
              <div class="head">
                <div class="ear l"></div><div class="ear r"></div>
                <div class="eyes">
                  <div class="eye" :class="{ glow: state === 'processing' }"><div class="pupil"></div></div>
                  <div class="eye" :class="{ glow: state === 'processing' }"><div class="pupil"></div></div>
                </div>
                <div class="mouth"></div>
              </div>
            </div>
          </div>
        </div>
      </button>
    </div>

    <!-- PANEL -->
    <div class="ra-panel" :class="{ open: open }">
      <!-- header -->
      <div class="ra-header">
        <div class="ra-avatar">
          <svg width="20" height="20" viewBox="0 0 32 32" fill="none">
            <rect x="6" y="8" width="20" height="16" rx="6" fill="#fff" />
            <circle cx="12" cy="16" r="2.3" fill="#C2541E" />
            <circle cx="20" cy="16" r="2.3" fill="#C2541E" />
            <rect x="12.5" y="20" width="7" height="1.6" rx="0.8" fill="#C2541E" />
          </svg>
        </div>
        <div class="ra-head-text">
          <p class="ra-name">City Agent</p>
          <p class="ra-status" :class="statusClass">
            <span class="ra-statusdot" :style="{ background: statusDotColor }"></span>
            <span>{{ stateMeta.sub }}</span>
          </p>
        </div>
        <button class="ra-iconbtn" title="clear" @click="clear">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8M3 4v4h4" />
          </svg>
        </button>
        <button class="ra-iconbtn" title="collapse" @click="closePanel">
          <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
      </div>

      <!-- progress shimmer -->
      <div class="ra-bar" v-show="busy"><div class="ra-bar-fill"></div></div>

      <!-- log stream -->
      <div ref="logEl" class="ra-log">
        <div v-if="!logs.length" class="ra-empty">ready.</div>
        <div v-for="l in logs" :key="l.id" class="ra-line">
          <span class="ra-ts">{{ l.ts }}</span>
          <span class="ra-ico" v-html="iconFor(l)"></span>
          <span :class="lineClass(l)">{{ l.msg }}</span>
        </div>
      </div>

      <!-- footer -->
      <div class="ra-footer">
        <span class="ra-statusdot" :style="{ background: statusDotColor }"></span>
        <span class="ra-foot-label">{{ stateMeta.label }}</span>
      </div>
    </div>
   </template>
  </ClientOnly>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'

const { state, title, logs, open, busy, openPanel, closePanel, clear } = useActivity()

// Scope the robot to a single agent/studio context — only show on a studio,
// agent or report DETAIL page (not the Studios list, home, settings, etc.).
const route = useRoute()
const agentKey = computed(() => {
  const m = route.path.match(/^\/(studios|agents)\/([^/]+)/)
  // exclude list/new routes like /agents/new or /reports/new
  if (!m || m[2] === 'new') return ''
  return `${m[1]}:${m[2]}`
})
const visible = computed(() => agentKey.value !== '')
// Activity is per-agent: when the agent/studio/report changes, wipe the log so
// one studio's run never bleeds into another's panel.
watch(agentKey, () => { clear(); closePanel() })

const logEl = ref<HTMLElement | null>(null)

const STATE_META: Record<string, { label: string; sub: string; ant: boolean }> = {
  idle: { label: 'Idle', sub: 'City Agent · waiting for work', ant: true },
  thinking: { label: 'Thinking…', sub: 'planning the next step', ant: true },
  processing: { label: 'Processing', sub: 'working — merging · training · scanning', ant: true },
  success: { label: 'Done', sub: 'ready to answer', ant: false },
  error: { label: 'Problem', sub: 'a step failed — check logs', ant: false },
}

const stateMeta = computed(() => STATE_META[state.value] || STATE_META.idle)

// robot animation classes (port of mockup setState() class application)
const robotClasses = computed(() => {
  switch (state.value) {
    case 'thinking':
      return ['bob', 'think']
    case 'processing':
      return ['walk', 'proc']
    case 'success':
      return ['bob', 'happy']
    case 'error':
      return ['shake', 'err']
    default:
      return ['bob', 'blink']
  }
})

const statusDotColor = computed(() =>
  state.value === 'error' ? '#7a1f1f' : state.value === 'success' ? '#2f7d34' : '#C2541E'
)
const statusClass = computed(() => (state.value === 'error' ? 'err' : state.value === 'success' ? 'ok' : 'run'))

function onLauncherClick() {
  open.value ? closePanel() : openPanel()
}

const ICON = {
  spin: '<svg class="ra-ico-svg spin run" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.2-8.5" stroke-linecap="round"/></svg>',
  ok: '<svg class="ra-ico-svg ok" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3"><path d="m5 12 5 5L20 6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  err: '<svg class="ra-ico-svg err" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3"><path d="M18 6 6 18M6 6l12 12" stroke-linecap="round"/></svg>',
  warn: '<svg class="ra-ico-svg warn" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  dot: '<svg class="ra-ico-svg dim" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="3"/></svg>',
}

function iconFor(l: { level: string }): string {
  if (l.level === 'ok') return ICON.ok
  if (l.level === 'err') return ICON.err
  if (l.level === 'warn') return ICON.warn
  // the most-recent info line spins while busy, otherwise a calm dot
  const isLast = logs.value.length && logs.value[logs.value.length - 1].id === (l as any).id
  if (isLast && busy.value) return ICON.spin
  return ICON.dot
}

function lineClass(l: { level: string }): string {
  if (l.level === 'ok') return 'ok'
  if (l.level === 'err') return 'err'
  if (l.level === 'warn') return 'warn'
  return 'dim'
}

async function scrollToBottom() {
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}

// autoscroll on new logs
watch(() => logs.value.length, () => scrollToBottom())

// auto-open when work surfaces that the user should see
watch(state, (s) => {
  if (s === 'processing' || s === 'error') openPanel()
  if (open.value) scrollToBottom()
})
</script>

<style scoped>
/* ===== LAUNCHER (port of mockup-robot-logs.html) ===== */
.ra-launcher {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 60;
}
.ra-bot-btn {
  position: relative;
  width: 56px;
  height: 56px;
  /* no disc — just the pixel robot floating, soft shadow for depth */
  border-radius: 0;
  background: transparent;
  box-shadow: none;
  filter: drop-shadow(0 6px 12px rgba(168, 84, 47, 0.28));
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: transform 0.2s;
  border: none;
  padding: 0;
}
.ra-bot-btn:hover {
  transform: translateY(-2px);
}
.ra-bot-btn.busy::after {
  content: '';
  position: absolute;
  inset: 0;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 2px solid #c2683f;
  animation: ra-ring 1.4s ease-out infinite;
}
@keyframes ra-ring {
  0% {
    transform: scale(1);
    opacity: 0.6;
  }
  100% {
    transform: scale(1.6);
    opacity: 0;
  }
}
.ra-mini {
  transform: scale(0.2);
  transform-origin: center;
  pointer-events: none;
}
.ra-stage-mini {
  position: relative;
  width: 160px;
  height: 110px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ===== ROBOT (pixel Claude-Code style — ported from mockup-robot-claude.html) ===== */
.robot {
  position: relative;
  transition: transform 0.3s;
}
.robot.bob {
  animation: ra-bob 2.6s ease-in-out infinite;
}
@keyframes ra-bob {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-7px);
  }
}
.robot.shake {
  animation: ra-shake 0.4s linear infinite;
}
@keyframes ra-shake {
  0%,
  100% {
    transform: translateX(0);
  }
  25% {
    transform: translateX(-3px);
  }
  75% {
    transform: translateX(3px);
  }
}

/* antenna */
.antenna {
  position: absolute;
  left: 50%;
  top: -16px;
  transform: translateX(-50%);
  width: 5px;
  height: 14px;
  background: #a8542f;
  border-radius: 3px;
}
.antenna::before {
  content: '';
  position: absolute;
  left: 50%;
  top: -8px;
  transform: translateX(-50%);
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: #c2683f;
}
.antenna.live::before {
  animation: ra-beac 1s infinite;
}
@keyframes ra-beac {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(194, 104, 63, 0.6);
    background: #c2683f;
  }
  50% {
    box-shadow: 0 0 0 8px rgba(194, 104, 63, 0);
    background: #e89b6e;
  }
}

/* head */
.head {
  width: 150px;
  height: 96px;
  background: linear-gradient(160deg, #c2683f, #b05d38);
  border-radius: 30px;
  position: relative;
  box-shadow: inset 0 -6px 0 rgba(0, 0, 0, 0.08), 0 10px 24px rgba(168, 84, 47, 0.28);
}
/* ears */
.ear {
  position: absolute;
  top: 34px;
  width: 12px;
  height: 26px;
  background: #a8542f;
  border-radius: 4px;
}
.ear.l {
  left: -10px;
}
.ear.r {
  right: -10px;
}

/* eyes */
.eyes {
  position: absolute;
  top: 34px;
  left: 0;
  right: 0;
  display: flex;
  justify-content: center;
  gap: 30px;
}
.eye {
  width: 22px;
  height: 22px;
  background: #1f2328;
  border-radius: 5px;
  position: relative;
  transition: all 0.2s;
  overflow: hidden;
}
.eye .pupil {
  position: absolute;
  inset: 0;
  background: #1f2328;
  border-radius: 5px;
  transition: transform 0.25s;
}
.eye.glow {
  background: #231a16;
  box-shadow: 0 0 10px rgba(232, 155, 110, 0.9) inset;
}
.eye.glow .pupil {
  background: radial-gradient(circle at 50% 40%, #e89b6e, #1f2328 70%);
}
/* blink */
.robot.blink .eye {
  animation: ra-blink 4s infinite;
}
@keyframes ra-blink {
  0%,
  94%,
  100% {
    height: 22px;
    margin-top: 0;
  }
  97% {
    height: 3px;
    margin-top: 9px;
  }
}
/* thinking: eyes scan left-right */
.robot.think .pupil {
  animation: ra-scan 1.3s ease-in-out infinite;
}
@keyframes ra-scan {
  0%,
  100% {
    transform: translateX(-5px);
  }
  50% {
    transform: translateX(5px);
  }
}
/* happy ^ ^ */
.robot.happy .eye {
  height: 11px;
  border-radius: 11px 11px 3px 3px;
  margin-top: 6px;
}
/* error x x */
.robot.err .eye {
  background: transparent;
  box-shadow: none;
}
.robot.err .eye::before,
.robot.err .eye::after {
  content: '';
  position: absolute;
  top: 9px;
  left: 0;
  width: 22px;
  height: 3px;
  background: #7a1f1f;
  border-radius: 2px;
}
.robot.err .eye::before {
  transform: rotate(45deg);
}
.robot.err .eye::after {
  transform: rotate(-45deg);
}

/* mouth */
.mouth {
  position: absolute;
  bottom: 18px;
  left: 50%;
  transform: translateX(-50%);
  width: 40px;
  height: 6px;
  background: #1f2328;
  border-radius: 4px;
  transition: all 0.2s;
}
.robot.think .mouth {
  width: 18px;
}
.robot.happy .mouth {
  height: 14px;
  border-radius: 0 0 16px 16px;
}
.robot.proc .mouth {
  animation: ra-talk 0.35s steps(2) infinite;
}
@keyframes ra-talk {
  0% {
    width: 40px;
  }
  50% {
    width: 18px;
    height: 10px;
  }
  100% {
    width: 40px;
  }
}

/* energy rings (processing) */
.ring {
  position: absolute;
  width: 150px;
  height: 150px;
  border-radius: 50%;
  border: 2px dashed #c2683f;
  opacity: 0;
  pointer-events: none;
}
.proc-on .ring {
  opacity: 0.5;
  animation: ra-spin 3s linear infinite;
}
@keyframes ra-spin {
  to {
    transform: rotate(360deg);
  }
}
.ring2 {
  position: absolute;
  width: 175px;
  height: 175px;
  border-radius: 50%;
  border: 2px solid rgba(194, 104, 63, 0.25);
  opacity: 0;
  pointer-events: none;
}
.proc-on .ring2 {
  opacity: 1;
  animation: ra-pulse 1.6s ease-out infinite;
}
@keyframes ra-pulse {
  0% {
    transform: scale(0.85);
    opacity: 0.5;
  }
  100% {
    transform: scale(1.15);
    opacity: 0;
  }
}

/* thought bubble dots */
.thought {
  position: absolute;
  top: -34px;
  right: 30px;
  display: flex;
  gap: 5px;
  opacity: 0;
  transition: opacity 0.2s;
}
.think-on .thought {
  opacity: 1;
}
.thought i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c2683f;
  display: block;
  animation: ra-td 1.2s infinite;
}
.thought i:nth-child(2) {
  animation-delay: 0.2s;
}
.thought i:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes ra-td {
  0%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  50% {
    transform: translateY(-5px);
    opacity: 1;
  }
}

/* ===== PANEL (port of mockup-robot-logs.html) ===== */
.ra-panel {
  position: fixed;
  right: 24px;
  bottom: 92px;
  width: 380px;
  max-height: 72vh;
  background: #fff;
  border: 1px solid #e7e5dd;
  border-radius: 18px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.18);
  z-index: 60;
  display: none;
  flex-direction: column;
  overflow: hidden;
  font-family: Inter, system-ui, sans-serif;
  color: #1f2328;
}
.ra-panel.open {
  display: flex;
  animation: ra-rise 0.25s ease;
}
@keyframes ra-rise {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.ra-header {
  padding: 12px 14px;
  border-bottom: 1px solid #e7e5dd;
  display: flex;
  align-items: center;
  gap: 10px;
}
.ra-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #c2683f;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.ra-head-text {
  flex: 1;
  min-width: 0;
}
.ra-name {
  font-weight: 600;
  font-size: 14px;
  line-height: 1.2;
  margin: 0;
}
.ra-status {
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 2px 0 0;
}
.ra-statusdot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.ra-iconbtn {
  color: #9a958c;
  cursor: pointer;
  background: none;
  border: none;
  padding: 2px;
  display: flex;
}
.ra-iconbtn:hover {
  color: #1f2328;
}

.ra-bar {
  height: 3px;
  background: #efe9e1;
  overflow: hidden;
}
.ra-bar-fill {
  height: 100%;
  width: 40%;
  background: #c2683f;
  border-radius: 2px;
  animation: ra-shimmer 1.4s ease-in-out infinite;
}
@keyframes ra-shimmer {
  0% {
    margin-left: -40%;
  }
  100% {
    margin-left: 100%;
  }
}

.ra-log {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  font-size: 13px;
  min-height: 90px;
}
.ra-empty {
  color: #9a958c;
  font-size: 12px;
}
.ra-line {
  display: flex;
  gap: 9px;
  padding: 5px 0;
  align-items: flex-start;
  animation: ra-fade 0.25s ease;
}
@keyframes ra-fade {
  from {
    opacity: 0;
    transform: translateX(-4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
.ra-ts {
  color: #bcb4a8;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
  width: 48px;
  margin-top: 1px;
}
.ra-ico {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  margin-top: 1px;
  display: inline-flex;
}
:deep(.ra-ico-svg) {
  width: 16px;
  height: 16px;
}
:deep(.spin) {
  animation: ra-sp 1s linear infinite;
}
@keyframes ra-sp {
  to {
    transform: rotate(360deg);
  }
}
.dim,
:deep(.dim) {
  color: #6b6b6b;
}
.ok,
:deep(.ok) {
  color: #2f7d34;
}
.run,
:deep(.run) {
  color: #c2683f;
}
.warn,
:deep(.warn) {
  color: #b45309;
}
.err,
:deep(.err) {
  color: #7a1f1f;
}

.ra-footer {
  padding: 8px 14px;
  border-top: 1px solid #e7e5dd;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #6b6b6b;
}
.ra-foot-label {
  font-weight: 600;
}

.ra-log::-webkit-scrollbar {
  width: 7px;
}
.ra-log::-webkit-scrollbar-thumb {
  background: #dcd9cf;
  border-radius: 8px;
}
</style>
