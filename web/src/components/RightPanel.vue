<script setup>
import { computed } from 'vue'
import { artifactUrl } from '../api/client'
import { activeSkills, currentSession, openDiff, openFile, state, tokenCount } from '../stores/app'
import { kindLabel, sessionTitle, skillTitle, t } from '../i18n'
import FileTree from './FileTree.vue'
import Icon from './Icon.vue'
import PlanPanel from './PlanPanel.vue'
import StatusPill from './StatusPill.vue'

const emit = defineEmits(['open-file', 'open-diff'])

const tabs = [
  { id: 'overview', labelKey: 'session.overview', icon: 'compass' },
  { id: 'plan', labelKey: 'session.planTab', icon: 'layers' },
  { id: 'files', labelKey: 'session.files', icon: 'folder' },
  { id: 'changes', labelKey: 'session.changes', icon: 'git' },
  { id: 'artifacts', labelKey: 'session.output', icon: 'document' }
]

const session = currentSession
const planCount = computed(() => state.plan?.steps?.length || 0)
const changeCount = computed(() => state.changes.length)
const artifactCount = computed(() => state.artifacts.length)

function pickFile(path) {
  openFile(path)
  emit('open-file', path)
}

function pickDiff(path) {
  openDiff(path)
  emit('open-diff', path)
}

function openArtifact(artifact) {
  window.open(artifactUrl(artifact.id), '_blank', 'noopener')
}

function sizeLabel(size) {
  if (!size) return '—'
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size > 1024) return `${Math.round(size / 1024)} KB`
  return `${size} B`
}

const statusMap = {
  M: { label: 'M', cls: 'warn' },
  A: { label: 'A', cls: 'good' },
  '??': { label: 'U', cls: 'brand' },
  D: { label: 'D', cls: 'bad' },
  R: { label: 'R', cls: 'brand' }
}
</script>

<template>
  <aside class="right-panel">
    <div class="right-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="right-tab"
        :class="{ active: state.activeRightTab === tab.id }"
        :title="t(tab.labelKey)"
        @click="state.activeRightTab = tab.id"
      >
        <Icon :name="tab.icon" :size="15" />
        <span>{{ t(tab.labelKey) }}</span>
        <span v-if="tab.id === 'plan' && planCount" class="tab-count">{{ planCount }}</span>
        <span v-if="tab.id === 'changes' && changeCount" class="tab-count">{{ changeCount }}</span>
        <span v-if="tab.id === 'artifacts' && artifactCount" class="tab-count">{{ artifactCount }}</span>
      </button>
    </div>

    <div class="right-body">
      <template v-if="state.activeRightTab === 'overview'">
        <div class="overview-head">
          <div class="tiny faint">{{ t('session.currentSession') }}</div>
          <div class="overview-title">{{ session ? sessionTitle(session) : t('session.noSession') }}</div>
          <div class="row" style="gap: 6px; margin-top: 6px">
            <StatusPill :status="session?.status || 'idle'" />
            <span class="badge">{{ kindLabel(session?.kind) }}</span>
            <span v-if="state.live.route?.lite" class="badge">{{ t('session.lite') }}</span>
          </div>
        </div>

        <div class="info-grid">
          <div class="info-cell"><span>{{ t('session.model') }}</span><b class="truncate">{{ session?.model || t('kind.auto') }}</b></div>
          <div class="info-cell"><span>{{ t('session.effort') }}</span><b>{{ session?.thinking || state.live.route?.thinking || t('kind.auto') }}</b></div>
          <div class="info-cell"><span>{{ t('session.context') }}</span><b class="mono">{{ (tokenCount / 1000).toFixed(1) }}k</b></div>
          <div class="info-cell"><span>{{ t('session.costEst') }}</span><b class="mono">¥{{ Number(session?.cost_est || 0).toFixed(4) }}</b></div>
        </div>

        <div class="overview-block">
          <div class="panel-label">{{ t('session.workspace') }}</div>
          <div class="workspace-line mono truncate" :title="session?.workspace">{{ session?.workspace || t('session.workspaceNotBound') }}</div>
        </div>

        <div class="overview-block">
          <div class="panel-label">{{ t('session.activeSkills') }}</div>
          <div v-if="activeSkills.length" class="row wrap" style="gap: 5px">
            <span v-for="skill in activeSkills" :key="skill.name" class="badge brand">
              <Icon name="sparkles" :size="10" /> {{ skillTitle(skill) }}
            </span>
          </div>
          <div v-else class="tiny faint">{{ t('session.autoSkills') }}</div>
        </div>

        <div class="overview-block" v-if="state.live.route">
          <div class="panel-label">{{ t('session.routing') }}</div>
          <div class="route-line">
            <span>{{ state.live.route.task_type || 'dev' }}</span>
            <span>·</span>
            <span>{{ state.live.route.level || 'normal' }}</span>
            <span>·</span>
            <span>{{ state.live.route.model || session?.model }}</span>
          </div>
        </div>

        <div class="overview-block" v-if="state.live.notices.length">
          <div class="panel-label">{{ t('session.liveActivity') }}</div>
          <div v-for="(notice, index) in state.live.notices.slice(0, 10)" :key="index" class="notice-row">
            <span class="notice-dot" :class="notice.kind" />
            <span>{{ notice.text }}</span>
          </div>
        </div>
      </template>

      <template v-else-if="state.activeRightTab === 'plan'">
        <PlanPanel />
      </template>

      <template v-else-if="state.activeRightTab === 'files'">
        <FileTree :items="state.tree" :selected="state.selectedFile" @open="pickFile" />
      </template>

      <template v-else-if="state.activeRightTab === 'changes'">
        <div class="changes-panel">
          <div class="row" style="justify-content: space-between; margin-bottom: 4px">
            <div class="panel-label" style="margin: 0">{{ t('session.workspaceChanges') }}</div>
            <span class="badge" :class="changeCount ? 'warn' : 'good'">{{ changeCount }}</span>
          </div>
          <button v-if="changeCount" class="btn sm" style="width: 100%" @click="pickDiff('')">
            <Icon name="git" :size="13" /> {{ t('session.viewFullDiff') }}
          </button>
          <button v-for="change in state.changes" :key="change.path" class="change-row" @click="pickDiff(change.path)">
            <span class="badge" :class="statusMap[change.status]?.cls || ''">{{ statusMap[change.status]?.label || change.status }}</span>
            <span class="mono truncate" style="font-size: 11px">{{ change.path }}</span>
            <Icon name="chevron-right" :size="12" style="margin-left: auto; color: var(--faint)" />
          </button>
          <div v-if="!changeCount" class="tiny faint" style="padding: 12px 2px">{{ t('session.noChanges') }}</div>
        </div>
      </template>

      <template v-else>
        <div class="artifacts-panel">
          <div class="panel-label">{{ t('session.generatedOutputs') }}</div>
          <div v-for="artifact in state.artifacts" :key="artifact.id" class="artifact-card">
            <div class="artifact-icon">
              <Icon :name="artifact.kind === 'plan' ? 'document' : artifact.kind === 'storyboard' ? 'video' : 'file'" :size="15" />
            </div>
            <div class="artifact-copy">
              <span class="truncate">{{ artifact.name }}</span>
              <span class="tiny faint">{{ t(`artifact.${artifact.kind}`, {}, artifact.kind) }} · {{ sizeLabel(artifact.size) }}</span>
            </div>
            <button class="icon-btn" :title="t('common.open')" @click="openArtifact(artifact)">
              <Icon name="external" :size="13" />
            </button>
          </div>
          <div v-if="!state.artifacts.length" class="tiny faint" style="padding: 12px 2px">
            {{ t('session.generatedHint') }}
          </div>
        </div>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.right-panel { display: flex; flex-direction: column; min-height: 0; border-left: 1px solid var(--line); background: color-mix(in srgb, var(--surface) 62%, transparent); backdrop-filter: blur(14px); }
