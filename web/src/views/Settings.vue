<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import { loadSettings, saveDefaultWorkspace, saveGate, saveSetting, setTheme, state, toast } from '../stores/app'
import { i18n, localeOptions, setLocale, t } from '../i18n'
import DirPicker from '../components/DirPicker.vue'
import Icon from '../components/Icon.vue'

const gate = ref({ mode: 'ask', allow: [] })
const workspace = ref('')
const showDir = ref(false)
const info = ref(null)
const savingGate = ref(false)
const autoResume = ref(state.settings.auto_resume !== '0')
const checkpoints = ref(state.settings.checkpoints !== '0')

const confirmTools = computed(() => (info.value?.tools || []).filter((tool) => tool.confirm))

const providers = computed(() => state.health?.providers || [])

function sync() {
  gate.value = {
    mode: state.settings.gate?.mode || 'ask',
    allow: [...(state.settings.gate?.allow || [])]
  }
  workspace.value = state.settings.default_workspace || ''
  autoResume.value = state.settings.auto_resume !== '0'
  checkpoints.value = state.settings.checkpoints !== '0'
}

function toggleAllow(name) {
  const set = new Set(gate.value.allow)
  if (set.has(name)) set.delete(name)
  else set.add(name)
  gate.value.allow = [...set]
}

async function saveGateSettings() {
  savingGate.value = true
  try {
    await saveGate(gate.value.mode, gate.value.mode === 'allow_list' ? gate.value.allow : [])
    sync()
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    savingGate.value = false
  }
}

async function saveWorkspace() {
  try {
    await saveDefaultWorkspace(workspace.value)
    sync()
  } catch (error) {
    toast(error.message, 'bad')
  }
}

async function toggleRuntime(key, value) {
  try {
    await saveSetting(key, value ? '1' : '0')
    state.settings[key] = value ? '1' : '0'
    toast(t('settings.runtimeSaved'), 'good')
  } catch (error) {
    toast(error.message, 'bad')
  }
}

function chooseDir(path) {
  workspace.value = path
  saveWorkspace()
}

