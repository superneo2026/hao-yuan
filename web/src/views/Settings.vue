<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api/client'
import { loadSettings, refreshModels, saveDefaultWorkspace, saveGate, saveSetting, setTheme, state, toast } from '../stores/app'
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

const providers = computed(() =>
  (state.health?.providers || []).filter((provider) => provider.name !== 'mock' && provider.configured)
)

const modelConfig = ref({ path: '', providers: [], default_provider: '', default_model: '' })
const modelDraft = ref(null)
const savingModel = ref(false)

const configuredProviders = computed(() => (modelConfig.value.providers || []).filter((provider) => provider.has_key))
const pendingProviders = computed(() => (modelConfig.value.providers || []).filter((provider) => !provider.has_key))
const routeOptions = computed(() => {
  const out = []
  for (const provider of configuredProviders.value) {
    for (const model of provider.models || []) out.push({ provider: provider.name, model, label: `${provider.name} / ${model}` })
  }
  return out
})
const routeValue = computed(() => {
  const { default_provider: provider, default_model: model } = modelConfig.value
  if (!provider || !model) return ''
  const usable = routeOptions.value.some((option) => option.provider === provider && option.model === model)
  return usable ? `${provider}|${model}` : ''
})
const draftModels = computed(() => splitList(modelDraft.value?.modelsText))

function splitList(text) {
  return String(text || '')
    .split(/[\n,;]+/)
    .map((value) => value.trim())
    .filter(Boolean)
}

function applyModelConfig(view) {
  modelConfig.value = view
  refreshModels().catch(() => {})
}

function startAddProvider(template = null) {
  modelDraft.value = {
    name: template?.name || '',
    builtin: !!template?.builtin,
    base_url: template?.base_url || '',
    api_key: '',
    clear_key: false,
    has_key: false,
    modelsText: (template?.models || []).join('\n'),
    default_model: template?.default_model || '',
    supports_thinking: template ? template.supports_thinking !== false : true,
    thinkingText: (template?.thinking_models || []).join(','),
    max_output_tokens: template?.max_output_tokens || 8192
  }
}

function startEditProvider(provider) {
  modelDraft.value = {
    name: provider.name,
    builtin: provider.builtin,
    base_url: provider.base_url || '',
    api_key: '',
    clear_key: false,
    has_key: provider.has_key,
    modelsText: (provider.models || []).join('\n'),
    default_model: provider.default_model || '',
    supports_thinking: provider.supports_thinking !== false,
    thinkingText: (provider.thinking_models || []).join(','),
    max_output_tokens: provider.max_output_tokens || 8192
  }
}

function cancelModelDraft() {
  modelDraft.value = null
}

async function reloadModelConfig() {
  try {
    applyModelConfig(await api.config())
  } catch (error) {
    toast(error.message, 'bad')
  }
}

async function saveProvider() {
  const draft = modelDraft.value
  if (!draft) return
  if (!/^[A-Za-z0-9._-]+$/.test(draft.name.trim())) {
    toast(t('settings.providerName'), 'bad')
    return
  }
  savingModel.value = true
  try {
    const view = await api.saveConfig({
      providers: [
        {
          name: draft.name.trim(),
          base_url: draft.base_url.trim(),
          api_key: draft.api_key.trim(),
          clear_key: draft.clear_key,
          models: splitList(draft.modelsText),
          default_model: draft.default_model.trim(),
          supports_thinking: draft.supports_thinking,
          thinking_models: splitList(draft.thinkingText),
          max_output_tokens: Number(draft.max_output_tokens) || 0
        }
      ]
    })
    applyModelConfig(view)
    modelDraft.value = null
    toast(t('settings.savedConfig'), 'good')
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    savingModel.value = false
  }
}

async function removeProvider(provider) {
  if (!provider || provider.builtin) return
  if (!window.confirm(`${t('common.delete')} ${provider.name}?`)) return
  try {
    applyModelConfig(await api.saveConfig({ removed: [provider.name] }))
    toast(t('settings.savedConfig'), 'good')
  } catch (error) {
    toast(error.message, 'bad')
  }
}

async function saveDefaultRoute(event) {
  const [provider, model] = String(event.target.value || '').split('|')
  if (!provider || !model) return
  modelConfig.value = { ...modelConfig.value, default_provider: provider, default_model: model }
  try {
    applyModelConfig(await api.saveConfig({ default_provider: provider, default_model: model }))
    toast(t('settings.savedConfig'), 'good')
  } catch (error) {
    toast(error.message, 'bad')
  }
}

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

