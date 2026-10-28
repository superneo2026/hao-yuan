<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  authBlocked,
  boot,
  closePalette,
  markUnauthorized,
  openPalette,
  selectSession,
  setTheme,
  state,
  togglePluginNav,
  toggleRemoteNav,
  toggleSidebar
} from './stores/app'
import { t } from './i18n'
import AppTopbar from './components/AppTopbar.vue'
import AuthGate from './components/AuthGate.vue'
import CommandPalette from './components/CommandPalette.vue'
import Icon from './components/Icon.vue'
import LanguageSelect from './components/LanguageSelect.vue'
import NewTaskModal from './components/NewTaskModal.vue'
import SessionList from './components/SessionList.vue'
import ToastStack from './components/ToastStack.vue'
import UserAccountModal from './components/UserAccountModal.vue'

const router = useRouter()
const route = useRoute()

watch(
  () => state.currentId,
  (id) => {
    if (!id) {
      if (route.name === 'session') router.replace('/')
      return
    }
    if (route.name !== 'workbench' && route.name !== 'session') return
    const target = `/s/${encodeURIComponent(id)}`
    if (route.fullPath !== target) router.replace(target)
  }
)

watch(
  () => route.fullPath,
  () => {
    const id = typeof route.params.id === 'string' ? route.params.id : ''
    if (route.name === 'session') {
      if (id && id !== state.currentId) selectSession(id, false)
      return
    }
    if (route.name === 'workbench' && !id && state.currentId) {
      router.replace(`/s/${encodeURIComponent(state.currentId)}`)
    }
  }
)

const navItems = [
  { path: '/', labelKey: 'nav.workbench', icon: 'terminal' },
  { path: '/console', labelKey: 'nav.console', icon: 'activity' },
  {
    key: 'plugins',
    labelKey: 'nav.plugins',
    icon: 'puzzle',
    children: [
      { path: '/plugins', name: 'plugins', labelKey: 'plugins.tabInstalled', icon: 'puzzle' },
      { path: '/plugins/center', name: 'plugin-center', labelKey: 'plugins.tabMarket', icon: 'cloud' }
    ]
  },
  { path: '/orchestrator', labelKey: 'nav.orchestrator', icon: 'network' },
  { path: '/skills', labelKey: 'nav.skills', icon: 'sparkles' },
  { path: '/usage', labelKey: 'nav.usage', icon: 'chart' }
]

const pluginGroupActive = computed(() => ['plugins', 'plugin-center'].includes(route.name))
const showTopbar = computed(() => !['workbench', 'session'].includes(route.name))
const remoteReady = computed(() => state.remote.enabled)
const remoteSystems = computed(() => state.remote.outgoing || [])
const remoteGroupActive = computed(() => ['remote', 'remote-system'].includes(route.name))

function onPluginParent() {
  if (state.sidebarCollapsed) router.push('/plugins')
  else togglePluginNav()
}

function onRemoteParent() {
  if (state.sidebarCollapsed) router.push('/remote')
  else toggleRemoteNav()
}

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
  window.addEventListener('hy:unauthorized', markUnauthorized)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKey)
  window.removeEventListener('hy:unauthorized', markUnauthorized)
})
</script>

