<template>
  <!-- v3 enriched pipeline. Self-contained: paints the whole dark panel (the
       parent .cai-right has no padding). "How City Agent turns a question into an
       answer" — 5-step sweep + live mini-widgets, rotating platform messages,
       floating question, feature marquee, canvas data-spine. -->
  <div class="aus-panel" ref="wrap">
    <canvas ref="cv" class="aus-cv"></canvas>

    <div class="aus">
      <div class="aus-head">
        <span class="aus-live"><i></i>live</span>
        <span class="aus-title">How City Agent turns a question into an answer</span>
      </div>

      <div class="aus-msg">
        <transition name="aus-msgfade" mode="out-in"><span :key="msgIdx" class="aus-msg-t">{{ messages[msgIdx] }}</span></transition>
      </div>
      <div class="aus-ask">
        <transition name="aus-msgfade" mode="out-in"><span :key="active" class="aus-ask-t">“{{ questions[active] }}”</span></transition>
      </div>

      <div class="aus-steps">
        <div v-for="(s, i) in steps" :key="i" class="aus-step" :class="{ on: active === i }">
          <div class="aus-num">{{ i + 1 }}</div>
          <div class="aus-body">
            <div class="aus-r">
              <span class="aus-name">{{ s.name }}</span>
              <span class="aus-metric" :style="{ color: s.color }">{{ i === 4 ? counter.toLocaleString() : s.metric }}</span>
            </div>
            <div class="aus-desc">{{ s.desc }}</div>

            <div v-if="active === i" class="aus-mini">
              <div v-if="i === 0" class="aus-chips">
                <span v-for="(c, ci) in connectors" :key="c.name" class="aus-chip" :style="chipStyle(c, ci)">{{ c.name }}</span>
              </div>
              <div v-else-if="i === 1" class="aus-schema">
                <span v-for="n in 5" :key="n" class="aus-col" :style="{ animationDelay: (n * 0.09) + 's', width: (36 + (n * 11) % 40) + '%' }"></span>
              </div>
              <div v-else-if="i === 2" class="aus-sql"><span class="aus-kw">SELECT</span> region, <span class="aus-fn">SUM</span>(revenue)<br><span class="aus-kw">FROM</span> sales <span class="aus-kw">GROUP BY</span> region<span class="aus-caret"></span></div>
              <div v-else-if="i === 3" class="aus-bars"><span v-for="(b, bi) in bars" :key="bi" class="aus-bar" :style="{ height: b + '%', animationDelay: (bi * 0.05) + 's' }"></span></div>
              <div v-else class="aus-answer">
                <span class="aus-big">{{ counter.toLocaleString() }}</span><span class="aus-up">▲ 12%</span><span class="aus-dec">DECISION · act</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="aus-marq">
        <div class="aus-marq-track"><span v-for="(f, fi) in featuresLoop" :key="fi" class="aus-feat"><i :style="{ background: f.c }"></i>{{ f.t }}</span></div>
      </div>

      <div class="aus-foot">
        <span><b>677</b> routes</span><span><b>46</b> connectors</span>
        <span class="aus-sso"><i></i><b>SSO</b> ready</span>
      </div>
    </div>
  </div>
</template>

