<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { selectSession, startNewTask, state, supervisorAct, supervisorChat, toast } from '../stores/app'
import { kindLabel, sessionTitle, t } from '../i18n'
import Icon from '../components/Icon.vue'
import StatusPill from '../components/StatusPill.vue'

const router = useRouter()
const filter = ref('all')
const loading = ref(false)
const question = ref('')
const answer = ref('')
const asking = ref(false)
let timer = null

const snapshot = computed(() => state.supervisor || { summary: {}, items: [], alerts: [] })
const summary = computed(() => snapshot.value.summary || {})
const items = computed(() => {
  const all = snapshot.value.items || []
  if (filter.value === 'active') return all.filter((item) => ['running', 'queued', 'waiting_input'].includes(item.status))
  if (filter.value === 'alerts') return all.filter((item) => ['stale', 'error'].includes(item.health))
  if (filter.value === 'done') return all.filter((item) => item.status === 'done')
  return all
})

async function load() {
  loading.value = true
  try {
    state.supervisor = await (await import('../api/client')).api.supervisorOverview()
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    loading.value = false
  }
}

function open(item) {
  selectSession(item.id)
  router.push(`/s/${encodeURIComponent(item.id)}`)
}

async function newSession() {
  const session = await startNewTask()
  if (session) router.push(`/s/${encodeURIComponent(session.id)}`)
}

async function act(item, action) {
  await supervisorAct(item.id, action)
}

async function ask() {
  if (!question.value.trim() || asking.value) return
  asking.value = true
  try {
    const result = await supervisorChat(question.value.trim())
    answer.value = result.reply || ''
    question.value = ''
    await load()
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    asking.value = false
  }
}

function percent(item) {
  return item.plan_total ? Math.round((item.plan_done / item.plan_total) * 100) : 0
}

