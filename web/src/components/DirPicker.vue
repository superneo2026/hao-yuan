<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { t } from '../i18n'
import Icon from './Icon.vue'
import Modal from './Modal.vue'

const props = defineProps({
  initial: { type: String, default: '' },
  title: { type: String, default: '' }
})
const emit = defineEmits(['close', 'select'])

const current = ref('')
const parent = ref('')
const dirs = ref([])
const manual = ref(props.initial || '')
const loading = ref(false)
const error = ref('')

async function load(path = '') {
  loading.value = true
  error.value = ''
  try {
    const result = await api.fsList(path)
    current.value = result.path || ''
    parent.value = result.parent || ''
    dirs.value = result.dirs || []
    manual.value = current.value
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

function enter(path) {
  load(path)
}

function choose() {
  const value = current.value || manual.value
  if (!value) {
    error.value = t('dir.selectFirst')
    return
  }
  emit('select', value)
  emit('close')
}

function goManual() {
  load(manual.value.trim())
}

onMounted(() => load(props.initial || ''))
</script>

<template>
  <Modal :title="title || t('dir.title')" :subtitle="t('dir.subtitle')" width="620px" @close="emit('close')">
    <div class="row" style="margin-bottom: 12px">
      <button class="icon-btn" :disabled="!parent" :title="t('common.up')" @click="load(parent)">
        <Icon name="chevron-left" :size="17" />
      </button>
      <input v-model="manual" class="field mono" style="font-size: 12px" :placeholder="t('dir.placeholder')" @keydown.enter="goManual" />
      <button class="btn sm" @click="goManual">{{ t('common.go') }}</button>
    </div>
    <div class="mono tiny muted" style="margin-bottom: 8px; min-height: 18px">{{ current || t('dir.drives') }}</div>
    <div class="dir-list">
      <div v-if="loading" class="dir-loading"><span class="spinner" /> {{ t('common.loading') }}</div>
      <button v-for="dir in dirs" :key="dir" class="dir-row" @click="enter(dir)">
        <Icon name="folder" :size="16" style="color: var(--warn)" />
        <span class="truncate">{{ dir }}</span>
        <Icon name="chevron-right" :size="14" style="margin-left: auto; color: var(--faint)" />
      </button>
      <div v-if="!loading && !dirs.length" class="dir-empty">{{ t('dir.noSubfolders') }}</div>
    </div>
    <div v-if="error" class="tiny" style="color: var(--bad); margin-top: 8px">{{ error }}</div>
    <template #footer>
      <button class="btn" @click="emit('close')">{{ t('common.cancel') }}</button>
      <button class="btn primary" :disabled="!current" @click="choose">
        <Icon name="check" :size="15" /> {{ t('common.useThisFolder') }}
      </button>
    </template>
  </Modal>
</template>

<style scoped>
.dir-list { max-height: 340px; overflow-y: auto; border: 1px solid var(--line); border-radius: 12px; background: var(--surface-2); }
.dir-row { width: 100%; display: flex; align-items: center; gap: 9px; padding: 9px 12px; border: none; border-bottom: 1px solid var(--line); background: transparent; color: var(--ink-2); text-align: left; font-size: 12.5px; }
.dir-row:last-child { border-bottom: none; }
.dir-row:hover { background: var(--surface-3); color: var(--ink); }
.dir-loading, .dir-empty { padding: 18px; color: var(--faint); font-size: 12.5px; display: flex; align-items: center; gap: 8px; justify-content: center; }
</style>