onMounted(async () => {
  await loadSettings()
  sync()
  try {
    info.value = await api.info()
  } catch {
    /* optional */
  }
})
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <div class="page-kicker">{{ t('settings.kicker') }}</div>
        <h1>{{ t('settings.title') }}</h1>
        <p>{{ t('settings.subtitle') }}</p>
      </div>
      <span class="badge brand">{{ state.health?.version || '1.0.0' }}</span>
    </header>

    <div class="settings-grid">
      <section class="settings-card">
        <div class="settings-head">
          <span class="settings-icon"><Icon name="sun" :size="17" /></span>
          <div><b>{{ t('settings.appearance') }}</b><span>{{ t('settings.appearanceDesc') }}</span></div>
        </div>
        <div class="theme-options">
          <button class="theme-card" :class="{ active: state.theme === 'light' }" @click="setTheme('light')">
            <span class="theme-swatch light" />
            <span><b>{{ t('settings.light') }}</b><small>{{ t('settings.lightDesc') }}</small></span>
            <Icon v-if="state.theme === 'light'" name="check" :size="15" style="color: var(--brand)" />
          </button>
          <button class="theme-card" :class="{ active: state.theme === 'dark' }" @click="setTheme('dark')">
            <span class="theme-swatch dark" />
            <span><b>{{ t('settings.dark') }}</b><small>{{ t('settings.darkDesc') }}</small></span>
            <Icon v-if="state.theme === 'dark'" name="check" :size="15" style="color: var(--brand)" />
          </button>
        </div>
        <div class="language-block">
          <div class="language-head">
            <b>{{ t('settings.language') }}</b>
            <span>{{ t('settings.languageDesc') }}</span>
          </div>
          <div class="language-options">
            <button
              v-for="option in localeOptions"
              :key="option.id"
              class="language-option"
              :class="{ active: i18n.locale === option.id }"
              @click="setLocale(option.id)"
            >
              <span class="language-short">{{ option.short }}</span>
              <span>{{ option.label }}</span>
              <Icon v-if="i18n.locale === option.id" name="check" :size="14" />
            </button>
          </div>
        </div>
      </section>

      <section class="settings-card">
        <div class="settings-head">
          <span class="settings-icon"><Icon name="shield" :size="17" /></span>
          <div><b>{{ t('settings.gate') }}</b><span>{{ t('settings.gateDesc') }}</span></div>
        </div>
        <div class="radio-stack">
          <button v-for="mode in [{ id: 'ask', title: 'settings.askEvery', desc: 'settings.askEveryDesc' }, { id: 'allow_list', title: 'settings.allowSelected', desc: 'settings.allowSelectedDesc' }, { id: 'allow_all', title: 'settings.allowAll', desc: 'settings.allowAllDesc' }]" :key="mode.id" class="radio-card" :class="{ active: gate.mode === mode.id }" @click="gate.mode = mode.id">
            <span class="radio-dot" />
            <span class="radio-copy"><b>{{ t(mode.title) }}</b><span>{{ t(mode.desc) }}</span></span>
          </button>
        </div>
        <div v-if="gate.mode === 'allow_list'" class="allow-list">
          <div class="tiny faint" style="margin-bottom: 6px">{{ t('settings.autoApproved') }}</div>
          <button v-for="tool in confirmTools" :key="tool.name" class="allow-chip" :class="{ active: gate.allow.includes(tool.name) }" @click="toggleAllow(tool.name)">
            {{ tool.name }}
          </button>
        </div>
        <button class="btn primary sm" style="margin-top: 12px" :disabled="savingGate" @click="saveGateSettings">
          <span v-if="savingGate" class="spinner" style="width: 12px; height: 12px" /> {{ t('settings.savePolicy') }}
        </button>
      </section>

      <section class="settings-card">
        <div class="settings-head">
          <span class="settings-icon"><Icon name="folder" :size="17" /></span>
          <div><b>{{ t('settings.workspace') }}</b><span>{{ t('settings.workspaceDesc') }}</span></div>
        </div>
        <div class="row">
          <input v-model="workspace" class="field mono" style="font-size: 12px" :placeholder="t('dir.placeholder')" />
          <button class="btn" @click="showDir = true"><Icon name="folder" :size="14" /> {{ t('common.browse') }}</button>
          <button class="btn primary" @click="saveWorkspace">{{ t('common.save') }}</button>
        </div>
        <div class="tiny faint" style="margin-top: 6px">{{ t('settings.sandboxNote') }}</div>
      </section>

      <section class="settings-card">
        <div class="settings-head">
          <span class="settings-icon"><Icon name="zap" :size="17" /></span>
          <div><b>{{ t('settings.runtime') }}</b><span>{{ t('settings.runtimeDesc') }}</span></div>
        </div>
        <div class="toggle-row">
          <div><b>{{ t('settings.checkpoints') }}</b><span>{{ t('settings.checkpointsDesc') }}</span></div>
          <button class="switch" :class="{ on: checkpoints }" @click="checkpoints = !checkpoints; toggleRuntime('checkpoints', checkpoints)"><span /></button>
        </div>
        <div class="toggle-row">
          <div><b>{{ t('settings.autoResume') }}</b><span>{{ t('settings.autoResumeDesc') }}</span></div>
          <button class="switch" :class="{ on: autoResume }" @click="autoResume = !autoResume; toggleRuntime('auto_resume', autoResume)"><span /></button>
        </div>
      </section>

      <section class="settings-card wide">
        <div class="settings-head">
          <span class="settings-icon"><Icon name="brain" :size="17" /></span>
          <div><b>{{ t('settings.providers') }}</b><span>{{ t('settings.providersDesc') }}</span></div>
        </div>
        <div class="provider-grid">
          <div v-for="provider in providers" :key="provider.name" class="provider-card">
            <div class="row" style="justify-content: space-between">
              <b>{{ provider.name }}</b>
              <span class="badge" :class="provider.configured ? 'good' : 'warn'">{{ provider.configured ? t('settings.ready') : t('settings.noKey') }}</span>
            </div>
            <div class="tiny faint mono">{{ provider.models.join(' · ') }}</div>
            <div class="tiny faint">{{ t('settings.source', { source: provider.key_source }) }}</div>
          </div>
        </div>
      </section>

      <section class="settings-card wide">
        <div class="settings-head">
          <span class="settings-icon"><Icon name="compass" :size="17" /></span>
          <div><b>{{ t('settings.about') }}</b><span>{{ t('settings.aboutDesc') }}</span></div>
        </div>
        <div class="about-grid">
          <div><span>{{ t('common.version') }}</span><b>{{ state.health?.version }}</b></div>
          <div><span>{{ t('settings.platform') }}</span><b>{{ state.health?.platform }}</b></div>
          <div><span>{{ t('settings.tools') }}</span><b>{{ state.health?.tools }}</b></div>
          <div><span>{{ t('settings.skills') }}</span><b>{{ state.health?.skills }}</b></div>
          <div><span>{{ t('settings.plugins') }}</span><b>{{ state.health?.plugins?.length || 0 }}</b></div>
          <div><span>{{ t('settings.api') }}</span><b class="mono">127.0.0.1:8030</b></div>
        </div>
        <div class="row" style="margin-top: 12px">
          <a class="btn sm" href="http://127.0.0.1:8030/docs" target="_blank" rel="noopener">{{ t('settings.docs') }}</a>
          <span class="tiny faint">{{ t('settings.footer', { version: state.health?.version }) }}</span>
        </div>
      </section>
    </div>

    <DirPicker v-if="showDir" :initial="workspace" @close="showDir = false" @select="chooseDir" />
  </div>
