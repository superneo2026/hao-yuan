<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { state, selectSession, hideSession, purgeSession } from '../stores/app'
import { formatRelativeTime, kindLabel, sessionTitle, t } from '../i18n'
import Icon from './Icon.vue'

const emit = defineEmits(['new'])
const router = useRouter()

const pageSize = 20
const currentPage = ref(1)
const pageInput = ref('1')

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

const orderedEntries = computed(() =>
  groups.value.flatMap((group) =>
    group.items.map((item) => ({ group: group.key, labelKey: group.labelKey, item }))
  )
)
const totalCount = computed(() => orderedEntries.value.length)
const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize)))

const pageItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return orderedEntries.value.slice(start, start + pageSize)
})

const pageGroups = computed(() => {
  const result = []
  for (const entry of pageItems.value) {
    let group = result[result.length - 1]
    if (!group || group.key !== entry.group) {
      group = { key: entry.group, labelKey: entry.labelKey, items: [] }
      result.push(group)
    }
    group.items.push(entry.item)
  }
  return result
})

const pageNumbers = computed(() => {
  const total = totalPages.value
  const current = currentPage.value
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1)
  const wanted = new Set([1, total, current, current - 1, current + 1, current - 2, current + 2])
  const sorted = [...wanted].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b)
  const result = []
  let previous = 0
  for (const page of sorted) {
    if (previous && page - previous > 1) result.push('…')
    result.push(page)
    previous = page
  }
  return result
})

function setPage(page, syncInput = true) {
  const next = Math.min(Math.max(1, Math.floor(Number(page)) || 1), totalPages.value)
  currentPage.value = next
  if (syncInput) pageInput.value = String(next)
}

function jumpToPage() {
  const value = Number(pageInput.value)
  if (!Number.isFinite(value)) {
    pageInput.value = String(currentPage.value)
    return
  }
  setPage(value)
}

watch(
  () => state.currentId,
  (id) => {
    const index = orderedEntries.value.findIndex((entry) => entry.item.id === id)
    if (index >= 0) setPage(Math.floor(index / pageSize) + 1)
  },
  { immediate: true }
)

watch(totalCount, () => {
  if (currentPage.value === 1) {
    const index = orderedEntries.value.findIndex((entry) => entry.item.id === state.currentId)
    if (index >= pageSize) setPage(Math.floor(index / pageSize) + 1)
  }
})

watch(totalPages, (total) => {
  if (currentPage.value > total) setPage(total)
})

watch(currentPage, (page) => {
  pageInput.value = String(page)
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
    <div v-for="group in pageGroups" :key="group.key" class="session-group">
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

    <div v-if="totalPages > 1" class="session-pager">
      <div class="session-pages">
        <button class="page-btn" type="button" :disabled="currentPage <= 1" :title="t('session.prevPage')" @click="setPage(currentPage - 1)">
          <Icon name="chevron-left" :size="12" />
        </button>
        <template v-for="(page, index) in pageNumbers" :key="`${page}-${index}`">
          <span v-if="page === '…'" class="page-ellipsis">…</span>
          <button v-else class="page-btn" type="button" :class="{ active: page === currentPage }" @click="setPage(page)">
            {{ page }}
          </button>
        </template>
        <button class="page-btn" type="button" :disabled="currentPage >= totalPages" :title="t('session.nextPage')" @click="setPage(currentPage + 1)">
          <Icon name="chevron-right" :size="12" />
        </button>
      </div>
      <div class="session-jump">
        <span>{{ t('session.pageOf', { page: currentPage, total: totalPages }) }}</span>
        <input
          v-model="pageInput"
          class="session-jump-input"
          type="number"
          min="1"
          :max="totalPages"
          :placeholder="t('session.jumpPlaceholder')"
          @keyup.enter="jumpToPage"
        />
        <button class="page-btn" type="button" @click="jumpToPage">{{ t('session.jump') }}</button>
      </div>
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
.session-pager { display: flex; flex-direction: column; gap: 6px; padding: 6px 8px 2px; }
.session-pages { display: flex; align-items: center; justify-content: center; gap: 3px; flex-wrap: wrap; }
.page-btn { min-width: 24px; height: 24px; padding: 0 6px; border-radius: 7px; border: 1px solid var(--line); background: var(--surface); color: var(--muted); font-size: 11px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: all .15s var(--ease); }
.page-btn:hover:not(:disabled) { color: var(--ink); border-color: var(--line-strong); }
.page-btn.active { color: var(--brand); border-color: var(--brand-line); background: var(--brand-soft); font-weight: 650; }
.page-btn:disabled { opacity: .4; cursor: default; }
.page-ellipsis { color: var(--faint); font-size: 11px; padding: 0 2px; }
.session-jump { display: flex; align-items: center; justify-content: center; gap: 5px; color: var(--faint); font-size: 10.5px; }
.session-jump-input { width: 46px; height: 24px; padding: 0 4px; border-radius: 7px; border: 1px solid var(--line); background: var(--surface); color: var(--ink); font-size: 11px; text-align: center; }
.session-jump-input::-webkit-outer-spin-button, .session-jump-input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.session-empty { display: flex; align-items: center; gap: 8px; padding: 12px 10px; color: var(--faint); font-size: 12.5px; }
</style>
