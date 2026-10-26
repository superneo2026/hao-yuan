<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { state, selectSession, hideSession, purgeSession } from '../stores/app'
import { formatRelativeTime, kindLabel, sessionTitle, t } from '../i18n'
import Icon from './Icon.vue'

const emit = defineEmits(['new'])
const router = useRouter()

const kindIcon = {
  auto: 'sparkles',
  dev: 'terminal',
  coding: 'terminal',
  plan: 'document',
  video: 'video',
  robot: 'cpu',
  general: 'message'
}

const groups = computed(() => {
  const active = []
  const today = []
  const earlier = []
  const hidden = []
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  for (const session of state.sessions) {
    if (session.hidden) {
      hidden.push(session)
      continue
    }
    if (['running', 'queued', 'waiting_input'].includes(session.status)) {
      active.push(session)
      continue
    }
    const ts = Date.parse((session.updated_at || '').replace(' ', 'T')) || 0
    if (ts >= startOfToday) today.push(session)
    else earlier.push(session)
  }
  return [
    { key: 'active', labelKey: 'nav.active', items: active },
    { key: 'today', labelKey: 'nav.today', items: today },
    { key: 'earlier', labelKey: 'nav.earlier', items: earlier },
    { key: 'hidden', labelKey: 'nav.hidden', items: hidden }
  ].filter((group) => group.items.length)
})

function open(session) {
  if (session.hidden) {
    import('../api/client').then(({ api }) => api.unhideSession(session.id)).catch(() => {})
  }
  selectSession(session.id)
  router.push(`/s/${encodeURIComponent(session.id)}`)
  state.mobileNavOpen = false
}

function timeLabel(value) {
  return formatRelativeTime(value)
}

async function remove(session) {
  if (!window.confirm(t('session.deleteConfirm', { title: sessionTitle(session) }))) return
  await purgeSession(session.id)
}

async function hide(session) {
  await hideSession(session.id)
}
</script>

<template>
  <div class="session-list">
    <div class="session-list-head">
      <span class="nav-label" style="padding: 0">{{ t('nav.sessions') }}</span>
      <button class="icon-btn" style="width: 24px; height: 24px" :title="t('nav.newTask')" @click="emit('new')">
        <Icon name="plus" :size="15" />
      </button>
    </div>
    <div v-if="!state.sessions.length" class="session-empty">
      <Icon name="message" :size="18" />
      <span>{{ t('session.noSessions') }}</span>
    </div>
    <div v-for="group in groups" :key="group.key" class="session-group">
      <div class="session-group-label">{{ t(group.labelKey) }}</div>
      <button
        v-for="session in group.items"
        :key="session.id"
        class="session-item"
        :class="{ active: state.currentId === session.id, hidden: session.hidden }"
        @click="open(session)"
      >
        <span class="session-icon" :class="{ running: ['running','queued'].includes(session.status) }">
          <span v-if="['running','queued'].includes(session.status)" class="spinner" style="width: 12px; height: 12px" />
          <Icon v-else :name="kindIcon[session.kind] || 'message'" :size="14" />
        </span>
        <span class="session-copy">
          <span class="session-title truncate">{{ sessionTitle(session) }}</span>
          <span class="session-meta">
            <span class="status-dot" :class="session.status === 'waiting_input' ? 'waiting' : session.status" />
            <span>{{ kindLabel(session.kind) }}</span>
            <span v-if="session.plan" class="plan-mini">{{ t('session.planMini') }}</span>
            <span class="spacer" />
            <span>{{ timeLabel(session.updated_at) }}</span>
          </span>
        </span>
        <span class="session-actions">
          <span class="icon-btn" style="width: 22px; height: 22px" :title="t('session.hide')" @click.stop="hide(session)">
            <Icon name="close" :size="12" />
          </span>
          <span class="icon-btn" style="width: 22px; height: 22px" :title="t('session.delete')" @click.stop="remove(session)">
            <Icon name="trash2" :size="12" />
          </span>
        </span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.session-list { padding: 2px 0 10px; }
.session-list-head { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px 8px; }
.session-group { margin-bottom: 10px; }
.session-group-label { padding: 4px 10px; color: var(--faint); font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; font-weight: 620; }
.session-item {
  width: 100%; display: flex; align-items: flex-start; gap: 9px; text-align: left;
  padding: 8px 9px; border-radius: 10px; border: 1px solid transparent; background: transparent;
  color: var(--ink-2); transition: background .15s var(--ease), border-color .15s var(--ease);
}
.session-item:hover { background: var(--surface-2); }
.session-item.active { background: var(--brand-soft); border-color: var(--brand-line); color: var(--ink); }
.session-item.hidden { opacity: .55; }
.session-icon { width: 24px; height: 24px; border-radius: 7px; display: grid; place-items: center; background: var(--surface-2); color: var(--muted); flex: 0 0 24px; margin-top: 1px; }
.session-item.active .session-icon { color: var(--brand); background: color-mix(in srgb, var(--brand) 14%, transparent); }
.session-icon.running { color: var(--brand-2); }
.session-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.session-title { font-size: 13px; font-weight: 540; }
.session-meta { display: flex; align-items: center; gap: 6px; color: var(--faint); font-size: 10.5px; }
.session-meta .status-dot { width: 5px; height: 5px; flex-basis: 5px; }
.plan-mini { color: var(--brand); }
.session-actions { display: none; gap: 2px; margin-top: -2px; }
.session-item:hover .session-actions { display: flex; }
.session-empty { display: flex; align-items: center; gap: 8px; padding: 12px 10px; color: var(--faint); font-size: 12.5px; }
</style>
