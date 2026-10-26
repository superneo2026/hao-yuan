<script setup>
import { onMounted } from 'vue'
import { loadPlugins, state, toast, togglePlugin } from '../stores/app'
import { pluginDescription, t } from '../i18n'
import Icon from '../components/Icon.vue'

const icons = {
  coding: 'terminal',
  plans: 'document',
  video: 'video',
  supervisor: 'activity',
  orchestrator: 'network',
  embodied: 'cpu'
}

async function toggle(plugin) {
  try {
    await togglePlugin(plugin.name, !plugin.enabled)
  } catch (error) {
    toast(error.message, 'bad')
  }
}

function contributions(plugin) {
  const data = plugin.contributes || {}
  return [
    data.tools?.length ? t('common.tools', { n: data.tools.length }) : '',
    data.agents?.length ? t('common.agents', { n: data.agents.length }) : '',
    data.routes?.length ? t('common.routes', { n: data.routes.length }) : '',
    data.skills ? t('common.skills') : ''
  ].filter(Boolean)
}

function navLabel(item) {
  const keys = {
    Workbench: 'plugins.navWorkbench',
    Plans: 'plugins.navPlans',
    Storyboards: 'plugins.navStoryboards',
    Robotics: 'plugins.navRobotics'
  }
  return keys[item.label] ? t(keys[item.label]) : item.label
}

onMounted(() => loadPlugins())
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <div class="page-kicker">{{ t('plugins.kicker') }}</div>
        <h1>{{ t('plugins.title') }}</h1>
        <p>{{ t('plugins.subtitle') }}</p>
      </div>
      <span class="badge brand">{{ t('plugins.enabledCount', { n: state.plugins.filter((plugin) => plugin.enabled).length }) }}</span>
    </header>

    <div class="arch-strip">
      <div class="arch-card"><span class="arch-icon"><Icon name="database" :size="17" /></span><div><b>{{ t('plugins.kernel') }}</b><span>{{ t('plugins.kernelDesc') }}</span></div></div>
      <Icon name="arrow-right" :size="16" style="color: var(--faint)" />
      <div class="arch-card"><span class="arch-icon"><Icon name="puzzle" :size="17" /></span><div><b>{{ t('plugins.pluginsTitle') }}</b><span>{{ t('plugins.pluginsDesc') }}</span></div></div>
      <Icon name="arrow-right" :size="16" style="color: var(--faint)" />
      <div class="arch-card"><span class="arch-icon"><Icon name="sparkles" :size="17" /></span><div><b>{{ t('plugins.experience') }}</b><span>{{ t('plugins.experienceDesc') }}</span></div></div>
    </div>

    <div class="plugin-grid">
      <article v-for="plugin in state.plugins" :key="plugin.name" class="plugin-card" :class="{ disabled: !plugin.enabled, error: plugin.error }">
        <div class="plugin-head">
          <span class="plugin-icon"><Icon :name="icons[plugin.name] || 'puzzle'" :size="19" /></span>
          <div class="plugin-title">
            <div class="row" style="gap: 7px">
              <h3>{{ t(`plugin.title.${plugin.name}`, {}, plugin.title) }}</h3>
              <span class="badge" :class="plugin.loaded ? 'good' : plugin.enabled ? 'warn' : ''">
                {{ plugin.loaded ? t('plugins.loaded') : plugin.enabled ? t('plugins.inactive') : t('plugins.disabled') }}
              </span>
            </div>
            <span class="mono tiny faint">{{ plugin.name }} v{{ plugin.version }} · {{ plugin.author || 'HaoYuan' }}</span>
          </div>
          <button class="switch" :class="{ on: plugin.enabled }" :aria-label="`Toggle ${plugin.name}`" @click="toggle(plugin)">
            <span />
          </button>
        </div>
        <p class="plugin-desc">{{ pluginDescription(plugin.name, plugin.description) }}</p>
        <div class="plugin-tags">
          <span v-for="item in contributions(plugin)" :key="item" class="badge">{{ item }}</span>
          <span v-if="plugin.requires?.length" class="badge">{{ t('plugins.requires', { items: plugin.requires.join(', ') }) }}</span>
        </div>
        <div v-if="plugin.error" class="plugin-error"><Icon name="alert" :size="13" /> {{ plugin.error }}</div>
        <div v-if="plugin.frontend?.nav?.length" class="plugin-nav">
          <span class="tiny faint">{{ t('plugins.frontend') }}</span>
          <span v-for="nav in plugin.frontend.nav" :key="nav.path" class="badge brand">{{ navLabel(nav) }}</span>
        </div>
      </article>
    </div>

    <section class="plugin-doc card">
      <div>
        <div class="page-kicker">{{ t('plugins.build') }}</div>
        <h2>{{ t('plugins.dropFolder') }}</h2>
        <p>{{ t('plugins.doc') }}</p>
        <div class="doc-points">
          <span><Icon name="check" :size="13" /> {{ t('plugins.point1') }}</span>
          <span><Icon name="check" :size="13" /> {{ t('plugins.point2') }}</span>
          <span><Icon name="check" :size="13" /> {{ t('plugins.point3') }}</span>
          <span><Icon name="check" :size="13" /> {{ t('plugins.point4') }}</span>
        </div>
      </div>
      <pre class="plugin-code">{
  "name": "my-plugin",
  "title": "My Plugin",
  "version": "1.0.0",
  "requires": ["coding"],
  "default_enabled": true,
  "backend": "plugin.py",
  "routes": "routes.py",
  "contributes": {
    "tools": ["my_tool"],
    "agents": ["my_agent"],
    "skills": true
  },
  "frontend": {
    "nav": [{ "label": "My Plugin", "path": "/my-plugin" }]
  }
}</pre>
    </section>
  </div>
