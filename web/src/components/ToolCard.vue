<script setup>
import { computed, ref } from 'vue'
import { t } from '../i18n'
import Icon from './Icon.vue'

const props = defineProps({
  item: { type: Object, required: true },
  step: { type: [Number, String], default: 0 }
})

const open = ref(false)

const toolIcon = {
  read_file: 'file',
  read_range: 'file',
  write_file: 'edit',
  edit_file: 'edit',
  apply_patch: 'code',
  multi_edit: 'edit',
  glob: 'search',
  grep: 'search',
  search_symbol: 'search',
  list_dir: 'folder',
  project_scan: 'compass',
  run_shell: 'terminal',
  git: 'git',
  delete_path: 'trash',
  move_path: 'arrow-right',
  task: 'layers',
  plan_task: 'layers',
  update_plan: 'check',
  make_plan: 'document',
  make_storyboard: 'video',
  web_scaffold: 'layers',
  web_audit: 'shield',
  reference_digest: 'document',
  reference_compare: 'shield',
  baseline_audit: 'compass',
  doc_consistency: 'check',
  describe_image: 'eye',
  ask_user: 'message'
}

const args = computed(() => props.item.args || props.item.arguments || {})
const toolName = computed(() => props.item.tool || props.item.name || '')
const title = computed(() => t(`tool.${toolName.value}`, {}, toolName.value || 'Tool'))
const icon = computed(() => toolIcon[props.item.tool || props.item.name] || 'code')
const status = computed(() => props.item.status || (props.item.ok === false ? 'error' : 'done'))
const subtitle = computed(() => {
  const value = args.value
  if (value.path) return value.path
  if (value.file || value.filename || value.target) return value.file || value.filename || value.target
  if (value.command) return value.command
  if (value.pattern) return value.pattern
  if (value.query || value.name) return value.name || value.query
  if (value.expression) return value.expression
  if (value.description) return value.description
  if (value.action) return `git ${value.action} ${value.args || ''}`.trim()
  if (value.edits) return `${value.edits.length} edits`
  return ''
})

