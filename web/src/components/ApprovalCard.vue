<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { activeApproval, approveCurrent } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const approval = activeApproval
const isQuestion = computed(() => approval.value?.tool === 'ask_user')
const questionText = computed(() => String(approval.value?.args?.question || approval.value?.preview || ''))
const questionContext = computed(() => String(approval.value?.args?.context || ''))
const options = computed(() => {
  const raw = approval.value?.args?.options
  if (!Array.isArray(raw)) return []
  return raw.map((item) => String(item)).filter((item) => item.trim())
})
const allowFreeText = computed(() => approval.value?.args?.allow_free_text !== false)
const answerText = ref('')
const submitting = ref(false)
watch(
  () => approval.value?.approval_id,
  () => {
    answerText.value = ''
    submitting.value = false
  }
)
const previewLines = computed(() => {
  const text = approval.value?.preview || ''
  return text.split('\n').map((line) => ({
    text: line,
    type: line.startsWith('+') && !line.startsWith('+++') ? 'add'
      : line.startsWith('-') && !line.startsWith('---') ? 'del'
        : line.startsWith('@@') ? 'hunk'
          : 'ctx'
  }))
})
const argsText = computed(() => {
  try { return JSON.stringify(approval.value?.args || {}, null, 2) } catch { return '' }
})

async function answer(value) {
  if (submitting.value) return
  const text = String(value ?? '').trim()
  if (!text) return
  submitting.value = true
  try {
    await approveCurrent(true, text)
  } finally {
    submitting.value = false
  }
}

function skipQuestion() {
  answer(t('approval.skipAnswer', {}, '用户跳过，请按最佳判断继续。'))
}