</template>

<style scoped>
.arch-strip { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
.arch-card { flex: 1; min-width: 220px; display: flex; gap: 10px; align-items: center; padding: 13px 15px; border: 1px solid var(--line); border-radius: 13px; background: var(--surface); }
.arch-icon { width: 32px; height: 32px; border-radius: 9px; background: var(--brand-soft); color: var(--brand); display: grid; place-items: center; flex: 0 0 32px; }
.arch-card b { display: block; font-size: 12.5px; }
.arch-card span { display: block; font-size: 10.5px; color: var(--muted); }
.plugin-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; margin-bottom: 22px; }
.plugin-card { padding: 15px; background: var(--surface); border: 1px solid var(--line); border-radius: 15px; display: flex; flex-direction: column; gap: 10px; transition: all .16s var(--ease); }
.plugin-card:hover { border-color: var(--line-strong); }
.plugin-card.disabled { opacity: .62; }
.plugin-card.error { border-color: color-mix(in srgb, var(--bad) 40%, var(--line)); }
.plugin-head { display: flex; align-items: flex-start; gap: 10px; }
.plugin-icon { width: 38px; height: 38px; border-radius: 11px; background: var(--surface-2); color: var(--brand); display: grid; place-items: center; flex: 0 0 38px; }
.plugin-title { flex: 1; min-width: 0; }
.plugin-title h3 { margin: 0; font-size: 13.5px; letter-spacing: -.01em; }
.plugin-desc { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.55; flex: 1; }
.plugin-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.plugin-error { display: flex; gap: 6px; align-items: center; color: var(--bad); font-size: 11px; background: var(--bad-soft); border-radius: 8px; padding: 6px 8px; }
.plugin-nav { display: flex; align-items: center; gap: 5px; }
.switch { width: 36px; height: 20px; border-radius: 99px; border: 1px solid var(--line-strong); background: var(--surface-3); padding: 2px; flex: 0 0 36px; transition: all .18s var(--ease); }
.switch span { display: block; width: 14px; height: 14px; border-radius: 50%; background: var(--muted); transition: transform .18s var(--ease), background .18s; }
.switch.on { background: var(--brand-soft); border-color: var(--brand-line); }
.switch.on span { transform: translateX(16px); background: var(--brand); }
.plugin-doc { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; padding: 20px; align-items: start; }
.plugin-doc h2 { margin: 0 0 7px; font-size: 19px; letter-spacing: -.02em; }
.plugin-doc p { margin: 0 0 12px; color: var(--muted); font-size: 12.5px; }
.doc-points { display: flex; flex-direction: column; gap: 7px; color: var(--ink-2); font-size: 12px; }
.doc-points span { display: flex; align-items: center; gap: 7px; }
.doc-points .icon { color: var(--good); }
.plugin-code { margin: 0; font-family: var(--font-mono); font-size: 11px; line-height: 1.6; background: var(--code-bg); color: #cbd5e8; border: 1px solid #232a38; border-radius: 12px; padding: 14px; overflow: auto; }
@media (max-width: 860px) { .plugin-doc { grid-template-columns: 1fr; } }
</style>
