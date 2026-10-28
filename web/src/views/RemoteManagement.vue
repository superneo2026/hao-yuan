<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  addRemoteSystem,
  createRemoteKey,
  deleteRemoteIncoming,
  deleteRemoteKey,
  deleteRemoteSystem,
  loadRemoteManagement,
  loadRemoteSystem,
  refreshRemoteSystem,
  refreshRemoteSystems,
  remoteIncomingAction,
  remoteSystemAction,
  saveRemoteSettings,
  state,
  toast
} from '../stores/app'
import { t } from '../i18n'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()

const systemId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const detail = ref(null)
const loadingSystem = ref(false)
const fullscreen = ref(false)
const frameLoading = ref(false)
const frameTick = ref(0)
const keyLabel = ref('')
const connectCode = ref('')
const connectUrl = ref('')
const connectName = ref('')
const connecting = ref(false)
const savingSettings = ref(false)
const instanceName = ref('')
const publicUrl = ref('')
const openCodes = ref({})
const copied = ref('')
const busy = ref('')

const remote = computed(() => state.remote)
const instance = computed(() => remote.value.instance || {})
const keys = computed(() => remote.value.keys || [])
const incoming = computed(() => remote.value.incoming || [])
const outgoing = computed(() => remote.value.outgoing || [])
const pendingCount = computed(() => incoming.value.filter((item) => item.status === 'pending').length)
const approvedCount = computed(() => outgoing.value.filter((item) => item.enabled !== false && item.status === 'approved').length)
const localHint = computed(() => !!instance.value.local_hint)

const frameSrc = computed(() => {
  const system = detail.value
  if (!system || !system.remote_token || system.enabled === false) return ''
  try {
    const url = new URL(system.url)
    url.searchParams.set('hy_remote_token', system.remote_token)
    url.hash = ''
    return url.toString()
  } catch {
    return ''
  }
})

const detailStatus = computed(() => {
  if (!detail.value) return ''
  if (detail.value.enabled === false) return 'paused'
  return detail.value.status || 'pending'
})

const canEmbed = computed(() => !!frameSrc.value && detailStatus.value === 'approved')

function syncInstance() {
  instanceName.value = instance.value.name || ''
  publicUrl.value = instance.value.public_url || ''
}

async function refreshAll() {
  try {
    if (systemId.value) await loadSystem(systemId.value)
    else await loadRemoteManagement()
    syncInstance()
  } catch (error) {
    toast(error.message, 'bad')
  }
}

async function loadSystem(id) {
  loadingSystem.value = true
  try {
    detail.value = await loadRemoteSystem(id)
    if (detail.value && detail.value.status === 'approved' && detail.value.enabled !== false && !detail.value.remote_token) {
      detail.value = await refreshRemoteSystem(id)
    }
  } catch (error) {
    detail.value = null
    toast(error.message, 'bad')
    router.replace('/remote')
  } finally {
    loadingSystem.value = false
  }
}

async function saveInstance() {
  savingSettings.value = true
  try {
    await saveRemoteSettings({ instance_name: instanceName.value, public_url: publicUrl.value })
    await loadRemoteManagement()
    syncInstance()
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    savingSettings.value = false
  }
}

async function generateKey() {
  busy.value = 'create-key'
  try {
    const data = await createRemoteKey(keyLabel.value)
    keyLabel.value = ''
    if (data?.id) openCodes.value = { ...openCodes.value, [data.id]: true }
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busy.value = ''
  }
}

async function removeKey(key) {
  if (!window.confirm(t('remote.deleteKeyConfirm', { label: key.label }))) return
  busy.value = `key-${key.id}`
  try {
    await deleteRemoteKey(key.id)
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busy.value = ''
  }
}

async function actIncoming(item, action) {
  busy.value = `incoming-${item.id}`
  try {
    await remoteIncomingAction(item.id, action)
    const messages = {
      approve: t('remote.approvedToast'),
      reject: t('remote.rejectedToast'),
      revoke: t('remote.revokedToast'),
      restore: t('remote.restoredToast')
    }
    toast(messages[action] || t('remote.actionDone'), action === 'revoke' || action === 'reject' ? 'warn' : 'good')
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busy.value = ''
  }
}

async function removeIncoming(item) {
  if (!window.confirm(t('remote.deleteRequestConfirm', { name: item.manager_name }))) return
  busy.value = `incoming-${item.id}`
  try {
    await deleteRemoteIncoming(item.id)
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busy.value = ''
  }
}

