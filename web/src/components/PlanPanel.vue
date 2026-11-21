<script setup>
import { computed } from 'vue'
import { state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const steps = computed(() => state.plan?.steps || [])
const done = computed(() => steps.value.filter((step) => step.s === 'done').length)
const failed = computed(() => steps.value.some((step) => step.s === 'failed'))
const total = computed(() => steps.value.length)
const percent = computed(() => (total.value ? Math.round((done.value / total.value) * 100) : 0))
const planTitle = computed(() => state.plan?.title || t('session.planTitle'))
const current = computed(() => steps.value.find((step) => step.s === 'doing') || steps.value.find((step) => step.s === 'pending'))
const phase = computed(() => {
  if (steps.value.some((step) => step.s === 'doing')) return t('plan.doing')
  if (steps.value.some((step) => step.s === 'pending')) return t('plan.pending')
  if (failed.value) return t('plan.failed')
  return t('plan.done')
})

const statusLabel = {
  pending: 'plan.pending',
  doing: 'plan.doing',
  done: 'plan.done',
  failed: 'plan.failed',
  skipped: 'plan.skipped'
}
</script>

<template>
  <div class="plan-panel">
    <div v-if="!steps.length" class="plan-empty">
      <span class="empty-icon"><Icon name="layers" :size="20" /></span>
      <b>{{ t('plan.noPlan') }}</b>
      <p>{{ t('plan.noPlanDesc') }}</p>
    </div>

    <template v-else>
      <div class="plan-hero">
        <div class="hero-copy">
          <span class="hero-kicker" :class="{ doing: phase === t('plan.doing'), bad: phase === t('plan.failed') }">{{ phase }}</span>
          <b>{{ planTitle }}</b>
          <span class="hero-sub">{{ t('session.completeCount', { done, total }) }}</span>
        </div>
        <div class="gauge" :style="{ '--angle': `${percent * 3.6}deg` }">
          <span>{{ percent }}<i>%</i></span>
        </div>
      </div>

      <div v-if="current" class="plan-now">
        <span class="now-pulse" :class="{ waiting: current.s === 'pending' }" />
        <div class="now-copy">
          <span>{{ current.s === 'doing' ? t('plan.doing') : t('plan.pending') }}</span>
          <b>{{ current.t }}</b>
        </div>
      </div>

      <ol class="plan-steps">
        <li v-for="(step, index) in steps" :key="`${index}-${step.t}`" class="plan-step" :class="step.s">
          <span class="step-rail">
            <span class="step-marker">
              <Icon v-if="step.s === 'done'" name="check" :size="12" />
              <Icon v-else-if="step.s === 'failed'" name="x" :size="12" />
              <Icon v-else-if="step.s === 'skipped'" name="chevron-right" :size="12" />
              <span v-else-if="step.s === 'doing'" class="spinner" style="width: 10px; height: 10px" />
              <span v-else class="step-num">{{ index + 1 }}</span>
            </span>
          </span>
          <div class="step-copy">
            <span class="step-title">{{ step.t }}</span>
            <span v-if="step.note" class="step-note">{{ step.note }}</span>
          </div>
          <span class="step-state">{{ t(statusLabel[step.s] || 'plan.pending') }}</span>
        </li>
      </ol>
    </template>
  </div>
</template>

<style scoped>
.plan-panel { display: flex; flex-direction: column; gap: 14px; }
.plan-empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 6px; padding: 42px 18px; color: var(--muted); }
.empty-icon { width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center; background: var(--surface-2); color: var(--faint); border: 1px solid var(--line); margin-bottom: 4px; }
.plan-empty b { font-size: 12.5px; color: var(--ink-2); }
.plan-empty p { margin: 0; max-width: 220px; font-size: 11px; line-height: 1.55; color: var(--faint); }

