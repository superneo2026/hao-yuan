<script setup>
import { computed } from 'vue'
import { currentSession, state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'
import PlanPanel from './PlanPanel.vue'
import StatusPill from './StatusPill.vue'

const emit = defineEmits(['close'])

const session = currentSession
const steps = computed(() => state.plan?.steps || [])
const done = computed(() => steps.value.filter((step) => step.s === 'done').length)
</script>

<template>
  <aside class="right-panel">
    <header class="panel-head">
      <span class="panel-icon"><Icon name="layers" :size="15" /></span>
      <div class="panel-title">
        <b>{{ t('session.planTitle') }}</b>
        <span>{{ steps.length ? t('session.completeCount', { done, total: steps.length }) : t('plan.noPlan') }}</span>
      </div>
      <StatusPill v-if="session" :status="session.status" />
      <button class="icon-btn panel-close" :title="t('common.close')" @click="emit('close')">
        <Icon name="close" :size="15" />
      </button>
    </header>
    <div class="right-body">
      <PlanPanel />
    </div>
  </aside>
</template>

<style scoped>
.right-panel { display: flex; flex-direction: column; min-height: 0; border-left: 1px solid var(--line); background: color-mix(in srgb, var(--surface) 72%, transparent); backdrop-filter: blur(16px); }
.panel-head { display: flex; align-items: center; gap: 9px; padding: 13px 12px 12px 14px; border-bottom: 1px solid var(--line); background: linear-gradient(135deg, color-mix(in srgb, var(--brand) 6%, transparent), transparent 70%); }
.panel-icon { width: 30px; height: 30px; flex: 0 0 30px; border-radius: 9px; display: grid; place-items: center; background: var(--brand-soft); color: var(--brand); border: 1px solid var(--brand-line); }
.panel-title { display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1; }
.panel-title b { font-size: 12.5px; font-weight: 640; letter-spacing: -.01em; }
.panel-title span { font-size: 10.5px; color: var(--muted); }
.panel-close { width: 28px; height: 28px; flex: 0 0 28px; color: var(--faint); }
.panel-close:hover { color: var(--ink); }
.right-body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 14px 24px; }
</style>
