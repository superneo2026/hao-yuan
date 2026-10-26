<script setup>
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { activeApproval, approveCurrent } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const approval = activeApproval
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

function onKey(event) {
  if (!approval.value) return
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
  <div v-if="approval" class="approval-card slide-up">
    <div class="approval-head">
      <span class="approval-icon"><Icon name="shield" :size="18" /></span>
      <div class="approval-copy">
        <b>{{ t('approval.required') }}</b>
        <span>
          {{ t('approval.description', { tool: approval.tool }) }}
        </span>
      </div>
      <span class="badge warn">{{ t('approval.highRisk') }}</span>
    </div>
    <div class="approval-body">
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
    <div class="approval-foot">
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
</style>
