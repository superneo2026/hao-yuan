<script setup>
import { computed, onMounted } from 'vue'
import { loadUsage, state, toast } from '../stores/app'
import { t } from '../i18n'
import Icon from '../components/Icon.vue'

const daily = computed(() => state.usageDaily || [])
const today = computed(() => state.usageToday || { prompt_tokens: 0, completion_tokens: 0, cost_est: 0, models: [] })
const maxTokens = computed(() => Math.max(1, ...daily.value.map((row) => Number(row.prompt_tokens || 0) + Number(row.completion_tokens || 0))))
const totalPrompt = computed(() => daily.value.reduce((sum, row) => sum + Number(row.prompt_tokens || 0), 0))
const totalCompletion = computed(() => daily.value.reduce((sum, row) => sum + Number(row.completion_tokens || 0), 0))
const totalCost = computed(() => daily.value.reduce((sum, row) => sum + Number(row.cost_est || 0), 0))

function barHeight(row) {
  const value = Number(row.prompt_tokens || 0) + Number(row.completion_tokens || 0)
  return `${Math.max(2, (value / maxTokens.value) * 100)}%`
}
function shortDay(day) {
  return String(day || '').slice(5)
}
function fmt(value) {
  return Number(value || 0).toLocaleString()
}

onMounted(async () => {
  try {
    await loadUsage()
  } catch (error) {
    toast(error.message, 'bad')
  }
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <div class="page-kicker">{{ t('usage.kicker') }}</div>
        <h1>{{ t('usage.title') }}</h1>
        <p>{{ t('usage.subtitle') }}</p>
      </div>
      <a class="btn" href="/api/usage/export.csv"><Icon name="download" :size="14" /> {{ t('usage.export') }}</a>
    </header>

    <div class="stat-grid">
      <div class="stat-card"><span class="stat-icon"><Icon name="zap" :size="18" /></span><div><b>{{ fmt(Number(today.prompt_tokens || 0) + Number(today.completion_tokens || 0)) }}</b><span>{{ t('usage.tokensToday') }}</span></div></div>
      <div class="stat-card"><span class="stat-icon" style="color: var(--brand-2)"><Icon name="arrow-right" :size="18" /></span><div><b>{{ fmt(today.prompt_tokens) }}</b><span>{{ t('usage.promptToday') }}</span></div></div>
      <div class="stat-card"><span class="stat-icon" style="color: var(--good)"><Icon name="sparkles" :size="18" /></span><div><b>{{ fmt(today.completion_tokens) }}</b><span>{{ t('usage.completionToday') }}</span></div></div>
      <div class="stat-card"><span class="stat-icon" style="color: var(--warn)"><Icon name="chart" :size="18" /></span><div><b>¥{{ Number(today.cost_est || 0).toFixed(4) }}</b><span>{{ t('usage.estimatedToday') }}</span></div></div>
    </div>

    <div class="usage-grid">
      <section class="usage-card">
        <div class="usage-head">
          <div><b>{{ t('usage.dailyVolume') }}</b><span>{{ t('usage.dailyVolumeDesc') }}</span></div>
          <span class="badge">{{ t('usage.days', { n: daily.length }) }}</span>
        </div>
        <div class="chart">
          <div v-for="row in daily" :key="row.day" class="chart-col" :title="`${row.day}: ${fmt(Number(row.prompt_tokens || 0) + Number(row.completion_tokens || 0))} tokens`">
            <div class="chart-bar" :style="{ height: barHeight(row) }">
              <span class="chart-tip">{{ fmt(Number(row.prompt_tokens || 0) + Number(row.completion_tokens || 0)) }}</span>
            </div>
            <span class="chart-label">{{ shortDay(row.day) }}</span>
          </div>
          <div v-if="!daily.length" class="chart-empty">{{ t('usage.noUsage') }}</div>
        </div>
      </section>

      <section class="usage-card">
        <div class="usage-head">
          <div><b>{{ t('usage.composition') }}</b><span>{{ t('usage.last14') }}</span></div>
        </div>
        <div class="composition">
          <div class="comp-bar">
            <span class="comp-prompt" :style="{ width: `${totalPrompt + totalCompletion ? (totalPrompt / (totalPrompt + totalCompletion)) * 100 : 50}%` }" />
            <span class="comp-completion" :style="{ width: `${totalPrompt + totalCompletion ? (totalCompletion / (totalPrompt + totalCompletion)) * 100 : 50}%` }" />
          </div>
          <div class="comp-row"><span class="dot prompt" /> {{ t('usage.prompt') }} <b>{{ fmt(totalPrompt) }}</b></div>
          <div class="comp-row"><span class="dot completion" /> {{ t('usage.completion') }} <b>{{ fmt(totalCompletion) }}</b></div>
          <div class="comp-row"><span class="dot cost" /> {{ t('usage.estimatedCost') }} <b>¥{{ totalCost.toFixed(4) }}</b></div>
        </div>
      </section>

      <section class="usage-card wide">
        <div class="usage-head">
          <div><b>{{ t('usage.byModel') }}</b><span>{{ t('usage.allTime') }}</span></div>
        </div>
        <div class="table-wrap">
          <table class="tw">
            <thead><tr><th>{{ t('usage.provider') }}</th><th>{{ t('usage.model') }}</th><th>{{ t('usage.prompt') }}</th><th>{{ t('usage.completion') }}</th><th>{{ t('usage.cost') }}</th></tr></thead>
            <tbody>
              <tr v-for="row in state.usageByModel" :key="`${row.provider}-${row.model}`">
                <td>{{ row.provider }}</td>
                <td class="mono" style="font-size: 11px">{{ row.model }}</td>
                <td>{{ fmt(row.prompt_tokens) }}</td>
                <td>{{ fmt(row.completion_tokens) }}</td>
                <td>¥{{ Number(row.cost_est || 0).toFixed(4) }}</td>
              </tr>
              <tr v-if="!state.usageByModel.length"><td colspan="5" class="muted" style="text-align: center; padding: 24px">{{ t('usage.noModel') }}</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 18px; }
.stat-card { display: flex; gap: 11px; align-items: center; padding: 15px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow-card); }
.stat-icon { width: 36px; height: 36px; border-radius: 10px; background: var(--surface-2); display: grid; place-items: center; color: var(--brand); flex: 0 0 36px; }
.stat-card b { display: block; font-size: 21px; letter-spacing: -.03em; line-height: 1.15; }
.stat-card span { color: var(--muted); font-size: 11px; }
.usage-grid { display: grid; grid-template-columns: 1.6fr 1fr; gap: 12px; }
.usage-card { padding: 17px; background: var(--surface); border: 1px solid var(--line); border-radius: 15px; }
.usage-card.wide { grid-column: 1 / -1; }
.usage-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 14px; }
.usage-head b { display: block; font-size: 13px; }
.usage-head span { display: block; color: var(--muted); font-size: 11px; }
.chart { height: 210px; display: flex; align-items: flex-end; gap: 6px; padding-top: 18px; }
.chart-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 5px; height: 100%; justify-content: flex-end; min-width: 0; }
.chart-bar { width: 100%; max-width: 38px; border-radius: 5px 5px 2px 2px; background: linear-gradient(180deg, var(--brand), color-mix(in srgb, var(--brand) 45%, var(--brand-2))); position: relative; min-height: 2px; transition: height .5s var(--ease); }
.chart-bar:hover { filter: brightness(1.15); }
.chart-tip { position: absolute; top: -20px; left: 50%; transform: translateX(-50%); font-size: 9px; color: var(--muted); white-space: nowrap; opacity: 0; }
.chart-bar:hover .chart-tip { opacity: 1; }
.chart-label { font-size: 9px; color: var(--faint); white-space: nowrap; }
.chart-empty { height: 100%; display: grid; place-items: center; color: var(--faint); font-size: 12px; width: 100%; }
.composition { display: flex; flex-direction: column; gap: 12px; padding-top: 6px; }
.comp-bar { height: 12px; border-radius: 99px; overflow: hidden; display: flex; background: var(--surface-3); }
.comp-prompt { background: var(--brand); }
.comp-completion { background: var(--brand-2); }
.comp-row { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--muted); }
.comp-row b { margin-left: auto; color: var(--ink-2); font-family: var(--font-mono); font-size: 11.5px; }
.dot { width: 7px; height: 7px; border-radius: 50%; }
.dot.prompt { background: var(--brand); }
.dot.completion { background: var(--brand-2); }
.dot.cost { background: var(--warn); }
.table-wrap { overflow-x: auto; }
@media (max-width: 900px) { .stat-grid { grid-template-columns: 1fr 1fr; } .usage-grid { grid-template-columns: 1fr; } }
</style>
