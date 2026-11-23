<script setup>
import { computed } from 'vue'

const props = defineProps({
  points: { type: Array, default: () => [] },
  height: { type: Number, default: 240 },
})

const W = 860
const H = computed(() => props.height)
const PAD = { l: 48, r: 14, t: 14, b: 26 }

const series = computed(() => {
  const p = props.points
  if (!p.length) return { loss: [], ema: [], vb: `0 0 ${W} ${H.value}` }
  const ys = []
  for (const d of p) { if (d.loss != null) ys.push(d.loss) }
  const lo = Math.min(...ys), hi = Math.max(...ys)
  const span = Math.max(1e-4, hi - lo)
  const n = p.length
  const x = i => PAD.l + (i / Math.max(1, n - 1)) * (W - PAD.l - PAD.r)
  const y = v => PAD.t + (1 - (v - lo) / span) * (H.value - PAD.t - PAD.b)
  const toPath = key => p.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(d[key]).toFixed(1)}`).join(' ')
  const loss = toPath('loss')
  const ema = p.some(d => d.loss_ema != null) ? toPath('loss_ema') : ''
  const ticks = [0, .25, .5, .75, 1].map(f => ({ y: PAD.t + f * (H.value - PAD.t - PAD.b), v: (lo + (1 - f) * span).toFixed(3) }))
  return { loss, ema, ticks, lo, hi, n }
})

const last = computed(() => props.points[props.points.length - 1] || {})
</script>

<template>
  <div class="chartbox">
    <svg :viewBox="`0 0 ${W} ${H}`" preserveAspectRatio="none">
      <defs>
        <linearGradient id="gfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#7c3aed" stop-opacity=".22" />
          <stop offset="100%" stop-color="#7c3aed" stop-opacity="0" />
        </linearGradient>
      </defs>
      <g v-for="t in series.ticks" :key="t.y">
        <line :x1="PAD.l" :x2="W - PAD.r" :y1="t.y" :y2="t.y" stroke="#eef1f5" stroke-width="1" />
        <text :x="PAD.l - 8" :y="t.y + 3.5" text-anchor="end" font-size="9" fill="#94a3b8">{{ t.v }}</text>
      </g>
      <path v-if="series.loss" :d="series.loss + ` L${W - PAD.r},${H - PAD.b} L${PAD.l},${H - PAD.b} Z`" fill="url(#gfill)" />
      <path v-if="series.loss" :d="series.loss" fill="none" stroke="#7c3aed" stroke-width="1.6" />
      <path v-if="series.ema" :d="series.ema" fill="none" stroke="#f43f5e" stroke-width="1.8" opacity=".9" />
    </svg>
    <div class="legend">
      <span><i class="dot" style="background:#7c3aed"></i>step loss</span>
      <span><i class="dot" style="background:#f43f5e"></i>EMA</span>
      <span class="muted">last: {{ last.loss ?? '—' }} · points {{ series.n }}</span>
    </div>
  </div>
</template>

<style scoped>
.chartbox { padding: 8px 10px 6px; }
svg { width: 100%; height: 240px; display: block; }
.legend { display: flex; gap: 16px; font-size: .78em; color: #475569; padding: 0 4px 4px; align-items: center; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
.legend .muted { margin-left: auto; }
</style>
