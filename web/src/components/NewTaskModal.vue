<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createSession, recentSessionSettings, state, toast } from '../stores/app'
import { sessionTitle, skillTitle, t } from '../i18n'
import DirPicker from './DirPicker.vue'
import Icon from './Icon.vue'
import Modal from './Modal.vue'

const emit = defineEmits(['close'])
const router = useRouter()

const kinds = [
  { id: 'auto', titleKey: 'newTask.auto', descKey: 'newTask.autoDesc', icon: 'sparkles' },
  { id: 'dev', titleKey: 'newTask.coding', descKey: 'newTask.codingDesc', icon: 'terminal' },
  { id: 'plan', titleKey: 'newTask.plan', descKey: 'newTask.planDesc', icon: 'document' },
  { id: 'video', titleKey: 'newTask.video', descKey: 'newTask.videoDesc', icon: 'video' },
  { id: 'robot', titleKey: 'newTask.robot', descKey: 'newTask.robotDesc', icon: 'cpu' },
  { id: 'general', titleKey: 'newTask.chat', descKey: 'newTask.chatDesc', icon: 'message' }
]

function parseAllow(value) {
  if (Array.isArray(value)) return [...value]
  if (typeof value === 'string' && value) {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }
  return []
}

const inherited = recentSessionSettings()

const form = ref({
  kind: inherited?.kind || 'auto',
  title: '',
  workspace: inherited?.workspace || state.settings.default_workspace || '',
  provider: inherited?.provider || '',
  model: inherited?.model || '',
  thinking: inherited?.thinking || '',
  gate_mode: inherited?.gate_mode || '',
  gate_allow: parseAllow(inherited?.gate_allow),
  skills: parseAllow(inherited?.skills)
})

const showDir = ref(false)
const advanced = ref(false)
const submitting = ref(false)

const hasInheritedSettings = computed(
  () => !!(inherited && (inherited.model || inherited.thinking || inherited.gate_mode))
)

const modelOptions = computed(() => {
  const out = []
  for (const provider of state.models) {
    for (const model of provider.models || []) {
      out.push({ provider: provider.provider, model, label: `${provider.provider} / ${model}` })
    }
  }
  return out
})

const selectedSkills = computed(() => new Set(form.value.skills))

const defaultWorkspace = computed(() => state.settings.default_workspace || '')
const usingDefaultWorkspace = computed(() => !!defaultWorkspace.value && form.value.workspace === defaultWorkspace.value)

function toggleSkill(name) {
  const set = new Set(form.value.skills)
  if (set.has(name)) set.delete(name)
  else set.add(name)
  form.value.skills = [...set]
}

function chooseDir(path) {
  form.value.workspace = path
}

function onModelChange(event) {
  const value = event.target.value
  if (!value) {
    form.value.provider = ''
    form.value.model = ''
    return
  }
  const [provider, model] = value.split('|')
  form.value.provider = provider
  form.value.model = model
}

