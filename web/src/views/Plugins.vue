<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  installPluginFromCenter,
  loadMarketplace,
  loadPlugins,
  requestAccountSetup,
  state,
  toast,
  togglePlugin,
  uninstallPluginByName,
  uploadPluginPackage
} from '../stores/app'
import { pluginDescription, t } from '../i18n'
import Icon from '../components/Icon.vue'

const icons = {
  coding: 'terminal',
  plans: 'document',
  video: 'video',
  supervisor: 'activity',
  orchestrator: 'network',
  embodied: 'cpu',
  'user-account': 'shield',
  'remote-management': 'globe'
}

const route = useRoute()
const router = useRouter()
const corePlugins = new Set(['coding', 'plans', 'video', 'supervisor', 'orchestrator'])
const tab = computed(() => (route.name === 'plugin-center' || route.query.tab === 'market' ? 'market' : 'installed'))
const DEFAULT_CENTER_URL = 'https://hao-yuan.conductorer.com'

const centerInput = ref(localStorage.getItem('hy.pluginCenterUrl') || state.market.centerUrl || DEFAULT_CENTER_URL)
const query = ref('')
const category = ref('all')
const busyName = ref('')
const installingName = ref('')
const uploadOpen = ref(false)
const uploading = ref(false)
const dragOver = ref(false)
const fileInput = ref(null)

const enabledCount = computed(() => state.plugins.filter((plugin) => plugin.enabled).length)
const accountPlugin = computed(() => state.plugins.find((plugin) => plugin.name === 'user-account'))

const categories = computed(() => {
  const set = new Set()
  state.market.plugins.forEach((item) => {
    if (item.category) set.add(item.category)
  })
  return ['all', ...set]
})

const marketPlugins = computed(() => {
  const text = query.value.trim().toLowerCase()
  return state.market.plugins.filter((item) => {
    const matchesCategory = category.value === 'all' || item.category === category.value
    const haystack = [item.name, item.title, item.description, ...(item.tags || [])].join(' ').toLowerCase()
    return matchesCategory && (!text || haystack.includes(text))
  })
})

const accountState = computed(() => {
  if (!accountPlugin.value) return 'missing'
  if (!accountPlugin.value.enabled) return 'off'
  if (!state.auth.configured) return 'setup'
  return 'on'
})

function pluginTitle(plugin) {
  return t(`plugin.title.${plugin.name}`, {}, plugin.title)
}