<script lang="ts" setup>
const steps = [
  { name: 'Connect', desc: 'Power BI · Fabric · files — one sign-in.', color: '#F2C811', metric: '4 sources' },
  { name: 'Understand', desc: 'Reads your schema, learns from real data.', color: '#33C6D6', metric: '11 tables' },
  { name: 'Query', desc: 'Writes the source query — every time.', color: '#7FD08B', metric: 'read-only' },
  { name: 'Visualize', desc: 'Builds charts, dashboards, decks.', color: '#E0A44B', metric: '6 charts' },
  { name: 'Answer', desc: 'Decision + delivered to your team.', color: '#D67037', metric: '7,526' },
]
const connectors = [{ name: 'Power BI', color: '#F2C811' }, { name: 'Fabric', color: '#33C6D6' }, { name: 'Files', color: '#7FD08B' }, { name: 'SQL', color: '#E0A44B' }]
const questions = [
  'Connect my Power BI and Fabric in one sign-in',
  'What tables do we have and how do they join?',
  'Which regions grew fastest last quarter?',
  'Show revenue by region as a chart',
  'What should we do about the West region?',
]
const messages = [
  'One Microsoft sign-in → Power BI + Fabric agents.',
  'Answered with the source query — every time.',
  'Governed KPIs that match your reports, exactly.',
  'Ask in plain English. Get the real number.',
  'Dashboards, slide decks & Excel — built for you.',
  'Learns from your data, remembers what matters.',
  'Scheduled reports, emailed to your team.',
  'Read-only by design — your data stays safe.',
  'SSO, LDAP & Microsoft — enterprise ready.',
]
const features = [
  { t: 'Semantic layer', c: '#F2C811' }, { t: 'Read-only guard', c: '#7FD08B' },
  { t: 'SSO / LDAP', c: '#33C6D6' }, { t: 'Scheduled email', c: '#E0A44B' },
  { t: 'Mixture-of-Agents', c: '#D67037' }, { t: 'Shared memory', c: '#C98BE0' },
  { t: 'Forecasting', c: '#7FD08B' }, { t: 'Golden queries', c: '#F2C811' },
  { t: 'Power BI', c: '#F2C811' }, { t: 'Microsoft Fabric', c: '#33C6D6' },
  { t: 'Workflows', c: '#E0A44B' }, { t: 'Auto model routing', c: '#D67037' },
]
const featuresLoop = [...features, ...features]

const active = ref(0)
const counter = ref(0)
const bars = ref<number[]>([40, 65, 30, 82, 55, 70])
const msgIdx = ref(0)
let tick = 0, stepTimer: any = null, msgTimer: any = null

function chipStyle(c: any, ci: number) {
  const lit = (tick % connectors.length) >= ci
  return { color: lit ? '#1A1611' : '#9A8678', background: lit ? c.color : 'rgba(255,255,255,.05)', borderColor: lit ? c.color : 'rgba(255,255,255,.1)' }
}
function sweep() {
  active.value = (active.value + 1) % steps.length; tick++
  if (active.value === 4) { const target = 7526; counter.value = 0; const c = setInterval(() => { counter.value = Math.min(target, counter.value + 470); if (counter.value >= target) clearInterval(c) }, 40) }
  if (active.value === 3) bars.value = bars.value.map(() => 25 + Math.round(Math.random() * 70))
  stepTimer = setTimeout(sweep, active.value === 4 ? 1700 : 1150)
}
function cycleMsg() { msgIdx.value = (msgIdx.value + 1) % messages.length; msgTimer = setTimeout(cycleMsg, 2600) }