onMounted(() => {
  load()
  timer = setInterval(load, 12000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="page console-page">
    <header class="page-head">
      <div>
        <div class="page-kicker">{{ t('console.kicker') }}</div>
        <h1>{{ t('console.title') }}</h1>
        <p>{{ t('console.subtitle') }}</p>
      </div>
      <div class="row">
        <button class="btn" @click="load"><Icon name="refresh" :size="14" /> {{ t('common.refresh') }}</button>
        <button class="btn primary" @click="newSession"><Icon name="plus" :size="14" /> {{ t('console.newTask') }}</button>
      </div>
    </header>

    <div class="stat-grid">
      <div class="stat-card"><span class="stat-icon"><Icon name="activity" :size="18" /></span><div><b>{{ summary.total || 0 }}</b><span>{{ t('console.totalSessions') }}</span></div></div>
      <div class="stat-card"><span class="stat-icon" style="color: var(--brand-2)"><Icon name="zap" :size="18" /></span><div><b>{{ summary.active || 0 }}</b><span>{{ t('console.activeNow') }}</span></div></div>
      <div class="stat-card"><span class="stat-icon" style="color: var(--warn)"><Icon name="clock" :size="18" /></span><div><b>{{ summary.waiting || 0 }}</b><span>{{ t('console.waitingApproval') }}</span></div></div>
      <div class="stat-card"><span class="stat-icon" style="color: var(--bad)"><Icon name="alert" :size="18" /></span><div><b>{{ summary.alerts || 0 }}</b><span>{{ t('console.alerts') }}</span></div></div>
      <div class="stat-card"><span class="stat-icon" style="color: var(--good)"><Icon name="check" :size="18" /></span><div><b>{{ summary.done || 0 }}</b><span>{{ t('console.completed') }}</span></div></div>
    </div>

    <div v-if="snapshot.alerts?.length" class="alert-strip">
      <div class="alert-strip-head">
        <Icon name="alert" :size="15" style="color: var(--warn)" />
        <b>{{ t('console.alertsNeed', { n: snapshot.alerts.length }) }}</b>
      </div>
      <div v-for="item in snapshot.alerts" :key="item.id" class="alert-row">
        <StatusPill :status="item.status" :health="item.health" />
        <span class="truncate" style="min-width: 0; flex: 1">{{ sessionTitle(item) }}</span>
        <span class="tiny muted truncate" style="max-width: 260px">{{ item.reason }}</span>
        <button class="btn sm" @click="open(item)">{{ t('console.open') }}</button>
        <button v-if="item.status === 'error'" class="btn sm" @click="act(item, 'resume')"><Icon name="refresh" :size="12" /> {{ t('common.resume') }}</button>
        <button v-else class="btn sm danger" @click="act(item, 'cancel')"><Icon name="square" :size="12" /> {{ t('common.stop') }}</button>
      </div>
    </div>

    <div class="console-grid">
      <section>
        <div class="filter-row">
          <button v-for="option in ['all', 'active', 'alerts', 'done']" :key="option" class="filter-btn" :class="{ active: filter === option }" @click="filter = option">
            {{ t(`console.filter${option[0].toUpperCase()}${option.slice(1)}`) }}
          </button>
          <span class="spacer" />
          <span class="tiny faint">{{ snapshot.generated_at }}</span>
        </div>

        <div class="session-grid">
          <article v-for="item in items" :key="item.id" class="session-card" @click="open(item)">
            <div class="session-card-head">
              <StatusPill :status="item.status" :health="item.health" />
              <span class="badge">{{ kindLabel(item.kind) }}</span>
              <span class="spacer" />
              <span class="tiny faint">{{ item.updated_at?.slice(11, 16) }}</span>
            </div>
            <h3 class="truncate">{{ sessionTitle(item) }}</h3>
            <p class="session-question">{{ item.first_question || t('console.noUserMessage') }}</p>
            <div v-if="item.plan_total" class="mini-progress">
              <div class="mini-bar"><span :style="{ width: `${percent(item)}%` }" /></div>
              <span class="tiny faint">{{ item.plan_done }}/{{ item.plan_total }}</span>
            </div>
            <div class="session-card-foot">
              <span class="row" style="gap: 4px"><Icon name="database" :size="11" /> {{ (item.context_tokens / 1000).toFixed(1) }}k</span>
              <span v-if="item.skills_used?.length" class="row" style="gap: 4px"><Icon name="sparkles" :size="11" /> {{ item.skills_used.length }}</span>
              <span class="spacer" />
              <span v-if="item.health !== 'ok'" class="tiny" :style="{ color: item.health === 'stale' ? 'var(--warn)' : 'var(--bad)' }">{{ item.health }}</span>
              <Icon name="chevron-right" :size="13" style="color: var(--faint)" />
            </div>
          </article>
          <div v-if="!items.length" class="empty-card">
            <Icon name="activity" :size="22" />
            <b>{{ t('console.nothingHere') }}</b>
            <span>{{ t('console.nothingDesc') }}</span>
          </div>
        </div>
      </section>

      <aside class="supervisor-chat">
        <div class="chat-head">
          <span class="chat-avatar">S</span>
          <div><b>{{ t('console.askSupervisor') }}</b><span>{{ t('console.supervisorSubtitle') }}</span></div>
        </div>
        <div class="chat-answer">
          <div v-if="!answer" class="chat-hint">
            <Icon name="sparkles" :size="17" />
            <span>{{ t('console.hint1') }}</span>
            <span>{{ t('console.hint2') }}</span>
            <span>{{ t('console.hint3') }}</span>
          </div>
          <div v-else class="chat-reply">{{ answer }}</div>
        </div>
        <div class="chat-input">
          <textarea v-model="question" class="textarea" rows="2" :placeholder="t('console.askPlaceholder')" @keydown.ctrl.enter="ask" @keydown.meta.enter="ask" />
          <button class="btn primary sm" :disabled="asking" @click="ask">
            <span v-if="asking" class="spinner" style="width: 12px; height: 12px" />
            <Icon v-else name="send" :size="13" />
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.stat-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 20px; }
.stat-card { display: flex; gap: 11px; align-items: center; padding: 15px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow-card); }
.stat-icon { width: 36px; height: 36px; border-radius: 10px; background: var(--surface-2); display: grid; place-items: center; color: var(--brand); flex: 0 0 36px; }
.stat-card b { display: block; font-size: 22px; letter-spacing: -.03em; line-height: 1.1; }
.stat-card span { color: var(--muted); font-size: 11px; }
.alert-strip { border: 1px solid color-mix(in srgb, var(--warn) 32%, var(--line)); background: var(--warn-soft); border-radius: 14px; padding: 12px 14px; margin-bottom: 20px; }
.alert-strip-head { display: flex; align-items: center; gap: 7px; font-size: 12.5px; margin-bottom: 8px; }
.alert-row { display: flex; align-items: center; gap: 9px; padding: 7px 0; border-top: 1px solid color-mix(in srgb, var(--warn) 18%, transparent); font-size: 12px; }
.console-grid { display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 20px; align-items: start; }
.filter-row { display: flex; align-items: center; gap: 5px; margin-bottom: 11px; }
.filter-btn { height: 29px; padding: 0 11px; border-radius: 8px; border: 1px solid transparent; background: transparent; color: var(--muted); font-size: 12px; }
.filter-btn:hover { color: var(--ink); }
.filter-btn.active { background: var(--brand-soft); border-color: var(--brand-line); color: var(--brand); }
.session-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 11px; }
.session-card { padding: 14px; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; cursor: pointer; transition: all .16s var(--ease); }
.session-card:hover { border-color: var(--brand-line); transform: translateY(-2px); box-shadow: var(--shadow-card); }
.session-card-head { display: flex; align-items: center; gap: 6px; }
.session-card-head .badge { height: 18px; font-size: 9.5px; padding: 0 6px; }
.session-card h3 { margin: 9px 0 4px; font-size: 13.5px; letter-spacing: -.01em; }
.session-question { margin: 0; color: var(--muted); font-size: 11.5px; line-height: 1.5; min-height: 34px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.mini-progress { display: flex; align-items: center; gap: 7px; margin-top: 9px; }
.mini-bar { flex: 1; height: 4px; border-radius: 99px; background: var(--surface-3); overflow: hidden; }
.mini-bar span { display: block; height: 100%; background: linear-gradient(90deg, var(--brand), var(--brand-2)); }
.session-card-foot { display: flex; align-items: center; gap: 9px; margin-top: 11px; padding-top: 9px; border-top: 1px solid var(--line); color: var(--faint); font-size: 10.5px; }
.empty-card { grid-column: 1 / -1; display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 40px; border: 1px dashed var(--line); border-radius: 14px; color: var(--muted); font-size: 12px; }
.empty-card b { color: var(--ink-2); }
.supervisor-chat { position: sticky; top: 16px; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line); border-radius: 16px; overflow: hidden; box-shadow: var(--shadow-card); }
.chat-head { display: flex; gap: 9px; align-items: center; padding: 13px 14px; border-bottom: 1px solid var(--line); }
.chat-avatar { width: 30px; height: 30px; border-radius: 9px; background: linear-gradient(140deg, var(--brand), var(--brand-2)); color: #fff; display: grid; place-items: center; font-weight: 700; font-size: 12px; }
.chat-head b { display: block; font-size: 12.5px; }
.chat-head span { display: block; color: var(--faint); font-size: 10.5px; }
.chat-answer { min-height: 180px; max-height: 340px; overflow-y: auto; padding: 14px; }
.chat-hint { display: flex; flex-direction: column; gap: 8px; color: var(--muted); font-size: 11.5px; }
.chat-hint span { padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 9px; }
.chat-reply { white-space: pre-wrap; color: var(--ink-2); font-size: 12.5px; line-height: 1.65; }
.chat-input { display: flex; gap: 7px; padding: 10px; border-top: 1px solid var(--line); background: var(--surface-2); }
.chat-input .textarea { font-size: 12px; }
@media (max-width: 1100px) {
  .stat-grid { grid-template-columns: repeat(3, 1fr); }
  .console-grid { grid-template-columns: 1fr; }
  .supervisor-chat { position: static; }
}
@media (max-width: 640px) {
  .stat-grid { grid-template-columns: 1fr 1fr; }
}
</style>
