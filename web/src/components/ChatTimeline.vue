<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { currentSession, state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'
import Markdown from './Markdown.vue'
import ToolCard from './ToolCard.vue'

const scroller = ref(null)
const autoScroll = ref(true)
const activityOpen = ref({})
const liveActivityOpen = ref(false)
const activeQuestionId = ref('')
const now = ref(Date.now())
let ticking = null
let scrollScheduled = false

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

function enrichTool(item) {
  const meta = state.activity.tools[item.call_id]
  if (meta) {
    if (item.ms === undefined && meta.ms !== undefined) item.ms = meta.ms
    if (!item.status && meta.status) item.status = meta.status
  }
  return item
}

function formatDuration(ms) {
  if (ms === undefined || ms === null || Number.isNaN(Number(ms)) || Number(ms) < 0) return ''
  const value = Number(ms)
  if (value < 1000) return `${Math.round(value)}ms`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}m${rest ? ` ${rest}s` : ''}`
}

const groups = computed(() => {
  const out = []
  const callIndex = new Map()
  let turn = null
  for (const message of state.messages) {
    if (message.role === 'user') {
      turn = null
      out.push({ kind: 'user', id: message.id, content: message.content, created_at: message.created_at })
      continue
    }
    if (message.role === 'assistant') {
      if (!turn) {
        turn = { kind: 'turn', id: `turn-${message.id}`, segments: [], created_at: message.created_at }
        out.push(turn)
      }
      const rawCalls = parseJson(message.tool_args, [])
      const tools = (Array.isArray(rawCalls) ? rawCalls : []).map((call) => {
        let args = {}
        try { args = JSON.parse(call.function?.arguments || '{}') } catch { args = {} }
        const item = enrichTool({
          call_id: call.id,
          tool: call.function?.name,
          args,
          status: 'done'
        })
        callIndex.set(call.id, item)
        return item
      })
      turn.segments.push({
        id: message.id,
        content: message.content || '',
        reasoning: message.reasoning || '',
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
      } else if (turn) {
        const tool = enrichTool({ call_id: message.tool_call_id || message.id, tool: message.tool_name, args: parseJson(message.tool_args, {}), ...parsed })
        turn.segments.push({ id: message.id, content: '', reasoning: '', tools: [tool], created_at: message.created_at })
        callIndex.set(message.tool_call_id || message.id, tool)
      } else {
        out.push({
          kind: 'tool',
          id: message.id,
          tools: [enrichTool({ call_id: message.tool_call_id || message.id, tool: message.tool_name, args: parseJson(message.tool_args, {}), ...parsed })]
        })
      }
    }
  }

  for (const group of out) {
    if (group.kind !== 'turn') continue
    let step = 0
    const reasoningParts = []
    let reasoningCount = 0
    let lastText = ''
    for (const segment of group.segments) {
      if (segment.reasoning.trim()) {
        reasoningParts.push(segment.reasoning.trim())
        reasoningCount++
      }
      for (const tool of segment.tools) tool.step = ++step
      if (segment.content.trim()) lastText = segment.id
      segment.hasMeta = false
    }
    group.reasoning = reasoningParts.join('\n\n')
    group.reasoningCount = reasoningCount
    group.stepCount = step
    for (let index = group.segments.length - 1; index >= 0; index--) {
      if (group.segments[index].content.trim()) {
        group.segments[index].hasMeta = true
        group.lastSegment = group.segments[index]
        break
      }
    }
  }
  return out
})

const userQuestions = computed(() =>
  groups.value
    .filter((group) => group.kind === 'user')
    .map((group, index) => ({ id: group.id, order: index + 1, content: group.content || '' }))
)

const liveText = computed(() => Object.values(state.live.streams).join(''))
const liveReasoning = computed(() => Object.values(state.live.reasoning).join(''))
const liveTools = computed(() => state.live.toolOrder.map((id) => state.live.tools[id]).filter(Boolean))

const isBusy = computed(() => ['running', 'queued', 'waiting_input'].includes(currentSession.value?.status))
const showEmpty = computed(() => !state.messages.length && !liveText.value && liveTools.value.length === 0)

const liveDone = computed(() => liveTools.value.filter((tool) => tool.status === 'done').length)
const liveFailed = computed(() => liveTools.value.filter((tool) => tool.status === 'error').length)
const liveTotal = computed(() => Math.max(state.activity.steps || 0, liveTools.value.length))
const livePhase = computed(() => {
  const status = currentSession.value?.status
  if (status === 'waiting_input') return t('run.waitingApproval')
  if (status === 'queued') return t('run.queued')
  if (liveTools.value.some((tool) => tool.status === 'running')) return t('run.working')
  if (liveReasoning.value && !liveText.value) return t('run.thinking')
  return t('run.working')
})
const liveElapsed = computed(() => {
  const start = state.activity.startedAt
  if (!start) return ''
  const end = state.activity.endedAt || now.value
  return formatDuration(end - start)
})

const allTools = computed(() =>
  groups.value.flatMap((group) => (group.kind === 'turn' ? group.segments.flatMap((segment) => segment.tools) : group.tools || []))
)
const toolTotal = computed(() => allTools.value.length)
const toolFailed = computed(() => allTools.value.filter((tool) => tool.status === 'error').length)
const runElapsed = computed(() => {
  const { startedAt, endedAt } = state.activity
  if (startedAt && endedAt) return formatDuration(endedAt - startedAt)
  const run = state.runs?.[0]
  if (run?.created_at && run?.updated_at) return formatDuration(Date.parse(String(run.updated_at).replace(' ', 'T')) - Date.parse(String(run.created_at).replace(' ', 'T')))
  return ''
})
const runSteps = computed(() => {
  const run = state.runs?.[0]
  if (run?.step_count) return Number(run.step_count)
  return state.activity.steps || groups.value.filter((group) => group.kind === 'turn').reduce((sum, group) => sum + group.segments.length, 0)
})
const runCost = computed(() => Number(currentSession.value?.cost_est || 0))
const showSummary = computed(() => {
  const status = currentSession.value?.status
  return !isBusy.value && (status === 'done' || status === 'error') && toolTotal.value > 0
})

function groupDuration(tools) {
  const total = tools.reduce((sum, tool) => sum + (Number(tool.ms) || 0), 0)
  return total ? formatDuration(total) : ''
}

function toggleActivity(id) {
  activityOpen.value[id] = !activityOpen.value[id]
}

function activityVisible(id) {
  return activityOpen.value[id] === true
}

function toggleLiveActivity() {
  liveActivityOpen.value = !liveActivityOpen.value
}

function atBottom() {
  const el = scroller.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 140
}

function syncActiveQuestion() {
  const el = scroller.value
  if (!el || !userQuestions.value.length) return
  const edges = Array.from(el.querySelectorAll('[data-user-id]'))
  const line = el.getBoundingClientRect().top + 72
  let current = edges[0]?.dataset.userId || ''
  for (const node of edges) {
    if (node.getBoundingClientRect().top <= line) current = node.dataset.userId
    else break
  }
  activeQuestionId.value = current
}

function onScroll() {
  autoScroll.value = atBottom()
  syncActiveQuestion()
}

function scrollBottom(smooth = true) {
  if (scrollScheduled) return
  scrollScheduled = true
  nextTick(() => {
    scrollScheduled = false
    const el = scroller.value
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  })
}

function jumpToQuestion(id) {
  const el = scroller.value
  const node = el?.querySelector(`[data-user-id="${String(id).replace(/"/g, '\\"')}"]`)
  if (!el || !node) return
  const top = node.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop - 12
  el.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  activeQuestionId.value = id
}