// canvas: data-spine + packets + ambient dust
const wrap = ref<HTMLElement | null>(null)
const cv = ref<HTMLCanvasElement | null>(null)
let raf = 0, stopped = false, W = 0, H = 0, DPR = 1
let packets: any[] = [], dust: any[] = []
const ACC = '#D67037'
function size() {
  const el = wrap.value, c = cv.value; if (!el || !c) return
  const r = el.getBoundingClientRect(); W = r.width; H = r.height
  DPR = Math.min(2, window.devicePixelRatio || 1); c.width = W * DPR; c.height = H * DPR
  const ctx = c.getContext('2d'); if (ctx) ctx.setTransform(DPR, 0, 0, DPR, 0, 0)
  packets = Array.from({ length: 40 }, (_, i) => ({ p: Math.random(), sp: 0.004 + Math.random() * 0.008, r: 1.2 + Math.random() * 1.8, c: ['#F2C811', '#33C6D6', '#7FD08B', '#E0A44B', ACC, '#C98BE0'][i % 6] }))
  dust = Array.from({ length: 64 }, () => ({ x: Math.random() * W, y: Math.random() * H, vx: (Math.random() - .5) * .14, vy: (Math.random() - .5) * .14, r: Math.random() * 1.3 + .3, a: Math.random() * .4 + .1 }))
}
function frame() {
  const c = cv.value; if (!c) return
  const ctx = c.getContext('2d'); if (!ctx) return
  ctx.clearRect(0, 0, W, H); const gx = 30
  ctx.strokeStyle = 'rgba(214,112,55,.22)'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(gx, 8); ctx.lineTo(gx, H - 8); ctx.stroke()
  for (let i = 0; i < 5; i++) { const y = 40 + i * ((H - 90) / 4), on = active.value === i; ctx.beginPath(); ctx.arc(gx, y, on ? 6 : 3.2, 0, 7); ctx.fillStyle = on ? ACC : 'rgba(214,112,55,.4)'; ctx.fill(); if (on) { ctx.beginPath(); ctx.arc(gx, y, 11, 0, 7); ctx.strokeStyle = 'rgba(214,112,55,.35)'; ctx.lineWidth = 1.4; ctx.stroke() } }
  packets.forEach(pk => { pk.p += pk.sp; if (pk.p > 1) pk.p -= 1; const y = 12 + pk.p * (H - 24); ctx.beginPath(); ctx.arc(gx, y, pk.r, 0, 7); ctx.fillStyle = pk.c; ctx.globalAlpha = .9; ctx.fill(); ctx.globalAlpha = 1; ctx.beginPath(); ctx.moveTo(gx, y); ctx.lineTo(gx, y - 10); ctx.strokeStyle = pk.c; ctx.globalAlpha = .18; ctx.lineWidth = pk.r; ctx.stroke(); ctx.globalAlpha = 1 })
  dust.forEach(d => { d.x += d.vx; d.y += d.vy; if (d.x < 0) d.x = W; if (d.x > W) d.x = 0; if (d.y < 0) d.y = H; if (d.y > H) d.y = 0; ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, 7); ctx.fillStyle = 'rgba(230,200,160,' + d.a + ')'; ctx.fill() })
  if (!stopped) raf = requestAnimationFrame(frame)
}
const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion:reduce)').matches
onMounted(() => {
  size(); window.addEventListener('resize', size)
  sweep(); msgTimer = setTimeout(cycleMsg, 2600)
  if (!reduced) raf = requestAnimationFrame(frame)
})
onBeforeUnmount(() => { stopped = true; cancelAnimationFrame(raf); clearTimeout(stepTimer); clearTimeout(msgTimer); window.removeEventListener('resize', size) })
</script>

