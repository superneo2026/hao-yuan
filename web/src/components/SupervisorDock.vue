<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, supervisorChatStream } from '../api/client'
import { state, toast } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'
import Markdown from './Markdown.vue'

const CHAT_KEY = 'hy.supervisorChatId'
const MODEL_KEY = 'hy.supervisorModel'
const route = useRoute()
const router = useRouter()

const open = ref(false)
const expanded = ref(false)
const busy = ref(false)
const question = ref('')
const messages = ref([])
const chatId = ref(localStorage.getItem(CHAT_KEY) || '')
const view = ref('chat')
const chats = ref([])
const models = ref([])
const model = ref(localStorage.getItem(MODEL_KEY) || '')
const snapshot = ref(null)
const scroller = ref(null)
const copied = ref(false)
const linkCopied = ref(false)
const historyLoading = ref(false)
let timer = null

const summary = computed(() => snapshot.value?.summary || {})
const alerts = computed(() => Number(summary.value.alerts || 0))
const chatShortId = computed(() => (chatId.value ? chatId.value.slice(0, 12) : '—'))
const currentModelLabel = computed(() => models.value.find((item) => item.value === model.value)?.label || model.value || '—')

function nowStamp() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

async function loadSnapshot() {
  try {
    snapshot.value = await api.supervisorOverview()
  } catch {
    /* dock stays usable if the overview call fails */
  }
}

async function loadModels() {
  try {
    const data = await api.models()
    const flat = []
    for (const provider of data?.providers || []) {
      const options = provider.models?.length ? provider.models : [provider.default_model]
      for (const name of options || []) {
        if (!name) continue
        flat.push({ value: name, label: `${provider.provider} · ${name}`, provider: provider.provider })
      }
    }
    models.value = flat
    if (!model.value && flat.length) selectModel(flat.find((item) => item.value === 'glm-5.3-flash')?.value || flat[0].value)
  } catch {
    /* ignore model list failures, the server keeps its default */
  }
}

function selectModel(value) {
  model.value = value || ''
  if (value) localStorage.setItem(MODEL_KEY, value)
}

async function loadMessages() {
  if (!chatId.value) return
  try {
    const rows = await api.supervisorMessages(chatId.value)
    messages.value = (rows || []).map((row) => ({
      role: row.role,
      content: row.content || '',
      actions: row.actions || [],
      model: row.model || '',
      provider: row.provider || '',
      usage: row.usage || {},
      created_at: row.created_at || ''
    }))
  } catch {
    /* ignore history load failures */
  }
}

async function loadChats() {
  historyLoading.value = true
  try {
    chats.value = await api.supervisorChats()
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    historyLoading.value = false
  }
}

