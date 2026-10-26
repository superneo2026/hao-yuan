<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { openDiff, renameSession, state } from '../stores/app'
import { kindLabel, t } from '../i18n'
import ApprovalCard from '../components/ApprovalCard.vue'
import ChatTimeline from '../components/ChatTimeline.vue'
import Composer from '../components/Composer.vue'
import DiffView from '../components/DiffView.vue'
import FileViewer from '../components/FileViewer.vue'
import Icon from '../components/Icon.vue'
import LanguageSelect from '../components/LanguageSelect.vue'
import RightPanel from '../components/RightPanel.vue'
import StatusPill from '../components/StatusPill.vue'

const router = useRouter()
const composer = ref(null)
const RIGHT_PANEL_KEY = 'hy.rightOpen.v2'
const rightOpen = ref(window.innerWidth > 960 && localStorage.getItem(RIGHT_PANEL_KEY) === '1')
const rightWidth = ref(Number(localStorage.getItem('hy.rightWidth') || 370))
const fileOpen = ref(false)
const diffOpen = ref(false)

const session = computed(() => state.session)

function toggleRight() {
  rightOpen.value = !rightOpen.value
  localStorage.setItem(RIGHT_PANEL_KEY, rightOpen.value ? '1' : '0')
}

function startResize(event) {
  const startX = event.clientX
  const startWidth = rightWidth.value
  function move(moveEvent) {
    const next = Math.max(290, Math.min(620, startWidth + (startX - moveEvent.clientX)))
    rightWidth.value = next
  }
  function up() {
    localStorage.setItem('hy.rightWidth', String(rightWidth.value))
    window.removeEventListener('mousemove', move)
    window.removeEventListener('mouseup', up)
  }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

function suggest(text) {
  composer.value?.fill(text)
}

async function editTitle() {
  if (!session.value) return
  const title = window.prompt(t('session.renamePrompt'), session.value.title || '')
  if (title) await renameSession(title.trim())
}

function openNew() {
  state.newTaskOpen = true
}

function goConsole() {
  router.push('/console')
}

function onOpenFile() {
  fileOpen.value = true
}

function onOpenDiff(path) {
  if (typeof path === 'string' && path !== undefined) openDiff(path)
  diffOpen.value = true
}

function closeFile() {
  fileOpen.value = false
}

function closeDiff() {
  diffOpen.value = false
}
</script>

<template>
  <div class="workbench">
    <header class="topbar">
      <button class="icon-btn mobile-menu" :title="t('nav.menu')" @click="state.mobileNavOpen = !state.mobileNavOpen">
        <Icon name="menu" :size="18" />
      </button>
      <div class="topbar-left">
        <div class="topbar-title" @click="editTitle" :title="t('session.clickToRename')">
          {{ session?.title || t('session.workbenchTitle') }}
        </div>
        <div class="topbar-meta">
          <StatusPill v-if="session" :status="session.status" />
          <span v-if="session" class="badge">{{ kindLabel(session.kind) }}</span>
          <span v-if="session?.workspace" class="tiny faint mono truncate topbar-workspace">{{ session.workspace }}</span>
        </div>
      </div>
      <div class="spacer" />
      <div class="topbar-actions">
        <LanguageSelect />
        <button class="btn sm" :title="t('nav.newTask')" @click="openNew"><Icon name="plus" :size="14" /><span class="hide-sm">{{ t('nav.newTask') }}</span></button>
        <button class="icon-btn console-btn" :title="t('nav.console')" @click="goConsole"><Icon name="activity" :size="17" /></button>
        <button class="icon-btn" :class="{ active: rightOpen }" :title="t('session.togglePanel')" @click="toggleRight">
          <Icon name="panel" :size="17" />
        </button>
      </div>
    </header>

    <div v-if="!session" class="no-session">
      <div class="empty-state">
        <div class="empty-inner">
          <div class="welcome-mark">
            <span class="brand-mark" style="width: 60px; height: 60px; border-radius: 18px; font-size: 26px">H</span>
          </div>
          <h2>{{ t('session.commandTeamTitle') }}</h2>
          <p>{{ t('session.commandTeamDesc') }}</p>
          <div class="row" style="justify-content: center; gap: 9px">
            <button class="btn primary lg" @click="openNew"><Icon name="plus" :size="16" /> {{ t('nav.newTask') }}</button>
            <button class="btn lg" @click="goConsole"><Icon name="activity" :size="16" /> {{ t('session.openConsole') }}</button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="workbench-body" :style="{ gridTemplateColumns: rightOpen ? `minmax(0, 1fr) ${rightWidth}px` : 'minmax(0, 1fr)' }">
      <section class="main-column">
        <ChatTimeline @suggest="suggest" />
        <ApprovalCard />
        <Composer ref="composer" />
      </section>
      <template v-if="rightOpen">
        <div class="resizer" @mousedown.prevent="startResize" />
        <RightPanel @open-file="onOpenFile" @open-diff="onOpenDiff" />
      </template>
    </div>
    <div v-if="rightOpen" class="right-backdrop" @click="toggleRight" />

    <Teleport to="body">
      <div v-if="fileOpen && session" class="overlay file-overlay" @mousedown.self="closeFile">
        <div class="file-modal">
          <div class="file-modal-head">
            <div class="row" style="gap: 8px">
              <Icon name="code" :size="16" style="color: var(--brand)" />
              <b>{{ t('session.filePreview') }}</b>
              <span class="tiny faint">{{ t('common.readOnly') }}</span>
            </div>
            <div class="spacer" />
            <button class="icon-btn" @click="closeFile"><Icon name="close" :size="16" /></button>
          </div>
          <div class="file-modal-body">
            <FileViewer :file="state.fileContent" :loading="state.busy.loadingFile" @diff="onOpenDiff" />
          </div>
        </div>
      </div>
      <div v-if="diffOpen && session" class="overlay file-overlay" @mousedown.self="closeDiff">
        <div class="file-modal">
          <div class="file-modal-head">
            <div class="row" style="gap: 8px">
              <Icon name="git" :size="16" style="color: var(--brand)" />
              <b>{{ t('session.diff') }}</b>
              <span class="tiny faint">{{ session.workspace }}</span>
            </div>
            <div class="spacer" />
            <button class="icon-btn" @click="closeDiff"><Icon name="close" :size="16" /></button>
          </div>
          <div class="file-modal-body">
            <DiffView :diff="state.diffText" :path="state.diffPath" />
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.workbench { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.topbar { height: var(--topbar-h); flex: 0 0 var(--topbar-h); display: flex; align-items: center; gap: 10px; padding: 0 16px; border-bottom: 1px solid var(--line); background: color-mix(in srgb, var(--surface) 55%, transparent); backdrop-filter: blur(14px); }
.mobile-menu { display: none; }
.topbar-left { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.topbar-title { font-size: 13.5px; font-weight: 620; letter-spacing: -.01em; cursor: pointer; max-width: 380px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.topbar-title:hover { color: var(--brand); }
.topbar-meta { display: flex; align-items: center; gap: 6px; min-width: 0; }
.topbar-meta .badge { height: 18px; font-size: 9.5px; padding: 0 6px; }
.topbar-workspace { max-width: 280px; }
.topbar-actions { display: flex; align-items: center; gap: 6px; }
.workbench-body { flex: 1; min-height: 0; display: grid; }
.main-column { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.resizer { width: 5px; cursor: col-resize; background: transparent; position: relative; z-index: 4; }
.resizer:hover { background: var(--brand-line); }
.no-session { flex: 1; min-height: 0; display: grid; place-items: center; }
.file-overlay { align-items: center; padding: 24px; }
.file-modal { width: min(1280px, calc(100vw - 48px)); height: min(880px, calc(100vh - 64px)); display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--line-strong); border-radius: 18px; box-shadow: var(--shadow-soft); overflow: hidden; animation: slide-up .2s var(--ease); }
.file-modal-head { display: flex; align-items: center; gap: 8px; padding: 11px 14px; border-bottom: 1px solid var(--line); }
.file-modal-body { flex: 1; min-height: 0; padding: 12px; }
.hide-sm { display: inline; }
.right-backdrop { display: none; }
@media (max-width: 960px) {
  .workbench-body { grid-template-columns: minmax(0, 1fr) !important; }
  .resizer { display: none; }
  .right-panel {
    position: fixed; top: 0; right: 0; bottom: 0;
    width: min(390px, 92vw); z-index: 78;
    background: var(--surface); box-shadow: var(--shadow-soft);
    border-left: 1px solid var(--line-strong);
  }
  .right-backdrop {
    display: block; position: fixed; inset: 0; z-index: 77;
    background: rgba(4, 6, 10, .5); backdrop-filter: blur(2px);
  }
  .mobile-menu { display: inline-grid; }
  .hide-sm { display: none; }
}
@media (max-width: 640px) {
  .topbar-meta { display: none; }
  .topbar-title { max-width: 46vw; }
  .console-btn { display: none; }
}
</style>