<style scoped>
.aus-panel { position: absolute; inset: 0; border-radius: 24px; overflow: hidden; padding: 24px; display: flex; flex-direction: column;
  background: radial-gradient(120% 90% at 70% 0%, #2A1F18 0%, #17120E 55%, #100C09 100%); }
.aus-cv { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
.aus { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; }

.aus-head { position: relative; display: flex; align-items: center; gap: 10px; padding: 2px 4px 12px 40px; }
.aus-live { display: inline-flex; align-items: center; gap: 6px; font-size: 10.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: #E2B07A; }
.aus-live i { width: 7px; height: 7px; border-radius: 50%; background: #D67037; box-shadow: 0 0 10px 2px rgba(214,112,55,.7); animation: aus-pulse 1.6s ease-in-out infinite; }
.aus-title { font-family: 'Spectral', ui-serif, Georgia, serif; font-size: 14.5px; color: #E8DDD2; line-height: 1.2; }

.aus-msg { position: relative; min-height: 40px; margin: 0 4px 4px 40px; display: flex; align-items: center; padding: 8px 14px; border-radius: 12px; background: linear-gradient(90deg, rgba(214,112,55,.16), rgba(214,112,55,.04)); border: 1px solid rgba(214,112,55,.24); }
.aus-msg-t { font-family: 'Spectral', ui-serif, Georgia, serif; font-size: 15.5px; font-weight: 500; color: #F3E7DA; line-height: 1.25; }
.aus-ask { position: relative; margin: 0 4px 8px 40px; }
.aus-ask-t { display: inline-block; font-size: 12px; color: #BBAB9B; font-style: italic; }
.aus-msgfade-enter-active, .aus-msgfade-leave-active { transition: opacity .3s, transform .3s; }
.aus-msgfade-enter-from { opacity: 0; transform: translateY(6px); }
.aus-msgfade-leave-to { opacity: 0; transform: translateY(-6px); }

.aus-steps { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; justify-content: center; gap: 5px; padding-left: 40px; }
.aus-step { display: flex; gap: 12px; padding: 9px 12px 9px 10px; border-radius: 13px; border: 1px solid transparent; transition: background .3s, border-color .3s, transform .3s; }
.aus-step.on { background: rgba(255,255,255,.045); border-color: rgba(214,112,55,.3); transform: translateX(2px); }
.aus-num { flex: none; width: 22px; height: 22px; border-radius: 7px; display: grid; place-items: center; font-size: 12px; font-weight: 700; color: #9A8678; background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.08); transition: .3s; }
.aus-step.on .aus-num { color: #1A1611; background: #D67037; border-color: #D67037; }
.aus-body { flex: 1; min-width: 0; }
.aus-r { display: flex; align-items: baseline; gap: 8px; }
.aus-name { font-size: 14px; font-weight: 600; color: #F1E6DB; }
.aus-metric { margin-left: auto; font-size: 11px; font-weight: 600; font-family: ui-monospace, Menlo, monospace; }
.aus-desc { font-size: 12px; color: #9A8678; margin-top: 1px; }
.aus-mini { margin-top: 9px; animation: aus-in .3s ease both; }
.aus-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.aus-chip { font-size: 11px; font-weight: 600; padding: 3px 9px; border-radius: 7px; border: 1px solid; transition: .25s; }
.aus-schema { display: flex; flex-direction: column; gap: 4px; }
.aus-col { height: 5px; border-radius: 3px; background: linear-gradient(90deg, rgba(51,198,214,.7), rgba(51,198,214,.15)); animation: aus-scan .8s ease both; }
.aus-sql { font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; line-height: 1.55; color: #D8C7B4; background: rgba(0,0,0,.25); border: 1px solid rgba(255,255,255,.07); border-radius: 9px; padding: 8px 11px; }
.aus-kw { color: #E0A44B; font-weight: 700; } .aus-fn { color: #7FD08B; }
.aus-caret { display: inline-block; width: 6px; height: 13px; background: #D67037; margin-left: 2px; vertical-align: -2px; animation: aus-blink .9s steps(1) infinite; }
.aus-bars { display: flex; align-items: flex-end; gap: 5px; height: 46px; }
.aus-bar { flex: 1; min-width: 0; border-radius: 4px 4px 1px 1px; background: linear-gradient(180deg, #D67037, #B8431A); animation: aus-grow .5s cubic-bezier(.2,.8,.2,1) both; }
.aus-answer { display: flex; align-items: baseline; gap: 10px; }
.aus-big { font-family: 'Spectral', serif; font-size: 26px; font-weight: 700; color: #fff; font-variant-numeric: tabular-nums; }
.aus-up { font-size: 12px; font-weight: 700; color: #7FD08B; }
.aus-dec { margin-left: auto; font-size: 10px; font-weight: 700; letter-spacing: .05em; color: #E2B07A; background: rgba(214,112,55,.14); border: 1px solid rgba(214,112,55,.3); padding: 3px 8px; border-radius: 6px; }

.aus-marq { position: relative; overflow: hidden; margin: 6px 0 2px; mask-image: linear-gradient(90deg, transparent, #000 8%, #000 92%, transparent); }
.aus-marq-track { display: inline-flex; gap: 8px; white-space: nowrap; padding-left: 40px; animation: aus-marq 22s linear infinite; }
.aus-feat { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; font-weight: 600; color: #CDBFAF; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); padding: 5px 11px; border-radius: 999px; }
.aus-feat i { width: 6px; height: 6px; border-radius: 50%; flex: none; }

.aus-foot { position: relative; display: flex; align-items: center; gap: 18px; padding: 12px 4px 2px 40px; border-top: 1px solid rgba(255,255,255,.07); margin-top: 6px; font-size: 12.5px; color: #9A8678; }
.aus-foot b { color: #D9CABB; }
.aus-sso { margin-left: auto; display: inline-flex; align-items: center; gap: 7px; }
.aus-sso i { width: 6px; height: 6px; border-radius: 50%; background: #3FA86B; }

@keyframes aus-pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }
@keyframes aus-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }
@keyframes aus-scan { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: none; } }
@keyframes aus-grow { from { height: 0; } }
@keyframes aus-blink { 0%,49% { opacity: 1; } 50%,100% { opacity: 0; } }
@keyframes aus-marq { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@media (prefers-reduced-motion: reduce) { .aus-cv { display: none; } .aus-caret, .aus-live i, .aus-marq-track { animation: none; } }
</style>