function pluginIcon(plugin) {
  return icons[plugin.name] || 'puzzle'
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

function categoryLabel(value) {
  return t(`plugins.category.${value}`, {}, value)
}

function setTab(value) {
  if (tab.value === value) return
  router.push(value === 'market' ? { name: 'plugin-center' } : { name: 'plugins' })
}

async function retryCenter() {
  await loadMarketplace(centerInput.value)
  if (state.market.centerUrl) centerInput.value = state.market.centerUrl
}

function downloads(value) {
  const count = Number(value) || 0
  if (count >= 1000) return `${(count / 1000).toFixed(count >= 10000 ? 0 : 1)}k`
  return `${count}`
}

async function refresh() {
  try {
    await Promise.all([loadPlugins(), loadMarketplace()])
  } catch (error) {
    toast(error.message, 'bad')
  }
}

async function toggle(plugin) {
  busyName.value = plugin.name
  try {
    await togglePlugin(plugin.name, !plugin.enabled)
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busyName.value = ''
  }
}

async function install(item) {
  installingName.value = item.name
  try {
    await installPluginFromCenter(item)
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    installingName.value = ''
  }
}

const pendingRemove = ref(null)
const removing = ref(false)

function remove(plugin) {
  if (plugin.enabled) {
    toast(t('plugins.uninstallDisabled'), 'warn')
    return
  }
  pendingRemove.value = plugin
}

async function confirmRemove() {
  const plugin = pendingRemove.value
  if (!plugin || removing.value) return
  removing.value = true
  try {
    await uninstallPluginByName(plugin.name)
    pendingRemove.value = null
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    removing.value = false
  }
}

function openAccount() {
  if (!state.auth.authenticated) return
  state.accountOpen = true
}

async function accountAction() {
  if (accountState.value === 'on') openAccount()
  else if (accountState.value === 'off' && accountPlugin.value) {
    await toggle(accountPlugin.value)
    if (state.auth.enabled && !state.auth.configured) requestAccountSetup()
  } else if (accountState.value === 'setup') requestAccountSetup()
}

function chooseFile() {
  fileInput.value?.click()
}

async function handleFile(file) {
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    toast(t('plugins.uploadZipOnly'), 'bad')
    return
  }
  uploading.value = true
  try {
    await uploadPluginPackage(file)
    uploadOpen.value = false
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onInput(event) {
  handleFile(event.target.files?.[0])
}

function onDrop(event) {
  dragOver.value = false
  handleFile(event.dataTransfer?.files?.[0])
}

onMounted(() => {
  refresh()
})
</script>

<template>
  <div class="page plugins-page">
    <header class="plugin-hero">
      <div class="hero-orbs" aria-hidden="true"><span /><span /><span /></div>
      <div class="hero-copy">
        <div class="page-kicker">{{ t('plugins.kicker') }}</div>
        <h1>{{ tab === 'market' ? t('plugins.centerTitle') : t('plugins.myPluginsTitle') }}</h1>
        <p>{{ tab === 'market' ? t('plugins.centerSubtitle') : t('plugins.myPluginsSubtitle') }}</p>
        <div class="hero-stats">
          <span><b>{{ state.plugins.length }}</b>{{ t('plugins.installed') }}</span>
          <span><b>{{ enabledCount }}</b>{{ t('plugins.running') }}</span>
          <span><b>{{ state.market.plugins.length }}</b>{{ t('plugins.available') }}</span>
        </div>
      </div>
      <div class="hero-actions">
        <button class="btn hero-btn" @click="refresh">
          <Icon name="refresh" :size="15" /> {{ t('common.refresh') }}
        </button>
        <button class="btn primary hero-btn" @click="uploadOpen = true">
          <Icon name="upload" :size="15" /> {{ t('plugins.upload') }}
        </button>
      </div>
    </header>

    <div class="plugin-tabs">
      <button class="plugin-tab" :class="{ active: tab === 'installed' }" @click="setTab('installed')">
        <Icon name="puzzle" :size="15" />
        {{ t('plugins.tabInstalled') }}
        <span class="tab-count">{{ state.plugins.length }}</span>
      </button>
      <button class="plugin-tab" :class="{ active: tab === 'market' }" @click="setTab('market')">
        <Icon name="cloud" :size="15" />
        {{ t('plugins.tabMarket') }}
        <span class="tab-count">{{ state.market.plugins.length }}</span>
      </button>
      <span class="spacer" />
      <span class="badge" :class="state.market.online ? 'good' : 'warn'">
        <span class="status-dot" :class="state.market.online ? 'done' : 'waiting'" />
        {{ state.market.online ? t('plugins.centerOnline') : t('plugins.centerOffline') }}
      </span>
      <span class="badge brand">{{ t('plugins.enabledCount', { n: enabledCount }) }}</span>
    </div>

    <template v-if="tab === 'installed'">
      <section v-if="accountPlugin" class="account-strip" :class="accountState">
        <span class="account-strip-icon"><Icon name="shield" :size="20" /></span>
        <div class="account-strip-copy">
          <div class="row" style="gap: 8px">
            <b>{{ t('plugins.accountTitle') }}</b>
            <span class="badge" :class="accountState === 'on' ? 'good' : accountState === 'off' ? '' : 'warn'">
              {{ t(`plugins.accountState.${accountState}`) }}
            </span>
          </div>
          <span>{{ t('plugins.accountDesc') }}</span>
        </div>
        <button class="btn sm primary" :disabled="busyName === 'user-account'" @click="accountAction">
          <Icon :name="accountState === 'off' ? 'play' : 'key'" :size="14" />
          {{ accountState === 'off' ? t('plugins.start') : accountState === 'setup' ? t('plugins.accountSetup') : t('plugins.accountManage') }}
        </button>
      </section>

      <div class="plugin-grid">
        <article
          v-for="plugin in state.plugins"
          :key="plugin.name"
          class="plugin-card"
          :class="{ disabled: !plugin.enabled, error: plugin.error }"
        >
          <div class="plugin-head">
            <span class="plugin-icon"><Icon :name="pluginIcon(plugin)" :size="19" /></span>
            <div class="plugin-title">
              <div class="row" style="gap: 7px">
                <h3>{{ pluginTitle(plugin) }}</h3>
                <span class="badge" :class="plugin.error ? 'bad' : plugin.enabled ? (plugin.loaded ? 'good' : 'warn') : ''">
                  {{ plugin.error ? t('plugins.failed') : plugin.enabled ? (plugin.loaded ? t('plugins.running') : t('plugins.pending')) : t('plugins.stopped') }}
                </span>
              </div>
              <span class="mono tiny faint">{{ plugin.name }} v{{ plugin.version }} · {{ plugin.author || 'HaoYuan' }}</span>
            </div>
          </div>
          <p class="plugin-desc">{{ pluginDescription(plugin.name, plugin.description) }}</p>
          <div class="plugin-tags">
            <span v-for="item in contributions(plugin)" :key="item" class="badge">{{ item }}</span>
            <span v-if="corePlugins.has(plugin.name)" class="badge brand">{{ t('plugins.core') }}</span>
            <span v-if="plugin.requires?.length" class="badge">{{ t('plugins.requires', { items: plugin.requires.join(', ') }) }}</span>
          </div>
          <div v-if="plugin.error" class="plugin-error"><Icon name="alert" :size="13" /> {{ plugin.error }}</div>
          <div class="plugin-actions">
            <button
              class="btn sm"
              :class="plugin.enabled ? 'danger' : 'primary'"
              :disabled="busyName === plugin.name"
              @click="toggle(plugin)"
            >
              <span v-if="busyName === plugin.name" class="spinner" style="width: 11px; height: 11px" />
              <Icon v-else :name="plugin.enabled ? 'square' : 'play'" :size="13" />
              {{ plugin.enabled ? t('plugins.close') : t('plugins.start') }}
            </button>
            <button v-if="plugin.name === 'user-account'" class="btn sm" @click="accountAction">
              <Icon name="settings" :size="13" /> {{ t('plugins.settings') }}
            </button>
            <span class="spacer" />
            <button
              v-if="!corePlugins.has(plugin.name)"
              class="btn sm delete-btn"
              :class="{ 'delete-locked': plugin.enabled }"
              :disabled="removing && pendingRemove && pendingRemove.name === plugin.name"
              :title="plugin.enabled ? t('plugins.uninstallDisabled') : t('plugins.uninstall')"
              @click="remove(plugin)"
            >
              <Icon name="trash" :size="13" />
              {{ t('common.delete') }}
            </button>
          </div>
        </article>
      </div>

      <section class="manual-card card">
        <div class="manual-head">
          <span class="manual-icon"><Icon name="code" :size="18" /></span>
          <div>
            <div class="page-kicker">{{ t('plugins.build') }}</div>
            <h2>{{ t('plugins.threeWays') }}</h2>
            <p>{{ t('plugins.threeWaysDesc') }}</p>
          </div>
        </div>
        <div class="way-grid">
          <div class="way-card">
            <span class="way-num">1</span>
            <b>{{ t('plugins.way1') }}</b>
            <span>{{ t('plugins.way1Desc') }}</span>
          </div>
          <div class="way-card">
            <span class="way-num">2</span>
            <b>{{ t('plugins.way2') }}</b>
            <span>{{ t('plugins.way2Desc') }}</span>
          </div>
          <div class="way-card">
            <span class="way-num">3</span>
            <b>{{ t('plugins.way3') }}</b>
            <span>{{ t('plugins.way3Desc') }}</span>
            <code class="mono tiny">api/plugins/&lt;name&gt;/plugin.json</code>
          </div>
        </div>
      </section>
    </template>

    <template v-else>
      <div class="market-toolbar">
        <div class="search-box">
          <Icon name="search" :size="15" />
          <input v-model="query" class="search-input" :placeholder="t('plugins.searchPlaceholder')" />
          <button v-if="query" class="icon-btn" @click="query = ''"><Icon name="close" :size="13" /></button>
        </div>
        <div class="category-row">
          <button
            v-for="item in categories"
            :key="item"
            class="category-chip"
            :class="{ active: category === item }"
            @click="category = item"
          >
            {{ categoryLabel(item) }}
          </button>
        </div>
      </div>

      <div v-if="state.market.loading" class="market-grid">
        <div v-for="n in 6" :key="n" class="market-card skeleton-card"><div class="skeleton" style="height: 100%" /></div>
      </div>

      <section v-else-if="!state.market.online" class="offline-card card">
        <span class="offline-icon"><Icon name="cloud" :size="26" /></span>
        <h2>{{ t('plugins.offlineTitle') }}</h2>
        <p>{{ t('plugins.offlineDesc') }}</p>
        <div class="center-config">
          <label class="label" for="center-url" style="text-align: left">{{ t('plugins.centerUrlLabel') }}</label>
          <div class="center-url-row">
            <input id="center-url" v-model="centerInput" class="field mono" placeholder="http://127.0.0.1:8180" @keyup.enter="retryCenter" />
            <button class="btn primary" :disabled="state.market.loading" @click="retryCenter">
              <span v-if="state.market.loading" class="spinner" style="width: 12px; height: 12px" />
              <Icon v-else name="refresh" :size="15" /> {{ t('plugins.retry') }}
            </button>
          </div>
          <span class="tiny faint">{{ t('plugins.centerUrlHint') }}</span>
        </div>
        <div v-if="state.market.error" class="offline-error mono tiny">{{ state.market.error }}</div>
      </section>

      <div v-else-if="marketPlugins.length" class="market-grid">
        <article v-for="item in marketPlugins" :key="item.name" class="market-card" :class="[`cat-${item.category || 'other'}`, { installed: item.installed }]">
          <div class="market-cover">
            <span class="market-icon"><Icon :name="item.icon || 'puzzle'" :size="24" /></span>
            <span v-if="item.featured && !item.installed" class="badge brand featured-tag"><Icon name="sparkles" :size="11" /> {{ t('plugins.featured') }}</span>
            <span v-if="item.installed" class="badge good featured-tag"><Icon name="check" :size="11" /> {{ t('plugins.installed') }}</span>
          </div>
          <div class="market-body">
            <div class="row" style="justify-content: space-between; gap: 8px">
              <h3>{{ item.title }}</h3>
              <span class="mono tiny faint">v{{ item.version }}</span>
            </div>
            <p>{{ item.description }}</p>
            <div class="plugin-tags">
              <span v-for="tag in (item.tags || []).slice(0, 3)" :key="tag" class="badge">{{ tag }}</span>
            </div>
          </div>
          <div class="market-foot">
            <span class="tiny faint"><Icon name="download" :size="12" /> {{ downloads(item.downloads) }} · {{ item.author || 'HaoYuan' }}</span>
            <span class="spacer" />
            <button
              v-if="!item.installed"
              class="btn sm primary"
              :disabled="installingName === item.name"
              @click="install(item)"
            >
              <span v-if="installingName === item.name" class="spinner" style="width: 11px; height: 11px" />
              <Icon v-else name="download" :size="13" />
              {{ installingName === item.name ? t('plugins.installing') : t('plugins.install') }}
            </button>
            <span v-else class="badge good">{{ t('plugins.installed') }}</span>
          </div>
        </article>
      </div>

      <div v-else class="empty-market">
        <Icon name="search" :size="28" />
        <b>{{ t('plugins.noResults') }}</b>
        <span>{{ t('plugins.noResultsDesc') }}</span>
      </div>
    </template>

    <div v-if="uploadOpen" class="overlay" @click.self="!uploading && (uploadOpen = false)">
      <div class="modal upload-modal">
        <div class="modal-head">
          <span class="upload-head-icon"><Icon name="upload" :size="17" /></span>
          <div style="flex: 1">
            <h3>{{ t('plugins.uploadTitle') }}</h3>
            <span class="tiny faint">{{ t('plugins.uploadDesc') }}</span>
          </div>
          <button class="icon-btn" :disabled="uploading" @click="uploadOpen = false"><Icon name="close" :size="15" /></button>
        </div>
        <div class="modal-body">
          <div
            class="drop-zone"
            :class="{ active: dragOver }"
            @click="chooseFile"
            @dragover.prevent="dragOver = true"
            @dragleave.prevent="dragOver = false"
            @drop.prevent="onDrop"
          >
            <span class="drop-icon"><Icon :name="uploading ? 'refresh' : 'package'" :size="26" /></span>
            <b>{{ uploading ? t('plugins.uploading') : t('plugins.dropHere') }}</b>
            <span>{{ t('plugins.dropHint') }}</span>
            <span class="btn sm" style="margin-top: 6px"><Icon name="folder" :size="13" /> {{ t('plugins.chooseFile') }}</span>
            <input ref="fileInput" type="file" accept=".zip" hidden @change="onInput" />
          </div>
          <div class="upload-notes">
            <span><Icon name="check" :size="13" /> {{ t('plugins.uploadNote1') }}</span>
            <span><Icon name="check" :size="13" /> {{ t('plugins.uploadNote2') }}</span>
            <span><Icon name="check" :size="13" /> {{ t('plugins.uploadNote3') }}</span>
          </div>
        </div>
        <div class="modal-foot">
          <span class="tiny faint" style="margin-right: auto">{{ t('plugins.uploadRestart') }}</span>
          <button class="btn" :disabled="uploading" @click="uploadOpen = false">{{ t('common.cancel') }}</button>
        </div>
      </div>
    </div>

    <div v-if="pendingRemove" class="overlay" @click.self="!removing && (pendingRemove = null)">
      <div class="modal confirm-modal">
        <div class="modal-head">
          <span class="confirm-head-icon"><Icon name="alert" :size="17" /></span>
          <div style="flex: 1">
            <h3>{{ t('plugins.uninstallTitle') }}</h3>
            <span class="tiny faint">{{ t('plugins.uninstallSubtitle') }}</span>
          </div>
          <button class="icon-btn" :disabled="removing" @click="pendingRemove = null"><Icon name="close" :size="15" /></button>
        </div>
        <div class="modal-body">
          <p class="confirm-text">{{ t('plugins.uninstallConfirm', { name: pluginTitle(pendingRemove) }) }}</p>
          <ul class="confirm-list">
            <li><Icon name="trash" :size="13" /> {{ t('plugins.uninstallPoint1') }}</li>
            <li><Icon name="alert" :size="13" /> {{ t('plugins.uninstallPoint2') }}</li>
          </ul>
        </div>
        <div class="modal-foot">
          <button class="btn" :disabled="removing" @click="pendingRemove = null">{{ t('common.cancel') }}</button>
          <button class="btn danger" :disabled="removing" @click="confirmRemove">
            <span v-if="removing" class="spinner" style="width: 11px; height: 11px" />
            <Icon v-else name="trash" :size="14" />
            {{ removing ? t('plugins.uninstalling') : t('plugins.uninstallAction') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.plugins-page { max-width: 1420px; padding-top: 26px; }
.plugin-hero {
  position: relative;
  overflow: hidden;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 26px;
  padding: 30px 32px 28px;
  margin-bottom: 18px;
  border: 1px solid color-mix(in srgb, var(--brand) 18%, var(--line));
  border-radius: 24px;
  background:
    linear-gradient(125deg, color-mix(in srgb, var(--brand) 13%, var(--surface)) 0%, color-mix(in srgb, var(--brand-2) 7%, var(--surface)) 46%, var(--surface) 100%);
  box-shadow: 0 24px 60px color-mix(in srgb, var(--brand) 9%, transparent);
  animation: hy-rise .45s var(--ease) both;
}
.plugin-hero::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(420px 240px at 8% -10%, color-mix(in srgb, var(--brand) 22%, transparent), transparent 64%),
    radial-gradient(360px 220px at 92% 130%, color-mix(in srgb, var(--brand-2) 18%, transparent), transparent 66%);
  pointer-events: none;
}
.hero-orbs { position: absolute; inset: 0; pointer-events: none; }
.hero-orbs span { position: absolute; border-radius: 50%; filter: blur(1px); opacity: .65; }
.hero-orbs span:nth-child(1) { width: 190px; height: 190px; right: 140px; top: -110px; background: radial-gradient(circle, color-mix(in srgb, var(--brand) 28%, transparent), transparent 68%); }
.hero-orbs span:nth-child(2) { width: 120px; height: 120px; right: 36px; bottom: -68px; background: radial-gradient(circle, color-mix(in srgb, var(--brand-2) 26%, transparent), transparent 68%); }
.hero-orbs span:nth-child(3) { width: 74px; height: 74px; right: 330px; bottom: -42px; background: radial-gradient(circle, color-mix(in srgb, var(--good) 20%, transparent), transparent 70%); }
.hero-copy { position: relative; z-index: 1; min-width: 0; }
.plugin-hero .page-kicker { margin-bottom: 8px; letter-spacing: .18em; }
.plugin-hero h1 {
  margin: 0 0 10px;
  font-size: clamp(30px, 3.1vw, 42px);
  line-height: 1.05;
  letter-spacing: -.045em;
  background: linear-gradient(120deg, var(--ink) 18%, color-mix(in srgb, var(--brand) 58%, var(--ink)) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.plugin-hero p { margin: 0; max-width: 640px; color: var(--muted); font-size: 13px; line-height: 1.7; }
.hero-stats { display: flex; gap: 7px; flex-wrap: wrap; margin-top: 18px; }
.hero-stats span {
  display: inline-flex; align-items: baseline; gap: 6px;
  padding: 6px 12px;
  border-radius: 99px;
  border: 1px solid color-mix(in srgb, var(--brand) 18%, var(--line));
  background: color-mix(in srgb, var(--surface) 58%, transparent);
  color: var(--muted);
  font-size: 10.5px;
  letter-spacing: .02em;
  backdrop-filter: blur(8px);
}
.hero-stats b { font-size: 15px; color: var(--ink); letter-spacing: -.02em; }
.hero-actions { position: relative; z-index: 1; display: flex; gap: 8px; flex: 0 0 auto; padding-top: 4px; }
.hero-btn { height: 38px; border-radius: 11px; }

.plugin-tabs {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 18px; padding: 5px;
  background: color-mix(in srgb, var(--surface) 72%, transparent);
  border: 1px solid var(--line);
  border-radius: 14px;
  backdrop-filter: blur(14px);
  box-shadow: 0 10px 30px color-mix(in srgb, #000 4%, transparent);
  animation: hy-rise .45s .04s var(--ease) both;
}
.plugin-tab { display: inline-flex; align-items: center; gap: 7px; height: 36px; padding: 0 14px; border-radius: 10px; border: 1px solid transparent; background: transparent; color: var(--muted); font-size: 12.5px; font-weight: 600; transition: all .16s var(--ease); }
.plugin-tab .icon { color: var(--faint); transition: color .16s var(--ease); }
.plugin-tab:hover { color: var(--ink); background: var(--surface-2); }
.plugin-tab.active {
  color: var(--ink);
  background: linear-gradient(120deg, color-mix(in srgb, var(--brand) 17%, var(--surface)), color-mix(in srgb, var(--brand-2) 9%, var(--surface)));
  border-color: color-mix(in srgb, var(--brand) 26%, var(--line));
  box-shadow: 0 6px 18px color-mix(in srgb, var(--brand) 12%, transparent);
}
.plugin-tab.active .icon { color: var(--brand); }
.tab-count { display: inline-grid; place-items: center; min-width: 20px; height: 18px; padding: 0 5px; border-radius: 99px; background: var(--surface-3); font-size: 10px; }
.plugin-tab.active .tab-count { background: color-mix(in srgb, var(--brand) 16%, transparent); color: var(--brand); }

.account-strip {
  position: relative;
  overflow: hidden;
  display: flex; align-items: center; gap: 14px;
  padding: 18px 20px; margin-bottom: 16px;
  border-radius: 18px;
  border: 1px solid color-mix(in srgb, var(--good) 26%, var(--line));
  background: linear-gradient(120deg, var(--good-soft), var(--surface) 62%);
  box-shadow: 0 14px 36px color-mix(in srgb, var(--good) 7%, transparent);
  animation: hy-rise .45s .06s var(--ease) both;
}
.account-strip::after {
  content: "";
  position: absolute;
  right: -40px; top: -60px;
  width: 180px; height: 180px;
  border-radius: 50%;
  background: radial-gradient(circle, color-mix(in srgb, var(--good) 18%, transparent), transparent 68%);
  pointer-events: none;
}
.account-strip.off { border-color: var(--line); background: var(--surface); }
.account-strip.setup { border-color: color-mix(in srgb, var(--warn) 34%, var(--line)); background: linear-gradient(120deg, var(--warn-soft), var(--surface)); }
.account-strip-icon { width: 50px; height: 50px; flex: 0 0 50px; border-radius: 15px; display: grid; place-items: center; background: linear-gradient(140deg, color-mix(in srgb, var(--good) 20%, var(--surface)), color-mix(in srgb, var(--brand-2) 10%, var(--surface))); color: var(--good); border: 1px solid color-mix(in srgb, var(--good) 28%, transparent); box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 8px 20px color-mix(in srgb, var(--good) 12%, transparent); }
.account-strip.off .account-strip-icon { background: var(--surface-2); color: var(--muted); border-color: var(--line); box-shadow: none; }
.account-strip.setup .account-strip-icon { background: linear-gradient(140deg, var(--warn-soft), color-mix(in srgb, var(--warn) 8%, var(--surface))); color: var(--warn); border-color: color-mix(in srgb, var(--warn) 28%, transparent); }
.account-strip-copy { flex: 1; min-width: 0; }
.account-strip-copy b { font-size: 14px; letter-spacing: -.01em; }
.account-strip-copy > span { display: block; color: var(--muted); font-size: 11.5px; }

.plugin-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; margin-bottom: 22px; animation: hy-rise .5s .08s var(--ease) both; }
.plugin-card {
  position: relative;
  overflow: hidden;
  padding: 18px;
  background: linear-gradient(180deg, var(--surface), color-mix(in srgb, var(--surface-2) 40%, var(--surface)));
  border: 1px solid var(--line);
  border-radius: 18px;
  display: flex; flex-direction: column; gap: 11px;
  transition: transform .2s var(--ease), border-color .2s var(--ease), box-shadow .2s var(--ease), opacity .2s var(--ease);
}
.plugin-card::before {
  content: "";
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--brand) 34%, transparent), transparent);
  opacity: 0;
  transition: opacity .2s var(--ease);
}
.plugin-card:hover { border-color: var(--line-strong); transform: translateY(-3px); box-shadow: 0 22px 48px color-mix(in srgb, var(--brand) 10%, transparent); }
.plugin-card:hover::before { opacity: 1; }
.plugin-card.disabled { opacity: .66; }
.plugin-card.disabled:hover { opacity: .86; }
.plugin-card.error { border-color: color-mix(in srgb, var(--bad) 40%, var(--line)); }
.plugin-head { display: flex; align-items: flex-start; gap: 11px; }
.plugin-icon {
  width: 46px; height: 46px; flex: 0 0 46px;
  border-radius: 14px;
  background: linear-gradient(140deg, color-mix(in srgb, var(--brand) 18%, var(--surface)), color-mix(in srgb, var(--brand-2) 10%, var(--surface)));
  color: var(--brand);
  display: grid; place-items: center;
  border: 1px solid color-mix(in srgb, var(--brand) 20%, var(--line));
  box-shadow: inset 0 1px 0 rgba(255,255,255,.12), 0 8px 18px color-mix(in srgb, var(--brand) 10%, transparent);
}
.plugin-card:nth-child(3n + 2) .plugin-icon { background: linear-gradient(140deg, color-mix(in srgb, var(--good) 17%, var(--surface)), color-mix(in srgb, var(--brand-2) 10%, var(--surface))); color: var(--good); border-color: color-mix(in srgb, var(--good) 20%, var(--line)); }
.plugin-card:nth-child(3n + 3) .plugin-icon { background: linear-gradient(140deg, color-mix(in srgb, var(--warn) 16%, var(--surface)), color-mix(in srgb, var(--brand) 10%, var(--surface))); color: var(--warn); border-color: color-mix(in srgb, var(--warn) 20%, var(--line)); }
.plugin-title { flex: 1; min-width: 0; }
.plugin-title h3 { margin: 0; font-size: 14px; letter-spacing: -.015em; }
.plugin-desc { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.6; flex: 1; }
.plugin-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.plugin-error { display: flex; gap: 6px; align-items: center; color: var(--bad); font-size: 11px; background: var(--bad-soft); border-radius: 8px; padding: 6px 8px; }
.plugin-actions { display: flex; align-items: center; gap: 6px; padding-top: 11px; border-top: 1px solid var(--line); }
.delete-btn { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 28%, var(--line)); background: transparent; }
.delete-btn:hover { background: color-mix(in srgb, var(--bad) 10%, transparent); border-color: color-mix(in srgb, var(--bad) 46%, var(--line)); color: var(--bad); }
.delete-btn.delete-locked { opacity: .55; color: var(--muted); border-color: var(--line); }
.delete-btn.delete-locked:hover { background: var(--surface-2); color: var(--muted); }

.manual-card { padding: 24px; margin-top: 6px; border-radius: 20px; background: linear-gradient(180deg, var(--surface), color-mix(in srgb, var(--surface-2) 35%, var(--surface))); animation: hy-rise .5s .1s var(--ease) both; }
.manual-head { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 18px; }
.manual-icon { width: 42px; height: 42px; flex: 0 0 42px; border-radius: 12px; display: grid; place-items: center; background: var(--brand-soft); color: var(--brand); border: 1px solid var(--brand-line); }
.manual-head h2 { margin: 0 0 4px; font-size: 20px; letter-spacing: -.025em; }
.manual-head p { margin: 0; color: var(--muted); font-size: 12px; }
.way-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 11px; }
.way-card {
  position: relative;
  padding: 16px;
  background: color-mix(in srgb, var(--surface-2) 68%, transparent);
  border: 1px solid var(--line);
  border-radius: 14px;
  display: flex; flex-direction: column; gap: 5px;
  transition: border-color .16s var(--ease), transform .16s var(--ease);
}
.way-card:hover { border-color: var(--brand-line); transform: translateY(-2px); }
.way-num { width: 22px; height: 22px; display: grid; place-items: center; border-radius: 7px; background: var(--brand-soft); color: var(--brand); font-size: 11px; font-weight: 700; margin-bottom: 3px; }
.way-card b { font-size: 12.5px; }
.way-card span { font-size: 11px; color: var(--muted); line-height: 1.5; }
.way-card code { margin-top: 4px; color: var(--brand); font-size: 10px; word-break: break-all; }

