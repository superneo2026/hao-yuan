<script setup>
import { computed } from 'vue'
import { t } from '../i18n'
import Icon from './Icon.vue'

const props = defineProps({
  diff: { type: String, default: '' },
  path: { type: String, default: '' }
})

const lines = computed(() => {
  const rows = (props.diff || '').split('\n')
  return rows.map((line) => {
    let type = 'ctx'
    if (line.startsWith('+++') || line.startsWith('---')) type = 'file'
    else if (line.startsWith('+')) type = 'add'
    else if (line.startsWith('-')) type = 'del'
    else if (line.startsWith('@@')) type = 'hunk'
    else if (line.startsWith('diff ') || line.startsWith('index ')) type = 'meta'
    return { line, type }
  })
})
const added = computed(() => lines.value.filter((row) => row.type === 'add').length)
const removed = computed(() => lines.value.filter((row) => row.type === 'del').length)

function copy() {
  navigator.clipboard?.writeText(props.diff || '')
}
</script>

<template>
  <div class="diff-view">
    <div class="diff-head">
      <div class="row" style="gap: 7px; min-width: 0">
        <Icon name="git" :size="14" style="color: var(--brand)" />
        <span class="mono truncate">{{ path || t('diff.allChanges') }}</span>
      </div>
      <div class="row" style="gap: 6px">
        <span class="badge good">+{{ added }}</span>
        <span class="badge bad">-{{ removed }}</span>
        <button class="icon-btn" :title="t('diff.copy')" @click="copy"><Icon name="copy" :size="13" /></button>
      </div>
    </div>
    <div class="diff-body scroll-y">
      <div v-if="!diff" class="diff-empty">
        <Icon name="git" :size="20" />
        <b>{{ t('diff.cleanTitle') }}</b>
        <span>{{ t('diff.cleanDesc') }}</span>
      </div>
      <div v-else class="diff-code">
        <div v-for="(row, index) in lines" :key="index" class="diff-row" :class="row.type">
          <span class="diff-sign">{{ row.type === 'add' ? '+' : row.type === 'del' ? '-' : ' ' }}</span>
          <span class="diff-text">{{ row.line || ' ' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diff-view { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.diff-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 9px 7px 11px; border-bottom: 1px solid var(--line); background: var(--surface-2); border-radius: 9px 9px 0 0; font-size: 11.5px; }
.diff-body { flex: 1; min-height: 0; background: var(--code-bg); border: 1px solid #232a38; border-top: none; border-radius: 0 0 9px 9px; }
.diff-code { padding: 7px 0; }
.diff-row { display: flex; gap: 6px; font-family: var(--font-mono); font-size: 11.5px; line-height: 1.65; white-space: pre-wrap; padding: 0 10px 0 0; }
.diff-sign { width: 18px; flex: 0 0 18px; text-align: center; color: #4d5668; user-select: none; }
.diff-text { color: #c6cedd; min-width: 0; }
.diff-row.add { background: rgba(45, 190, 130, .10); }
.diff-row.add .diff-text, .diff-row.add .diff-sign { color: #79e0b4; }
.diff-row.del { background: rgba(242, 109, 125, .09); }
.diff-row.del .diff-text, .diff-row.del .diff-sign { color: #f28b98; }
.diff-row.hunk { background: rgba(124, 108, 255, .10); }
.diff-row.hunk .diff-text { color: #9aa9ff; }
.diff-row.file .diff-text, .diff-row.meta .diff-text { color: #6a7488; }
.diff-empty { height: 100%; min-height: 190px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: var(--muted); font-size: 12px; }
.diff-empty b { color: var(--ink-2); font-size: 13px; }
</style>
