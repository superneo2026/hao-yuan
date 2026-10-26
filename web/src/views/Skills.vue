<script setup>
import { computed, onMounted, ref } from 'vue'
import { deleteSkill, loadSkills, saveSkill, state, toast } from '../stores/app'
import { kindLabel, skillDescription, skillTitle, t } from '../i18n'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'

const query = ref('')
const filter = ref('all')
const editing = ref(null)
const saving = ref(false)

const filtered = computed(() => {
  const search = query.value.trim().toLowerCase()
  return state.skills.filter((skill) => {
    if (filter.value !== 'all' && !skill.kinds.includes(filter.value) && !skill.kinds.includes('*')) return false
    if (!search) return true
    return `${skill.name} ${skill.title} ${skill.description} ${(skill.triggers || []).join(' ')}`.toLowerCase().includes(search)
  })
})

function blank() {
  return { name: '', title: '', description: '', kinds: ['dev'], triggersText: '', body: '' }
}

function openNew() {
  editing.value = { ...blank(), isNew: true }
}

function openEdit(skill) {
  editing.value = {
    ...skill,
    isNew: false,
    triggersText: (skill.triggers || []).join(', '),
    body: '',
    originalName: skill.name
  }
  import('../api/client').then(({ api }) => {
    api.skill(skill.name).then((full) => {
      if (editing.value) editing.value.body = full.body || ''
    })
  })
}

async function save() {
  const form = editing.value
  if (!form || saving.value) return
  saving.value = true
  try {
    await saveSkill(
      {
        name: form.name,
        title: form.title,
        description: form.description,
        kinds: form.kinds,
        triggers: form.triggersText.split(',').map((item) => item.trim()).filter(Boolean),
        body: form.body
      },
      form.isNew ? '' : form.originalName
    )
    editing.value = null
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    saving.value = false
  }
}

async function remove() {
  if (!editing.value) return
  if (!window.confirm(t('skills.deleteConfirm', { title: editing.value.title }))) return
  try {
    await deleteSkill(editing.value.originalName || editing.value.name)
    editing.value = null
  } catch (error) {
    toast(error.message, 'bad')
  }
}

function toggleKind(kind) {
  if (!editing.value) return
  const set = new Set(editing.value.kinds)
  if (kind === '*') editing.value.kinds = set.has('*') ? [] : ['*']
  else {
    set.delete('*')
    if (set.has(kind)) set.delete(kind)
    else set.add(kind)
    editing.value.kinds = [...set]
  }
}

