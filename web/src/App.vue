<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { boot, closePalette, openPalette, setTheme, state, toggleSidebar } from './stores/app'
import { t } from './i18n'
import CommandPalette from './components/CommandPalette.vue'
import Icon from './components/Icon.vue'
import LanguageSelect from './components/LanguageSelect.vue'
import NewTaskModal from './components/NewTaskModal.vue'
import SessionList from './components/SessionList.vue'
import ToastStack from './components/ToastStack.vue'

const router = useRouter()

const navItems = [
  { path: '/', labelKey: 'nav.workbench', icon: 'terminal' },
  { path: '/console', labelKey: 'nav.console', icon: 'activity' },
  { path: '/orchestrator', labelKey: 'nav.orchestrator', icon: 'network' },
  { path: '/skills', labelKey: 'nav.skills', icon: 'sparkles' },
  { path: '/plugins', labelKey: 'nav.plugins', icon: 'puzzle' },
  { path: '/usage', labelKey: 'nav.usage', icon: 'chart' }
]

const connectionLabel = computed(() => {
  if (state.connection === 'connected') return t('conn.live')
  if (state.connection === 'connecting') return t('conn.connecting')
  return t('conn.offline')
})

function newTask() {
  state.newTaskOpen = true
}

function onGlobalKey(event) {
  const meta = event.metaKey || event.ctrlKey
  if (meta && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    openPalette()
  } else if (meta && event.key.toLowerCase() === 'n') {
    event.preventDefault()
    newTask()
  } else if (meta && event.key.toLowerCase() === 'b') {
    event.preventDefault()
    toggleSidebar()
  } else if (event.key === 'Escape') {
    closePalette()
    state.mobileNavOpen = false
    if (state.newTaskOpen) state.newTaskOpen = false
  }
}

onMounted(() => {
  boot()
  window.addEventListener('keydown', onGlobalKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey))
</script>

<template>
  <div class="app-shell" :class="{ 'sidebar-collapsed': state.sidebarCollapsed, 'mobile-nav-open': state.mobileNavOpen }">
    <aside class="sidebar">
      <div class="sidebar-head">
        <div class="brand-mark">H</div>
        <div class="brand-text">
          <b>{{ t('app.title') }}</b>
          <span>{{ t('app.tagline') }}</span>
        </div>
        <button
          class="icon-btn collapse-btn"
          :title="state.sidebarCollapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')"
          @click="toggleSidebar"
        >
          <Icon :name="state.sidebarCollapsed ? 'chevron-right' : 'panel'" :size="15" />
        </button>
      </div>

      <div style="padding: 0 12px 8px">
        <button class="btn primary new-task-btn" style="width: 100%" :title="t('nav.newTask')" @click="newTask">
          <Icon name="plus" :size="15" /> <span class="new-task-label">{{ t('nav.newTask') }}</span>
          <span class="new-task-kbd">⌘N</span>
        </button>
      </div>

      <div class="sidebar-scroll">
        <nav class="nav-section">
          <router-link v-for="item in navItems" :key="item.path" :to="item.path" class="nav-link" @click="state.mobileNavOpen = false">
            <Icon :name="item.icon" :size="16" class="icon" />
            <span>{{ t(item.labelKey) }}</span>
          </router-link>
          <router-link to="/settings" class="nav-link" @click="state.mobileNavOpen = false">
            <Icon name="settings" :size="16" class="icon" />
            <span>{{ t('nav.settings') }}</span>
          </router-link>
        </nav>

        <div class="sidebar-divider" />

        <SessionList @new="newTask" />
      </div>

      <div class="sidebar-foot">
        <span class="status-dot" :class="state.connection === 'connected' ? 'done' : state.connection === 'connecting' ? 'running' : 'error'" />
        <span class="foot-text tiny muted">{{ connectionLabel }}</span>
        <span class="spacer" />
        <LanguageSelect :compact="state.sidebarCollapsed" drop-up />
        <button class="icon-btn" :title="state.theme === 'dark' ? t('nav.switchLight') : t('nav.switchDark')" @click="setTheme(state.theme === 'dark' ? 'light' : 'dark')">
          <Icon :name="state.theme === 'dark' ? 'sun' : 'moon'" :size="15" />
        </button>
        <button class="icon-btn" :title="t('nav.commandPalette')" @click="openPalette">
          <Icon name="command" :size="15" />
        </button>
      </div>
    </aside>

    <main class="main">
      <router-view />
    </main>
  </div>

  <div v-if="state.mobileNavOpen" class="mobile-backdrop" @click="state.mobileNavOpen = false" />

  <CommandPalette />
  <ToastStack />
  <NewTaskModal v-if="state.newTaskOpen" @close="state.newTaskOpen = false" />
</template>

<style scoped>
.main { min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.collapse-btn { margin-left: auto; }
.sidebar-divider { height: 1px; background: var(--line); margin: 12px 10px; }
.new-task-btn { position: relative; }
.new-task-kbd { margin-left: auto; font-family: var(--font-mono); font-size: 9px; opacity: .7; }
.mobile-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 65; display: none; }
.sidebar-collapsed .brand-text, .sidebar-collapsed .nav-link span, .sidebar-collapsed .new-task-label, .sidebar-collapsed .new-task-kbd { display: none; }
.sidebar-collapsed .sidebar-head { flex-direction: column; justify-content: center; gap: 8px; padding: 14px 8px 10px; }
.sidebar-collapsed .collapse-btn { display: inline-grid; margin-left: 0; width: 38px; height: 28px; border: 1px solid var(--line); background: var(--surface-2); }
.sidebar-collapsed .nav-link { justify-content: center; }
.sidebar-collapsed .new-task-btn { padding: 0; }
.sidebar-collapsed .sidebar-foot { flex-direction: column; gap: 7px; padding: 10px 8px; }
.sidebar-collapsed .sidebar-foot .spacer { display: none; }
.sidebar-collapsed .sidebar-foot .foot-text { display: none; }
@media (max-width: 640px) {
  .mobile-backdrop { display: block; }
}
</style>
