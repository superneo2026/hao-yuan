<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { advanceOrchestration, createOrchestration, loadOrchestrations, mergeOrchestration, selectSession, state, toast } from '../stores/app'
import { t } from '../i18n'
import DirPicker from '../components/DirPicker.vue'
import Icon from '../components/Icon.vue'

const router = useRouter()
const goal = ref('')
const workspace = ref(state.settings.default_workspace || '')
const provider = ref('')
const model = ref('')
const showDir = ref(false)
const creating = ref(false)
const selectedId = ref('')
const detail = ref(null)
let timer = null

const orchestrations = computed(() => state.orchestrations || [])
const selected = computed(() => detail.value || orchestrations.value.find((item) => item.id === selectedId.value))

async function load() {
  try {
    await loadOrchestrations()
    if (!selectedId.value && state.orchestrations.length) selectedId.value = state.orchestrations[0].id
    if (selectedId.value) await loadDetail(selectedId.value)
  } catch (error) {
    toast(error.message, 'bad')
  }
}

async function loadDetail(id) {
  try {
    const { api } = await import('../api/client')
    detail.value = await api.orchestration(id)
  } catch {
    detail.value = null
  }
}

async function create() {
  if (!goal.value.trim() || !workspace.value || creating.value) return
  creating.value = true
  try {
    const data = await createOrchestration({
      goal: goal.value.trim(),
      workspace: workspace.value,
      provider: provider.value,
      model: model.value
    })
    selectedId.value = data.id
    detail.value = data
    goal.value = ''
    toast(t('orch.created'), 'good')
  } catch (error) {
    toast(error.message, 'bad', 7000)
  } finally {
    creating.value = false
  }
}

async function advance() {
  if (!selected.value) return
  try {
    await advanceOrchestration(selected.value.id)
    await loadDetail(selected.value.id)
  } catch (error) {
    toast(error.message, 'bad')
  }
}

async function merge() {
  if (!selected.value) return
  try {
    const result = await mergeOrchestration(selected.value.id)
    toast(result.merged ? t('orch.merged') : t('orch.mergeConflicts'), result.merged ? 'good' : 'warn', 7000)
    await loadDetail(selected.value.id)
  } catch (error) {
    toast(error.message, 'bad')
  }
}

function openWorker(task) {
  if (!task.session_id) return
  selectSession(task.session_id)
  router.push(`/s/${encodeURIComponent(task.session_id)}`)
}

function selectOrch(item) {
  selectedId.value = item.id
  loadDetail(item.id)
}

const statusClass = {
  done: 'good',
  running: 'brand',
  planning: 'brand',
  merging: 'warn',
  error: 'bad'
}

function orchestrationStatusLabel(status) {
  return t(`orch.status.${status}`, {}, t(`status.${status}`, {}, status))
}

function taskStatusLabel(status) {
  return t(`orch.task.${status}`, {}, status)
}