onMounted(() => loadSkills())
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <div class="page-kicker">{{ t('skills.kicker') }}</div>
        <h1>{{ t('skills.title') }}</h1>
        <p>{{ t('skills.subtitle') }}</p>
      </div>
      <button class="btn primary" @click="openNew"><Icon name="plus" :size="15" /> {{ t('skills.new') }}</button>
    </header>

    <div class="filter-row">
      <input v-model="query" class="field" style="max-width: 320px" :placeholder="t('skills.search')" />
      <div class="row" style="gap: 4px">
        <button v-for="kind in ['all', 'dev', 'plan', 'video', '*']" :key="kind" class="filter-btn" :class="{ active: filter === kind }" @click="filter = kind">
          {{ kind === 'all' ? t('skills.all') : kind === '*' ? t('skills.global') : kindLabel(kind) }}
        </button>
      </div>
      <span class="spacer" />
      <span class="badge">{{ t('skills.count', { n: filtered.length }) }}</span>
    </div>

    <div class="skill-grid">
      <article v-for="skill in filtered" :key="skill.name" class="skill-card" @click="openEdit(skill)">
        <div class="skill-head">
          <span class="skill-icon"><Icon name="sparkles" :size="16" /></span>
          <div class="skill-title-block">
            <h3>{{ skillTitle(skill) }}</h3>
            <span class="mono tiny faint">{{ skill.name }}</span>
          </div>
          <span class="badge" :class="skill.source === 'core' ? 'brand' : ''">{{ t(`source.${skill.source}`, {}, skill.source) }}</span>
        </div>
        <p>{{ skillDescription(skill) || t('skills.noDescription') }}</p>
        <div class="skill-tags">
          <span v-for="kind in skill.kinds" :key="kind" class="badge">{{ kind === '*' ? t('skills.global') : kindLabel(kind) }}</span>
          <span class="tiny faint">{{ t('common.chars', { n: skill.chars }) }}</span>
        </div>
        <div v-if="skill.triggers?.length" class="skill-triggers">
          <Icon name="zap" :size="11" /> {{ skill.triggers.slice(0, 6).join(' · ') }}
        </div>
      </article>
      <button class="skill-card add-card" @click="openNew">
        <Icon name="plus" :size="20" />
        <b>{{ t('skills.create') }}</b>
        <span>{{ t('skills.createDesc') }}</span>
      </button>
    </div>

    <Modal v-if="editing" :title="editing.isNew ? t('skills.newTitle') : t('skills.editTitle')" :subtitle="t('skills.savedAs')" width="760px" @close="editing = null">
      <div class="form-grid">
        <div>
          <label class="label">{{ t('common.name') }}</label>
          <input v-model="editing.name" class="field mono" :disabled="!editing.isNew" :placeholder="t('skills.namePlaceholder')" />
        </div>
        <div>
          <label class="label">{{ t('common.title') }}</label>
          <input v-model="editing.title" class="field" :placeholder="t('skills.titlePlaceholder')" />
        </div>
      </div>
      <label class="label" style="margin-top: 12px">{{ t('common.description') }}</label>
      <input v-model="editing.description" class="field" :placeholder="t('skills.descPlaceholder')" />
      <label class="label" style="margin-top: 12px">{{ t('skills.kinds') }}</label>
      <div class="row wrap" style="gap: 5px">
        <button v-for="kind in ['*', 'dev', 'plan', 'video']" :key="kind" class="kind-chip" :class="{ active: editing.kinds.includes(kind) }" @click="toggleKind(kind)">
          {{ kind === '*' ? t('skills.global') : kindLabel(kind) }}
        </button>
      </div>
      <label class="label" style="margin-top: 12px">{{ t('skills.triggers') }}</label>
      <input v-model="editing.triggersText" class="field" :placeholder="t('skills.triggersPlaceholder')" />
      <label class="label" style="margin-top: 12px">{{ t('skills.methodology') }}</label>
      <textarea v-model="editing.body" class="textarea mono" rows="14" style="font-size: 12px" :placeholder="t('skills.bodyPlaceholder')" />
      <template #footer>
        <button v-if="!editing.isNew && editing.source === 'core'" class="btn danger" @click="remove"><Icon name="trash" :size="14" /> {{ t('common.delete') }}</button>
        <span class="spacer" />
        <button class="btn" @click="editing = null">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="saving" @click="save">
          <span v-if="saving" class="spinner" /> {{ t('skills.save') }}
        </button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.filter-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }
.filter-btn { height: 29px; padding: 0 11px; border-radius: 8px; border: 1px solid transparent; background: transparent; color: var(--muted); font-size: 12px; }
.filter-btn.active { background: var(--brand-soft); border-color: var(--brand-line); color: var(--brand); }
.skill-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.skill-card { display: flex; flex-direction: column; gap: 9px; padding: 15px; background: var(--surface); border: 1px solid var(--line); border-radius: 15px; text-align: left; color: var(--ink-2); cursor: pointer; transition: all .16s var(--ease); }
.skill-card:hover { border-color: var(--brand-line); transform: translateY(-2px); box-shadow: var(--shadow-card); }
.skill-head { display: flex; align-items: flex-start; gap: 9px; }
.skill-icon { width: 32px; height: 32px; border-radius: 9px; background: var(--brand-soft); color: var(--brand); display: grid; place-items: center; flex: 0 0 32px; }
.skill-title-block { min-width: 0; flex: 1; }
.skill-title-block h3 { margin: 0; font-size: 13.5px; letter-spacing: -.01em; }
.skill-card p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.55; min-height: 36px; }
.skill-tags { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.skill-triggers { display: flex; align-items: center; gap: 5px; color: var(--faint); font-size: 10.5px; border-top: 1px solid var(--line); padding-top: 8px; }
.add-card { align-items: center; justify-content: center; text-align: center; border-style: dashed; min-height: 180px; color: var(--muted); }
.add-card b { color: var(--ink-2); font-size: 13px; }
.add-card span { font-size: 11.5px; max-width: 220px; }
.add-card:hover { color: var(--brand); }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.kind-chip { padding: 4px 10px; border-radius: 99px; border: 1px solid var(--line); background: var(--surface-2); color: var(--muted); font-size: 11.5px; }
.kind-chip.active { border-color: var(--brand-line); background: var(--brand-soft); color: var(--brand); }
@media (max-width: 640px) { .form-grid { grid-template-columns: 1fr; } }
</style>
