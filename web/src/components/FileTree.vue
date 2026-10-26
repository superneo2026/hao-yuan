<script setup>
import { computed, ref, watch } from 'vue'
import { t } from '../i18n'
import Icon from './Icon.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  selected: { type: String, default: '' }
})
const emit = defineEmits(['open'])

const expanded = ref(new Set())
const query = ref('')

const sorted = computed(() =>
  [...props.items].sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
    return a.path.localeCompare(b.path)
  })
)

const byPath = computed(() => {
  const map = new Map()
  for (const item of sorted.value) map.set(item.path, item)
  return map
})

function parentsOf(path) {
  const parts = path.split('/')
  const out = []
  for (let i = 1; i < parts.length; i += 1) out.push(parts.slice(0, i).join('/'))
  return out
}

watch(
  () => props.selected,
  (path) => {
    if (!path) return
    const next = new Set(expanded.value)
    for (const parent of parentsOf(path)) next.add(parent)
    expanded.value = next
  },
  { immediate: true }
)

const rows = computed(() => {
  const search = query.value.trim().toLowerCase()
  if (search) {
    return sorted.value
      .filter((item) => item.path.toLowerCase().includes(search))
      .slice(0, 400)
      .map((item) => ({ ...item, depth: item.path.split('/').length - 1 }))
  }
  const out = []
  for (const item of sorted.value) {
    const parents = parentsOf(item.path)
    if (parents.some((parent) => !expanded.value.has(parent))) continue
    out.push({ ...item, depth: parents.length })
    if (out.length >= 1200) break
  }
  return out
})

function toggle(row) {
  if (row.type !== 'dir') {
    emit('open', row.path)
    return
  }
  const next = new Set(expanded.value)
  if (next.has(row.path)) next.delete(row.path)
  else next.add(row.path)
  expanded.value = next
}

function fileColor(name) {
  if (/\.(vue|jsx|tsx)$/.test(name)) return 'var(--good)'
  if (/\.(js|ts|mjs|cjs)$/.test(name)) return 'var(--warn)'
  if (/\.(py|go|rs|java|c|cpp|h)$/.test(name)) return 'var(--brand-2)'
  if (/\.(json|ya?ml|toml|ini)$/.test(name)) return 'var(--muted)'
  if (/\.(md|txt)$/.test(name)) return 'var(--faint)'
  if (/\.(css|scss|less)$/.test(name)) return 'var(--brand)'
  return 'var(--muted)'
}
</script>

<template>
  <div class="file-tree">
    <input v-model="query" class="field tree-search" :placeholder="t('files.filter')" />
    <div class="tree-scroll">
      <button
        v-for="row in rows"
        :key="row.path"
        class="tree-row"
        :class="{ selected: row.path === selected, dir: row.type === 'dir' }"
        :style="{ paddingLeft: `${8 + Math.min(row.depth, 12) * 12}px` }"
        :title="row.path"
        @click="toggle(row)"
      >
        <span class="tree-caret">
          <Icon
            v-if="row.type === 'dir'"
            :name="expanded.has(row.path) ? 'chevron-down' : 'chevron-right'"
            :size="11"
          />
        </span>
        <Icon
          :name="row.type === 'dir' ? 'folder' : 'file'"
          :size="14"
          :style="{ color: row.type === 'dir' ? 'var(--warn)' : fileColor(row.name) }"
        />
        <span class="truncate tree-name">{{ row.name }}</span>
        <span v-if="row.type === 'file' && row.size" class="tree-size">{{ row.size > 1024 ? `${Math.round(row.size / 1024)}k` : `${row.size}b` }}</span>
      </button>
      <div v-if="!rows.length" class="tree-empty">{{ query ? t('files.noMatch') : t('files.empty') }}</div>
    </div>
  </div>
</template>

<style scoped>
.file-tree { display: flex; flex-direction: column; gap: 8px; min-height: 0; height: 100%; }
.tree-search { height: 31px; font-size: 12px; padding: 5px 9px; }
.tree-scroll { flex: 1; overflow-y: auto; min-height: 0; padding-right: 2px; }
.tree-row { width: 100%; display: flex; align-items: center; gap: 6px; padding: 4px 8px; border: none; background: transparent; color: var(--ink-2); border-radius: 6px; text-align: left; font-size: 12px; }
.tree-row:hover { background: var(--surface-2); }
.tree-row.selected { background: var(--brand-soft); color: var(--ink); }
.tree-caret { width: 12px; height: 12px; display: grid; place-items: center; color: var(--faint); flex: 0 0 12px; }
.tree-name { min-width: 0; flex: 1; }
.tree-row.dir .tree-name { color: var(--ink); font-weight: 520; }
.tree-size { font-family: var(--font-mono); font-size: 9px; color: var(--faint); }
.tree-empty { padding: 22px 10px; text-align: center; color: var(--faint); font-size: 12px; }
</style>