.market-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 11px; margin-bottom: 18px; animation: hy-rise .45s .04s var(--ease) both; }
.search-box {
  display: flex; align-items: center; gap: 8px;
  flex: 1; min-width: 240px; height: 42px; padding: 0 13px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 78%, transparent);
  backdrop-filter: blur(10px);
  color: var(--faint);
  transition: all .18s var(--ease);
}
.search-box:focus-within { border-color: var(--brand-line); background: var(--surface); box-shadow: 0 0 0 3px var(--brand-soft), 0 10px 24px color-mix(in srgb, var(--brand) 8%, transparent); }
.search-input { flex: 1; min-width: 0; border: none; outline: none; background: transparent; font-size: 13px; }
.category-row { display: flex; gap: 6px; flex-wrap: wrap; }
.category-chip { height: 32px; padding: 0 13px; border-radius: 99px; border: 1px solid var(--line); background: color-mix(in srgb, var(--surface) 78%, transparent); color: var(--muted); font-size: 11.5px; transition: all .16s var(--ease); }
.category-chip:hover { color: var(--ink); border-color: var(--line-strong); background: var(--surface); }
.category-chip.active { color: var(--brand); background: var(--brand-soft); border-color: var(--brand-line); box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand) 6%, transparent); }

.market-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px; animation: hy-rise .5s .08s var(--ease) both; }
.market-card {
  display: flex; flex-direction: column;
  background: linear-gradient(180deg, var(--surface), color-mix(in srgb, var(--surface-2) 34%, var(--surface)));
  border: 1px solid var(--line);
  border-radius: 18px;
  overflow: hidden;
  transition: transform .2s var(--ease), border-color .2s var(--ease), box-shadow .2s var(--ease);
}
.market-card:hover { border-color: var(--line-strong); transform: translateY(-3px); box-shadow: 0 22px 48px color-mix(in srgb, var(--brand) 10%, transparent); }
.market-card.installed { border-color: color-mix(in srgb, var(--good) 26%, var(--line)); }
.market-cover { position: relative; height: 92px; display: flex; align-items: center; padding: 0 18px; background: linear-gradient(135deg, color-mix(in srgb, var(--brand) 18%, transparent), color-mix(in srgb, var(--brand-2) 8%, transparent)); border-bottom: 1px solid var(--line); }
.market-card.cat-security .market-cover { background: linear-gradient(135deg, color-mix(in srgb, var(--brand) 22%, var(--surface)), color-mix(in srgb, var(--brand-2) 10%, var(--surface))); }
.market-card.cat-developer .market-cover { background: linear-gradient(135deg, color-mix(in srgb, var(--brand-2) 20%, var(--surface)), color-mix(in srgb, var(--brand) 8%, var(--surface))); }
.market-card.cat-productivity .market-cover { background: linear-gradient(135deg, color-mix(in srgb, var(--good) 18%, var(--surface)), color-mix(in srgb, var(--brand-2) 8%, var(--surface))); }
.market-cover::after {
  content: "";
  position: absolute;
  right: -30px; top: -50px;
  width: 150px; height: 150px;
  border-radius: 50%;
  background: radial-gradient(circle, color-mix(in srgb, var(--brand) 22%, transparent), transparent 68%);
  pointer-events: none;
}
.market-icon { position: relative; z-index: 1; width: 52px; height: 52px; border-radius: 15px; display: grid; place-items: center; background: var(--surface); color: var(--brand); border: 1px solid var(--line); box-shadow: 0 12px 26px color-mix(in srgb, #000 10%, transparent); }
.featured-tag { position: absolute; z-index: 2; top: 12px; right: 12px; }
.market-body { padding: 16px 18px 11px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
.market-body h3 { margin: 0; font-size: 14.5px; letter-spacing: -.02em; }
.market-body p { margin: 0; color: var(--muted); font-size: 11.5px; line-height: 1.6; flex: 1; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.market-foot { display: flex; align-items: center; gap: 8px; padding: 12px 18px; border-top: 1px solid var(--line); background: color-mix(in srgb, var(--surface-2) 62%, transparent); }
.market-foot .tiny { display: inline-flex; align-items: center; gap: 4px; }
.skeleton-card { height: 250px; padding: 0; }
.offline-card { padding: 44px 24px; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 8px; }
.offline-icon { width: 58px; height: 58px; border-radius: 17px; display: grid; place-items: center; background: var(--warn-soft); color: var(--warn); border: 1px solid color-mix(in srgb, var(--warn) 24%, transparent); margin-bottom: 4px; }
.offline-card h2 { margin: 0; font-size: 19px; letter-spacing: -.02em; }
.offline-card p { margin: 0 0 4px; color: var(--muted); font-size: 12.5px; max-width: 460px; }
.center-config { width: min(520px, 100%); display: flex; flex-direction: column; gap: 6px; margin-top: 6px; text-align: left; }
.center-url-row { display: flex; gap: 8px; }
.center-url-row .field { flex: 1; min-width: 0; }
.offline-error { color: var(--bad); max-width: 520px; word-break: break-word; margin-top: 2px; }
.empty-market { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 60px 20px; color: var(--faint); }
.empty-market b { color: var(--ink-2); font-size: 14px; }
.empty-market span { font-size: 12px; }

.upload-modal { width: min(560px, calc(100vw - 32px)); }
.upload-head-icon { width: 36px; height: 36px; flex: 0 0 36px; border-radius: 10px; display: grid; place-items: center; background: var(--brand-soft); color: var(--brand); border: 1px solid var(--brand-line); }
.drop-zone { display: flex; flex-direction: column; align-items: center; gap: 5px; padding: 30px 20px; border: 1.5px dashed var(--line-strong); border-radius: 15px; background: var(--surface-2); text-align: center; cursor: pointer; transition: all .16s var(--ease); }
.drop-zone:hover, .drop-zone.active { border-color: var(--brand); background: var(--brand-soft); }
.drop-icon { width: 52px; height: 52px; border-radius: 15px; display: grid; place-items: center; background: var(--surface); color: var(--brand); border: 1px solid var(--line); margin-bottom: 4px; }
.drop-zone b { font-size: 13.5px; }
.drop-zone > span:not(.drop-icon):not(.btn) { color: var(--muted); font-size: 11.5px; }
.upload-notes { display: flex; flex-direction: column; gap: 6px; margin-top: 14px; }
.upload-notes span { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 11.5px; }
.upload-notes .icon { color: var(--good); }

.confirm-modal { width: min(470px, calc(100vw - 32px)); }
.confirm-head-icon { width: 36px; height: 36px; flex: 0 0 36px; border-radius: 10px; display: grid; place-items: center; background: var(--bad-soft, color-mix(in srgb, var(--bad) 12%, transparent)); color: var(--bad); border: 1px solid color-mix(in srgb, var(--bad) 24%, transparent); }
.confirm-text { margin: 0 0 12px; color: var(--ink-2); font-size: 13px; line-height: 1.65; }
.confirm-list { margin: 0; padding: 12px 14px; list-style: none; display: flex; flex-direction: column; gap: 8px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface-2); }
.confirm-list li { display: flex; align-items: flex-start; gap: 8px; font-size: 12px; color: var(--muted); line-height: 1.5; }
.confirm-list li .icon { flex: 0 0 auto; margin-top: 2px; color: var(--bad); }
.confirm-list li:last-child .icon { color: var(--warn); }

@keyframes hy-rise {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (max-width: 860px) {
  .way-grid { grid-template-columns: 1fr; }
  .account-strip { flex-wrap: wrap; }
  .plugin-hero { flex-direction: column; align-items: stretch; }
  .hero-actions { width: 100%; }
  .hero-actions .btn { flex: 1; }
}
@media (max-width: 720px) {
  .plugins-page { padding-top: 18px; }
  .plugin-hero { padding: 22px 20px; border-radius: 20px; }
  .plugin-hero h1 { font-size: 30px; }
  .plugin-grid, .market-grid { grid-template-columns: 1fr; }
  .plugin-tabs { gap: 6px; }
  .plugin-tabs .spacer, .plugin-tabs > .badge { display: none; }
  .plugin-tab { flex: 1; justify-content: center; }
  .account-strip { flex-wrap: wrap; padding: 15px; }
  .account-strip .btn { width: 100%; justify-content: center; }
  .manual-card { padding: 16px; }
  .category-row { width: 100%; }
  .market-toolbar { align-items: stretch; }
}
</style>
