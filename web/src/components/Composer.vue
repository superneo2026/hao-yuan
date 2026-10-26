<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { currentSession, isActive, patchSession, resumeSession, sendMessage, state, stopSession, tokenCount } from '../stores/app'
import { skillTitle, t } from '../i18n'
import DirPicker from './DirPicker.vue'
import Icon from './Icon.vue'

const text = ref('')
const textarea = ref(null)
const showDir = ref(false)

const draftKey = computed(() => `hy.draft.${state.currentId || 'new'}`)
const models = computed(() => {
  const out = []
  for (const provider of state.models) {
    for (const model of provider.models || []) out.push({ provider: provider.provider, model, label: model })
  }
  return out
})
const modelValue = computed(() => {
  const session = currentSession.value || {}
  const exists = models.value.some((option) => option.provider === session.provider && option.model === session.model)
  return exists ? `${session.provider}|${session.model}` : ''
})
const status = computed(() => currentSession.value?.status || 'idle')

watch(
  () => state.currentId,
  () => {
    text.value = localStorage.getItem(draftKey.value) || ''
    resize()
  },
  { immediate: true }
)

watch(text, (value) => {
  localStorage.setItem(draftKey.value, value)
})

function resize() {
  nextTick(() => {
    const el = textarea.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  })
}

function onInput() {
  resize()
}

async function send() {
  const content = text.value.trim()
  if (!content) return
  text.value = ''
  localStorage.removeItem(draftKey.value)
  resize()
  await sendMessage(content)
}

function onKeydown(event) {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key !== 'Enter') return
  if (event.shiftKey) return
  event.preventDefault()
  send()
}

function onModelChange(event) {
  const value = event.target.value
  if (!value) {
    patchSession({ provider: '', model: '' })
    return
  }
  const [provider, model] = value.split('|')
  patchSession({ provider, model })
}

function onThinkingChange(event) {
  patchSession({ thinking: event.target.value })
}

function onGateChange(event) {
  patchSession({ gate_mode: event.target.value })
}

async function chooseDir(path) {
  await patchSession({ workspace: path })
}

function fill(value) {
  text.value = value
  resize()
  textarea.value?.focus()
}

defineExpose({ fill })
</script>

<template>
  <div class="composer-wrap">
    <div class="composer">
      <div v-if="isActive || status === 'error'" class="composer-status">
        <span v-if="isActive" class="row small muted">
          <span class="spinner" style="width: 12px; height: 12px" />
          {{ status === 'waiting_input' ? t('chat.waitingApproval') : status === 'queued' ? t('chat.queued') : t('chat.agentWorking') }}
          <span v-if="state.live.route" class="badge brand">
            {{ state.live.route.model || currentSession?.model }}
          </span>
          <span v-if="state.live.route?.lite" class="badge">{{ t('session.lite') }}</span>
          <span class="spacer" />
          <button class="btn sm danger" @click="stopSession"><Icon name="square" :size="12" /> {{ t('common.stop') }}</button>
        </span>
        <span v-else class="row small muted">
          <span class="status-dot error" /> {{ t('chat.lastFailed') }}
          <span class="spacer" />
          <button class="btn sm" @click="resumeSession"><Icon name="refresh" :size="12" /> {{ t('common.resume') }}</button>
        </span>
      </div>

      <div class="composer-box">
        <textarea
          ref="textarea"
          v-model="text"
          class="composer-input"
          rows="1"
          :placeholder="t('chat.placeholder')"
          @input="onInput"
          @keydown="onKeydown"
        />
        <div class="composer-toolbar">
          <div class="row" style="gap: 6px; min-width: 0">
            <button class="tool-pill" :title="currentSession?.workspace || t('chat.noWorkspace')" @click="showDir = true">
              <Icon name="folder" :size="13" />
              <span class="truncate" style="max-width: 190px">
                {{ currentSession?.workspace ? currentSession.workspace.split(/[\\/]/).pop() : t('chat.noWorkspace') }}
              </span>
              <Icon name="chevron-down" :size="11" />
            </button>
            <select class="mini-select" :value="modelValue" :title="t('session.model')" @change="onModelChange">
              <option value="">{{ t('chat.autoModel') }}</option>
              <option v-for="option in models" :key="`${option.provider}|${option.model}`" :value="`${option.provider}|${option.model}`">
                {{ option.label }}
              </option>
            </select>
            <select class="mini-select" :value="currentSession?.thinking || ''" :title="t('session.effort')" @change="onThinkingChange">
              <option value="">{{ t('chat.autoEffort') }}</option>
              <option value="off">{{ t('chat.noThinking') }}</option>
              <option value="low">{{ t('chat.low') }}</option>
              <option value="high">{{ t('chat.high') }}</option>
            </select>
            <select class="mini-select" :value="currentSession?.gate_mode || ''" :title="t('settings.gate')" @change="onGateChange">
              <option value="">{{ t('chat.globalGate') }}</option>
              <option value="ask">{{ t('chat.ask') }}</option>
              <option value="allow_all">{{ t('chat.allowAll') }}</option>
            </select>
          </div>
          <div class="row" style="gap: 8px">
            <span class="tiny faint token-count" :title="t('session.context')">{{ t('chat.ctx', { n: (tokenCount / 1000).toFixed(1) }) }}</span>
            <span class="kbd-hint" :title="t('chat.sendHint')">↵</span>
            <button class="send-btn" :disabled="!text.trim() || state.busy.sending" :title="t('common.send')" @click="send">
              <span v-if="state.busy.sending" class="spinner" style="width: 14px; height: 14px" />
              <Icon v-else name="send" :size="16" />
            </button>
          </div>
        </div>
      </div>
      <div class="composer-foot">
        <span>{{ t('chat.disclaimer') }}</span>
        <span v-if="state.live.skills.length" class="row" style="gap: 5px">
          <Icon name="sparkles" :size="11" style="color: var(--brand)" />
          {{ state.live.skills.map((skill) => skillTitle(skill)).join(' · ') }}
        </span>
      </div>
    </div>
  </div>
  <DirPicker v-if="showDir" :initial="currentSession?.workspace || ''" @close="showDir = false" @select="chooseDir" />
