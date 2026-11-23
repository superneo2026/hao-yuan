<script setup>
import { computed } from 'vue'
import { artifactUrl } from '../api/client'
import { currentSession, state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'
import PlanPanel from './PlanPanel.vue'
import StatusPill from './StatusPill.vue'

const emit = defineEmits(['close'])

const session = currentSession
const steps = computed(() => state.plan?.steps || [])
const done = computed(() => steps.value.filter((step) => step.s === 'done').length)
const artifacts = computed(() => state.artifacts || [])

function artifactName(item) {
  return item?.name || String(item?.path || '').split(/[\\/]/).pop() || 'artifact'
}

function isImage(item) {
  return /\.(png|jpe?g|webp|gif)$/i.test(artifactName(item))
}
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
      <section v-if="artifacts.length" class="artifact-section">
        <div class="artifact-head">
          <Icon name="package" :size="14" />
          <b>{{ t('artifacts.title', {}, 'Artifacts') }}</b>
          <span>{{ artifacts.length }}</span>
        </div>
        <ul class="artifact-list">
          <li v-for="item in artifacts.slice(0, 24)" :key="item.id" class="artifact-item">
            <a :href="artifactUrl(item.id)" target="_blank" rel="noopener">
              <img v-if="isImage(item)" :src="artifactUrl(item.id)" :alt="artifactName(item)" loading="lazy" />
              <span v-else class="artifact-icon"><Icon name="document" :size="15" /></span>
              <span class="artifact-name mono truncate">{{ artifactName(item) }}</span>
            </a>
          </li>
        </ul>
      </section>
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
.artifact-section { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); }
.artifact-head { display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--muted); margin-bottom: 8px; }
.artifact-head b { color: var(--ink-2); font-size: 11.5px; }
.artifact-head span { margin-left: auto; font-size: 10px; color: var(--faint); }
.artifact-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.artifact-item a { display: flex; align-items: center; gap: 8px; padding: 6px 7px; border: 1px solid var(--line); border-radius: 9px; text-decoration: none; color: var(--ink-2); background: var(--surface); }
.artifact-item a:hover { border-color: var(--brand-line); background: var(--brand-soft); }
.artifact-item img { width: 40px; height: 28px; object-fit: cover; border-radius: 5px; border: 1px solid var(--line); }
.artifact-icon { width: 28px; height: 28px; flex: 0 0 28px; display: grid; place-items: center; border-radius: 6px; background: var(--surface-2); color: var(--muted); }
.artifact-name { font-size: 10.5px; min-width: 0; flex: 1; }
</style>