function oneLine(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

const changeLines = computed(() => {
  const value = args.value
  if (value.old !== undefined && value.new !== undefined) {
    return [
      ...String(value.old).split('\n').map((text) => ({ type: 'del', text })),
      ...String(value.new).split('\n').map((text) => ({ type: 'add', text }))
    ]
  }
  if (typeof value.patch === 'string' && value.patch.trim()) {
    return value.patch.split('\n').slice(0, 400).map((text) => {
      let type = 'ctx'
      if (text.startsWith('+') && !text.startsWith('+++')) type = 'add'
      else if (text.startsWith('-') && !text.startsWith('---')) type = 'del'
      else if (text.startsWith('@@')) type = 'hunk'
      return { type, text }
    })
  }
  return null
})

const detail = computed(() => {
  const value = args.value
  if (changeLines.value) return ''
  if (value.command !== undefined && typeof value.command === 'string') return value.command
  if (value.content !== undefined) return String(value.content).slice(0, 1600)
  if (value.prompt) return value.prompt
  if (value.edits) return JSON.stringify(value.edits, null, 2)
  return JSON.stringify(value, null, 2)
})
const resultText = computed(() => {
  const raw = props.item.result ?? props.item.summary ?? props.item.output
  if (raw === undefined || raw === null) return ''
  if (typeof raw === 'string') return raw
  try { return JSON.stringify(raw, null, 2) } catch { return String(raw) }
})
const hasBody = computed(() => Boolean(changeLines.value?.length || detail.value || resultText.value || props.item.error))
const hasChange = computed(() => Boolean(changeLines.value?.length))
const addedCount = computed(() => changeLines.value?.filter((line) => line.type === 'add').length || 0)
const removedCount = computed(() => changeLines.value?.filter((line) => line.type === 'del').length || 0)

function formatDuration(ms) {
  if (ms === undefined || ms === null || Number.isNaN(Number(ms))) return ''
  const value = Number(ms)
  if (value < 1000) return `${Math.round(value)}ms`
  const seconds = value / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}m${rest ? ` ${rest}s` : ''}`
}

const duration = computed(() => formatDuration(props.item.ms))

const errorTag = computed(() => {
  if (status.value !== 'error') return null
  const err = String(props.item.error || '')
  if (/truncat|missing required args|截断/i.test(err)) return t('run.truncatedArgs')
  return null
})

const resultTag = computed(() => {
  const raw = props.item.result ?? props.item.summary ?? ''
  const text = typeof raw === 'string' ? raw : ''
  if (!text) return null
  const name = toolName.value
  if (name === 'run_shell' || name === 'git') {
    const match = text.match(/\[exit\s+(-?\d+)\]/i)
    if (match) return { kind: Number(match[1]) === 0 ? 'good' : 'bad', label: t('run.exit', { n: match[1] }) }
  }
  if (name === 'read_file' || name === 'read_range') {
    const match = text.match(/\((\d+)\s*lines?\)/i)
    if (match) return { kind: 'muted', label: t('run.lines', { n: match[1] }) }
  }
  if (name === 'grep') {
    const match = text.match(/(\d+)\s*matches?/i)
    if (match) return { kind: 'muted', label: t('run.matches', { n: match[1] }) }
  }
  return null
})

const statusLabel = computed(() => {
  if (status.value === 'running') return t('tool.running')
  if (status.value === 'error') return t('tool.failed')
  return t('tool.done')
})
</script>

<template>
  <div class="tool-row" :class="[status, { open }]">
    <button class="tool-line" type="button" :title="`${title}${subtitle ? ` · ${oneLine(subtitle)}` : ''} · ${statusLabel}`" @click="open = !open">
      <span class="tool-state">
        <span v-if="status === 'running'" class="spinner" style="width: 11px; height: 11px" />
        <Icon v-else-if="status === 'error'" name="alert" :size="12" />
        <Icon v-else name="check" :size="12" />
      </span>
      <Icon :name="icon" :size="12" class="tool-icon" />
      <span class="tool-name">{{ title }}</span>
      <span v-if="subtitle" class="tool-target truncate">{{ oneLine(subtitle) }}</span>
      <span class="spacer" />
      <span v-if="errorTag" class="tool-tag bad">{{ errorTag }}</span>
      <span v-else-if="resultTag" class="tool-tag" :class="resultTag.kind">{{ resultTag.label }}</span>
      <span v-if="hasChange" class="tool-diffstat mono">
        <span v-if="addedCount" class="add">+{{ addedCount }}</span>
        <span v-if="removedCount" class="del">-{{ removedCount }}</span>
      </span>
      <span v-if="duration" class="tool-dur mono">{{ duration }}</span>
      <span v-else-if="status === 'running'" class="tool-dur mono running">{{ t('run.running') }}</span>
      <Icon :name="open && hasBody ? 'chevron-down' : 'chevron-right'" :size="12" class="tool-chevron" :class="{ hidden: !hasBody }" />
    </button>

    <div v-if="open && hasBody" class="tool-body">
      <div v-if="hasChange" class="tool-diff">
        <div v-for="(line, index) in changeLines" :key="index" class="tool-diff-line" :class="line.type">
          <span class="tool-diff-sign">{{ line.type === 'add' ? '+' : line.type === 'del' ? '-' : line.type === 'hunk' ? '@' : ' ' }}</span>
          <span class="tool-diff-text">{{ line.text || ' ' }}</span>
        </div>
      </div>
      <div v-else-if="detail" class="tool-section">
        <div class="tool-section-label">{{ t('tool.input') }}</div>
        <pre class="mono-pre tool-pre">{{ detail }}</pre>
      </div>
      <div v-if="item.error" class="tool-section">
        <div class="tool-section-label bad">{{ t('tool.error') }}</div>
        <pre class="mono-pre tool-pre">{{ item.error }}</pre>
      </div>
      <div v-if="resultText" class="tool-section">
        <div class="tool-section-label">{{ t('tool.result') }}</div>
        <pre class="mono-pre tool-pre">{{ resultText }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-row { min-width: 0; background: transparent; }
.tool-row.running { background: color-mix(in srgb, var(--brand) 5%, transparent); }
.tool-line { width: 100%; min-height: 34px; display: flex; align-items: center; gap: 7px; padding: 6px 10px; border: 0; background: transparent; color: var(--ink-2); text-align: left; }
.tool-line:hover { background: color-mix(in srgb, var(--surface-3) 45%, transparent); }
.tool-state { width: 14px; height: 14px; flex: 0 0 14px; display: grid; place-items: center; color: var(--good); }
.tool-row.running .tool-state { color: var(--brand); }
.tool-row.error .tool-state { color: var(--bad); }
.tool-icon { color: var(--faint); flex: 0 0 12px; }
.tool-name { flex: 0 0 auto; font-size: 11.5px; font-weight: 560; color: var(--ink); }
.tool-target { min-width: 0; flex: 0 1 auto; font-family: var(--font-mono); font-size: 10.5px; color: var(--faint); }
.tool-line .spacer { flex: 1 1 auto; }
.tool-tag { flex: 0 0 auto; padding: 0 5px; height: 15px; display: inline-flex; align-items: center; border-radius: 4px; font-size: 9.5px; font-weight: 560; background: var(--surface-3); color: var(--muted); }
.tool-tag.good { background: var(--good-soft); color: var(--good); }
.tool-tag.bad { background: var(--bad-soft); color: var(--bad); }
.tool-diffstat { display: inline-flex; gap: 4px; font-size: 9.5px; }
.tool-diffstat .add { color: var(--good); }
.tool-diffstat .del { color: var(--bad); }
.tool-dur { flex: 0 0 auto; font-size: 9.5px; color: var(--faint); }
.tool-dur.running { color: var(--brand); }
.tool-chevron { flex: 0 0 12px; color: var(--faint); transition: transform .16s var(--ease); }
.tool-chevron.hidden { visibility: hidden; }
.tool-body { border-top: 1px solid var(--line); padding: 8px 10px 10px; display: flex; flex-direction: column; gap: 8px; background: color-mix(in srgb, var(--surface) 60%, transparent); }
.tool-section-label { font-size: 9px; text-transform: uppercase; letter-spacing: .1em; color: var(--faint); margin-bottom: 4px; font-weight: 620; }
.tool-section-label.bad { color: var(--bad); }
.tool-pre { margin: 0; max-height: 300px; overflow: auto; background: var(--code-bg); color: #dbe2ee; border-radius: 7px; padding: 8px 10px; border: 1px solid #232a38; font-size: 11px; line-height: 1.55; }
.tool-diff { max-height: 320px; overflow: auto; border: 1px solid var(--line); border-radius: 7px; background: var(--code-bg); font-family: var(--font-mono); font-size: 11px; line-height: 1.55; }
.tool-diff-line { display: flex; gap: 7px; padding: 0 8px; color: #aab4c6; white-space: pre-wrap; word-break: break-word; }
.tool-diff-line .tool-diff-sign { flex: 0 0 8px; color: #5d6679; user-select: none; }
.tool-diff-line.add { background: rgba(55, 211, 155, .1); color: #9fe8c8; }
.tool-diff-line.add .tool-diff-sign { color: var(--good); }
.tool-diff-line.del { background: rgba(242, 109, 125, .1); color: #f4b3bc; }
.tool-diff-line.del .tool-diff-sign { color: var(--bad); }
.tool-diff-line.hunk { color: #8ea0c0; background: rgba(124, 108, 255, .08); }
@media (max-width: 720px) {
  .tool-target { max-width: 42vw; }
  .tool-diffstat { display: none; }
}
</style>