async function sendConnect() {
  if (!connectCode.value.trim()) {
    toast(t('remote.needKey'), 'warn')
    return
  }
  connecting.value = true
  try {
    await addRemoteSystem({ code: connectCode.value.trim(), url: connectUrl.value.trim(), name: connectName.value.trim() })
    connectCode.value = ''
    connectUrl.value = ''
    connectName.value = ''
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    connecting.value = false
  }
}

async function refreshSystems() {
  busy.value = 'refresh-all'
  try {
    await refreshRemoteSystems()
    toast(t('remote.refreshed'), 'good')
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busy.value = ''
  }
}

async function openSystem(system) {
  router.push(`/remote/system/${system.id}`)
}

async function refreshSystem() {
  if (!systemId.value) return
  busy.value = 'refresh-system'
  try {
    detail.value = await refreshRemoteSystem(systemId.value)
    frameTick.value++
    toast(t('remote.refreshed'), detailStatus.value === 'approved' ? 'good' : 'warn')
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busy.value = ''
  }
}

async function systemAction(action) {
  if (!systemId.value) return
  busy.value = `system-${action}`
  try {
    detail.value = await remoteSystemAction(systemId.value, action)
    toast(action === 'pause' ? t('remote.pausedToast') : t('remote.resumedToast'), 'info')
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busy.value = ''
  }
}

async function removeSystem(system) {
  const target = system || detail.value
  if (!target) return
  if (!window.confirm(t('remote.removeSystemConfirm', { name: target.name || target.url }))) return
  busy.value = 'remove-system'
  try {
    await deleteRemoteSystem(target.id)
    if (systemId.value) router.push('/remote')
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    busy.value = ''
  }
}

async function copyText(text, mark = '') {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = mark
    toast(t('common.copied'), 'good', 1600)
    setTimeout(() => {
      if (copied.value === mark) copied.value = ''
    }, 1600)
  } catch {
    toast(t('common.copyFailed'), 'bad')
  }
}

function toggleCode(id) {
  openCodes.value = { ...openCodes.value, [id]: !openCodes.value[id] }
}

function statusLabel(status) {
  return t(`remote.status.${status || 'pending'}`)
}

function statusTone(status) {
  if (status === 'approved') return 'good'
  if (status === 'pending') return 'warn'
  if (status === 'revoked' || status === 'rejected') return 'bad'
  return ''
}

function incomingActions(item) {
  if (item.status === 'pending') return ['approve', 'reject', 'delete']
  if (item.status === 'approved') return ['revoke', 'delete']
  return ['restore', 'delete']
}

function actionLabel(action) {
  return t(`remote.action.${action}`)
}

function actionIcon(action) {
  return { approve: 'check', reject: 'close', revoke: 'log-out', restore: 'refresh', delete: 'trash' }[action] || 'circle'
}

function openExternal() {
  const url = frameSrc.value || detail.value?.url
  if (url) window.open(url, '_blank', 'noopener')
}

function onKeydown(event) {
  if (event.key === 'Escape' && fullscreen.value) fullscreen.value = false
}

watch(
  systemId,
  async (id) => {
    detail.value = null
    fullscreen.value = false
    if (id) await loadSystem(id)
    else await loadRemoteManagement()
  },
  { immediate: true }
)

watch(
  () => remote.value.instance,
  () => syncInstance()
)