</template>

<style scoped>
.composer-wrap { padding: 0 24px 16px; }
.composer { max-width: 900px; margin: 0 auto; }
.composer-status { padding: 0 4px 7px; }
.composer-box { border: 1px solid var(--line-strong); background: var(--surface); border-radius: 16px; box-shadow: var(--shadow-card); overflow: hidden; transition: border-color .16s var(--ease), box-shadow .16s var(--ease); }
.composer-box:focus-within { border-color: var(--brand-line); box-shadow: 0 0 0 4px var(--brand-soft), var(--shadow-card); }
.composer-input { width: 100%; border: none; background: transparent; outline: none; resize: none; padding: 14px 15px 8px; min-height: 44px; max-height: 220px; color: var(--ink); font-size: 14px; line-height: 1.55; }
.composer-input::placeholder { color: var(--faint); }
.composer-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 7px 9px 9px; }
.tool-pill, .mini-select { display: inline-flex; align-items: center; gap: 5px; height: 27px; padding: 0 9px; border-radius: 8px; border: 1px solid var(--line); background: var(--surface-2); color: var(--muted); font-size: 11.5px; }
.tool-pill:hover, .mini-select:hover { color: var(--ink); border-color: var(--line-strong); }
.mini-select { appearance: none; padding-right: 9px; max-width: 130px; }
.send-btn { width: 34px; height: 34px; border-radius: 10px; border: none; background: linear-gradient(135deg, var(--brand), color-mix(in srgb, var(--brand) 55%, var(--brand-2))); color: #fff; display: grid; place-items: center; box-shadow: 0 8px 20px rgba(124, 108, 255, .28); }
.send-btn:disabled { opacity: .4; box-shadow: none; cursor: not-allowed; }
.kbd-hint { font-family: var(--font-mono); font-size: 10px; color: var(--faint); border: 1px solid var(--line); border-radius: 4px; padding: 1px 4px; }
.composer-foot { display: flex; justify-content: space-between; gap: 10px; padding: 7px 4px 0; color: var(--faint); font-size: 10.5px; }
.token-count { font-family: var(--font-mono); }
@media (max-width: 720px) {
  .composer-wrap { padding: 0 12px 12px; }
  .composer-foot { display: none; }
  .mini-select { display: none; }
}
</style>