<template>
  <AuthGate v-if="authBlocked || state.authSetupOpen" />

  <div v-else class="app-shell" :class="{ 'sidebar-collapsed': state.sidebarCollapsed, 'mobile-nav-open': state.mobileNavOpen }">
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
          <div class="nav-label">{{ t('nav.workspace') }}</div>
          <template v-for="item in navItems" :key="item.key || item.path">
            <router-link
              v-if="!item.children"
              :to="item.path"
              class="nav-link"
              :class="{ 'router-link-active': item.path === '/' && route.name === 'session' }"
              @click="state.mobileNavOpen = false"
            >
              <Icon :name="item.icon" :size="16" class="icon" />
              <span>{{ t(item.labelKey) }}</span>
            </router-link>
            <div v-else class="nav-group">
              <button
                type="button"
                class="nav-link nav-parent"
                :class="{ 'router-link-active': pluginGroupActive }"
                @click="onPluginParent"
              >
                <Icon :name="item.icon" :size="16" class="icon" />
                <span>{{ t(item.labelKey) }}</span>
                <Icon class="nav-caret" :class="{ open: state.pluginNavOpen }" name="chevron-down" :size="13" />
              </button>
              <div v-show="state.pluginNavOpen" class="nav-sub">
                <router-link
                  v-for="child in item.children"
                  :key="child.path"
                  :to="child.path"
                  class="nav-link nav-sublink"
                  active-class="nav-prefix"
                  exact-active-class="router-link-active"
                  @click="state.mobileNavOpen = false"
                >
                  <Icon :name="child.icon" :size="14" class="icon" />
                  <span>{{ t(child.labelKey) }}</span>
                </router-link>
              </div>
            </div>
          </template>
          <router-link to="/settings" class="nav-link" @click="state.mobileNavOpen = false">
            <Icon name="settings" :size="16" class="icon" />
            <span>{{ t('nav.settings') }}</span>
          </router-link>
          <div v-if="remoteReady" class="nav-group remote-nav-group">
            <button
              type="button"
              class="nav-link nav-parent"
              :class="{ 'router-link-active': remoteGroupActive }"
              @click="onRemoteParent"
            >
              <Icon name="globe" :size="16" class="icon" />
              <span>{{ t('nav.remote') }}</span>
              <Icon class="nav-caret" :class="{ open: state.remoteNavOpen }" name="chevron-down" :size="13" />
            </button>
            <div v-show="state.remoteNavOpen" class="nav-sub">
              <router-link
                to="/remote"
                class="nav-link nav-sublink"
                exact-active-class="router-link-active"
                @click="state.mobileNavOpen = false"
              >
                <Icon name="network" :size="14" class="icon" />
                <span>{{ t('remote.overview') }}</span>
              </router-link>
              <router-link
                v-for="system in remoteSystems"
                :key="system.id"
                :to="`/remote/system/${system.id}`"
                class="nav-link nav-sublink"
                active-class="nav-prefix"
                exact-active-class="router-link-active"
                @click="state.mobileNavOpen = false"
              >
                <span class="remote-status-dot" :class="system.status" />
                <span class="remote-nav-name">{{ system.name || system.target_name || system.url }}</span>
              </router-link>
            </div>
          </div>
        </nav>

        <div class="sidebar-divider" />

        <SessionList @new="newTask" />
      </div>

      <div class="sidebar-foot">
        <span class="status-dot" :class="state.connection === 'connected' ? 'done' : state.connection === 'connecting' ? 'running' : 'error'" />
        <span class="foot-text tiny muted">{{ connectionLabel }}</span>
        <span class="spacer" />
        <template v-if="!showTopbar">
          <LanguageSelect :compact="state.sidebarCollapsed" drop-up />
          <button class="icon-btn" :title="state.theme === 'dark' ? t('nav.switchLight') : t('nav.switchDark')" @click="setTheme(state.theme === 'dark' ? 'light' : 'dark')">
            <Icon :name="state.theme === 'dark' ? 'sun' : 'moon'" :size="15" />
          </button>
          <button class="icon-btn" :title="t('nav.commandPalette')" @click="openPalette">
            <Icon name="command" :size="15" />
          </button>
        </template>
      </div>
    </aside>

    <main class="main">
      <AppTopbar v-if="showTopbar" />
      <div class="main-view">
        <router-view />
      </div>
    </main>
  </div>

  <div v-if="state.mobileNavOpen" class="mobile-backdrop" @click="state.mobileNavOpen = false" />

  <CommandPalette />
  <ToastStack />
  <NewTaskModal v-if="state.newTaskOpen" @close="state.newTaskOpen = false" />
  <UserAccountModal v-if="state.accountOpen" @close="state.accountOpen = false" />
</template>

<style scoped>
.main { min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.main-view { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.collapse-btn { margin-left: auto; }

.sidebar {
  background:
    radial-gradient(520px 300px at 0% 0%, color-mix(in srgb, var(--brand) 10%, transparent), transparent 62%),
    radial-gradient(380px 260px at 100% 100%, color-mix(in srgb, var(--brand-2) 6%, transparent), transparent 60%),
    linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, transparent), color-mix(in srgb, var(--bg-2) 88%, transparent));
  box-shadow: inset -1px 0 0 color-mix(in srgb, #fff 5%, transparent);
}
.sidebar-head { padding: 20px 16px 14px; gap: 12px; }
.brand-mark {
  border-radius: 13px;
  box-shadow: 0 12px 32px color-mix(in srgb, var(--brand) 38%, transparent);
}
.brand-text b { font-size: 15.5px; letter-spacing: -.02em; }
.brand-text span { font-size: 9.5px; letter-spacing: .15em; text-transform: uppercase; color: var(--faint); }
.collapse-btn { width: 30px; height: 30px; }

.new-task-btn {
  position: relative;
  height: 42px;
  border-radius: 13px;
  font-size: 13px;
  letter-spacing: .01em;
  box-shadow: 0 14px 32px color-mix(in srgb, var(--brand) 30%, transparent);
  overflow: hidden;
}
.new-task-btn::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(110deg, transparent 22%, rgba(255, 255, 255, .22) 48%, transparent 72%);
  transform: translateX(-120%);
  transition: transform .55s var(--ease);
}
.new-task-btn:hover::after { transform: translateX(120%); }
.new-task-kbd { margin-left: auto; font-family: var(--font-mono); font-size: 9px; opacity: .72; }

