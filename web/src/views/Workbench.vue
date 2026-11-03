<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { closeSessionTab, openDiff, renameSession, selectSession, startNewTask, state } from '../stores/app'
import { kindLabel, sessionTitle, t } from '../i18n'
import AccountMenu from '../components/AccountMenu.vue'
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
const isMac = /Mac|iPhone|iPad/.test(navigator.platform)
const shortcutLabel = isMac ? '⌘ N' : 'Ctrl N'
const RIGHT_PANEL_KEY = 'hy.rightOpen.v2'
const rightOpen = ref(window.innerWidth > 960 && localStorage.getItem(RIGHT_PANEL_KEY) === '1')
const rightWidth = ref(Number(localStorage.getItem('hy.rightWidth') || 370))
const fileOpen = ref(false)
const diffOpen = ref(false)

const session = computed(() => state.session)
const currentTitle = computed(() => (session.value ? sessionTitle(session.value) : t('session.workbenchTitle')))
const tabsRef = ref(null)
const tabs = computed(() =>
  state.openSessionIds
    .map((id) => state.sessions.find((item) => item.id === id))
    .filter(Boolean)
)

watch(
  () => state.currentId,
  async (id) => {
    await nextTick()
    const el = Array.from(tabsRef.value?.children || []).find((node) => node.dataset.tabId === id)
    if (el) el.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }
)

function openTab(tab) {
  if (tab.id === state.currentId) return
  selectSession(tab.id)
  router.push(`/s/${encodeURIComponent(tab.id)}`)
}

function closeTab(id) {
  closeSessionTab(id)
}

function onTabsWheel(event) {
  const el = event.currentTarget
  if (!el || el.scrollWidth <= el.clientWidth) return
  if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return
  el.scrollLeft += event.deltaY
  event.preventDefault()
}

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

async function editTitle() {
  if (!session.value) return
  const title = window.prompt(t('session.renamePrompt'), currentTitle.value)
  if (title) await renameSession(title.trim())
}

async function openNew() {
  const session = await startNewTask()
  if (session) router.push(`/s/${encodeURIComponent(session.id)}`)
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
        <div class="topbar-title-row">
          <div class="topbar-title" @click="editTitle" :title="t('session.clickToRename')">
            {{ currentTitle }}
          </div>
          <button
            type="button"
            class="new-chat-btn"
            :title="`${t('nav.newTask')} (${shortcutLabel})`"
            :aria-label="`${t('nav.newTask')} (${shortcutLabel})`"
            @click="openNew"
          >
            <Icon name="plus" :size="13" />
          </button>
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
        <AccountMenu v-if="state.auth.authenticated" />
      </div>
    </header>

    <div v-if="tabs.length" ref="tabsRef" class="session-tabs" role="tablist" @wheel="onTabsWheel">
      <div
        v-for="tab in tabs"
        :key="tab.id"
        class="session-tab"
        :class="{ active: tab.id === state.currentId }"
        role="tab"
        tabindex="0"
        :aria-selected="tab.id === state.currentId"
        :data-tab-id="tab.id"
        :title="sessionTitle(tab)"
        @click="openTab(tab)"
        @keydown.enter.prevent="openTab(tab)"
        @keydown.space.prevent="openTab(tab)"
      >
        <span class="status-dot" :class="tab.status === 'waiting_input' ? 'waiting' : tab.status" />
        <span class="tab-title truncate">{{ sessionTitle(tab) }}</span>
        <button
          type="button"
          class="tab-close"
          :title="t('session.closeTab')"
          :aria-label="`${t('session.closeTab')}: ${sessionTitle(tab)}`"
          @click.stop="closeTab(tab.id)"
          @keydown.enter.stop
          @keydown.space.stop
        >
          <Icon name="close" :size="11" />
        </button>
      </div>
    </div>

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
        <ChatTimeline />
        <ApprovalCard />
        <Composer />
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
.topbar { position: relative; z-index: 60; height: var(--topbar-h); flex: 0 0 var(--topbar-h); display: flex; align-items: center; gap: 10px; padding: 0 16px; border-bottom: 1px solid var(--line); background: color-mix(in srgb, var(--surface) 55%, transparent); backdrop-filter: blur(14px); }
.mobile-menu { display: none; }
.topbar-left { min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.topbar-title-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.topbar-title { font-size: 13.5px; font-weight: 620; letter-spacing: -.01em; cursor: pointer; max-width: 380px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.topbar-title:hover { color: var(--brand); }
.new-chat-btn {
  display: inline-grid;
  place-items: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border-radius: 6px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--muted);
  flex: 0 0 auto;
  cursor: pointer;
  transition: color .14s var(--ease), border-color .14s var(--ease), background .14s var(--ease);
}
.new-chat-btn:hover { color: var(--ink); border-color: var(--brand-line); background: var(--surface-3); }
.topbar-meta { display: flex; align-items: center; gap: 6px; min-width: 0; }
.topbar-meta .badge { height: 18px; font-size: 9.5px; padding: 0 6px; }
.topbar-workspace { max-width: 280px; }
.topbar-actions { display: flex; align-items: center; gap: 6px; }
.session-tabs {
  flex: 0 0 auto; display: flex; align-items: center; gap: 6px;
  padding: 6px 16px; border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 70%, transparent);
  overflow-x: auto; overflow-y: hidden; scrollbar-width: thin;
}
.session-tabs::-webkit-scrollbar { height: 4px; }
.session-tabs::-webkit-scrollbar-thumb { background: var(--line-strong); border-radius: 999px; }
.session-tab {
  display: inline-flex; align-items: center; gap: 7px; flex: 0 0 auto;
  max-width: 220px; height: 28px; padding: 0 8px 0 10px;
  border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2);
  color: var(--muted); font-size: 11.5px; cursor: pointer;
  transition: background .15s var(--ease), border-color .15s var(--ease), color .15s var(--ease);
}
.session-tab:hover { background: var(--surface); border-color: var(--line-strong); color: var(--ink-2); }
.session-tab.active { background: var(--brand-soft); border-color: var(--brand-line); color: var(--brand); }
.session-tab .tab-title { max-width: 160px; }
.session-tab.active .tab-title { color: var(--ink); font-weight: 600; }
.session-tab .status-dot { flex: 0 0 5px; width: 5px; height: 5px; }
.session-tab .tab-close { display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 5px; color: var(--faint); opacity: .55; background: none; border: 0; padding: 0; font: inherit; cursor: pointer; }
.session-tab:hover .tab-close, .session-tab.active .tab-close { opacity: 1; }
.session-tab .tab-close:hover { background: color-mix(in srgb, var(--bad) 14%, transparent); color: var(--bad); }
.session-tab:focus-visible, .session-tab .tab-close:focus-visible { outline: 2px solid var(--brand); outline-offset: 1px; }
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
  .session-tabs { padding: 6px 10px; }
  .session-tab { max-width: 168px; }
  .session-tab .tab-title { max-width: 112px; }
}
</style>