onMounted(() => {
  syncInstance()
  window.addEventListener('keydown', onKeydown)
  if (!systemId.value) loadRemoteManagement().catch(() => {}).then(syncInstance)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="page remote-page">
    <template v-if="!systemId">
      <header class="page-head">
        <div>
          <div class="page-kicker">{{ t('remote.kicker') }}</div>
          <h1>{{ t('remote.title') }}</h1>
          <p>{{ t('remote.subtitle') }}</p>
        </div>
        <div class="remote-head-actions">
          <span v-if="pendingCount" class="badge warn"><Icon name="alert" :size="12" /> {{ t('remote.pendingBadge', { n: pendingCount }) }}</span>
          <button class="btn" :disabled="remote.loading" @click="refreshAll">
            <span v-if="remote.loading" class="spinner" style="width: 12px; height: 12px" />
            <Icon v-else name="refresh" :size="15" /> {{ t('common.refresh') }}
          </button>
        </div>
      </header>

      <div v-if="remote.error" class="remote-error"><Icon name="alert" :size="14" /> {{ remote.error }}</div>

      <section class="remote-instance card">
        <div class="instance-main">
          <span class="instance-icon"><Icon name="globe" :size="21" /></span>
          <div class="instance-copy">
            <div class="row" style="gap: 8px; flex-wrap: wrap">
              <h2>{{ instance.name || 'HaoYuan' }}</h2>
              <span class="badge good"><span class="status-dot done" /> {{ t('remote.online') }}</span>
              <span v-if="approvedCount" class="badge">{{ t('remote.managingCount', { n: approvedCount }) }}</span>
            </div>
            <span class="mono tiny faint">{{ instance.public_url || t('remote.urlUnset') }}</span>
          </div>
        </div>
        <div class="instance-settings">
          <label class="field-wrap">
            <span>{{ t('remote.instanceName') }}</span>
            <input v-model="instanceName" class="field" :placeholder="t('remote.instanceNamePlaceholder')" />
          </label>
          <label class="field-wrap">
            <span>{{ t('remote.publicUrl') }}</span>
            <input v-model="publicUrl" class="field mono" placeholder="https://haoyuan.example.com" />
          </label>
          <button class="btn primary" :disabled="savingSettings" @click="saveInstance">
            <span v-if="savingSettings" class="spinner" style="width: 12px; height: 12px" />
            <Icon v-else name="check" :size="14" /> {{ t('common.save') }}
          </button>
        </div>
      </section>
      <p v-if="localHint" class="remote-hint">
        <Icon name="alert" :size="13" />
        {{ t('remote.localHint') }}
      </p>

      <div class="remote-grid">
        <section class="remote-card card">
          <div class="remote-card-head">
            <span class="remote-card-icon key"><Icon name="key" :size="17" /></span>
            <div>
              <h2>{{ t('remote.keysTitle') }}</h2>
              <p>{{ t('remote.keysDesc') }}</p>
            </div>
            <span class="badge">{{ keys.length }}</span>
          </div>
          <div class="key-create">
            <input v-model="keyLabel" class="field" :placeholder="t('remote.keyLabelPlaceholder')" @keyup.enter="generateKey" />
            <button class="btn primary" :disabled="busy === 'create-key'" @click="generateKey">
              <span v-if="busy === 'create-key'" class="spinner" style="width: 12px; height: 12px" />
              <Icon v-else name="plus" :size="14" /> {{ t('remote.generateKey') }}
            </button>
          </div>
          <div class="key-list">
            <div v-for="key in keys" :key="key.id" class="key-item">
              <div class="key-top">
                <div class="key-name">
                  <b>{{ key.label }}</b>
                  <span class="mono tiny faint">{{ key.masked_secret }}</span>
                </div>
                <div class="key-actions">
                  <button class="btn sm" @click="toggleCode(key.id)">
                    <Icon :name="openCodes[key.id] ? 'eye-off' : 'eye'" :size="13" />
                    {{ openCodes[key.id] ? t('remote.hideCode') : t('remote.showCode') }}
                  </button>
                  <button class="btn sm" @click="copyText(key.connection_code, key.id)">
                    <Icon :name="copied === key.id ? 'check' : 'copy'" :size="13" /> {{ t('remote.copyCode') }}
                  </button>
                  <button class="icon-btn" :disabled="busy === `key-${key.id}`" @click="removeKey(key)">
                    <Icon name="trash" :size="14" />
                  </button>
                </div>
              </div>
              <div v-if="openCodes[key.id]" class="key-code">
                <textarea class="field mono" readonly :value="key.connection_code" rows="3" @focus="$event.target.select()" />
                <span class="tiny faint">{{ t('remote.keyCodeHint', { name: instance.name }) }}</span>
              </div>
            </div>
            <div v-if="!keys.length" class="empty-block">
              <Icon name="key" :size="24" />
              <b>{{ t('remote.noKeys') }}</b>
              <span>{{ t('remote.noKeysDesc') }}</span>
            </div>
          </div>
        </section>

        <section class="remote-card card">
          <div class="remote-card-head">
            <span class="remote-card-icon accept"><Icon name="log-in" :size="17" /></span>
            <div>
              <h2>{{ t('remote.incomingTitle') }}</h2>
              <p>{{ t('remote.incomingDesc') }}</p>
            </div>
            <span class="badge" :class="pendingCount ? 'warn' : ''">{{ incoming.length }}</span>
          </div>
          <div class="request-list">
            <div v-for="item in incoming" :key="item.id" class="request-item">
              <div class="request-top">
                <div class="request-copy">
                  <div class="row" style="gap: 7px; flex-wrap: wrap">
                    <b>{{ item.manager_name }}</b>
                    <span class="badge" :class="statusTone(item.status)">{{ statusLabel(item.status) }}</span>
                    <span class="badge">{{ item.key_label }}</span>
                  </div>
                  <span class="mono tiny faint">{{ item.manager_url || t('remote.urlUnknown') }}</span>
                </div>
                <span class="tiny faint">{{ item.created_at?.replace('T', ' ').slice(0, 19) }}</span>
              </div>
              <div class="request-actions">
                <button
                  v-for="action in incomingActions(item)"
                  :key="action"
                  class="btn sm"
                  :class="{ primary: action === 'approve' || action === 'restore', danger: action === 'revoke' || action === 'reject' }"
                  :disabled="busy === `incoming-${item.id}`"
                  @click="action === 'delete' ? removeIncoming(item) : actIncoming(item, action)"
                >
                  <Icon :name="actionIcon(action)" :size="13" /> {{ actionLabel(action) }}
                </button>
              </div>
            </div>
            <div v-if="!incoming.length" class="empty-block">
              <Icon name="log-in" :size="24" />
              <b>{{ t('remote.noIncoming') }}</b>
              <span>{{ t('remote.noIncomingDesc') }}</span>
            </div>
          </div>
        </section>
      </div>

      <section class="remote-card card outgoing-card">
        <div class="remote-card-head">
          <span class="remote-card-icon manage"><Icon name="network" :size="17" /></span>
          <div>
            <h2>{{ t('remote.outgoingTitle') }}</h2>
            <p>{{ t('remote.outgoingDesc') }}</p>
          </div>
          <button class="btn sm" :disabled="busy === 'refresh-all'" @click="refreshSystems">
            <span v-if="busy === 'refresh-all'" class="spinner" style="width: 11px; height: 11px" />
            <Icon v-else name="refresh" :size="13" /> {{ t('remote.refreshAll') }}
          </button>
        </div>

        <div class="connect-form">
          <label class="field-wrap connect-code">
            <span>{{ t('remote.connectCode') }}</span>
            <input v-model="connectCode" class="field mono" :placeholder="t('remote.connectCodePlaceholder')" />
          </label>
          <label class="field-wrap">
            <span>{{ t('remote.displayName') }}</span>
            <input v-model="connectName" class="field" :placeholder="t('remote.displayNamePlaceholder')" />
          </label>
          <label class="field-wrap">
            <span>{{ t('remote.fallbackUrl') }}</span>
            <input v-model="connectUrl" class="field mono" placeholder="http://192.168.1.20:8030" />
          </label>
          <button class="btn primary connect-btn" :disabled="connecting" @click="sendConnect">
            <span v-if="connecting" class="spinner" style="width: 12px; height: 12px" />
            <Icon v-else name="send" :size="14" /> {{ connecting ? t('remote.sending') : t('remote.sendRequest') }}
          </button>
        </div>
        <p class="tiny faint connect-hint">{{ t('remote.connectHint') }}</p>

        <div class="system-list">
          <article v-for="system in outgoing" :key="system.id" class="system-item">
            <span class="system-avatar"><Icon name="globe" :size="18" /></span>
            <div class="system-copy">
              <div class="row" style="gap: 8px; flex-wrap: wrap">
                <b>{{ system.name || system.target_name || system.url }}</b>
                <span class="badge" :class="statusTone(system.status)">{{ system.enabled === false ? t('remote.status.paused') : statusLabel(system.status) }}</span>
                <span v-if="system.target_name" class="badge">{{ system.target_name }}</span>
              </div>
              <span class="mono tiny faint">{{ system.url }}</span>
              <span v-if="system.last_error" class="system-error"><Icon name="alert" :size="12" /> {{ system.last_error }}</span>
            </div>
            <div class="system-actions">
              <button class="btn sm primary" :disabled="system.status !== 'approved' || system.enabled === false" @click="openSystem(system)">
                <Icon name="external" :size="13" /> {{ t('remote.open') }}
              </button>
              <button class="icon-btn" :title="t('common.refresh')" @click="refreshSystems">
                <Icon name="refresh" :size="14" />
              </button>
              <button class="icon-btn" :title="t('remote.remove')" @click="removeSystem(system)">
                <Icon name="trash" :size="14" />
              </button>
            </div>
          </article>
          <div v-if="!outgoing.length" class="empty-block wide">
            <Icon name="network" :size="24" />
            <b>{{ t('remote.noSystems') }}</b>
            <span>{{ t('remote.noSystemsDesc') }}</span>
          </div>
        </div>
      </section>
    </template>

    <div v-else class="remote-workspace" :class="{ fullscreen }">
      <header class="ws-bar">
        <div class="ws-identity">
          <button class="icon-btn ws-back" title="返回" @click="router.push('/remote')">
            <Icon name="chevron-left" :size="16" />
          </button>
          <span class="system-avatar sm"><Icon name="globe" :size="16" /></span>
          <div class="ws-copy">
            <div class="row" style="gap: 8px; flex-wrap: wrap">
              <b>{{ detail?.name || detail?.target_name || t('remote.remoteSystem') }}</b>
              <span class="badge" :class="statusTone(detailStatus)">{{ detailStatus === 'paused' ? t('remote.status.paused') : statusLabel(detailStatus) }}</span>
              <span v-if="detail?.last_error" class="badge bad">{{ t('remote.offline') }}</span>
            </div>
            <span class="mono tiny faint">{{ detail?.url }}</span>
          </div>
        </div>
        <div class="ws-actions">
          <button class="btn sm" :disabled="busy === 'refresh-system'" @click="refreshSystem">
            <span v-if="busy === 'refresh-system'" class="spinner" style="width: 11px; height: 11px" />
            <Icon v-else name="refresh" :size="13" /> {{ t('remote.refreshToken') }}
          </button>
          <button class="btn sm" @click="openExternal"><Icon name="external" :size="13" /> {{ t('remote.openExternal') }}</button>
          <button class="btn sm" :disabled="!detail" @click="systemAction(detail?.enabled === false ? 'resume' : 'pause')">
            <Icon :name="detail?.enabled === false ? 'play' : 'square'" :size="13" />
            {{ detail?.enabled === false ? t('remote.resume') : t('remote.pause') }}
          </button>
          <button class="icon-btn" :title="t('remote.remove')" @click="removeSystem(detail)">
            <Icon name="trash" :size="14" />
          </button>
          <button class="btn sm" @click="fullscreen = !fullscreen">
            <Icon :name="fullscreen ? 'close' : 'plus'" :size="13" />
            {{ fullscreen ? t('remote.exitFullscreen') : t('remote.fullscreen') }}
          </button>
        </div>
      </header>

      <div class="ws-body">
        <div v-if="loadingSystem" class="ws-placeholder"><span class="spinner" /> {{ t('common.loading') }}</div>
        <div v-else-if="!canEmbed" class="ws-placeholder">
          <span class="placeholder-icon" :class="statusTone(detailStatus)"><Icon name="globe" :size="28" /></span>
          <b>{{ t('remote.notReadyTitle') }}</b>
          <span>{{ t(`remote.notReady.${detailStatus || 'pending'}`) }}</span>
          <div class="row" style="gap: 8px; flex-wrap: wrap; justify-content: center">
            <button class="btn primary" :disabled="busy === 'refresh-system'" @click="refreshSystem">
              <Icon name="refresh" :size="14" /> {{ t('remote.checkAgain') }}
            </button>
            <button class="btn" @click="router.push('/remote')">{{ t('remote.backOverview') }}</button>
          </div>
          <span v-if="detail?.last_error" class="mono tiny" style="color: var(--bad)">{{ detail.last_error }}</span>
        </div>
        <template v-else>
          <div v-if="frameLoading" class="frame-loading"><span class="spinner" /> {{ t('remote.connectingFrame') }}</div>
          <iframe
            :key="`${frameSrc}-${frameTick}`"
            class="remote-frame"
            :src="frameSrc"
            :title="detail?.name || 'HaoYuan'"
            allow="clipboard-read; clipboard-write; fullscreen"
            referrerpolicy="no-referrer"
            @load="frameLoading = false"
          />
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.remote-page { max-width: 1420px; padding-top: 24px; overflow-x: hidden; }
.remote-page .page-head { min-width: 0; }
.remote-page .page-head > div:first-child { min-width: 0; }
.remote-page .page-head p { max-width: 760px; }
.remote-head-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.remote-error {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 14px; padding: 11px 14px;
  border-radius: 12px; border: 1px solid color-mix(in srgb, var(--bad) 30%, var(--line));
  background: var(--bad-soft); color: var(--bad); font-size: 12px;
}
.remote-instance {
  display: flex; align-items: flex-end; justify-content: space-between; gap: 22px; flex-wrap: wrap;
  padding: 20px 22px; margin-bottom: 12px;
  background: linear-gradient(120deg, color-mix(in srgb, var(--brand) 9%, var(--surface)), var(--surface) 58%);
  border-color: color-mix(in srgb, var(--brand) 20%, var(--line));
}
.instance-main { display: flex; align-items: center; gap: 14px; min-width: 0; flex: 1 1 320px; }
.instance-icon {
  width: 54px; height: 54px; flex: 0 0 54px; border-radius: 16px; display: grid; place-items: center;
  color: var(--brand); border: 1px solid color-mix(in srgb, var(--brand) 24%, var(--line));
  background: linear-gradient(140deg, color-mix(in srgb, var(--brand) 17%, var(--surface)), color-mix(in srgb, var(--brand-2) 8%, var(--surface)));
  box-shadow: 0 10px 24px color-mix(in srgb, var(--brand) 14%, transparent);
}
.instance-copy { min-width: 0; }
.instance-copy h2 { margin: 0; font-size: 20px; letter-spacing: -.025em; }
.instance-copy > span { display: block; margin-top: 3px; word-break: break-all; }
.instance-settings { display: flex; align-items: flex-end; gap: 10px; flex-wrap: wrap; min-width: 0; }
.instance-settings .field-wrap { width: 220px; min-width: 0; }
.instance-settings .field-wrap:first-child { width: 170px; }
.remote-hint { display: flex; align-items: flex-start; gap: 7px; margin: -2px 0 16px; color: var(--warn); font-size: 11.5px; }
.remote-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-bottom: 14px; }
.remote-card { padding: 18px; border-radius: 18px; min-width: 0; }
.remote-card-head { display: flex; align-items: flex-start; gap: 11px; margin-bottom: 15px; }
.remote-card-head > div { flex: 1; min-width: 0; }
.remote-card-head h2 { margin: 0 0 3px; font-size: 16px; letter-spacing: -.02em; }
.remote-card-head p { margin: 0; color: var(--muted); font-size: 11.5px; line-height: 1.55; }
.remote-card-icon { width: 40px; height: 40px; flex: 0 0 40px; border-radius: 12px; display: grid; place-items: center; border: 1px solid var(--line); }
.remote-card-icon.key { color: var(--brand); background: var(--brand-soft); border-color: var(--brand-line); }
.remote-card-icon.accept { color: var(--good); background: var(--good-soft); border-color: color-mix(in srgb, var(--good) 24%, var(--line)); }
.remote-card-icon.manage { color: var(--warn); background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 24%, var(--line)); }
.key-create { display: flex; gap: 8px; margin-bottom: 12px; }
.key-create .field { flex: 1; min-width: 0; }
.key-list, .request-list, .system-list { display: flex; flex-direction: column; gap: 9px; }
.key-item, .request-item, .system-item {
  padding: 12px 13px; border-radius: 13px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 45%, var(--surface));
  min-width: 0;
}
.key-top, .request-top, .system-item { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.key-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.key-actions, .request-actions, .system-actions { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.key-code { margin-top: 10px; display: flex; flex-direction: column; gap: 5px; }
.key-code textarea { width: 100%; resize: vertical; font-size: 10.5px; line-height: 1.5; }
.request-copy, .system-copy { min-width: 0; display: flex; flex-direction: column; gap: 3px; flex: 1; }
.request-copy > span, .system-copy > span { word-break: break-all; }
.request-actions { margin-top: 10px; justify-content: flex-start; padding-top: 10px; border-top: 1px dashed var(--line); }
.system-item { align-items: center; }
.system-avatar {
  width: 42px; height: 42px; flex: 0 0 42px; border-radius: 13px; display: grid; place-items: center;
  color: var(--brand); background: var(--brand-soft); border: 1px solid var(--brand-line);
}
.system-avatar.sm { width: 34px; height: 34px; flex: 0 0 34px; border-radius: 10px; }
.system-error { display: inline-flex; align-items: center; gap: 5px; color: var(--bad); font-size: 11px; word-break: break-word; }
.outgoing-card { margin-bottom: 20px; }
.connect-form { display: grid; grid-template-columns: minmax(220px, 2fr) minmax(130px, 1fr) minmax(180px, 1.2fr) auto; gap: 9px; align-items: end; }
.connect-btn { height: 38px; }
.connect-hint { display: block; margin: 8px 0 14px; }
.field-wrap { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.field-wrap > span { font-size: 10.5px; color: var(--muted); letter-spacing: .02em; }
.field-wrap .field { width: 100%; min-width: 0; }
.empty-block {
  display: flex; flex-direction: column; align-items: center; gap: 5px;
  padding: 34px 18px; border: 1px dashed var(--line); border-radius: 14px;
  color: var(--faint); text-align: center;
}
.empty-block.wide { padding: 40px 18px; }
.empty-block b { color: var(--ink-2); font-size: 13px; }
.empty-block span { color: var(--muted); font-size: 11.5px; }

.remote-workspace { display: flex; flex-direction: column; flex: 1; min-height: 0; margin: -10px -4px 0; }
.remote-workspace.fullscreen {
  position: fixed; inset: 0; z-index: 95;
  margin: 0; padding: 0;
  background: var(--bg);
}
.ws-bar {
  display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap;
  padding: 10px 14px; margin-bottom: 10px;
  border: 1px solid var(--line); border-radius: 14px;
  background: color-mix(in srgb, var(--surface) 82%, transparent);
  backdrop-filter: blur(10px);
}
.fullscreen .ws-bar { border-radius: 0; border-left: none; border-right: none; border-top: none; margin-bottom: 0; }
.ws-identity { display: flex; align-items: center; gap: 10px; min-width: 0; flex: 1 1 260px; }
.ws-copy { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.ws-copy > span { word-break: break-all; }
.ws-actions { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; min-width: 0; }
.ws-body {
  position: relative; flex: 1; min-height: 480px;
  height: calc(100vh - 180px);
  border: 1px solid var(--line); border-radius: 16px; overflow: hidden;
  background: var(--surface-2);
}
.fullscreen .ws-body { height: calc(100vh - 61px); border-radius: 0; border: none; }
.remote-frame { width: 100%; height: 100%; border: none; display: block; background: #fff; }
.ws-placeholder {
  height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 9px;
  padding: 30px; text-align: center; color: var(--muted); font-size: 12px;
}
.ws-placeholder b { color: var(--ink); font-size: 16px; }
.placeholder-icon {
  width: 64px; height: 64px; border-radius: 18px; display: grid; place-items: center;
  background: var(--brand-soft); color: var(--brand); border: 1px solid var(--brand-line);
}
.placeholder-icon.warn { background: var(--warn-soft); color: var(--warn); border-color: color-mix(in srgb, var(--warn) 24%, var(--line)); }
.placeholder-icon.bad { background: var(--bad-soft); color: var(--bad); border-color: color-mix(in srgb, var(--bad) 24%, var(--line)); }
.frame-loading {
  position: absolute; inset: 0; z-index: 2;
  display: flex; align-items: center; justify-content: center; gap: 9px;
  background: color-mix(in srgb, var(--surface) 82%, transparent);
  color: var(--muted); font-size: 12px; backdrop-filter: blur(3px);
}

@media (max-width: 1100px) {
  .remote-grid { grid-template-columns: 1fr; }
  .connect-form { grid-template-columns: 1fr 1fr; }
  .connect-btn { grid-column: span 2; }
}
@media (max-width: 720px) {
  .remote-page { padding-top: 16px; }
  .instance-settings { width: 100%; }
  .instance-settings .field-wrap, .instance-settings .field-wrap:first-child { flex: 1; width: auto; min-width: 140px; }
  .instance-settings .btn { width: 100%; justify-content: center; }
  .key-create { flex-direction: column; }
  .key-top, .request-top, .system-item { flex-direction: column; align-items: stretch; }
  .key-actions, .system-actions { justify-content: flex-start; }
  .connect-form { grid-template-columns: 1fr; }
  .connect-btn { grid-column: auto; }
  .ws-body { height: calc(100vh - 250px); min-height: 320px; }
  .ws-bar { align-items: stretch; }
  .ws-actions { width: 100%; }
  .ws-actions .btn { flex: 1 1 calc(50% - 7px); justify-content: center; }
  .ws-actions .icon-btn { flex: 0 0 34px; }
  .instance-settings .field-wrap { flex: 1 1 100%; }
  .connect-form .field-wrap { min-width: 0; }
}
</style>