onMounted(() => {
  load()
  timer = setInterval(() => {
    if (selectedId.value) loadDetail(selectedId.value)
    loadOrchestrations().catch(() => {})
  }, 6000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <div class="page-kicker">{{ t('orch.kicker') }}</div>
        <h1>{{ t('orch.title') }}</h1>
        <p>{{ t('orch.subtitle') }}</p>
      </div>
      <span class="badge brand">{{ t('orch.runs', { n: orchestrations.length }) }}</span>
    </header>

    <section class="create-card">
      <div class="create-grid">
        <div style="flex: 2">
          <label class="label">{{ t('orch.goal') }}</label>
          <textarea v-model="goal" class="textarea" rows="2" :placeholder="t('orch.goalPlaceholder')" />
        </div>
        <div>
          <label class="label">{{ t('orch.gitWorkspace') }}</label>
          <div class="row">
            <input v-model="workspace" class="field mono" style="font-size: 11.5px" :placeholder="t('orch.gitPlaceholder')" />
            <button class="btn" @click="showDir = true"><Icon name="folder" :size="14" /></button>
          </div>
          <div class="row" style="margin-top: 7px; gap: 6px">
            <select v-model="provider" class="select" style="font-size: 11.5px">
              <option value="">{{ t('orch.autoProvider') }}</option>
              <option v-for="item in state.models" :key="item.provider" :value="item.provider">{{ item.provider }}</option>
            </select>
            <button class="btn primary" :disabled="creating" @click="create">
              <span v-if="creating" class="spinner" style="width: 12px; height: 12px" />
              <Icon v-else name="network" :size="14" />
              {{ t('orch.launch') }}
            </button>
          </div>
        </div>
      </div>
      <div class="tiny faint" style="margin-top: 7px">
        {{ t('orch.require') }}
      </div>
    </section>

    <div class="orch-grid">
      <aside class="orch-list">
        <div class="panel-label">{{ t('common.runs') }}</div>
        <button v-for="item in orchestrations" :key="item.id" class="orch-item" :class="{ active: selectedId === item.id }" @click="selectOrch(item)">
          <div class="row" style="justify-content: space-between">
            <span class="badge" :class="statusClass[item.status] || ''">{{ orchestrationStatusLabel(item.status) }}</span>
            <span class="tiny faint">{{ item.created_at?.slice(5, 16) }}</span>
          </div>
          <div class="truncate" style="font-size: 12px; margin-top: 5px">{{ item.goal }}</div>
          <div class="tiny faint mono truncate">{{ item.workspace }}</div>
        </button>
        <div v-if="!orchestrations.length" class="tiny faint" style="padding: 16px 4px; text-align: center">
          {{ t('orch.noRuns') }}
        </div>
      </aside>

      <section v-if="selected" class="orch-detail">
        <div class="orch-detail-head">
          <div>
            <div class="row" style="gap: 7px">
              <span class="badge" :class="statusClass[selected.status] || ''">{{ orchestrationStatusLabel(selected.status) }}</span>
              <span class="mono tiny faint">{{ selected.id }}</span>
            </div>
            <h2>{{ selected.goal }}</h2>
            <div class="mono tiny faint">{{ selected.workspace }}</div>
          </div>
          <div class="row">
            <button class="btn sm" @click="advance"><Icon name="zap" :size="13" /> {{ t('orch.advance') }}</button>
            <button class="btn sm" @click="merge"><Icon name="git" :size="13" /> {{ t('orch.merge') }}</button>
          </div>
        </div>
        <div v-if="selected.error" class="orch-error">{{ selected.error }}</div>
        <div class="task-list">
          <div v-for="task in selected.tasks" :key="task.id" class="task-card">
            <div class="task-head">
              <span class="task-seq">{{ task.seq + 1 }}</span>
              <div class="task-title">
                <b>{{ task.title }}</b>
                <span class="mono tiny faint">{{ task.id }} · {{ task.role }}</span>
              </div>
              <span class="badge" :class="task.status === 'done' ? 'good' : task.status === 'error' ? 'bad' : task.status === 'running' ? 'brand' : ''">{{ taskStatusLabel(task.status) }}</span>
            </div>
            <div class="task-meta">
              <span v-if="task.depends_on?.length"><Icon name="network" :size="11" /> {{ t('orch.depends', { items: task.depends_on.join(', ') }) }}</span>
              <span v-if="task.branch" class="mono"><Icon name="git" :size="11" /> {{ task.branch }}</span>
              <span v-if="task.worktree" class="mono truncate" :title="task.worktree"><Icon name="folder" :size="11" /> {{ task.worktree.split(/[\\/]/).slice(-2).join('/') }}</span>
            </div>
            <div class="task-foot">
              <span class="tiny faint">{{ (task.instruction || '').slice(0, 140) }}</span>
              <span class="spacer" />
              <button v-if="task.session_id" class="btn sm" @click="openWorker(task)">{{ t('orch.openWorker') }}</button>
            </div>
          </div>
          <div v-if="!selected.tasks?.length" class="tiny faint" style="padding: 20px">{{ t('orch.noTasks') }}</div>
        </div>
      </section>
      <section v-else class="orch-detail empty">
        <Icon name="network" :size="26" />
        <b>{{ t('orch.selectOrLaunch') }}</b>
        <span>{{ t('orch.selectDesc') }}</span>
      </section>
    </div>

    <DirPicker v-if="showDir" :initial="workspace" @close="showDir = false" @select="workspace = $event" />
  </div>
</template>

<style scoped>
.create-card { padding: 16px; background: var(--surface); border: 1px solid var(--line); border-radius: 15px; margin-bottom: 14px; }
.create-grid { display: flex; gap: 12px; align-items: flex-end; }
.orch-grid { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 12px; align-items: start; }
.orch-list { display: flex; flex-direction: column; gap: 4px; padding: 12px; background: var(--surface); border: 1px solid var(--line); border-radius: 15px; }
.orch-item { padding: 10px; border-radius: 9px; border: 1px solid transparent; background: transparent; text-align: left; color: var(--ink-2); }
.orch-item:hover { background: var(--surface-2); }
.orch-item.active { background: var(--brand-soft); border-color: var(--brand-line); }
.orch-detail { padding: 17px; background: var(--surface); border: 1px solid var(--line); border-radius: 15px; }
.orch-detail.empty { min-height: 260px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 7px; color: var(--muted); font-size: 12px; border-style: dashed; }
.orch-detail.empty b { color: var(--ink-2); font-size: 13px; }
.orch-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding-bottom: 13px; border-bottom: 1px solid var(--line); }
.orch-detail-head h2 { margin: 7px 0 4px; font-size: 17px; letter-spacing: -.02em; }
.orch-error { margin-top: 10px; padding: 8px 10px; border-radius: 9px; background: var(--bad-soft); color: var(--bad); font-size: 11.5px; }
.task-list { display: flex; flex-direction: column; gap: 8px; margin-top: 13px; }
.task-card { border: 1px solid var(--line); border-radius: 11px; padding: 10px 12px; background: var(--surface-2); }
.task-head { display: flex; align-items: center; gap: 9px; }
.task-seq { width: 21px; height: 21px; border-radius: 50%; display: grid; place-items: center; background: var(--surface-3); color: var(--muted); font-size: 10px; flex: 0 0 21px; }
.task-title { flex: 1; min-width: 0; }
.task-title b { display: block; font-size: 12.5px; }
.task-meta { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 6px; color: var(--faint); font-size: 10.5px; }
.task-meta span { display: flex; align-items: center; gap: 4px; min-width: 0; }
.task-foot { display: flex; align-items: center; gap: 8px; margin-top: 8px; padding-top: 7px; border-top: 1px solid var(--line); }
.panel-label { font-size: 9.5px; text-transform: uppercase; letter-spacing: .11em; color: var(--faint); font-weight: 650; margin-bottom: 6px; }
@media (max-width: 900px) {
  .orch-grid { grid-template-columns: 1fr; }
  .create-grid { flex-direction: column; align-items: stretch; }
}
</style>
