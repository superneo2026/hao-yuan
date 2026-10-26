<script setup>
import { computed, ref } from 'vue'
import { t } from '../i18n'
import Icon from './Icon.vue'

const props = defineProps({
  file: { type: Object, default: null },
  loading: { type: Boolean, default: false }
})
const emit = defineEmits(['diff'])

const wrap = ref(false)

const lines = computed(() => {
  if (!props.file?.content) return []
  const all = props.file.content.split('\n')
  return all.slice(0, 4000)
})
const truncated = computed(() => (props.file?.content || '').split('\n').length > 4000)

function copy() {
  navigator.clipboard?.writeText(props.file?.content || '')
}
</script>

<template>
  <div class="file-viewer">
    <div v-if="loading" class="viewer-state"><span class="spinner" /> {{ t('files.loading') }}</div>
    <div v-else-if="!file" class="viewer-state">
      <Icon name="file" :size="22" />
      <b>{{ t('files.noOpen') }}</b>
      <span>{{ t('files.noOpenDesc') }}</span>
    </div>
    <template v-else>
      <div class="viewer-head">
        <div class="viewer-title">
          <Icon name="file" :size="14" style="color: var(--brand-2)" />
          <span class="mono truncate">{{ file.path }}</span>
        </div>
        <div class="row" style="gap: 4px">
          <span class="badge">{{ file.language }}</span>
          <span class="tiny faint">{{ file.lines }} lines</span>
          <button class="icon-btn" :title="t('files.wrap')" :class="{ active: wrap }" @click="wrap = !wrap">
            <Icon name="menu" :size="14" />
          </button>
          <button class="icon-btn" :title="t('files.copy')" @click="copy"><Icon name="copy" :size="14" /></button>
          <button class="icon-btn" :title="t('files.diff')" @click="emit('diff', file.path)"><Icon name="git" :size="14" /></button>
        </div>
      </div>
      <div class="viewer-body scroll-y" :class="{ wrap }">
        <div v-for="(line, index) in lines" :key="index" class="code-row">
          <span class="line-no">{{ index + 1 }}</span>
          <span class="line-text">{{ line || ' ' }}</span>
        </div>
        <div v-if="truncated" class="truncated-note">{{ t('files.truncated') }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.file-viewer { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.viewer-head { display: flex; align-items: center; gap: 8px; padding: 7px 8px 7px 11px; border-bottom: 1px solid var(--line); background: var(--surface-2); border-radius: 9px 9px 0 0; }
.viewer-title { display: flex; align-items: center; gap: 6px; min-width: 0; flex: 1; font-size: 11.5px; }
.viewer-body { flex: 1; min-height: 0; background: var(--code-bg); border-radius: 0 0 9px 9px; border: 1px solid #232a38; border-top: none; padding: 7px 0; }
.code-row { display: flex; gap: 12px; padding: 0 12px; font-family: var(--font-mono); font-size: 11.5px; line-height: 1.65; white-space: pre; }
.viewer-body.wrap .code-row { white-space: pre-wrap; }
.line-no { width: 34px; flex: 0 0 34px; text-align: right; color: #4d5668; user-select: none; }
.line-text { color: #d6dce8; min-width: 0; }
.viewer-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 7px; color: var(--muted); font-size: 12px; border: 1px dashed var(--line); border-radius: 10px; min-height: 180px; }
.viewer-state b { color: var(--ink-2); font-size: 13px; }
.truncated-note { padding: 10px 12px; color: var(--warn); font-size: 11px; font-family: var(--font-sans); }
</style>
