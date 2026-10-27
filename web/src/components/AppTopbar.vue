<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { openPalette, setTheme, state } from '../stores/app'
import { t } from '../i18n'
import AccountMenu from './AccountMenu.vue'
import Icon from './Icon.vue'
import LanguageSelect from './LanguageSelect.vue'

const route = useRoute()

const titleKeys = {
  plugins: 'plugins.myPluginsTitle',
  'plugin-center': 'plugins.centerTitle',
  skills: 'nav.skills',
  settings: 'nav.settings',
  usage: 'nav.usage',
  console: 'nav.console',
  orchestrator: 'nav.orchestrator'
}

const pageTitle = computed(() => t(titleKeys[route.name] || 'app.title'))
const connectionLabel = computed(() => {
  if (state.connection === 'connected') return t('conn.live')
  if (state.connection === 'connecting') return t('conn.connecting')
  return t('conn.offline')
})
</script>

<template>
  <header class="app-topbar">
    <button class="icon-btn mobile-nav-btn" :title="t('nav.menu')" @click="state.mobileNavOpen = !state.mobileNavOpen">
      <Icon name="menu" :size="17" />
    </button>
    <div class="crumbs">
      <span class="crumb-root"><span class="crumb-mark">H</span><span class="crumb-brand">{{ t('app.title') }}</span></span>
      <Icon name="chevron-right" :size="12" class="crumb-sep" />
      <span class="crumb-page">{{ pageTitle }}</span>
    </div>

    <button class="command-pill" @click="openPalette">
      <Icon name="search" :size="14" />
      <span>{{ t('topbar.command') }}</span>
      <kbd>⌘K</kbd>
    </button>

    <div class="top-actions">
      <span class="conn-pill">
        <span class="status-dot" :class="state.connection === 'connected' ? 'done' : state.connection === 'connecting' ? 'running' : 'error'" />
        {{ connectionLabel }}
      </span>
      <button class="icon-btn top-icon" :title="state.theme === 'dark' ? t('nav.switchLight') : t('nav.switchDark')" @click="setTheme(state.theme === 'dark' ? 'light' : 'dark')">
        <Icon :name="state.theme === 'dark' ? 'sun' : 'moon'" :size="16" />
      </button>
      <LanguageSelect />
      <span class="top-sep" />
      <AccountMenu v-if="state.auth.authenticated" />
    </div>
  </header>
</template>

<style scoped>
.app-topbar {
  position: relative;
  z-index: 40;
  flex: 0 0 58px;
  height: 58px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 22px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 62%, transparent);
  backdrop-filter: blur(20px) saturate(140%);
}
.app-topbar::after {
  content: "";
  position: absolute;
  left: 0; right: 0; bottom: -1px;
  height: 1px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--brand) 26%, transparent), transparent);
  pointer-events: none;
}
.mobile-nav-btn { display: none; width: 32px; height: 32px; flex: 0 0 32px; }
.crumbs { display: flex; align-items: center; gap: 8px; min-width: 0; }
.crumb-root { display: inline-flex; align-items: center; gap: 7px; min-width: 0; }
.crumb-mark {
  width: 22px; height: 22px; flex: 0 0 22px;
  display: grid; place-items: center;
  border-radius: 7px;
  background: linear-gradient(140deg, var(--brand), var(--brand-2));
  color: #fff; font-size: 10px; font-weight: 800;
  box-shadow: 0 4px 12px color-mix(in srgb, var(--brand) 28%, transparent);
}
.crumb-brand { font-size: 12px; font-weight: 650; color: var(--muted); letter-spacing: .01em; }
.crumb-sep { color: var(--faint); }
.crumb-page { font-size: 12.5px; font-weight: 620; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.command-pill {
  flex: 1;
  max-width: 380px;
  margin-left: 8px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 72%, transparent);
  color: var(--faint);
  font-size: 11.5px;
  transition: all .16s var(--ease);
}
.command-pill:hover { border-color: var(--brand-line); color: var(--ink-2); background: var(--surface-2); }
.command-pill span { flex: 1; text-align: left; }
.command-pill kbd {
  font-family: var(--font-mono);
  font-size: 9px;
  padding: 1px 5px;
  border-radius: 5px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--faint);
}
.top-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.conn-pill {
  display: inline-flex; align-items: center; gap: 6px;
  height: 26px; padding: 0 9px;
  border-radius: 99px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 65%, transparent);
  color: var(--muted);
  font-size: 10.5px;
  font-weight: 560;
}
.top-icon { width: 30px; height: 30px; }
.top-sep { width: 1px; height: 20px; background: var(--line); margin: 0 2px; }
@media (max-width: 900px) {
  .command-pill, .conn-pill, .crumb-brand { display: none; }
}
@media (max-width: 720px) {
  .app-topbar { padding: 0 14px; gap: 8px; }
  .crumb-sep { display: none; }
  .top-sep, .top-icon { display: none; }
}
@media (max-width: 640px) {
  .mobile-nav-btn { display: inline-grid; }
}
</style>