.plan-hero { display: flex; align-items: center; gap: 12px; padding: 13px 14px; border: 1px solid var(--line); border-radius: 14px; background: linear-gradient(150deg, var(--surface), color-mix(in srgb, var(--brand) 5%, var(--surface))); }
.hero-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.hero-kicker { font-size: 9px; text-transform: uppercase; letter-spacing: .1em; font-weight: 680; color: var(--muted); }
.hero-kicker.doing { color: var(--brand); }
.hero-kicker.bad { color: var(--bad); }
.hero-copy b { font-size: 13px; font-weight: 640; letter-spacing: -.01em; line-height: 1.35; word-break: break-word; }
.hero-sub { font-size: 10.5px; color: var(--faint); }
.gauge { position: relative; width: 48px; height: 48px; flex: 0 0 48px; border-radius: 50%; display: grid; place-items: center; background: conic-gradient(var(--brand) var(--angle), var(--surface-3) 0); transition: background .45s var(--ease); }
.gauge::before { content: ""; position: absolute; inset: 4px; border-radius: 50%; background: var(--surface); }
.gauge span { position: relative; font-size: 11.5px; font-weight: 740; color: var(--ink-2); letter-spacing: -.03em; }
.gauge i { font-style: normal; font-size: 8px; font-weight: 600; color: var(--faint); margin-left: 1px; }

.plan-now { display: flex; align-items: flex-start; gap: 9px; padding: 9px 11px; border-radius: 11px; background: var(--brand-soft); border: 1px solid var(--brand-line); }
.now-pulse { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: var(--brand); margin-top: 6px; animation: plan-pulse 1.6s infinite; }
.now-pulse.waiting { background: var(--faint); animation: none; }
.now-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.now-copy span { font-size: 8.5px; text-transform: uppercase; letter-spacing: .09em; font-weight: 680; color: var(--brand); }
.now-copy b { font-size: 11.5px; font-weight: 560; color: var(--ink); line-height: 1.4; word-break: break-word; }
@keyframes plan-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--brand) 40%, transparent); }
  70% { box-shadow: 0 0 0 6px transparent; }
  100% { box-shadow: 0 0 0 0 transparent; }
}

.plan-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.plan-step { position: relative; display: flex; align-items: flex-start; gap: 10px; padding: 7px 6px 7px 2px; border-radius: 9px; transition: background .15s var(--ease); }
.plan-step:hover { background: var(--surface-2); }
.step-rail { position: relative; width: 22px; flex: 0 0 22px; display: flex; justify-content: center; }
.step-rail::after { content: ""; position: absolute; top: 25px; bottom: -8px; left: 50%; width: 1.5px; transform: translateX(-50%); background: var(--line); }
.plan-step:last-child .step-rail::after { display: none; }
.plan-step.done .step-rail::after { background: color-mix(in srgb, var(--good) 38%, var(--line)); }
.step-marker { position: relative; z-index: 1; width: 20px; height: 20px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-3); color: var(--faint); font-size: 10px; border: 1.5px solid var(--surface); transition: background .2s var(--ease), color .2s var(--ease), box-shadow .2s var(--ease); }
.step-num { font-size: 9.5px; font-weight: 650; }
.plan-step.done .step-marker { background: var(--good-soft); color: var(--good); animation: plan-mark-pop .3s var(--ease); }
@keyframes plan-mark-pop {
  0% { transform: scale(.72); }
  60% { transform: scale(1.12); }
  100% { transform: scale(1); }
}
.plan-step.doing .step-marker { background: var(--brand-soft); color: var(--brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand) 12%, transparent); }
.plan-step.failed .step-marker { background: var(--bad-soft); color: var(--bad); }
.plan-step.skipped .step-marker { background: var(--surface-3); color: var(--faint); }
.step-copy { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; padding-top: 1px; }
.step-title { font-size: 12px; color: var(--ink-2); line-height: 1.45; word-break: break-word; transition: color .2s var(--ease); }
.plan-step.done .step-title { color: var(--muted); }
.plan-step.doing .step-title { color: var(--ink); font-weight: 560; }
.step-note { font-size: 10.5px; color: var(--faint); line-height: 1.45; word-break: break-word; }
.step-state { flex: 0 0 auto; margin-top: 2px; font-size: 9px; font-weight: 650; text-transform: uppercase; letter-spacing: .07em; color: var(--faint); }
.plan-step.done .step-state { color: var(--good); }
.plan-step.doing .step-state { color: var(--brand); }
.plan-step.failed .step-state { color: var(--bad); }
</style>
