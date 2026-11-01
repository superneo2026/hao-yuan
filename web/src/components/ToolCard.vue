<script setup>
import { computed, ref, watch } from 'vue'
import { t } from '../i18n'
import Icon from './Icon.vue'

const props = defineProps({
  item: { type: Object, required: true },
  step: { type: [Number, String], default: 0 }
})

const open = ref(false)
watch(
  () => props.item.status,
  (status) => {
    if (status === 'running' || status === 'error') open.value = true
  },
  { immediate: true }
)

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
  web_audit: 'shield'
}

const args = computed(() => props.item.args || props.item.arguments || {})
const toolName = computed(() => props.item.tool || props.item.name || '')
const title = computed(() => t(`tool.${toolName.value}`, {}, toolName.value || 'Tool'))
const icon = computed(() => toolIcon[props.item.tool || props.item.name] || 'code')
const status = computed(() => props.item.status || (props.item.ok === false ? 'error' : 'done'))
const subtitle = computed(() => {
  const value = args.value
  if (value.path) return value.path
  if (value.command) return value.command
  if (value.pattern) return value.pattern
  if (value.query || value.name) return value.name || value.query
  if (value.expression) return value.expression
  if (value.description) return value.description
  if (value.action) return `git ${value.action} ${value.args || ''}`.trim()
  if (value.edits) return `${value.edits.length} edits`
  return ''
})
const detail = computed(() => {
  const value = args.value
  if (value.patch) return value.patch
  if (value.old !== undefined) return `- ${String(value.old).slice(0, 1200)}\n+ ${String(value.new || '').slice(0, 1200)}`
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
const hasBody = computed(() => Boolean(detail.value || resultText.value || props.item.error))

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
</script>

<template>
  <div class="tool-card" :class="[status, { open }]">
    <button class="tool-head" @click="open = !open">
      <span v-if="step" class="tool-step mono">{{ step }}</span>
      <span class="tool-icon">
        <span v-if="status === 'running'" class="spinner" style="width: 12px; height: 12px" />
        <Icon v-else-if="status === 'error'" name="alert" :size="13" />
        <Icon v-else name="check" :size="13" />
      </span>
      <span class="tool-main">
        <span class="tool-title">
          {{ title }}
          <span v-if="subtitle" class="tool-sub truncate">{{ subtitle }}</span>
        </span>
        <span class="tool-meta">
          <span v-if="errorTag" class="tool-tag bad">{{ errorTag }}</span>
          <span v-if="resultTag" class="tool-tag" :class="resultTag.kind">{{ resultTag.label }}</span>
          <span v-if="duration" class="tool-dur mono">{{ duration }}</span>
          <span v-else-if="status === 'running'" class="tool-dur running">{{ t('run.running') }}</span>
          <span v-else-if="status === 'error'" style="color: var(--bad)">{{ t('tool.failed') }}</span>
          <span v-else style="color: var(--good)">{{ t('tool.done') }}</span>
        </span>
      </span>
      <Icon :name="open ? 'chevron-down' : 'chevron-right'" :size="14" class="tool-chevron" />
    </button>
    <div v-if="open && hasBody" class="tool-body">
      <div v-if="detail" class="tool-section">
        <div class="tool-section-label">{{ t('tool.input') }}</div>
        <pre class="mono-pre tool-pre">{{ detail }}</pre>
      </div>
      <div v-if="item.error" class="tool-section">
        <div class="tool-section-label" style="color: var(--bad)">{{ t('tool.error') }}</div>
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
.tool-card { border: 1px solid var(--line); border-radius: 11px; background: var(--surface); overflow: hidden; transition: border-color .16s var(--ease), box-shadow .16s var(--ease); }
.tool-card.running { border-color: var(--brand-line); box-shadow: 0 0 0 3px var(--brand-soft); }
.tool-card.error { border-color: color-mix(in srgb, var(--bad) 38%, var(--line)); }
.tool-head { width: 100%; display: flex; align-items: center; gap: 9px; padding: 8px 10px; background: transparent; border: none; text-align: left; color: var(--ink-2); }
.tool-head:hover { background: var(--surface-2); }
.tool-step { flex: 0 0 18px; width: 18px; height: 18px; border-radius: 6px; background: var(--surface-3); color: var(--muted); font-size: 9.5px; display: grid; place-items: center; }
.tool-icon { width: 26px; height: 26px; border-radius: 7px; background: var(--surface-2); color: var(--muted); display: grid; place-items: center; flex: 0 0 26px; }
.tool-card.running .tool-icon { color: var(--brand); background: var(--brand-soft); }
.tool-card.running .tool-icon .spinner { border-color: color-mix(in srgb, var(--brand) 30%, transparent); border-top-color: var(--brand); }
.tool-card.done .tool-icon { color: var(--good); background: var(--good-soft); }
.tool-card.error .tool-icon { color: var(--bad); background: var(--bad-soft); }
.tool-main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 2px; }
.tool-title { font-size: 12px; font-weight: 560; display: flex; gap: 7px; align-items: baseline; min-width: 0; }
.tool-sub { font-family: var(--font-mono); font-size: 10.5px; color: var(--faint); font-weight: 400; }
.tool-meta { display: flex; gap: 8px; color: var(--faint); font-size: 10px; align-items: center; }
.tool-tag { padding: 0 6px; height: 15px; display: inline-flex; align-items: center; border-radius: 5px; font-size: 9.5px; font-weight: 560; background: var(--surface-3); color: var(--muted); }
.tool-tag.good { background: var(--good-soft); color: var(--good); }
.tool-tag.bad { background: var(--bad-soft); color: var(--bad); }
.tool-tag.muted { background: var(--surface-3); color: var(--muted); }
.tool-dur { color: var(--muted); }
.tool-dur.running { color: var(--brand); }
.tool-chevron { color: var(--faint); flex: 0 0 14px; }
.tool-body { border-top: 1px solid var(--line); padding: 8px 10px 10px; display: flex; flex-direction: column; gap: 8px; background: var(--surface-2); }
.tool-section-label { font-size: 9.5px; text-transform: uppercase; letter-spacing: .1em; color: var(--faint); margin-bottom: 4px; font-weight: 620; }
.tool-pre { margin: 0; max-height: 280px; background: var(--code-bg); color: #dbe2ee; border-radius: 8px; padding: 9px 10px; border: 1px solid #232a38; }
</style>
