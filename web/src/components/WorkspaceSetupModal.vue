<script setup>
import { ref } from 'vue'
import { dismissWorkspaceSetup, saveDefaultWorkspace, state, toast } from '../stores/app'
import { t } from '../i18n'
import DirPicker from './DirPicker.vue'
import Icon from './Icon.vue'
import Modal from './Modal.vue'

const emit = defineEmits(['close'])

const workspace = ref(state.settings.default_workspace || '')
const showDir = ref(false)
const saving = ref(false)

function chooseDir(path) {
  workspace.value = path
}

function close() {
  dismissWorkspaceSetup()
  emit('close')
}

async function save() {
  const path = workspace.value.trim()
  if (saving.value || !path) return
  saving.value = true
  try {
    await saveDefaultWorkspace(path)
    close()
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Modal :title="t('setup.workspaceTitle')" :subtitle="t('setup.workspaceDesc')" width="640px" @close="close">
    <label class="label">{{ t('newTask.workspace') }}</label>
    <div class="row">
      <input
        v-model="workspace"
        class="field mono"
        style="font-size: 12px"
        :placeholder="t('newTask.workspacePlaceholder')"
        @keydown.enter="save"
      />
      <button class="btn" @click="showDir = true"><Icon name="folder" :size="15" /> {{ t('common.browse') }}</button>
    </div>
    <div class="tiny faint" style="margin-top: 8px; display: flex; align-items: center; gap: 6px">
      <Icon name="sparkles" :size="13" />
      {{ t('setup.workspaceHint') }}
    </div>
    <template #footer>
      <button class="btn ghost" @click="close">{{ t('setup.skip') }}</button>
      <button class="btn primary" :disabled="saving || !workspace.trim()" @click="save">
        <span v-if="saving" class="spinner" />
        <Icon v-else name="check" :size="15" />
        {{ t('setup.saveAndStart') }}
      </button>
    </template>
  </Modal>
  <DirPicker v-if="showDir" :initial="workspace" @close="showDir = false" @select="chooseDir" />
</template>
