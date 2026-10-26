<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { currentSession, state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'
import Markdown from './Markdown.vue'
import ToolCard from './ToolCard.vue'

const emit = defineEmits(['suggest'])

const scroller = ref(null)
const autoScroll = ref(true)
const showReasoning = ref({})

function parseJson(text, fallback) {
  try {
    const value = JSON.parse(text || '')
    return value ?? fallback
  } catch {
    return fallback
  }
}

function parseToolResult(content) {
  const parsed = parseJson(content, null)
  if (parsed && typeof parsed === 'object' && 'ok' in parsed) {
    return {
      ok: parsed.ok,
      result: parsed.result,
      error: parsed.error,
      status: parsed.ok ? 'done' : 'error',
      summary: typeof parsed.result === 'string' ? parsed.result.slice(0, 180) : ''
    }
  }
  return { status: 'done', result: content, error: '' }
}

const groups = computed(() => {
  const out = []
  const callIndex = new Map()
  for (const message of state.messages) {
    if (message.role === 'user') {
      out.push({ kind: 'user', id: message.id, content: message.content, created_at: message.created_at })
      continue
    }
    if (message.role === 'assistant') {
      const rawCalls = parseJson(message.tool_args, [])
      const tools = (Array.isArray(rawCalls) ? rawCalls : []).map((call) => {
        let args = {}
        try { args = JSON.parse(call.function?.arguments || '{}') } catch { args = {} }
        const item = {
          call_id: call.id,
          tool: call.function?.name,
          args,
          status: 'done'
        }
        callIndex.set(call.id, item)
        return item
      })
      out.push({
        kind: 'assistant',
        id: message.id,
        content: message.content,
        reasoning: message.reasoning,
        tools,
        created_at: message.created_at
      })
      continue
    }
    if (message.role === 'tool') {
      const item = callIndex.get(message.tool_call_id)
      const parsed = parseToolResult(message.content)
      if (item) {
        Object.assign(item, parsed, { tool: item.tool || message.tool_name, args: item.args || parseJson(message.tool_args, {}) })
      } else {
        out.push({
          kind: 'tool',
          id: message.id,
          tools: [{ call_id: message.tool_call_id || message.id, tool: message.tool_name, args: parseJson(message.tool_args, {}), ...parsed }]
        })
      }
    }
  }
  return out
})

const liveText = computed(() => Object.values(state.live.streams).join(''))
const liveReasoning = computed(() => Object.values(state.live.reasoning).join(''))
const liveTools = computed(() => state.live.toolOrder.map((id) => state.live.tools[id]).filter(Boolean))

const isBusy = computed(() => ['running', 'queued', 'waiting_input'].includes(currentSession.value?.status))
const showEmpty = computed(() => !state.messages.length && !liveText.value && liveTools.value.length === 0)

function atBottom() {
  const el = scroller.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 140
}

function onScroll() {
  autoScroll.value = atBottom()
}

function scrollBottom(smooth = true) {
  nextTick(() => {
    const el = scroller.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  })
}

watch(
  () => state.scrollTick,
  () => {
    if (autoScroll.value) scrollBottom(false)
  }
)

watch(
  () => state.currentId,
  () => {
    autoScroll.value = true
    scrollBottom(false)
  }
)

onMounted(() => scrollBottom(false))

function copy(text) {
  navigator.clipboard?.writeText(text || '')
}

function timeLabel(value) {
  if (!value) return ''
  const date = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

const suggestions = computed(() => [
  { icon: 'compass', text: t('chat.suggestion1') },
  { icon: 'alert', text: t('chat.suggestion2') },
  { icon: 'sparkles', text: t('chat.suggestion3') },
  { icon: 'code', text: t('chat.suggestion4') }
])
</script>

<template>
  <div class="timeline-wrap">
    <div ref="scroller" class="timeline scroll-y" @scroll="onScroll">
      <div v-if="showEmpty" class="empty-state">
        <div class="empty-inner">
          <div class="welcome-mark">
            <span class="brand-mark" style="width: 54px; height: 54px; border-radius: 17px; font-size: 23px">H</span>
          </div>
          <h2>{{ t('chat.whatBuild') }}</h2>
          <p>
            {{ t('chat.welcomeDesc') }}
            <span class="mono" style="color: var(--ink-2)">{{ currentSession?.workspace || t('chat.noWorkspace') }}</span>
          </p>
          <div class="suggestions">
            <button v-for="suggestion in suggestions" :key="suggestion.text" class="suggestion" @click="emit('suggest', suggestion.text)">
              <span class="suggestion-icon"><Icon :name="suggestion.icon" :size="15" /></span>
              <span>{{ suggestion.text }}</span>
              <Icon name="arrow-right" :size="14" class="suggestion-arrow" />
            </button>
          </div>
        </div>
      </div>

      <div v-else class="timeline-inner">
        <div v-for="group in groups" :key="group.id" class="timeline-group slide-up">
          <template v-if="group.kind === 'user'">
            <div class="message user">
              <div class="avatar user-avatar">{{ t('chat.you') }}</div>
              <div class="bubble-wrap">
                <div class="bubble user-bubble">{{ group.content }}</div>
                <div class="message-meta">
                  <span>{{ timeLabel(group.created_at) }}</span>
                  <button class="icon-btn" style="width: 20px; height: 20px" @click="copy(group.content)">
                    <Icon name="copy" :size="11" />
                  </button>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="group.kind === 'assistant'">
            <div class="message assistant">
              <div class="avatar assistant-avatar">H</div>
              <div class="assistant-body">
                <details v-if="group.reasoning" class="reasoning">
                  <summary @click.stop="showReasoning[group.id] = !showReasoning[group.id]">
                    <Icon name="brain" :size="13" /> {{ t('chat.reasoning') }}
                    <Icon :name="showReasoning[group.id] ? 'chevron-down' : 'chevron-right'" :size="12" />
                  </summary>
                  <div class="reasoning-body">{{ group.reasoning }}</div>
                </details>
                <Markdown v-if="group.content" :content="group.content" />
                <div v-if="group.content" class="message-meta">
                  <span>{{ timeLabel(group.created_at) }}</span>
                  <button class="icon-btn" style="width: 20px; height: 20px" @click="copy(group.content)">
                    <Icon name="copy" :size="11" />
                  </button>
                </div>
                <div v-if="group.tools.length" class="tool-stack">
                  <ToolCard v-for="tool in group.tools" :key="tool.call_id" :item="tool" />
                </div>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="tool-only">
              <ToolCard v-for="tool in group.tools" :key="tool.call_id" :item="tool" />
            </div>
          </template>
        </div>

        <div v-if="liveTools.length || liveText || liveReasoning" class="message assistant live">
          <div class="avatar assistant-avatar live-avatar">H</div>
          <div class="assistant-body">
            <div class="thinking-line" v-if="isBusy && !liveText">
              <span class="spinner" />
              <span>{{ currentSession?.status === 'waiting_input' ? t('chat.waitingForApproval') : t('chat.working') }}</span>
            </div>
            <details v-if="liveReasoning" class="reasoning" open>
              <summary><Icon name="brain" :size="13" /> {{ t('chat.reasoning') }} <span class="spinner" v-if="isBusy" style="width: 10px; height: 10px" /></summary>
              <div class="reasoning-body">{{ liveReasoning }}</div>
            </details>
            <Markdown v-if="liveText" :content="liveText" />
            <div v-if="liveTools.length" class="tool-stack">
              <ToolCard v-for="tool in liveTools" :key="tool.call_id" :item="tool" />
            </div>
          </div>
        </div>
        <div style="height: 12px" />
      </div>
    </div>

    <button v-if="!autoScroll && !showEmpty" class="jump-bottom" @click="scrollBottom()">
      <Icon name="chevron-down" :size="14" /> {{ t('chat.latest') }}
    </button>
  </div>
</template>

<style scoped>
.timeline-wrap { position: relative; min-height: 0; flex: 1; display: flex; flex-direction: column; }
.timeline { flex: 1; padding: 26px 28px 12px; }
.timeline-inner { max-width: 880px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
.timeline-group { display: flex; flex-direction: column; gap: 8px; }
.message { display: flex; gap: 11px; align-items: flex-start; }
.message.user { flex-direction: row; }
.avatar { width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center; font-size: 10px; font-weight: 700; flex: 0 0 28px; margin-top: 1px; }
.user-avatar { background: var(--surface-3); color: var(--muted); border: 1px solid var(--line); font-size: 9px; letter-spacing: .02em; }
.assistant-avatar { background: linear-gradient(140deg, var(--brand), var(--brand-2)); color: #fff; box-shadow: 0 6px 18px rgba(124, 108, 255, .28); }
.live-avatar { animation: pulse 2s infinite; }
.bubble-wrap { display: flex; flex-direction: column; gap: 4px; max-width: min(720px, 100%); }
.bubble { padding: 10px 14px; border-radius: 4px 14px 14px 14px; background: var(--user-bubble); border: 1px solid var(--brand-line); color: var(--ink); white-space: pre-wrap; word-break: break-word; font-size: 13.5px; }
.assistant-body { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 8px; padding-top: 2px; }
.message-meta { display: flex; align-items: center; gap: 6px; color: var(--faint); font-size: 10.5px; opacity: .8; }
.reasoning { border: 1px solid var(--line); border-radius: 10px; background: var(--surface-2); overflow: hidden; }
.reasoning summary { display: flex; align-items: center; gap: 6px; padding: 7px 10px; color: var(--muted); font-size: 11.5px; cursor: pointer; list-style: none; }
.reasoning summary::-webkit-details-marker { display: none; }
.reasoning-body { padding: 0 12px 10px; color: var(--muted); font-size: 12px; line-height: 1.65; white-space: pre-wrap; max-height: 280px; overflow-y: auto; }
.tool-stack { display: flex; flex-direction: column; gap: 6px; margin-top: 2px; }
.tool-only { padding-left: 39px; display: flex; flex-direction: column; gap: 6px; }
.thinking-line { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12.5px; padding: 4px 0; }
.welcome-mark { display: flex; justify-content: center; margin-bottom: 18px; }
.suggestions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; text-align: left; margin-top: 8px; }
.suggestion { display: flex; align-items: center; gap: 9px; padding: 11px 12px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-2); font-size: 12.5px; transition: all .15s var(--ease); }
.suggestion:hover { border-color: var(--brand-line); background: var(--brand-soft); color: var(--ink); transform: translateY(-1px); }
.suggestion-icon { width: 26px; height: 26px; border-radius: 8px; display: grid; place-items: center; background: var(--surface-2); color: var(--brand); flex: 0 0 26px; }
.suggestion-arrow { margin-left: auto; opacity: 0; color: var(--brand); }
.suggestion:hover .suggestion-arrow { opacity: 1; }
.jump-bottom { position: absolute; left: 50%; bottom: 16px; transform: translateX(-50%); display: inline-flex; align-items: center; gap: 5px; padding: 6px 11px; border-radius: 99px; border: 1px solid var(--line-strong); background: var(--elevated); color: var(--ink-2); font-size: 11.5px; box-shadow: var(--shadow-card); }
.jump-bottom:hover { color: var(--ink); border-color: var(--brand-line); }
@media (max-width: 720px) {
  .timeline { padding: 18px 16px 8px; }
  .suggestions { grid-template-columns: 1fr; }
  .tool-only { padding-left: 0; }
}
</style>
