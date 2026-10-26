<script setup>
import { computed } from 'vue'
import { state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const steps = computed(() => state.plan?.steps || [])
const done = computed(() => steps.value.filter((step) => step.s === 'done').length)
const percent = computed(() => (steps.value.length ? Math.round((done.value / steps.value.length) * 100) : 0))
const current = computed(() => steps.value.find((step) => step.s === 'doing') || steps.value.find((step) => step.s === 'pending'))

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
    <div v-if="!steps.length" class="panel-empty">
      <div class="panel-empty-icon"><Icon name="layers" :size="20" /></div>
      <b>{{ t('plan.noPlan') }}</b>
      <span>{{ t('plan.noPlanDesc') }}</span>
    </div>
    <template v-else>
      <div class="plan-head">
        <div>
          <div class="plan-title">{{ state.plan.title || t('session.planTitle') }}</div>
          <div class="tiny muted">{{ t('session.completeCount', { done, total: steps.length }) }}</div>
        </div>
        <span class="plan-percent">{{ percent }}%</span>
      </div>
      <div class="progress"><span :style="{ width: `${percent}%` }" /></div>
      <div class="plan-current" v-if="current">
        <Icon name="arrow-right" :size="13" style="color: var(--brand)" />
        <span class="truncate">{{ current.t }}</span>
      </div>
      <div class="plan-steps">
        <div v-for="(step, index) in steps" :key="index" class="plan-step" :class="step.s">
          <span class="step-marker">
            <Icon v-if="step.s === 'done'" name="check" :size="12" />
            <Icon v-else-if="step.s === 'failed'" name="x" :size="12" />
            <span v-else-if="step.s === 'doing'" class="spinner" style="width: 10px; height: 10px" />
            <span v-else>{{ index + 1 }}</span>
          </span>
          <span class="step-copy">
            <span class="step-title">{{ step.t }}</span>
            <span v-if="step.note" class="step-note">{{ step.note }}</span>
            <span class="step-status">{{ t(statusLabel[step.s] || 'plan.pending') }}</span>
          </span>
        </div>
      </div>
    </template>

    <div v-if="state.live.notices.length" class="activity-block">
      <div class="panel-label">{{ t('plan.activity') }}</div>
      <div v-for="(notice, index) in state.live.notices.slice(0, 8)" :key="index" class="activity-row">
        <span class="activity-dot" :class="notice.kind" />
        <span>{{ notice.text }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.plan-panel { display: flex; flex-direction: column; gap: 12px; }
.plan-head { display: flex; align-items: flex-start; gap: 10px; }
.plan-title { font-size: 13.5px; font-weight: 620; letter-spacing: -.01em; }
.plan-percent { font-size: 18px; font-weight: 720; color: var(--brand); letter-spacing: -.03em; }
.progress { height: 5px; border-radius: 99px; background: var(--surface-3); overflow: hidden; }
.progress span { display: block; height: 100%; background: linear-gradient(90deg, var(--brand), var(--brand-2)); border-radius: 99px; transition: width .4s var(--ease); }
.plan-current { display: flex; align-items: center; gap: 7px; padding: 8px 10px; border-radius: 9px; background: var(--brand-soft); border: 1px solid var(--brand-line); color: var(--ink-2); font-size: 12px; }
.plan-steps { display: flex; flex-direction: column; gap: 3px; }
.plan-step { display: flex; gap: 9px; padding: 7px 8px; border-radius: 9px; }
.plan-step:hover { background: var(--surface-2); }
.step-marker { width: 19px; height: 19px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-3); color: var(--faint); font-size: 10px; flex: 0 0 19px; margin-top: 1px; }
.plan-step.done .step-marker { background: var(--good-soft); color: var(--good); }
.plan-step.doing .step-marker { background: var(--brand-soft); color: var(--brand); }
.plan-step.failed .step-marker { background: var(--bad-soft); color: var(--bad); }
.step-copy { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.step-title { font-size: 12px; color: var(--ink-2); }
.plan-step.done .step-title { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--faint); }
.step-note { font-size: 10.5px; color: var(--faint); }
.step-status { font-size: 9.5px; color: var(--faint); text-transform: uppercase; letter-spacing: .07em; }
.panel-empty { display: flex; flex-direction: column; align-items: flex-start; gap: 5px; color: var(--muted); font-size: 12px; padding: 8px 0; }
.panel-empty-icon { width: 36px; height: 36px; border-radius: 11px; background: var(--surface-2); color: var(--muted); display: grid; place-items: center; margin-bottom: 4px; }
.panel-empty b { color: var(--ink-2); font-size: 12.5px; }
.activity-block { border-top: 1px solid var(--line); padding-top: 11px; }
.panel-label { font-size: 9.5px; text-transform: uppercase; letter-spacing: .11em; color: var(--faint); font-weight: 650; margin-bottom: 7px; }
.activity-row { display: flex; gap: 7px; font-size: 11px; color: var(--muted); padding: 3px 0; line-height: 1.45; }
.activity-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--brand); margin-top: 6px; flex: 0 0 5px; }
.activity-dot.repair { background: var(--warn); }
.activity-dot.verify { background: var(--brand-2); }
.activity-dot.context { background: var(--good); }
</style>