</template>

<style scoped>
.settings-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-items: start; }
.settings-card { padding: 17px; background: var(--surface); border: 1px solid var(--line); border-radius: 15px; display: flex; flex-direction: column; }
.settings-card.wide { grid-column: 1 / -1; }
.settings-head { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 13px; }
.settings-icon { width: 33px; height: 33px; border-radius: 9px; background: var(--surface-2); color: var(--brand); display: grid; place-items: center; flex: 0 0 33px; }
.settings-head b { display: block; font-size: 13px; }
.settings-head span { display: block; color: var(--muted); font-size: 11px; }
.theme-options { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.theme-card { display: flex; align-items: center; gap: 9px; padding: 9px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); color: var(--ink-2); text-align: left; }
.theme-card.active { border-color: var(--brand-line); background: var(--brand-soft); }
.theme-card b { display: block; font-size: 12px; }
.theme-card small { color: var(--faint); font-size: 10px; }
.theme-swatch { width: 28px; height: 28px; border-radius: 8px; flex: 0 0 28px; border: 1px solid var(--line-strong); }
.theme-swatch.dark { background: linear-gradient(140deg, #0b0e15, #1b2130); }
.theme-swatch.light { background: linear-gradient(140deg, #ffffff, #e9edf6); }
.language-block { margin-top: 14px; padding-top: 13px; border-top: 1px solid var(--line); }
.language-head b { display: block; font-size: 12px; }
.language-head span { display: block; color: var(--faint); font-size: 10.5px; margin-bottom: 8px; }
.language-options { display: flex; gap: 6px; flex-wrap: wrap; }
.language-option { display: inline-flex; align-items: center; gap: 6px; padding: 6px 9px; border-radius: 8px; border: 1px solid var(--line); background: var(--surface-2); color: var(--muted); font-size: 11.5px; }
.language-option:hover { color: var(--ink); border-color: var(--line-strong); }
.language-option.active { border-color: var(--brand-line); background: var(--brand-soft); color: var(--brand); }
.language-short { width: 21px; height: 18px; border-radius: 4px; display: grid; place-items: center; background: var(--surface-3); color: inherit; font-size: 9px; font-weight: 650; }
.language-option.active .language-short { background: color-mix(in srgb, var(--brand) 15%, transparent); color: var(--brand); }
.radio-stack { display: flex; flex-direction: column; gap: 6px; }
.radio-card { display: flex; gap: 9px; align-items: flex-start; padding: 9px 10px; border-radius: 10px; border: 1px solid var(--line); background: var(--surface-2); text-align: left; color: var(--ink-2); }
.radio-card.active { border-color: var(--brand-line); background: var(--brand-soft); }
.radio-dot { width: 13px; height: 13px; border-radius: 50%; border: 1.5px solid var(--line-strong); margin-top: 3px; flex: 0 0 13px; }
.radio-card.active .radio-dot { border-color: var(--brand); box-shadow: inset 0 0 0 3px var(--brand); background: var(--surface); }
.radio-copy b { display: block; font-size: 12px; }
.radio-copy span { display: block; font-size: 10.5px; color: var(--faint); }
.allow-list { margin-top: 10px; }
.allow-chip { display: inline-flex; padding: 3px 8px; margin: 3px 3px 0 0; border-radius: 6px; border: 1px solid var(--line); background: var(--surface-2); color: var(--muted); font-size: 10.5px; font-family: var(--font-mono); }
.allow-chip.active { border-color: var(--brand-line); background: var(--brand-soft); color: var(--brand); }
.toggle-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 0; border-top: 1px solid var(--line); }
.toggle-row b { display: block; font-size: 12px; }
.toggle-row span { display: block; font-size: 10.5px; color: var(--faint); }
.switch { width: 36px; height: 20px; border-radius: 99px; border: 1px solid var(--line-strong); background: var(--surface-3); padding: 2px; flex: 0 0 36px; }
.switch span { display: block; width: 14px; height: 14px; border-radius: 50%; background: var(--muted); transition: transform .18s var(--ease), background .18s; }
.switch.on { background: var(--brand-soft); border-color: var(--brand-line); }
.switch.on span { transform: translateX(16px); background: var(--brand); }
.provider-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 9px; }
.provider-card { padding: 11px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface-2); display: flex; flex-direction: column; gap: 4px; }
.about-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; }
.about-grid div { padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 9px; }
.about-grid span { display: block; font-size: 9.5px; text-transform: uppercase; letter-spacing: .08em; color: var(--faint); }
.about-grid b { font-size: 12px; font-weight: 560; }
@media (max-width: 860px) { .settings-grid { grid-template-columns: 1fr; } .about-grid { grid-template-columns: 1fr 1fr; } }
</style>