.nav-section { margin: 10px 0 6px; }
.nav-label {
  padding: 2px 12px 8px;
  font-size: 9.5px;
  letter-spacing: .18em;
  color: var(--faint);
}
.nav-link {
  position: relative;
  min-height: 40px;
  padding: 8px 11px;
  border-radius: 11px;
  font-size: 13px;
  font-weight: 560;
  color: var(--ink-2);
  transition: background .16s var(--ease), color .16s var(--ease), border-color .16s var(--ease), transform .16s var(--ease);
}
.nav-link .icon { width: 17px; height: 17px; color: var(--muted); transition: color .16s var(--ease); }
.nav-link:hover { background: color-mix(in srgb, var(--surface-2) 84%, transparent); color: var(--ink); border-color: transparent; }
.nav-link.router-link-active {
  background: linear-gradient(110deg, color-mix(in srgb, var(--brand) 15%, transparent), color-mix(in srgb, var(--brand-2) 7%, transparent));
  border-color: color-mix(in srgb, var(--brand) 26%, var(--line));
  color: var(--ink);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .07), 0 10px 26px color-mix(in srgb, var(--brand) 10%, transparent);
}
.nav-link.router-link-active::before {
  content: "";
  position: absolute;
  left: -1px;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 3px;
  background: linear-gradient(var(--brand), var(--brand-2));
  box-shadow: 0 0 14px color-mix(in srgb, var(--brand) 70%, transparent);
}
.nav-link.router-link-active .icon { color: var(--brand); }

.nav-group { display: flex; flex-direction: column; }
.nav-parent { width: 100%; background: transparent; text-align: left; cursor: pointer; font-family: inherit; }
.nav-caret { margin-left: auto; color: var(--faint); transition: transform .18s var(--ease); }
.nav-caret.open { transform: rotate(180deg); }
.nav-sub {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin: 4px 0 6px 18px;
  padding-left: 11px;
  border-left: 1px solid var(--line);
}
.nav-sublink { min-height: 34px; padding: 7px 10px; font-size: 12.5px; border-radius: 9px; }
.nav-sublink .icon { width: 15px; height: 15px; }
.nav-sublink:hover { background: color-mix(in srgb, var(--surface-2) 75%, transparent); }
.nav-sublink.router-link-active {
  background: color-mix(in srgb, var(--brand) 11%, transparent);
  border-color: transparent;
  color: var(--brand);
  box-shadow: none;
}
.nav-sublink.router-link-active::before { display: none; }
.nav-sublink.router-link-active .icon { color: var(--brand); }
.remote-nav-group { margin-top: 4px; }
.remote-nav-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.remote-status-dot {
  width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%;
  background: var(--faint);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--faint) 15%, transparent);
}
.remote-status-dot.approved { background: var(--good); box-shadow: 0 0 0 3px color-mix(in srgb, var(--good) 16%, transparent); }
.remote-status-dot.pending { background: var(--warn); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 16%, transparent); }
.remote-status-dot.revoked, .remote-status-dot.rejected { background: var(--bad); box-shadow: 0 0 0 3px color-mix(in srgb, var(--bad) 16%, transparent); }

.sidebar-divider { height: 1px; background: var(--line); margin: 14px 10px; }
.sidebar-foot {
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 55%, transparent);
  backdrop-filter: blur(12px);
  padding: 12px 14px;
}
.sidebar-foot .icon-btn { width: 30px; height: 30px; }

.mobile-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 65; display: none; }
.sidebar-collapsed .brand-text, .sidebar-collapsed .nav-link span, .sidebar-collapsed .new-task-label, .sidebar-collapsed .new-task-kbd, .sidebar-collapsed .nav-label { display: none; }
.sidebar-collapsed .sidebar-head { flex-direction: column; justify-content: center; gap: 8px; padding: 14px 8px 10px; }
.sidebar-collapsed .collapse-btn { display: inline-grid; margin-left: 0; width: 38px; height: 28px; border: 1px solid var(--line); background: var(--surface-2); }
.sidebar-collapsed .nav-link { justify-content: center; padding: 9px 0; }
.sidebar-collapsed .nav-link.router-link-active::before { top: 12px; bottom: 12px; }
.sidebar-collapsed .nav-sub, .sidebar-collapsed .nav-caret { display: none; }
.sidebar-collapsed .nav-parent { justify-content: center; padding: 9px 0; }
.sidebar-collapsed .new-task-btn { padding: 0; }
.sidebar-collapsed .sidebar-foot { flex-direction: column; gap: 7px; padding: 10px 8px; }
.sidebar-collapsed .sidebar-foot .spacer { display: none; }
.sidebar-collapsed .sidebar-foot .foot-text { display: none; }
@media (min-width: 641px) and (max-width: 860px) {
  .nav-sub { margin-left: 0; padding-left: 0; border-left: none; }
  .nav-sublink { justify-content: center; padding: 9px 0; }
  .nav-caret { display: none; }
  .nav-parent { justify-content: center; padding: 9px 0; }
}
@media (max-width: 640px) {
  .mobile-backdrop { display: block; }
}
</style>