function onKey(event) {
  if (!approval.value || isQuestion.value) return
  const tag = (event.target?.tagName || '').toLowerCase()
  if (tag === 'input' || tag === 'textarea' || event.target?.isContentEditable) return
  if (event.key.toLowerCase() === 'a') {
    event.preventDefault()
    approveCurrent(true)
  } else if (event.key.toLowerCase() === 'r') {
    event.preventDefault()
    approveCurrent(false, 'rejected by keyboard')
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div v-if="approval" class="approval-card slide-up" :class="{ question: isQuestion }">
    <div class="approval-head">
      <span class="approval-icon"><Icon :name="isQuestion ? 'message' : 'shield'" :size="18" /></span>
      <div class="approval-copy">
        <b>{{ isQuestion ? t('approval.question', {}, '需要你确认') : t('approval.required') }}</b>
        <span v-if="isQuestion">{{ t('approval.questionHint', {}, '任务已暂停，确认后会从当前步骤继续，不会重新开始。') }}</span>
        <span v-else>{{ t('approval.description', { tool: approval.tool }) }}</span>
      </div>
      <span class="badge" :class="isQuestion ? 'question-badge' : 'warn'">{{ isQuestion ? t('approval.realtime', {}, '实时交互') : t('approval.highRisk') }}</span>
    </div>

    <div v-if="isQuestion" class="approval-body question-body">
      <div class="question-text">{{ questionText }}</div>
      <div v-if="questionContext" class="question-context">{{ questionContext }}</div>
      <div v-if="options.length" class="question-options">
        <button
          v-for="(option, index) in options"
          :key="index"
          type="button"
          class="btn question-option"
          :disabled="submitting"
          @click="answer(option)"
        >
          <span class="question-option-index">{{ index + 1 }}</span>{{ option }}
        </button>
      </div>
    </div>

    <div v-else class="approval-body">
      <pre v-if="previewLines.length > 1 || (previewLines[0] && previewLines[0].text)" class="diff-preview"><span
        v-for="(line, index) in previewLines"
        :key="index"
        class="diff-line"
        :class="line.type"
      >{{ line.text }}{{ '\n' }}</span></pre>
      <details v-else class="approval-args">
        <summary>{{ t('approval.arguments') }}</summary>
        <pre class="mono-pre">{{ argsText }}</pre>
      </details>
    </div>

    <div v-if="isQuestion" class="approval-foot question-foot">
      <input
        v-if="allowFreeText"
        v-model="answerText"
        class="question-input"
        :disabled="submitting"
        :placeholder="t('approval.typeAnswer', {}, '也可以直接输入你的回答…')"
        @keydown.enter.exact.prevent="answer(answerText)"
      />
      <span class="spacer" />
      <button class="btn" type="button" :disabled="submitting" @click="skipQuestion">{{ t('approval.skip', {}, '跳过，自行判断') }}</button>
      <button v-if="allowFreeText" class="btn primary" type="button" :disabled="submitting || !answerText.trim()" @click="answer(answerText)">
        <Icon name="send" :size="13" /> {{ t('approval.confirmContinue', {}, '确认并继续') }}
      </button>
    </div>
    <div v-else class="approval-foot">
      <span class="tiny faint"><span class="kbd">A</span> {{ t('approval.shortApprove') }} · <span class="kbd">R</span> {{ t('approval.shortReject') }}</span>
      <span class="spacer" />
      <button class="btn" @click="approveCurrent(false, 'rejected from UI')"><Icon name="x" :size="14" /> {{ t('approval.reject') }}</button>
      <button class="btn primary" @click="approveCurrent(true)"><Icon name="check" :size="14" /> {{ t('approval.approve') }}</button>
    </div>
  </div>
</template>

<style scoped>
.approval-card { max-width: 900px; margin: 0 auto 10px; border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--line)); border-radius: 15px; background: color-mix(in srgb, var(--warn-soft) 60%, var(--surface)); box-shadow: var(--shadow-card); overflow: hidden; }
.approval-head { display: flex; align-items: flex-start; gap: 11px; padding: 13px 15px; }
.approval-icon { width: 34px; height: 34px; border-radius: 10px; background: var(--warn-soft); color: var(--warn); display: grid; place-items: center; flex: 0 0 34px; }
.approval-copy { display: flex; flex-direction: column; gap: 2px; flex: 1; }
.approval-copy b { font-size: 13.5px; }
.approval-copy span { color: var(--muted); font-size: 12px; }
.approval-body { padding: 0 15px 12px; }
.diff-preview { margin: 0; max-height: 280px; overflow: auto; background: var(--code-bg); color: #d6dce8; border: 1px solid #232a38; border-radius: 10px; padding: 10px 12px; font-family: var(--font-mono); font-size: 11.5px; line-height: 1.55; white-space: pre-wrap; }
.diff-line.add { color: #74e0b0; }
.diff-line.del { color: #f28b98; }
.diff-line.hunk { color: #8ea6ff; }
.approval-args summary { cursor: pointer; color: var(--muted); font-size: 12px; }
.approval-foot { display: flex; align-items: center; gap: 8px; padding: 10px 15px; border-top: 1px solid color-mix(in srgb, var(--warn) 25%, var(--line)); background: color-mix(in srgb, var(--surface) 55%, transparent); }
.kbd { font-family: var(--font-mono); border: 1px solid var(--line-strong); background: var(--surface-3); border-radius: 4px; padding: 0 4px; font-size: 10px; }

.approval-card.question {
  border-color: color-mix(in srgb, var(--brand) 45%, var(--line));
  background: color-mix(in srgb, var(--brand) 6%, var(--surface));
}
.approval-card.question .approval-icon {
  background: color-mix(in srgb, var(--brand) 14%, transparent);
  color: var(--brand);
}
.question-badge {
  border: 1px solid color-mix(in srgb, var(--brand) 40%, transparent);
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  color: var(--brand);
}
.question-body { display: flex; flex-direction: column; gap: 10px; }
.question-text { font-size: 13.5px; line-height: 1.7; color: var(--ink); white-space: pre-wrap; word-break: break-word; }
.question-context { font-size: 11.5px; line-height: 1.6; color: var(--muted); padding: 8px 10px; border-radius: 8px; background: color-mix(in srgb, var(--surface-2) 70%, transparent); border: 1px dashed var(--line); white-space: pre-wrap; }
.question-options { display: flex; flex-wrap: wrap; gap: 8px; }
.question-option { justify-content: flex-start; gap: 7px; }
.question-option-index {
  display: inline-grid;
  place-items: center;
  width: 17px;
  height: 17px;
  border-radius: 5px;
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  color: var(--brand);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 700;
}
.question-foot { border-top-color: color-mix(in srgb, var(--brand) 22%, var(--line)); }
.question-input {
  flex: 1;
  min-width: 160px;
  padding: 8px 11px;
  border-radius: 9px;
  border: 1px solid var(--line-strong);
  background: var(--surface);
  color: var(--ink);
  font-size: 12.5px;
  outline: none;
  transition: border-color .16s var(--ease), box-shadow .16s var(--ease);
}
.question-input:focus { border-color: var(--brand); box-shadow: 0 0 0 3px color-mix(in srgb, var(--brand) 16%, transparent); }
.question-input:disabled { opacity: .6; }
</style>