async function create() {
  if (submitting.value) return
  submitting.value = true
  try {
    const session = await createSession(form.value)
    emit('close')
    router.push(`/s/${encodeURIComponent(session.id)}`)
    toast(t('session.created', { title: sessionTitle(session) }), 'good')
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Modal :title="t('session.newTitle')" :subtitle="t('session.newSubtitle')" width="720px" @close="emit('close')">
    <div class="kind-grid">
      <button
        v-for="kind in kinds"
        :key="kind.id"
        class="kind-card"
        :class="{ active: form.kind === kind.id }"
        @click="form.kind = kind.id"
      >
        <span class="kind-icon"><Icon :name="kind.icon" :size="18" /></span>
        <span class="kind-copy">
          <b>{{ t(kind.titleKey) }}</b>
          <span>{{ t(kind.descKey) }}</span>
        </span>
        <Icon v-if="form.kind === kind.id" name="check" :size="15" class="kind-check" />
      </button>
    </div>

    <div class="divider" />

    <label class="label">{{ t('newTask.title') }}</label>
    <input v-model="form.title" class="field" :placeholder="t('newTask.titlePlaceholder')" @keydown.enter="create" />

    <label class="label" style="margin-top: 14px">{{ t('newTask.workspace') }}</label>
    <div class="row">
      <input v-model="form.workspace" class="field mono" style="font-size: 12px" :placeholder="t('newTask.workspacePlaceholder')" />
      <button class="btn" @click="showDir = true"><Icon name="folder" :size="15" /> {{ t('common.browse') }}</button>
    </div>
    <div class="ws-hint tiny">
      <span v-if="usingDefaultWorkspace" class="ws-default-badge">
        <Icon name="check" :size="12" /> {{ t('newTask.defaultBadge') }}
      </span>
      <button
        v-else-if="defaultWorkspace"
        type="button"
        class="ws-default-btn"
        @click="form.workspace = defaultWorkspace"
      >
        <Icon name="refresh" :size="12" /> {{ t('newTask.useDefault') }}
      </button>
      <span class="faint">{{ t('newTask.workspaceHint') }}</span>
    </div>

    <button class="advanced-toggle" @click="advanced = !advanced">
      <Icon :name="advanced ? 'chevron-down' : 'chevron-right'" :size="14" />
      {{ t('newTask.advanced') }}
      <span v-if="hasInheritedSettings" class="inherit-pill"><Icon name="refresh" :size="11" /> {{ t('newTask.inheritedBadge') }}</span>
    </button>

    <div v-if="advanced" class="advanced-grid">
      <div class="advanced-note tiny faint">
        <Icon name="refresh" :size="12" />
        <span>{{ hasInheritedSettings ? t('newTask.inheritedHint') : t('newTask.noInheritedHint') }}</span>
      </div>
      <div>
        <label class="label">{{ t('newTask.model') }}</label>
        <select class="select" :value="form.provider && form.model ? `${form.provider}|${form.model}` : ''" @change="onModelChange">
          <option value="">{{ t('newTask.autoRecommended') }}</option>
          <option v-for="option in modelOptions" :key="`${option.provider}|${option.model}`" :value="`${option.provider}|${option.model}`">
            {{ option.label }}
          </option>
        </select>
      </div>
      <div>
        <label class="label">{{ t('newTask.effort') }}</label>
        <select v-model="form.thinking" class="select">
          <option value="">{{ t('kind.auto') }}</option>
          <option value="off">{{ t('chat.noThinking') }}</option>
          <option value="low">{{ t('chat.low') }}</option>
          <option value="high">{{ t('chat.high') }}</option>
        </select>
      </div>
      <div>
        <label class="label">{{ t('newTask.gate') }}</label>
        <select v-model="form.gate_mode" class="select">
          <option value="">{{ t('newTask.globalSetting') }}</option>
          <option value="ask">{{ t('newTask.askWrites') }}</option>
          <option value="allow_all">{{ t('newTask.allowWrites') }}</option>
        </select>
      </div>
    </div>

    <div v-if="state.skills.length" style="margin-top: 16px">
      <label class="label">{{ t('newTask.skills') }}</label>
      <div class="skill-chips">
        <button
          v-for="skill in state.skills"
          :key="skill.name"
          class="skill-chip"
          :class="{ active: selectedSkills.has(skill.name) }"
          @click="toggleSkill(skill.name)"
        >
          <Icon name="sparkles" :size="12" />
          {{ skillTitle(skill) }}
        </button>
      </div>
    </div>

    <template #footer>
      <button class="btn" @click="emit('close')">{{ t('common.cancel') }}</button>
      <button class="btn primary" :disabled="submitting" @click="create">
        <span v-if="submitting" class="spinner" />
        <Icon v-else name="arrow-right" :size="15" />
        {{ t('newTask.create') }}
      </button>
    </template>
  </Modal>
  <DirPicker v-if="showDir" :initial="form.workspace" @close="showDir = false" @select="chooseDir" />
</template>

<style scoped>
.kind-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; }
.kind-card {
  position: relative; display: flex; align-items: flex-start; gap: 9px; text-align: left;
  padding: 12px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface-2);
  color: var(--ink-2); transition: all .15s var(--ease);
}
.kind-card:hover { border-color: var(--line-strong); }
.kind-card.active { border-color: var(--brand-line); background: var(--brand-soft); color: var(--ink); }
.kind-icon { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; background: var(--surface-3); color: var(--muted); flex: 0 0 30px; }
.kind-card.active .kind-icon { background: color-mix(in srgb, var(--brand) 16%, transparent); color: var(--brand); }
.kind-copy { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.kind-copy b { font-size: 13px; font-weight: 600; }
.kind-copy span { font-size: 11px; color: var(--faint); line-height: 1.35; }
.kind-check { position: absolute; right: 9px; top: 9px; color: var(--brand); }
.advanced-toggle { display: flex; align-items: center; gap: 6px; margin-top: 16px; border: none; background: transparent; color: var(--muted); font-size: 12px; padding: 0; }
.ws-hint { margin-top: 6px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ws-default-badge { display: inline-flex; align-items: center; gap: 4px; padding: 1px 8px; border-radius: 99px; background: var(--brand-soft); border: 1px solid var(--brand-line); color: var(--brand); font-size: 10.5px; }
.ws-default-btn { display: inline-flex; align-items: center; gap: 4px; padding: 0; border: none; background: transparent; color: var(--brand); font-size: 11px; }
.ws-default-btn:hover { text-decoration: underline; }
.inherit-pill { display: inline-flex; align-items: center; gap: 4px; margin-left: 4px; padding: 1px 7px; border-radius: 99px; background: var(--brand-soft); border: 1px solid var(--brand-line); color: var(--brand); font-size: 10px; font-weight: 520; }
.advanced-note { grid-column: 1 / -1; display: flex; align-items: center; gap: 5px; }
.advanced-toggle:hover { color: var(--ink); }
.advanced-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px; }
.skill-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.skill-chip { display: inline-flex; align-items: center; gap: 5px; padding: 5px 9px; border-radius: 99px; border: 1px solid var(--line); background: var(--surface-2); color: var(--muted); font-size: 11.5px; }
.skill-chip.active { border-color: var(--brand-line); background: var(--brand-soft); color: var(--brand); }
@media (max-width: 720px) {
  .kind-grid { grid-template-columns: repeat(2, 1fr); }
  .advanced-grid { grid-template-columns: 1fr; }
}
</style>