watch(
  [() => state.scrollTick, liveText, liveReasoning, liveTools, () => state.messages.length],
  () => {
    if (autoScroll.value) scrollBottom(false)
  }
)

watch(
  () => groups.value.length,
  () => nextTick(syncActiveQuestion)
)

watch(
  () => state.currentId,
  () => {
    autoScroll.value = true
    liveActivityOpen.value = false
    activeQuestionId.value = ''
    scrollBottom(false)
    nextTick(syncActiveQuestion)
  }
)

watch(
  isBusy,
  (busy) => {
    if (busy) {
      now.value = Date.now()
      if (!ticking) ticking = setInterval(() => { now.value = Date.now() }, 1000)
    } else if (ticking) {
      clearInterval(ticking)
      ticking = null
    }
  },
  { immediate: true }
)

onMounted(() => {
  scrollBottom(false)
  nextTick(syncActiveQuestion)
})
onBeforeUnmount(() => {
  if (ticking) clearInterval(ticking)
})

function copy(text) {
  navigator.clipboard?.writeText(text || '')
}

function timeLabel(value) {
  if (!value) return ''
  const date = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
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
        </div>
      </div>

      <div v-else class="timeline-inner">
        <div v-for="group in groups" :key="group.id" class="timeline-group slide-up">
          <template v-if="group.kind === 'user'">
            <div class="message user" :data-user-id="group.id">
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

          <template v-else-if="group.kind === 'turn'">
            <div class="message assistant turn">
              <div class="avatar assistant-avatar">H</div>
              <div class="assistant-body turn-body">
                <details v-if="group.reasoning" class="reasoning turn-reasoning">
                  <summary>
                    <Icon name="brain" :size="13" /> {{ t('chat.reasoning') }}
                    <span v-if="group.reasoningCount > 1" class="reasoning-count">{{ t('run.reasoningSegments', { n: group.reasoningCount }) }}</span>
                    <span class="spacer" />
                    <Icon name="chevron-right" :size="12" class="reasoning-caret" />
                  </summary>
                  <div class="reasoning-body">{{ group.reasoning }}</div>
                </details>

                <template v-for="segment in group.segments" :key="segment.id">
                  <div v-if="segment.content || segment.tools.length" class="turn-step">
                    <span class="turn-dot" />
                    <div class="turn-step-body">
                      <div v-if="segment.content" class="bubble assistant-bubble">
                        <Markdown :content="segment.content" />
                      </div>
                      <div v-if="segment.tools.length" class="activity">
                        <button class="activity-head" @click="toggleActivity(segment.id)">
                          <Icon name="layers" :size="12" />
                          <span>{{ t('run.activity') }}</span>
                          <span class="activity-count">{{ segment.tools.length }}</span>
                          <span class="spacer" />
                          <span v-if="groupDuration(segment.tools)" class="activity-dur mono">{{ groupDuration(segment.tools) }}</span>
                          <Icon :name="activityVisible(segment.id) ? 'chevron-down' : 'chevron-right'" :size="13" />
                        </button>
                        <div v-show="activityVisible(segment.id)" class="activity-steps">
                          <ToolCard v-for="tool in segment.tools" :key="tool.call_id" :item="tool" :step="tool.step" />
                        </div>
                      </div>
                      <div v-if="segment.hasMeta" class="message-meta">
                        <span>{{ timeLabel(segment.created_at) }}</span>
                        <button class="icon-btn" style="width: 20px; height: 20px" @click="copy(segment.content)">
                          <Icon name="copy" :size="11" />
                        </button>
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </template>

          <template v-else>
            <div class="tool-only">
              <ToolCard v-for="tool in group.tools" :key="tool.call_id" :item="tool" />
            </div>
          </template>
        </div>

        <div v-if="isBusy" class="live-run">
          <span class="live-run-dot" />
          <span class="live-run-phase">{{ livePhase }}</span>
          <span v-if="liveElapsed" class="live-run-elapsed mono">{{ liveElapsed }}</span>
          <span v-if="liveTotal" class="live-run-sep" />
          <span v-if="liveTotal" class="live-run-ops mono">{{ liveDone }}/{{ liveTotal }}</span>
          <span v-if="liveFailed" class="live-run-fail">{{ t('run.failedCount', { n: liveFailed }) }}</span>
          <span class="spacer" />
          <span v-if="currentSession?.model" class="live-run-model mono">{{ currentSession.model }}</span>
        </div>

        <div v-if="liveTools.length || liveText || liveReasoning" class="message assistant live">
          <div class="avatar assistant-avatar live-avatar">H</div>
          <div class="assistant-body">
            <div v-if="liveReasoning || liveText" class="bubble assistant-bubble" :class="{ streaming: isBusy && !!liveText }">
              <details v-if="liveReasoning" class="reasoning" open>
                <summary><Icon name="brain" :size="13" /> {{ t('chat.reasoning') }} <span class="spinner" v-if="isBusy && !liveText" style="width: 10px; height: 10px" /></summary>
                <div class="reasoning-body">{{ liveReasoning }}</div>
              </details>
              <Markdown v-if="liveText" :content="liveText" />
            </div>
            <div class="thinking-line" v-if="isBusy && !liveText && !liveReasoning">
              <span class="thinking-dots"><i /><i /><i /></span>
              <span>{{ currentSession?.status === 'waiting_input' ? t('chat.waitingForApproval') : t('chat.working') }}</span>
            </div>
            <div v-if="liveTools.length" class="activity">
              <button class="activity-head" type="button" :aria-expanded="liveActivityOpen" @click="toggleLiveActivity">
                <Icon name="layers" :size="12" />
                <span>{{ t('run.activity') }}</span>
                <span class="activity-count">{{ liveDone }}/{{ liveTools.length }}</span>
                <span class="spacer" />
                <span v-if="liveFailed" class="activity-fail">{{ t('run.failedCount', { n: liveFailed }) }}</span>
                <span v-if="isBusy" class="spinner" style="width: 10px; height: 10px" />
                <Icon :name="liveActivityOpen ? 'chevron-down' : 'chevron-right'" :size="13" />
              </button>
              <div v-show="liveActivityOpen" class="activity-steps">
                <ToolCard v-for="(tool, index) in liveTools" :key="tool.call_id" :item="tool" :step="index + 1" />
              </div>
            </div>
          </div>
        </div>

        <div v-if="showSummary" class="run-summary" :class="{ hasError: toolFailed }">
          <div class="run-summary-head">
            <span class="run-summary-icon">
              <Icon :name="toolFailed ? 'alert' : 'check'" :size="13" />
            </span>
            <b>{{ toolFailed ? t('run.summaryError') : t('run.summaryTitle') }}</b>
            <span class="spacer" />
            <span v-if="runElapsed" class="run-summary-time mono">{{ t('run.elapsed') }} {{ runElapsed }}</span>
          </div>
          <div class="run-summary-grid">
            <span><b>{{ runSteps }}</b><em>{{ t('run.steps') }}</em></span>
            <span><b>{{ toolTotal }}</b><em>{{ t('run.ops') }}</em></span>
            <span :class="{ bad: toolFailed }"><b>{{ toolFailed }}</b><em>{{ t('run.failed') }}</em></span>
            <span><b class="mono">¥{{ runCost.toFixed(4) }}</b><em>{{ t('run.cost') }}</em></span>
          </div>
        </div>
        <div style="height: 12px" />
      </div>
    </div>

    <button v-if="!autoScroll && !showEmpty" class="jump-bottom" @click="scrollBottom()">
      <Icon name="chevron-down" :size="14" /> {{ t('chat.latest') }}
    </button>

    <div v-if="!showEmpty && userQuestions.length" class="question-rail">
      <button
        v-for="question in userQuestions"
        :key="question.id"
        type="button"
        class="question-pin"
        :class="{ active: question.id === activeQuestionId }"
        :aria-label="question.content"
        @click="jumpToQuestion(question.id)"
      >
        <span class="question-pin-dot" />
        <span class="question-tip">
          <span class="question-tip-index">Q{{ question.order }}</span>
          <span class="question-tip-text">{{ question.content }}</span>
        </span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.timeline-wrap { position: relative; min-height: 0; flex: 1; display: flex; flex-direction: column; container-type: inline-size; }
.timeline { flex: 1; padding: 26px 28px 12px; }
.timeline-inner { max-width: 880px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }
.timeline-group { display: flex; flex-direction: column; gap: 8px; }
.message { display: flex; gap: 11px; align-items: flex-start; }
.message.user { flex-direction: row-reverse; }
.message.assistant { flex-direction: row; }
.avatar { width: 28px; height: 28px; border-radius: 9px; display: grid; place-items: center; font-size: 10px; font-weight: 700; flex: 0 0 28px; margin-top: 1px; }
.user-avatar { background: color-mix(in srgb, var(--user-brand) 12%, transparent); color: var(--user-brand); border: 1px solid color-mix(in srgb, var(--user-brand) 30%, transparent); font-size: 9px; letter-spacing: .02em; }
.assistant-avatar { background: linear-gradient(140deg, var(--brand), var(--brand-2)); color: #fff; box-shadow: 0 6px 18px rgba(124, 108, 255, .28); }
.live-avatar { animation: pulse 2s infinite; }
.bubble-wrap { flex: 1; display: flex; flex-direction: column; align-items: flex-end; gap: 4px; max-width: min(760px, 100%); }
.bubble { padding: 10px 15px; color: var(--ink); white-space: pre-wrap; word-break: break-word; font-size: 13.5px; line-height: 1.68; }
.bubble.user-bubble {
  border-radius: 16px 5px 16px 16px;
  background: var(--user-bubble);
  border: 1px solid color-mix(in srgb, var(--user-brand) 42%, transparent);
  color: var(--user-bubble-ink);
  box-shadow: 0 10px 26px var(--user-glow);
}
.assistant-body { min-width: 0; flex: 1; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; padding-top: 2px; }
.bubble.assistant-bubble {
  border-radius: 5px 16px 16px 16px;
  background: var(--bot-bubble);
  border: 1px solid var(--line);
  color: var(--ink-2);
  box-shadow: 0 2px 10px color-mix(in srgb, #000 6%, transparent);
  max-width: min(760px, 100%);
  white-space: normal;
}
.assistant-bubble .reasoning { background: transparent; }
.assistant-bubble .reasoning-body { color: var(--muted); }
.assistant-bubble.streaming .markdown > :last-child::after {
  content: '';
  display: inline-block;
  width: 6px;
  height: 1.02em;
  margin-left: 2px;
  border-radius: 2px;
  background: var(--brand);
  vertical-align: text-bottom;
  animation: caret 1s steps(1) infinite;
}
@keyframes caret { 50% { opacity: 0 } }
.message-meta { display: flex; align-items: center; gap: 6px; color: var(--faint); font-size: 10.5px; opacity: .55; transition: opacity .16s var(--ease); }
.message:hover .message-meta { opacity: .9; }
.turn-body { gap: 10px; }
.turn-reasoning { width: 100%; max-width: min(760px, 100%); }
.reasoning-count { font-size: 10px; color: var(--faint); }
.reasoning-caret { transition: transform .18s var(--ease); }
.reasoning[open] .reasoning-caret { transform: rotate(90deg); }
.turn-step { position: relative; display: flex; gap: 10px; width: 100%; }
.turn-step + .turn-step { margin-top: 12px; }
.turn-dot { position: relative; z-index: 1; width: 7px; height: 7px; border-radius: 50%; background: var(--surface-3); border: 1px solid var(--line-strong); margin-top: 12px; flex: 0 0 7px; }
.turn-step::before { content: ''; position: absolute; left: 3px; top: -12px; bottom: -12px; width: 1px; background: var(--line); }
.turn-step:first-of-type::before { display: none; }
.turn-step-body { min-width: 0; flex: 1; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
.reasoning { border: 1px solid var(--line); border-radius: 10px; background: var(--surface-2); overflow: hidden; }
.reasoning summary { display: flex; align-items: center; gap: 6px; padding: 7px 10px; color: var(--muted); font-size: 11.5px; cursor: pointer; list-style: none; }
.reasoning summary::-webkit-details-marker { display: none; }
.reasoning-body { padding: 0 12px 10px; color: var(--muted); font-size: 12px; line-height: 1.65; white-space: pre-wrap; max-height: 280px; overflow-y: auto; }

.activity { align-self: stretch; border: 1px solid var(--line); border-radius: 13px; background: color-mix(in srgb, var(--surface-2) 55%, transparent); overflow: hidden; }
.activity-head { width: 100%; display: flex; align-items: center; gap: 7px; padding: 8px 11px; background: transparent; border: none; color: var(--muted); font-size: 11.5px; font-weight: 560; text-align: left; }
.activity-head:not(.static):hover { color: var(--ink); background: color-mix(in srgb, var(--surface-3) 55%, transparent); }
.activity-head .spacer { flex: 1; }
.activity-count { font-family: var(--font-mono); font-size: 10px; padding: 0 6px; height: 16px; display: inline-flex; align-items: center; border-radius: 6px; background: var(--surface-3); color: var(--muted); }
.activity-dur { font-size: 10px; color: var(--faint); }
.activity-fail { font-size: 10px; color: var(--bad); }
.activity-steps { display: flex; flex-direction: column; gap: 6px; padding: 2px 8px 9px; }
.activity-steps > * { position: relative; }

.live-run { align-self: stretch; display: flex; align-items: center; gap: 9px; padding: 7px 12px; border-radius: 999px; border: 1px solid var(--brand-line); background: color-mix(in srgb, var(--brand) 7%, var(--surface)); font-size: 11.5px; color: var(--ink-2); box-shadow: 0 4px 16px color-mix(in srgb, var(--brand) 10%, transparent); }
.live-run-dot { width: 8px; height: 8px; flex: 0 0 8px; border-radius: 50%; background: var(--brand); box-shadow: 0 0 0 4px color-mix(in srgb, var(--brand) 18%, transparent); animation: pulse 1.6s infinite; }
.live-run-phase { font-weight: 620; color: var(--ink); }
.live-run-elapsed { color: var(--muted); font-size: 10.5px; }
.live-run-sep { width: 1px; height: 12px; background: var(--line-strong); }
.live-run-ops { color: var(--muted); font-size: 10.5px; }
.live-run-fail { color: var(--bad); font-size: 10.5px; }
.live-run-model { color: var(--faint); font-size: 10px; }

.thinking-line { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12.5px; padding: 2px 0; }
.thinking-dots { display: inline-flex; gap: 3px; }
.thinking-dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--brand); animation: dot 1.2s infinite ease-in-out; }
.thinking-dots i:nth-child(2) { animation-delay: .15s; }
.thinking-dots i:nth-child(3) { animation-delay: .3s; }
@keyframes dot { 0%, 80%, 100% { opacity: .25; transform: translateY(0); } 40% { opacity: 1; transform: translateY(-2px); } }

.run-summary { align-self: stretch; border: 1px solid var(--line); border-radius: 14px; background: color-mix(in srgb, var(--good-soft) 55%, var(--surface)); padding: 11px 14px; }
.run-summary.hasError { background: color-mix(in srgb, var(--bad-soft) 45%, var(--surface)); border-color: color-mix(in srgb, var(--bad) 30%, var(--line)); }
.run-summary-head { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--ink); }
.run-summary-icon { width: 20px; height: 20px; border-radius: 6px; display: grid; place-items: center; background: var(--good); color: #fff; }
.run-summary.hasError .run-summary-icon { background: var(--bad); }
.run-summary-time { font-size: 10.5px; color: var(--muted); }
.run-summary-grid { display: flex; gap: 20px; margin-top: 9px; padding-top: 9px; border-top: 1px dashed var(--line); flex-wrap: wrap; }
.run-summary-grid > span { display: flex; flex-direction: column; gap: 1px; }
.run-summary-grid b { font-size: 13px; color: var(--ink); letter-spacing: -.01em; }
.run-summary-grid em { font-style: normal; font-size: 9.5px; text-transform: uppercase; letter-spacing: .08em; color: var(--faint); }
.run-summary-grid .bad b { color: var(--bad); }

.tool-only { padding-left: 39px; display: flex; flex-direction: column; gap: 6px; }
.welcome-mark { display: flex; justify-content: center; margin-bottom: 18px; }
.jump-bottom { position: absolute; left: 50%; bottom: 16px; transform: translateX(-50%); display: inline-flex; align-items: center; gap: 5px; padding: 6px 11px; border-radius: 99px; border: 1px solid var(--line-strong); background: var(--elevated); color: var(--ink-2); font-size: 11.5px; box-shadow: var(--shadow-card); }
.jump-bottom:hover { color: var(--ink); border-color: var(--brand-line); }

.question-rail {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 6;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 9px;
  padding: 9px 3px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--elevated) 88%, transparent);
  box-shadow: 0 6px 20px color-mix(in srgb, #000 8%, transparent);
  backdrop-filter: blur(8px);
}
.question-pin {
  position: relative;
  width: 16px;
  height: 16px;
  padding: 0;
  border: none;
  background: transparent;
  display: grid;
  place-items: center;
  cursor: pointer;
}
.question-pin-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--line-strong);
  transition: background .16s var(--ease), box-shadow .16s var(--ease), transform .16s var(--ease);
}
.question-pin:hover .question-pin-dot,
.question-pin.active .question-pin-dot {
  background: var(--brand);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--brand) 18%, transparent);
  transform: scale(1.05);
}
.question-tip {
  position: absolute;
  right: calc(100% + 8px);
  top: 50%;
  width: max-content;
  max-width: min(300px, 40vw);
  padding: 9px 11px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--elevated);
  box-shadow: var(--shadow-card);
  color: var(--ink-2);
  font-size: 11.5px;
  line-height: 1.55;
  text-align: left;
  opacity: 0;
  visibility: hidden;
  pointer-events: auto;
  transform: translateY(-50%) translateX(6px);
  transition: opacity .15s var(--ease), transform .15s var(--ease), visibility 0s;
}
.question-tip::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 100%;
  width: 12px;
}
.question-pin:hover .question-tip,
.question-pin:focus-visible .question-tip,
.question-pin:focus-within .question-tip {
  opacity: 1;
  visibility: visible;
  transform: translateY(-50%) translateX(0);
  transition-delay: 0s;
}
.question-tip-index {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  height: 16px;
  line-height: 16px;
  border-radius: 5px;
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  color: var(--brand);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
}
.question-tip-text {
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
}
@container (max-width: 980px) {
  .question-rail { display: none; }
}
@media (max-width: 1000px) {
  .question-rail { display: none; }
}
@media (max-width: 720px) {
  .timeline { padding: 18px 16px 8px; }
  .tool-only { padding-left: 0; }
  .run-summary-grid { gap: 14px; }
}
</style>