function scrollDown() {
  nextTick(() => {
    const el = scroller.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function toggle() {
  open.value = !open.value
  if (open.value) {
    await Promise.all([loadSnapshot(), loadModels(), loadMessages()])
    scrollDown()
  }
}

function close() {
  open.value = false
  expanded.value = false
}

function toggleExpand() {
  expanded.value = !expanded.value
  if (expanded.value) scrollDown()
}

function resetChat() {
  if (busy.value) return
  chatId.value = ''
  localStorage.removeItem(CHAT_KEY)
  messages.value = []
  question.value = ''
  view.value = 'chat'
}

async function openHistory() {
  view.value = 'history'
  await loadChats()
}

async function selectChat(id) {
  if (busy.value) return
  chatId.value = id
  localStorage.setItem(CHAT_KEY, id)
  view.value = 'chat'
  await loadMessages()
  scrollDown()
}

async function removeChat(id) {
  if (!window.confirm(t('supervisor.deleteChat'))) return
  try {
    await api.supervisorDeleteChat(id)
    if (chatId.value === id) {
      chatId.value = ''
      localStorage.removeItem(CHAT_KEY)
      messages.value = []
    }
    await loadChats()
  } catch (error) {
    toast(error.message, 'bad')
  }
}

async function copyId() {
  if (!chatId.value) return
  try {
    await navigator.clipboard.writeText(chatId.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1600)
  } catch {
    toast(chatId.value, 'info', 6000)
  }
}

function buildShareLink() {
  const href = window.location.href
  const hashIndex = href.indexOf('#')
  const prefix = hashIndex >= 0 ? href.slice(0, hashIndex) : href
  const hash = hashIndex >= 0 ? href.slice(hashIndex + 1) : ''
  const queryIndex = hash.indexOf('?')
  const rawPath = queryIndex >= 0 ? hash.slice(0, queryIndex) : hash
  const queryText = queryIndex >= 0 ? hash.slice(queryIndex + 1) : ''
  const params = new URLSearchParams(queryText)
  params.set('sup_chat', chatId.value)
  params.set('sup_open', '1')
  if (model.value) params.set('sup_model', model.value)
  if (expanded.value) params.set('sup_expand', '1')
  else params.delete('sup_expand')
  const path = rawPath.startsWith('/') ? rawPath : '/'
  return `${prefix}#${path}?${params.toString()}`
}

async function copyLink() {
  if (!chatId.value) {
    toast(t('supervisor.noChat'), 'info')
    return
  }
  const link = buildShareLink()
  try {
    await navigator.clipboard.writeText(link)
    linkCopied.value = true
    setTimeout(() => (linkCopied.value = false), 1600)
    toast(t('supervisor.linkCopied'), 'good', 2000)
  } catch {
    toast(link, 'info', 8000)
  }
  // Lock the current address bar to the shared view so a refresh reproduces it.
  const query = { ...route.query, sup_chat: chatId.value, sup_open: '1' }
  if (model.value) query.sup_model = model.value
  if (expanded.value) query.sup_expand = '1'
  else delete query.sup_expand
  router.replace({ path: route.path, query }).catch(() => {})
}

function applyShareParams() {
  const query = route.query
  const cid = typeof query.sup_chat === 'string' ? query.sup_chat : ''
  if (!cid) return
  const changed = cid !== chatId.value
  chatId.value = cid
  localStorage.setItem(CHAT_KEY, cid)
  if (typeof query.sup_model === 'string' && query.sup_model) selectModel(query.sup_model)
  expanded.value = query.sup_expand === '1'
  view.value = 'chat'
  open.value = true
  loadSnapshot()
  loadModels()
  if (changed || !messages.value.length) {
    loadMessages()
    scrollDown()
  }
}

function askHint(key) {
  question.value = (t(key) || '').replace(/[\u201c\u201d"]/g, '')
  send()
}

async function send() {
  const text = (question.value || '').trim()
  if (!text || busy.value) return
  view.value = 'chat'
  messages.value.push({ role: 'user', content: text, actions: [], created_at: nowStamp() })
  question.value = ''
  busy.value = true
  const index = messages.value.length
  messages.value.push({ role: 'assistant', content: '', actions: [], streaming: true, created_at: nowStamp() })
  scrollDown()

  let streamError = ''
  try {
    await supervisorChatStream({
      message: text,
      chatId: chatId.value,
      model: model.value,
      onEvent: (event, payload) => {
        if (event === 'meta') {
          if (payload.chat_id) {
            chatId.value = payload.chat_id
            localStorage.setItem(CHAT_KEY, payload.chat_id)
          }
        } else if (event === 'delta') {
          const current = messages.value[index]
          messages.value[index] = { ...current, content: (current.content || '') + (payload.text || '') }
          scrollDown()
        } else if (event === 'done') {
          if (payload.chat_id) {
            chatId.value = payload.chat_id
            localStorage.setItem(CHAT_KEY, payload.chat_id)
          }
          messages.value[index] = {
            role: 'assistant',
            content: payload.reply ?? messages.value[index].content,
            actions: payload.actions || [],
            model: payload.model || '',
            provider: payload.provider || '',
            usage: payload.usage || {},
            created_at: nowStamp(),
            streaming: false
          }
        } else if (event === 'error') {
          streamError = payload.message || 'stream failed'
        }
      }
    })
    if (streamError) {
      messages.value[index] = {
        role: 'assistant',
        content: `⚠️ ${streamError}`,
        actions: [],
        model: model.value,
        created_at: nowStamp(),
        streaming: false
      }
      toast(streamError, 'bad')
    }
    await loadSnapshot()
  } catch (error) {
    messages.value[index] = {
      role: 'assistant',
      content: `⚠️ ${error.message}`,
      actions: [],
      model: model.value,
      created_at: nowStamp(),
      streaming: false
    }
    toast(error.message, 'bad')
  } finally {
    busy.value = false
    scrollDown()
  }
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    send()
  }
}

function usageLabel(message) {
  const prompt = Number(message.usage?.prompt_tokens || 0)
  const completion = Number(message.usage?.completion_tokens || 0)
  if (!prompt && !completion) return ''
  return `${prompt + completion} tokens`
}

watch(messages, scrollDown, { deep: true })

watch(() => route.query.sup_chat, () => applyShareParams())

onMounted(() => {
  loadSnapshot()
  loadModels()
  applyShareParams()
  timer = setInterval(loadSnapshot, 30000)
})
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <div class="sup-dock" :class="{ open, expanded, collapsed: state.sidebarCollapsed }">
    <transition name="sup-pop">
      <section v-show="open" class="sup-panel" role="dialog" aria-label="AI Supervisor">
        <header class="sup-head">
          <span class="sup-avatar">S</span>
          <div class="sup-title">
            <b>{{ t('console.askSupervisor') }}</b>
            <span>{{ t('supervisor.summary', { active: summary.active || 0, alerts }) }}</span>
          </div>
          <span class="spacer" />
          <button class="icon-btn" :title="t('supervisor.history')" @click="view === 'history' ? (view = 'chat') : openHistory()">
            <Icon :name="view === 'history' ? 'message' : 'clock'" :size="14" />
          </button>
          <button
            class="icon-btn"
            :title="expanded ? t('supervisor.restore') : t('supervisor.maximize')"
            @click="toggleExpand"
          >
            <Icon :name="expanded ? 'minimize' : 'maximize'" :size="14" />
          </button>
          <button class="icon-btn" :title="t('supervisor.newChat')" @click="resetChat">
            <Icon name="plus" :size="14" />
          </button>
          <button class="icon-btn" :title="t('common.close')" @click="close">
            <Icon name="close" :size="14" />
          </button>
        </header>

        <div class="sup-meta">
          <button class="sup-id" :title="t('supervisor.copyId')" @click="copyId">
            <span class="sup-id-label">{{ t('supervisor.conversationId') }}</span>
            <code>{{ chatShortId }}</code>
            <Icon :name="copied ? 'check' : 'copy'" :size="12" />
          </button>
          <button class="icon-btn sup-link" :title="t('supervisor.copyLink')" @click="copyLink">
            <Icon :name="linkCopied ? 'check' : 'link'" :size="13" />
          </button>
          <span class="spacer" />
          <label class="sup-model" :title="t('supervisor.model')">
            <Icon name="cpu" :size="13" />
            <select :value="model" @change="selectModel($event.target.value)">
              <option v-for="item in models" :key="item.value" :value="item.value">{{ item.label }}</option>
            </select>
          </label>
        </div>

        <div v-if="view === 'history'" class="sup-body history">
          <div v-if="historyLoading" class="sup-empty">{{ t('supervisor.loading') }}</div>
          <div v-else-if="!chats.length" class="sup-empty">
            <Icon name="message" :size="18" />
            <p>{{ t('supervisor.noHistory') }}</p>
          </div>
          <div v-else class="history-list">
            <article
              v-for="chat in chats"
              :key="chat.id"
              class="history-item"
              :class="{ active: chat.id === chatId }"
              @click="selectChat(chat.id)"
            >
              <div class="history-main">
                <b class="truncate">{{ chat.title || chat.id.slice(0, 12) }}</b>
                <span class="history-sub">
                  {{ chat.model || t('supervisor.model') }} · {{ t('supervisor.messageCount', { n: chat.message_count || 0 }) }} ·
                  {{ (chat.updated_at || '').slice(5, 16) }}
                </span>
                <span class="history-sub truncate">{{ chat.last_message || '' }}</span>
              </div>
              <button class="icon-btn" :title="t('supervisor.delete')" @click.stop="removeChat(chat.id)">
                <Icon name="trash" :size="13" />
              </button>
            </article>
          </div>
        </div>

        <div v-else ref="scroller" class="sup-body">
          <div v-if="!messages.length" class="sup-hint">
            <Icon name="sparkles" :size="18" />
            <p>{{ t('supervisor.empty') }}</p>
            <button class="chip" @click="askHint('console.hint1')">{{ t('console.hint1') }}</button>
            <button class="chip" @click="askHint('console.hint3')">{{ t('console.hint3') }}</button>
          </div>
          <div v-for="(message, index) in messages" :key="index" class="sup-msg" :class="message.role">
            <span v-if="message.role === 'assistant'" class="msg-avatar">S</span>
            <div class="msg-main">
              <div class="bubble">
                <template v-if="message.role === 'assistant'">
                  <div v-if="message.streaming && !message.content" class="sup-typing">
                    <span class="spinner" style="width: 12px; height: 12px" /> {{ t('supervisor.thinking') }}
                  </div>
                  <Markdown v-else :content="message.content" />
                  <span v-if="message.streaming && message.content" class="caret" />
                </template>
                <template v-else>{{ message.content }}</template>
              </div>
              <div v-if="message.actions?.length" class="sup-actions">
                <span v-for="(action, actionIndex) in message.actions" :key="actionIndex" class="sup-action">
                  {{ action.action }} · {{ action.message }}
                </span>
              </div>
              <div v-if="message.role === 'assistant' && !message.streaming" class="msg-foot">
                <span v-if="message.model">{{ message.model }}</span>
                <span v-if="usageLabel(message)">{{ usageLabel(message) }}</span>
                <span v-if="message.created_at">{{ message.created_at.slice(11, 16) }}</span>
              </div>
            </div>
          </div>
        </div>

        <footer class="sup-input">
          <textarea
            v-model="question"
            class="textarea"
            rows="2"
            :placeholder="t('console.askPlaceholder')"
            @keydown="onKeydown"
          />
          <button class="btn primary sm" :disabled="busy || !question.trim()" @click="send">
            <Icon name="send" :size="13" />
          </button>
        </footer>
        <div class="sup-tip">{{ t('supervisor.sendHint') }}</div>
      </section>
    </transition>

    <button class="sup-fab" :class="{ active: open }" :title="t('console.askSupervisor')" @click="toggle">
      <Icon :name="open ? 'close' : 'brain'" :size="20" />
      <span v-if="alerts && !open" class="sup-badge">{{ alerts > 99 ? '99+' : alerts }}</span>
    </button>
  </div>
</template>

<style scoped>
.sup-dock { position: fixed; right: 22px; bottom: 22px; z-index: 60; }
.sup-fab {
  position: relative;
  width: 52px;
  height: 52px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  background: linear-gradient(140deg, var(--brand), var(--brand-2));
  border: 1px solid color-mix(in srgb, var(--brand) 40%, transparent);
  box-shadow: 0 16px 36px color-mix(in srgb, var(--brand) 42%, transparent);
  cursor: pointer;
  transition: transform .18s var(--ease), box-shadow .18s var(--ease);
}
.sup-fab:hover { transform: translateY(-2px) scale(1.04); }
.sup-badge {
  position: absolute;
  top: -3px;
  right: -3px;
  min-width: 19px;
  height: 19px;
  padding: 0 5px;
  border-radius: 10px;
  background: var(--bad);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  display: grid;
  place-items: center;
  box-shadow: 0 0 0 2px var(--bg);
}
.sup-panel {
  position: absolute;
  right: 0;
  bottom: 66px;
  width: min(420px, calc(100vw - 32px));
  height: min(600px, calc(100vh - 130px));
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--surface) 97%, transparent);
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: 0 26px 70px rgba(0, 0, 0, .42);
  overflow: hidden;
  backdrop-filter: blur(14px);
}
.sup-dock.expanded { z-index: 79; }
.sup-dock.expanded .sup-fab { display: none; }
.sup-dock.expanded .sup-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  left: var(--sidebar-w);
  width: auto;
  height: auto;
  max-height: none;
  border-radius: 0;
  border-top: none;
  border-right: none;
  border-bottom: none;
}
.sup-dock.expanded.collapsed .sup-panel { left: 76px; }
.sup-head {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 12px 12px 10px 14px;
  background: color-mix(in srgb, var(--surface-2) 60%, transparent);
}
.sup-avatar {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(140deg, var(--brand), var(--brand-2));
  flex: 0 0 30px;
}
.sup-title { display: flex; flex-direction: column; min-width: 0; }
.sup-title b { font-size: 13px; letter-spacing: -.01em; }
.sup-title span { font-size: 10.5px; color: var(--muted); }
.sup-head .icon-btn { width: 27px; height: 27px; }
.sup-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 35%, transparent);
}
.sup-id {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--muted);
  font-size: 10.5px;
  cursor: pointer;
}
.sup-id:hover { border-color: var(--brand-line); color: var(--brand); }
.sup-id-label { font-size: 9.5px; letter-spacing: .04em; text-transform: uppercase; color: var(--faint); }
.sup-id code { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-2); }
.sup-link { width: 24px; height: 24px; flex: 0 0 24px; }
.sup-model {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  color: var(--muted);
}
.sup-model select {
  max-width: 170px;
  height: 24px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 10.5px;
  padding: 0 4px;
}
.sup-body { flex: 1; min-height: 0; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.sup-body.history { gap: 8px; }
.sup-hint { margin: auto; display: flex; flex-direction: column; align-items: center; gap: 8px; text-align: center; color: var(--muted); padding: 20px; }
.sup-hint p { font-size: 12px; max-width: 280px; line-height: 1.6; }
.sup-empty { margin: auto; display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; padding: 30px; }
.chip { padding: 6px 10px; border-radius: 9px; border: 1px solid var(--line); background: var(--surface-2); color: var(--ink-2); font-size: 11.5px; cursor: pointer; }
.chip:hover { border-color: var(--brand-line); color: var(--brand); }
.sup-msg { display: flex; gap: 8px; max-width: 100%; }
.sup-msg.user { justify-content: flex-end; }
.msg-avatar {
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 800;
  color: #fff;
  background: linear-gradient(140deg, var(--brand), var(--brand-2));
  margin-top: 2px;
}
.msg-main { display: flex; flex-direction: column; gap: 4px; min-width: 0; max-width: 88%; }
.sup-msg.user .msg-main { align-items: flex-end; }
.sup-msg .bubble {
  padding: 9px 12px;
  border-radius: 13px;
  font-size: 12.5px;
  line-height: 1.58;
  word-break: break-word;
}
.sup-msg.user .bubble {
  white-space: pre-wrap;
  background: var(--brand-soft);
  border: 1px solid var(--brand-line);
  color: var(--ink);
  border-bottom-right-radius: 5px;
}
.sup-msg.assistant .bubble {
  white-space: normal;
  background: var(--surface-2);
  border: 1px solid var(--line);
  color: var(--ink);
  border-bottom-left-radius: 5px;
}
.sup-msg.assistant .bubble :deep(.markdown) { font-size: 12.5px; line-height: 1.58; color: inherit; }
.sup-msg.assistant .bubble :deep(.markdown > :first-child) { margin-top: 0; }
.sup-msg.assistant .bubble :deep(.markdown > :last-child) { margin-bottom: 0; }
.sup-msg.assistant .bubble :deep(p) { margin: 0 0 6px; }
.sup-msg.assistant .bubble :deep(p:last-child) { margin-bottom: 0; }
.sup-msg.assistant .bubble :deep(ul),
.sup-msg.assistant .bubble :deep(ol) { margin: 4px 0 6px; padding-left: 1.15em; }
.sup-msg.assistant .bubble :deep(li) { margin: 1.5px 0; }
.sup-msg.assistant .bubble :deep(li > p) { margin: 0; }
.sup-msg.assistant .bubble :deep(h1),
.sup-msg.assistant .bubble :deep(h2),
.sup-msg.assistant .bubble :deep(h3),
.sup-msg.assistant .bubble :deep(h4) { margin: 9px 0 4px; font-size: 1em; line-height: 1.35; letter-spacing: 0; }
.sup-msg.assistant .bubble :deep(h1) { font-size: 1.08em; }
.sup-msg.assistant .bubble :deep(h2) { font-size: 1.04em; }
.sup-msg.assistant .bubble :deep(code) {
  font-family: var(--font-mono);
  font-size: .9em;
  background: color-mix(in srgb, var(--brand) 10%, var(--surface-3));
  padding: .08em .34em;
  border-radius: 4px;
}
.sup-msg.assistant .bubble :deep(pre) { margin: 7px 0; padding: 9px 11px; border-radius: 9px; font-size: 11px; line-height: 1.5; }
.sup-msg.assistant .bubble :deep(pre code) { background: transparent; padding: 0; font-size: inherit; }
.sup-msg.assistant .bubble :deep(blockquote) { margin: 6px 0; padding: .1em 0 .1em .7em; border-left: 2px solid var(--brand-line); color: var(--muted); }
.sup-msg.assistant .bubble :deep(a) { color: var(--brand); text-decoration: underline; text-underline-offset: 2px; }
.sup-msg.assistant .bubble :deep(hr) { margin: 10px 0; border: none; border-top: 1px solid var(--line); }
.sup-msg.assistant .bubble :deep(table) { width: 100%; border-collapse: collapse; margin: 7px 0; font-size: 11px; }
.sup-msg.assistant .bubble :deep(th),
.sup-msg.assistant .bubble :deep(td) { border: 1px solid var(--line); padding: 4px 6px; text-align: left; }
.sup-msg.assistant .bubble :deep(th) { background: var(--surface-3); font-weight: 600; }
.sup-msg.assistant .bubble :deep(img) { max-width: 100%; border-radius: 8px; }
.msg-foot { display: flex; gap: 8px; font-size: 9.5px; color: var(--faint); padding: 0 3px; }
.caret { display: inline-block; width: 2px; height: 13px; margin-left: 2px; vertical-align: -2px; background: var(--brand); animation: sup-blink 1s steps(2) infinite; }
@keyframes sup-blink { 50% { opacity: 0; } }
.sup-typing { display: flex; align-items: center; gap: 7px; color: var(--muted); }
.sup-actions { display: flex; flex-wrap: wrap; gap: 5px; }
.sup-action { font-size: 10.5px; padding: 3px 8px; border-radius: 8px; background: var(--surface-2); border: 1px solid var(--line); color: var(--muted); }
.history-list { display: flex; flex-direction: column; gap: 6px; }
.history-item { display: flex; align-items: center; gap: 8px; padding: 10px 11px; border-radius: 11px; border: 1px solid var(--line); background: var(--surface); cursor: pointer; transition: border-color .15s var(--ease), background .15s var(--ease); }
.history-item:hover { border-color: var(--brand-line); }
.history-item.active { border-color: var(--brand-line); background: var(--brand-soft); }
.history-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.history-main b { font-size: 12.5px; }
.history-sub { font-size: 10px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sup-input { display: flex; gap: 8px; align-items: flex-end; padding: 10px 12px 6px; border-top: 1px solid var(--line); }
.sup-input .textarea { flex: 1; resize: none; font-size: 12.5px; }
.sup-input .btn { height: 34px; width: 38px; padding: 0; flex: 0 0 38px; }
.sup-tip { padding: 0 12px 9px; font-size: 9.5px; color: var(--faint); text-align: right; }
.sup-pop-enter-active, .sup-pop-leave-active { transition: opacity .16s var(--ease), transform .16s var(--ease); }
.sup-pop-enter-from, .sup-pop-leave-to { opacity: 0; transform: translateY(10px) scale(.98); }
@media (max-width: 860px) {
  .sup-dock.expanded .sup-panel { left: 76px; }
}
@media (max-width: 640px) {
  .sup-dock { right: 14px; bottom: 14px; }
  .sup-panel { width: calc(100vw - 28px); height: min(72vh, calc(100vh - 110px)); }
  .sup-dock.expanded .sup-panel { left: 0; width: 100vw; height: 100vh; border: none; }
}
</style>