const apiAddress = `${window.location.host}`
const docsUrl = `${window.location.origin}/docs`

onMounted(async () => {
  await loadSettings()
  sync()
  try {
    info.value = await api.info()
  } catch {
    /* optional */
  }
  try {
    modelConfig.value = await api.config()
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
          <span class="settings-icon"><Icon name="zap" :size="17" /></span>
          <div><b>{{ t('settings.models') }}</b><span>{{ t('settings.modelsDesc') }}</span></div>
        </div>
        <div class="config-path mono">{{ modelConfig.path }}</div>
        <div v-if="routeOptions.length" class="model-defaults">
          <label class="label">{{ t('settings.defaultRoute') }}</label>
          <select class="select" :value="routeValue" @change="saveDefaultRoute">
            <option value="">{{ t('settings.defaultRoute') }}</option>
            <option v-for="option in routeOptions" :key="`${option.provider}|${option.model}`" :value="`${option.provider}|${option.model}`">
              {{ option.label }}
            </option>
          </select>
        </div>
        <div v-else class="provider-empty">
          <b>{{ t('settings.noProviders') }}</b>
          <span>{{ t('settings.noProvidersDesc') }}</span>
        </div>
        <div v-if="configuredProviders.length" class="provider-grid">
          <div v-for="provider in configuredProviders" :key="provider.name" class="provider-card">
            <div class="row" style="justify-content: space-between">
              <b>{{ provider.name }}</b>
              <span class="badge good">{{ t('settings.ready') }}</span>
            </div>
            <div class="tiny faint mono">{{ provider.base_url || '—' }}</div>
            <div class="model-chip-row">
              <span v-for="model in provider.models" :key="model" class="model-chip" :class="{ active: model === provider.default_model }">{{ model }}</span>
            </div>
            <div class="tiny faint">{{ t('settings.source', { source: provider.key_source }) }} · {{ provider.max_output_tokens }} tokens</div>
            <div class="row" style="margin-top: 8px">
              <button class="btn sm" @click="startEditProvider(provider)">{{ t('common.edit') }}</button>
              <button v-if="!provider.builtin" class="btn sm danger" @click="removeProvider(provider)">{{ t('common.delete') }}</button>
            </div>
          </div>
        </div>
        <div v-if="pendingProviders.length" class="preset-row">
          <span class="tiny faint">{{ t('settings.pending') }}</span>
          <button v-for="provider in pendingProviders" :key="provider.name" class="btn sm" @click="startAddProvider(provider)">
            <Icon name="plus" :size="12" /> {{ provider.name }}
          </button>
        </div>
        <div class="row" style="margin-top: 12px">
          <button class="btn primary sm" @click="startAddProvider()">{{ t('settings.addProvider') }}</button>
          <button class="btn sm" @click="reloadModelConfig">{{ t('settings.refreshConfig') }}</button>
          <span class="tiny faint">{{ t('settings.modelsHint') }}</span>
        </div>

        <div v-if="modelDraft" class="model-editor">
          <div class="settings-head" style="margin-bottom: 10px">
            <span class="settings-icon"><Icon name="plus" :size="16" /></span>
            <div><b>{{ modelDraft.builtin ? t('settings.editProvider') : t('settings.addProvider') }}</b><span>{{ modelDraft.name || t('settings.providerName') }}</span></div>
          </div>
          <div class="editor-grid">
            <label>
              <span>{{ t('settings.providerName') }}</span>
              <input v-model="modelDraft.name" class="field mono" :disabled="modelDraft.builtin" placeholder="my-provider" />
            </label>
            <label>
              <span>{{ t('settings.baseUrl') }}</span>
              <input v-model="modelDraft.base_url" class="field mono" placeholder="https://api.example.com/v1" />
            </label>
            <label>
              <span>{{ t('settings.apiKey') }}</span>
              <input v-model="modelDraft.api_key" class="field mono" type="password" :placeholder="modelDraft.has_key ? t('settings.keyKeep') : 'sk-...'" autocomplete="off" />
            </label>
            <label>
              <span>{{ t('settings.maxOutput') }}</span>
              <input v-model="modelDraft.max_output_tokens" class="field mono" type="number" min="256" step="256" />
            </label>
            <label class="wide">
              <span>{{ t('settings.modelsList') }}</span>
              <textarea v-model="modelDraft.modelsText" class="field mono" rows="4" placeholder="model-a&#10;model-b" />
            </label>
            <label>
              <span>{{ t('settings.defaultModelField') }}</span>
              <select v-model="modelDraft.default_model" class="select">
                <option value="">{{ t('settings.defaultModelField') }}</option>
                <option v-for="model in draftModels" :key="model" :value="model">{{ model }}</option>
              </select>
            </label>
            <label>
              <span>{{ t('settings.thinkingModels') }}</span>
              <input v-model="modelDraft.thinkingText" class="field mono" placeholder="model-a,model-b" />
            </label>
          </div>
          <div class="editor-flags">
            <label class="check"><input v-model="modelDraft.supports_thinking" type="checkbox" /> {{ t('settings.supportsThinking') }}</label>
            <label v-if="modelDraft.has_key" class="check"><input v-model="modelDraft.clear_key" type="checkbox" /> {{ t('settings.clearKey') }}</label>
          </div>
          <div class="row">
            <button class="btn primary sm" :disabled="savingModel" @click="saveProvider">
              <span v-if="savingModel" class="spinner" style="width: 12px; height: 12px" /> {{ t('common.save') }}
            </button>
            <button class="btn sm" @click="cancelModelDraft">{{ t('common.cancel') }}</button>
          </div>
        </div>
      </section>

      <section class="settings-card wide">
        <div class="settings-head">
          <span class="settings-icon"><Icon name="brain" :size="17" /></span>
          <div><b>{{ t('settings.providers') }}</b><span>{{ t('settings.providersDesc') }}</span></div>
        </div>
        <div v-if="providers.length" class="provider-grid">
          <div v-for="provider in providers" :key="provider.name" class="provider-card">
            <div class="row" style="justify-content: space-between">
              <b>{{ provider.name }}</b>
              <span class="badge good">{{ t('settings.ready') }}</span>
            </div>
            <div class="tiny faint mono">{{ provider.models.join(' · ') }}</div>
            <div class="tiny faint">{{ t('settings.source', { source: provider.key_source }) }}</div>
          </div>
        </div>
        <div v-else class="provider-empty">
          <b>{{ t('settings.noProviders') }}</b>
          <span>{{ t('settings.noProvidersDesc') }}</span>
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
          <div><span>{{ t('settings.api') }}</span><b class="mono">{{ apiAddress }}</b></div>
        </div>
        <div class="row" style="margin-top: 12px">
          <a class="btn sm" :href="docsUrl" target="_blank" rel="noopener">{{ t('settings.docs') }}</a>
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
.provider-empty { padding: 14px; border: 1px dashed var(--line-strong); border-radius: 10px; background: var(--surface-2); display: flex; flex-direction: column; gap: 5px; }
.provider-empty b { font-size: 12px; }
.provider-empty span { font-size: 10.5px; color: var(--faint); }
.preset-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; }
.about-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; }
.about-grid div { padding: 9px 10px; background: var(--surface-2); border: 1px solid var(--line); border-radius: 9px; }
.about-grid span { display: block; font-size: 9.5px; text-transform: uppercase; letter-spacing: .08em; color: var(--faint); }
.about-grid b { font-size: 12px; font-weight: 560; }
@media (max-width: 860px) { .settings-grid { grid-template-columns: 1fr; } .about-grid { grid-template-columns: 1fr 1fr; } }

.config-path { font-size: 11px; color: var(--faint); background: var(--surface-2); border: 1px solid var(--line); border-radius: 8px; padding: 6px 9px; margin-bottom: 10px; word-break: break-all; }
.model-defaults { display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px; }
.model-defaults .label { font-size: 11px; color: var(--muted); }
.model-chip-row { display: flex; flex-wrap: wrap; gap: 4px; margin: 7px 0 5px; }
.model-chip { font-size: 10.5px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); background: var(--surface-2); }
.model-chip.active { border-color: var(--brand-line); background: var(--brand-soft); color: var(--brand); }
.model-editor { margin-top: 14px; padding: 13px; border: 1px dashed var(--line-strong); border-radius: 12px; background: var(--surface-2); }
.editor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.editor-grid label { display: flex; flex-direction: column; gap: 4px; }
.editor-grid label > span { font-size: 10.5px; color: var(--faint); }
.editor-grid label.wide { grid-column: 1 / -1; }
.editor-grid textarea { resize: vertical; min-height: 84px; }
.editor-flags { display: flex; flex-wrap: wrap; gap: 14px; margin: 9px 0; }
.check { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-2); }
.btn.danger { color: var(--bad, #d33); }
@media (max-width: 720px) { .editor-grid { grid-template-columns: 1fr; } }
</style>