.right-tabs { display: flex; gap: 2px; padding: 9px 8px 0; border-bottom: 1px solid var(--line); overflow-x: auto; }
.right-tab { display: flex; align-items: center; gap: 5px; height: 33px; padding: 0 9px; border: none; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); font-size: 11.5px; white-space: nowrap; }
.right-tab:hover { color: var(--ink); }
.right-tab.active { color: var(--ink); border-bottom-color: var(--brand); }
.tab-count { font-size: 9px; min-width: 14px; height: 14px; padding: 0 3px; border-radius: 99px; background: var(--surface-3); color: var(--muted); display: inline-grid; place-items: center; }
.right-body { flex: 1; min-height: 0; overflow-y: auto; padding: 15px 14px 24px; }
.overview-head { padding-bottom: 13px; border-bottom: 1px solid var(--line); }
.overview-title { font-size: 14px; font-weight: 640; letter-spacing: -.01em; margin-top: 3px; }
.info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; margin: 13px 0; }
.info-cell { background: var(--surface); padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.info-cell span { font-size: 9.5px; text-transform: uppercase; letter-spacing: .08em; color: var(--faint); }
.info-cell b { font-size: 11.5px; font-weight: 560; color: var(--ink-2); }
.overview-block { margin: 14px 0; }
.panel-label { font-size: 9.5px; text-transform: uppercase; letter-spacing: .11em; color: var(--faint); font-weight: 650; margin-bottom: 7px; }
.workspace-line { font-size: 10.5px; color: var(--muted); background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; }
.route-line { display: flex; gap: 5px; font-size: 11.5px; color: var(--muted); }
.notice-row { display: flex; gap: 7px; font-size: 11px; color: var(--muted); padding: 3px 0; line-height: 1.45; }
.notice-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--brand); margin-top: 6px; flex: 0 0 5px; }
.notice-dot.repair { background: var(--warn); }
.notice-dot.context { background: var(--good); }
.change-row, .artifact-card { width: 100%; display: flex; align-items: center; gap: 7px; padding: 7px 8px; border-radius: 8px; border: 1px solid transparent; background: transparent; color: var(--ink-2); text-align: left; }
.change-row:hover, .artifact-card:hover { background: var(--surface-2); border-color: var(--line); }
.change-row .badge { min-width: 22px; justify-content: center; padding: 0 5px; }
.artifact-card { margin-bottom: 3px; }
.artifact-icon { width: 28px; height: 28px; border-radius: 8px; background: var(--brand-soft); color: var(--brand); display: grid; place-items: center; flex: 0 0 28px; }
.artifact-copy { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; font-size: 11.5px; }
</style>
