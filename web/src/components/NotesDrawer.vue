<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api/client'
import { closeNotes, state, toast } from '../stores/app'
import { formatRelativeTime, t } from '../i18n'
import Icon from './Icon.vue'

const PAGE_SIZE_KEY = 'hy.notes.pageSize'
const PAGE_SIZES = [5, 8, 12, 20]
const MAX_CONTENT = 40000

const storedSize = Number(localStorage.getItem(PAGE_SIZE_KEY) || 8)
const pageSize = ref(PAGE_SIZES.includes(storedSize) ? storedSize : 8)
const page = ref(1)
const pages = ref(1)
const total = ref(0)
const items = ref([])
const query = ref('')
const loading = ref(false)
const error = ref('')
const editing = ref(null)
const confirmId = ref('')
const saving = ref(false)
const highlightId = ref('')
const listRef = ref(null)
const scrollRef = ref(null)
const titleRef = ref(null)

let loadToken = 0
let searchTimer = null
let deleteTimer = null
let autoTimer = null
let skipQueryWatch = false

const drag = reactive({
  active: false,
  started: false,
  note: null,
  sourcePage: 1,
  sourceIndex: -1,
  overIndex: null,
  x: 0,
  y: 0,
  startX: 0,
  startY: 0,
  width: 320,
  hint: '',
  autoDir: 0,
  turning: false
})

const open = computed(() => state.notesOpen)
const hasQuery = computed(() => query.value.trim().length > 0)
const canSave = computed(
  () => !!editing.value && !saving.value && (editing.value.title.trim() || editing.value.content.trim())
)
const dirty = computed(() => {
  const ed = editing.value
  return !!ed && (ed.title !== ed.originalTitle || ed.content !== ed.originalContent)
})
const showEmpty = computed(() => !loading.value && !error.value && items.value.length === 0)
const summaryLabel = computed(() =>
  hasQuery.value ? t('notes.searchResult', { n: total.value }) : t('notes.total', { n: total.value })
)
const dragStyle = computed(() => ({
  left: `${drag.x + 16}px`,
  top: `${Math.max(10, drag.y - 24)}px`,
  width: `${drag.width}px`
}))

async function load() {
  const token = ++loadToken
  loading.value = true
  error.value = ''
  try {
    const data = await api.notes(page.value, pageSize.value, query.value.trim())
    if (token !== loadToken) return
    items.value = data?.items || []
    total.value = Number(data?.total || 0)
    pages.value = Number(data?.pages || 1)
    page.value = Number(data?.page || 1)
  } catch (err) {
    if (token !== loadToken) return
    error.value = err?.message || t('notes.loadFailed')
  } finally {
    if (token === loadToken) loading.value = false
  }
}

watch(open, (value) => {
  if (value) {
    load()
  } else {
    editing.value = null
    confirmId.value = ''
    endDrag()
  }
})

watch(query, () => {
  if (skipQueryWatch) return
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    load()
  }, 280)
})

function goPage(target) {
  const next = Math.max(1, Math.min(pages.value, Number(target) || 1))
  if (next === page.value) return
  page.value = next
  load()
}

function onPageSizeChange() {
  localStorage.setItem(PAGE_SIZE_KEY, String(pageSize.value))
  page.value = 1
  load()
}

function beginCreate() {
  editing.value = { id: '', title: '', content: '', originalTitle: '', originalContent: '' }
  nextTick(() => titleRef.value?.focus())
}

function beginEdit(note) {
  if (drag.active) return
  confirmId.value = ''
  editing.value = {
    id: note.id,
    title: note.title || '',
    content: note.content || '',
    originalTitle: note.title || '',
    originalContent: note.content || ''
  }
  nextTick(() => titleRef.value?.focus())
}

function cancelEdit() {
  if (dirty.value && !window.confirm(t('notes.discard'))) return
  editing.value = null
}

function requestClose() {
  if (editing.value && dirty.value && !window.confirm(t('notes.discard'))) return
  editing.value = null
  endDrag()
  closeNotes()
}

async function save() {
  if (!canSave.value) return
  const ed = editing.value
  saving.value = true
  const payload = { title: ed.title.trim() || t('notes.untitled'), content: ed.content }
  try {
    if (ed.id) {
      await api.updateNote(ed.id, payload)
      toast(t('notes.saved'), 'good')
    } else {
      const created = await api.createNote(payload)
      toast(t('notes.created'), 'good')
      skipQueryWatch = true
      query.value = ''
      await nextTick()
      skipQueryWatch = false
      page.value = 1
      highlightId.value = created?.id || ''
      setTimeout(() => (highlightId.value = ''), 1800)
    }
    editing.value = null
    await load()
  } catch (err) {
    toast(err?.message || t('notes.loadFailed'), 'bad')
  } finally {
    saving.value = false
  }
}

function askDelete(note) {
  confirmId.value = note.id
  clearTimeout(deleteTimer)
  deleteTimer = setTimeout(() => (confirmId.value = ''), 4000)
}

async function remove(note) {
  clearTimeout(deleteTimer)
  confirmId.value = ''
  try {
    await api.deleteNote(note.id)
    toast(t('notes.deleted'), 'good')
    if (items.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (err) {
    toast(err?.message || t('notes.loadFailed'), 'bad')
  }
}

function onHandlePointerDown(event, note, index) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  if (hasQuery.value) {
    toast(t('notes.searchLocked'), 'info')
    return
  }
  if (items.value.length < 2) return
  if (loading.value) return
  const card = event.currentTarget.closest('[data-note-card]')
  if (!card) return
  const rect = card.getBoundingClientRect()
  Object.assign(drag, {
    active: true,
    started: false,
    note,
    sourcePage: page.value,
    sourceIndex: index,
    overIndex: index,
    x: event.clientX,
    y: event.clientY,
    startX: event.clientX,
    startY: event.clientY,
    width: Math.min(rect.width, 440),
    hint: '',
    autoDir: 0
  })
  window.addEventListener('pointermove', onPointerMove, { passive: false })
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointercancel', onPointerCancel)
}

function onPointerMove(event) {
  if (!drag.active) return
  drag.x = event.clientX
  drag.y = event.clientY
  if (!drag.started) {
    if (Math.abs(event.clientX - drag.startX) + Math.abs(event.clientY - drag.startY) < 5) return
    drag.started = true
    document.body.classList.add('notes-dragging')
  }
  event.preventDefault()
  updateDropIndex(event.clientY)
  scheduleAutoPage(event.clientY)
}

function updateDropIndex(y) {
  if (!listRef.value || drag.turning) return
  const cards = Array.from(listRef.value.querySelectorAll('[data-note-card]'))
  let index = cards.length
  for (let i = 0; i < cards.length; i += 1) {
    const rect = cards[i].getBoundingClientRect()
    if (y < rect.top + rect.height / 2) {
      index = i
      break
    }
  }
  drag.overIndex = index
}

function scheduleAutoPage(y) {
  const el = scrollRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const edge = Math.min(72, rect.height * 0.22)
  let dir = 0
  if (y < rect.top + edge && page.value > 1) dir = -1
  else if (y > rect.bottom - edge && page.value < pages.value) dir = 1
  if (dir !== drag.autoDir) {
    drag.autoDir = dir
    clearTimeout(autoTimer)
    if (dir) {
      drag.hint = dir < 0 ? t('notes.dragPrevPage') : t('notes.dragNextPage')
      autoTimer = setTimeout(() => {
        if (drag.active && drag.autoDir === dir) turnPage(dir)
      }, 700)
    } else {
      drag.hint = ''
    }
  }
}

async function turnPage(dir) {
  const target = page.value + dir
  if (target < 1 || target > pages.value) {
    drag.autoDir = 0
    drag.hint = ''
    return
  }
  drag.turning = true
  drag.overIndex = null
  page.value = target
  await load()
  drag.turning = false
  drag.overIndex = dir < 0 ? items.value.length : 0
  drag.hint = dir < 0 ? t('notes.pageSwitchedPrev') : t('notes.pageSwitchedNext')
}

async function onPointerUp() {
  if (!drag.active) return
  const wasStarted = drag.started
  const note = drag.note
  const over = drag.overIndex
  const sourcePage = drag.sourcePage
  const sourceIndex = drag.sourceIndex
  endDrag()
  if (!wasStarted || !note || over === null) return

  const base = (page.value - 1) * pageSize.value + over
  const sourceGlobal = (sourcePage - 1) * pageSize.value + sourceIndex
  const targetIndex = base - (sourceGlobal < base ? 1 : 0)
  if (targetIndex === sourceGlobal) return

  try {
    const result = await api.reorderNote(note.id, targetIndex)
    const resultIndex = Number(result?.target_index ?? targetIndex)
    const resultPage = Math.floor(resultIndex / pageSize.value) + 1
    highlightId.value = note.id
    if (resultPage !== page.value) {
      page.value = resultPage
      toast(t('notes.movedToPage', { page: resultPage }), 'good', 2200)
    } else {
      toast(t('notes.orderSaved'), 'good', 1800)
    }
    await load()
    setTimeout(() => (highlightId.value = ''), 1800)
  } catch (err) {
    toast(err?.message || t('notes.loadFailed'), 'bad')
    await load()
  }
}

function onPointerCancel() {
  endDrag()
}

function endDrag() {
  clearTimeout(autoTimer)
  drag.active = false
  drag.started = false
  drag.note = null
  drag.overIndex = null
  drag.hint = ''
  drag.autoDir = 0
  drag.turning = false
  document.body.classList.remove('notes-dragging')
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerCancel)
}

function onKeydown(event) {
  if (!open.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopImmediatePropagation()
    if (drag.active) endDrag()
    else if (editing.value) cancelEdit()
    else requestClose()
    return
  }
  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && editing.value) {
    event.preventDefault()
    event.stopImmediatePropagation()
    save()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown, true))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown, true)
  clearTimeout(searchTimer)
  clearTimeout(deleteTimer)
  endDrag()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="notes-fade">
      <div v-if="open" class="notes-backdrop" @click="requestClose" />
    </Transition>

    <Transition name="notes-slide">
      <aside v-if="open" class="notes-drawer" role="dialog" aria-modal="true" :aria-label="t('notes.title')">
        <header class="notes-head">
          <span class="notes-mark"><Icon name="document" :size="17" /></span>
          <div class="notes-head-text">
            <b>{{ t('notes.title') }}</b>
            <span>{{ t('notes.subtitle') }}</span>
          </div>
          <span class="notes-count">{{ t('notes.total', { n: total }) }}</span>
          <button class="icon-btn" :title="t('common.close')" @click="requestClose">
            <Icon name="close" :size="16" />
          </button>
        </header>

        <div v-if="editing" class="notes-editor">
          <div class="editor-bar">
            <button class="icon-btn" :title="t('common.cancel')" @click="cancelEdit">
              <Icon name="chevron-left" :size="17" />
            </button>
            <b>{{ editing.id ? t('notes.editTitle') : t('notes.createTitle') }}</b>
            <div class="spacer" />
            <button class="btn sm primary" :disabled="!canSave" @click="save">
              <span v-if="saving" class="spinner editor-spinner" />
              <Icon v-else name="check" :size="14" />
              {{ saving ? t('notes.saving') : t('common.save') }}
            </button>
          </div>
          <input
            ref="titleRef"
            v-model="editing.title"
            class="editor-title"
            maxlength="200"
            :placeholder="t('notes.titlePlaceholder')"
          />
          <textarea
            v-model="editing.content"
            class="editor-content"
            :maxlength="MAX_CONTENT"
            :placeholder="t('notes.contentPlaceholder')"
          />
          <div class="editor-foot">
            <span>{{ t('notes.keyboardHint') }}</span>
            <span class="mono">{{ t('notes.charCount', { n: editing.content.length, max: MAX_CONTENT }) }}</span>
          </div>
        </div>

        <template v-else>
          <div class="notes-toolbar">
            <div class="notes-search">
              <Icon name="search" :size="14" class="search-icon" />
              <input
                v-model="query"
                class="notes-search-input"
                :placeholder="t('notes.searchPlaceholder')"
                autocomplete="off"
              />
              <button v-if="hasQuery" class="icon-btn search-clear" :title="t('common.close')" @click="query = ''">
                <Icon name="close" :size="12" />
              </button>
            </div>
            <button class="btn primary notes-new-btn" @click="beginCreate">
              <Icon name="plus" :size="14" />
              <span>{{ t('notes.new') }}</span>
            </button>
          </div>

          <div class="notes-hint" :class="{ locked: hasQuery }">
            <Icon :name="hasQuery ? 'lock' : 'grip'" :size="12" />
            <span>{{ hasQuery ? t('notes.searchLocked') : t('notes.dragHint') }}</span>
          </div>

          <div ref="scrollRef" class="notes-scroll">
            <div v-if="loading && !items.length" class="notes-skeleton">
              <div v-for="i in 4" :key="i" class="skeleton sk-card" />
            </div>

            <div v-else-if="error" class="notes-empty">
              <span class="empty-icon"><Icon name="alert" :size="22" /></span>
              <b>{{ error }}</b>
              <button class="btn sm" @click="load">{{ t('common.refresh') }}</button>
            </div>

            <div v-else-if="showEmpty" class="notes-empty">
              <span class="empty-icon"><Icon :name="hasQuery ? 'search' : 'document'" :size="22" /></span>
              <b>{{ hasQuery ? t('notes.emptySearchTitle') : t('notes.emptyTitle') }}</b>
              <p>{{ hasQuery ? t('notes.emptySearchDesc') : t('notes.emptyDesc') }}</p>
              <button v-if="!hasQuery" class="btn sm primary" @click="beginCreate">
                <Icon name="plus" :size="13" />
                {{ t('notes.new') }}
              </button>
            </div>

            <div v-else ref="listRef" class="notes-list" :class="{ 'is-dragging': drag.active && drag.started }">
              <article
                v-for="(note, index) in items"
                :key="note.id"
                class="note-card"
                :class="{
                  dragging: drag.active && drag.note && drag.note.id === note.id,
                  'drop-before': drag.active && drag.started && drag.overIndex === index,
                  highlight: highlightId === note.id
                }"
                data-note-card
                @click="beginEdit(note)"
              >
                <button
                  type="button"
                  class="drag-handle"
                  :disabled="hasQuery"
                  :title="t('notes.dragHint')"
                  :aria-label="t('notes.dragHint')"
                  @pointerdown.stop.prevent="onHandlePointerDown($event, note, index)"
                  @click.stop
                >
                  <Icon name="grip" :size="14" />
                </button>

                <div class="note-body">
                  <div class="note-top">
                    <span class="note-title">{{ note.title || t('notes.untitled') }}</span>
                    <span class="note-time">{{ formatRelativeTime(note.updated_at) }}</span>
                  </div>
                  <p v-if="note.content" class="note-content">{{ note.content }}</p>
                  <p v-else class="note-content faint">—</p>
                </div>

                <div class="note-actions" @click.stop>
                  <template v-if="confirmId === note.id">
                    <button class="btn sm danger" @click="remove(note)">{{ t('notes.deleteConfirm') }}</button>
                    <button class="icon-btn" :title="t('common.cancel')" @click="confirmId = ''">
                      <Icon name="close" :size="12" />
                    </button>
                  </template>
                  <template v-else>
                    <button class="icon-btn" :title="t('common.edit')" @click="beginEdit(note)">
                      <Icon name="edit" :size="14" />
                    </button>
                    <button class="icon-btn danger-ghost" :title="t('common.delete')" @click="askDelete(note)">
                      <Icon name="trash" :size="14" />
                    </button>
                  </template>
                </div>
              </article>
              <div v-if="drag.active && drag.started && drag.overIndex === items.length" class="drop-end" />
            </div>
          </div>

          <footer class="notes-foot">
            <div class="foot-info">
              <span class="foot-summary">{{ summaryLabel }}</span>
              <label class="page-size">
                <span>{{ t('notes.pageSize') }}</span>
                <select v-model.number="pageSize" @change="onPageSizeChange">
                  <option v-for="size in PAGE_SIZES" :key="size" :value="size">{{ size }}</option>
                </select>
              </label>
            </div>
            <div class="pager">
              <button class="icon-btn" :title="t('notes.prevPage')" :disabled="page <= 1" @click="goPage(page - 1)">
                <Icon name="chevron-left" :size="15" />
              </button>
              <span class="page-pill">{{ page }} / {{ pages }}</span>
              <button
                class="icon-btn"
                :title="t('notes.nextPage')"
                :disabled="page >= pages"
                @click="goPage(page + 1)"
              >
                <Icon name="chevron-right" :size="15" />
              </button>
            </div>
          </footer>
        </template>
      </aside>
    </Transition>

    <div v-if="open && drag.active && drag.started" class="notes-drag-ghost" :style="dragStyle">
      <Icon name="grip" :size="14" />
      <span class="truncate">{{ drag.note?.title || t('notes.untitled') }}</span>
    </div>

    <Transition name="notes-fade">
      <div v-if="open && drag.active && drag.started && drag.hint" class="notes-drag-toast">
        <Icon name="layers" :size="14" />
        <span>{{ drag.hint }}</span>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.notes-backdrop {
  position: fixed;
  inset: 0;
  z-index: 98;
  background: rgba(4, 6, 10, 0.34);
  backdrop-filter: blur(2px);
}
.notes-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 99;
  width: min(448px, 100vw);
  display: flex;
  flex-direction: column;
  background:
    radial-gradient(420px 260px at 100% 0%, color-mix(in srgb, var(--brand) 10%, transparent), transparent 62%),
    linear-gradient(180deg, var(--surface), color-mix(in srgb, var(--surface) 88%, var(--bg-2)));
  border-left: 1px solid var(--line-strong);
  box-shadow: -28px 0 80px rgba(0, 0, 0, 0.34);
}
.notes-head {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 16px 16px 14px 18px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 62%, transparent);
  backdrop-filter: blur(16px);
}
.notes-mark {
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: #fff;
  background: linear-gradient(140deg, var(--brand), var(--brand-2));
  box-shadow: 0 8px 22px color-mix(in srgb, var(--brand) 34%, transparent);
}
.notes-head-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.notes-head-text b {
  font-size: 14.5px;
  letter-spacing: -0.015em;
}
.notes-head-text span {
  font-size: 10.5px;
  color: var(--faint);
  letter-spacing: 0.03em;
}
.notes-count {
  margin-left: auto;
  height: 22px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  border-radius: 99px;
  border: 1px solid var(--brand-line);
  background: var(--brand-soft);
  color: var(--brand);
  font-size: 10.5px;
  font-weight: 600;
  white-space: nowrap;
}
.notes-toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px 8px 18px;
}
.notes-search {
  position: relative;
  flex: 1;
  min-width: 0;
}
.search-icon {
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--faint);
  pointer-events: none;
}
.notes-search-input {
  width: 100%;
  height: 36px;
  padding: 0 32px 0 32px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--ink);
  outline: none;
  font-size: 12.5px;
  transition: border-color 0.15s var(--ease), box-shadow 0.15s var(--ease);
}
.notes-search-input:focus {
  border-color: var(--brand-line);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.notes-search-input::placeholder {
  color: var(--faint);
}
.search-clear {
  position: absolute;
  right: 5px;
  top: 50%;
  transform: translateY(-50%);
  width: 24px;
  height: 24px;
}
.notes-new-btn {
  height: 36px;
  border-radius: 10px;
  padding: 0 12px;
  flex: 0 0 auto;
}
.notes-hint {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 18px 8px;
  font-size: 10.5px;
  color: var(--faint);
}
.notes-hint.locked {
  color: var(--warn);
}
.notes-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 2px 12px 14px 14px;
  overscroll-behavior: contain;
}
.notes-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-height: 100%;
}
.note-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 11px 10px 11px 7px;
  border-radius: 13px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 70%, transparent);
  cursor: pointer;
  transition: border-color 0.16s var(--ease), background 0.16s var(--ease), transform 0.16s var(--ease),
    box-shadow 0.16s var(--ease);
}
.note-card:hover {
  border-color: var(--line-strong);
  background: var(--surface-2);
  box-shadow: 0 10px 26px rgba(0, 0, 0, 0.14);
}
.note-card.dragging {
  opacity: 0.38;
  border-color: var(--brand-line);
  border-style: dashed;
  background: var(--brand-soft);
}
.note-card.highlight {
  animation: note-flash 1.8s var(--ease);
}
.note-card.drop-before::before {
  content: "";
  position: absolute;
  left: 10px;
  right: 10px;
  top: -4px;
  height: 3px;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--brand), var(--brand-2));
  box-shadow: 0 0 12px color-mix(in srgb, var(--brand) 70%, transparent);
}
.drop-end {
  height: 3px;
  margin: 2px 10px 0;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--brand), var(--brand-2));
  box-shadow: 0 0 12px color-mix(in srgb, var(--brand) 70%, transparent);
}
.drag-handle {
  width: 24px;
  height: 30px;
  flex: 0 0 24px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--faint);
  cursor: grab;
  touch-action: none;
  transition: background 0.15s var(--ease), color 0.15s var(--ease);
}
.drag-handle:hover:not(:disabled) {
  background: var(--surface-3);
  color: var(--ink-2);
}
.drag-handle:disabled {
  cursor: not-allowed;
  opacity: 0.35;
}
.note-body {
  flex: 1;
  min-width: 0;
}
.note-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.note-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-weight: 620;
  letter-spacing: -0.01em;
  color: var(--ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.note-time {
  flex: 0 0 auto;
  font-size: 10px;
  color: var(--faint);
}
.note-content {
  margin: 4px 0 0;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
  word-break: break-word;
}
.note-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transform: translateX(4px);
  transition: opacity 0.15s var(--ease), transform 0.15s var(--ease);
}
.note-card:hover .note-actions,
.note-card:focus-within .note-actions {
  opacity: 1;
  transform: translateX(0);
}
.note-actions .icon-btn {
  width: 26px;
  height: 26px;
}
.note-actions .icon-btn.danger-ghost:hover {
  color: var(--bad);
  background: var(--bad-soft);
  border-color: color-mix(in srgb, var(--bad) 28%, transparent);
}
.note-actions .btn.sm {
  height: 26px;
  padding: 0 9px;
}
.notes-skeleton {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sk-card {
  height: 66px;
  border-radius: 13px;
}
.notes-empty {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 34px 20px;
  text-align: center;
}
.notes-empty .empty-icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 15px;
  border: 1px dashed var(--line-strong);
  background: color-mix(in srgb, var(--surface-2) 60%, transparent);
  color: var(--faint);
  margin-bottom: 4px;
}
.notes-empty b {
  font-size: 13.5px;
  color: var(--ink);
}
.notes-empty p {
  margin: 0 0 8px;
  font-size: 11.5px;
  color: var(--muted);
  max-width: 260px;
}
.notes-foot {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px 12px 18px;
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 60%, transparent);
  backdrop-filter: blur(14px);
}
.foot-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  font-size: 10.5px;
  color: var(--muted);
}
.foot-summary {
  white-space: nowrap;
}
.page-size {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.page-size select {
  height: 26px;
  padding: 0 22px 0 8px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--ink-2);
  font-size: 11px;
  outline: none;
}
.pager {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}
.pager .icon-btn {
  width: 28px;
  height: 28px;
}
.pager .icon-btn:disabled {
  opacity: 0.32;
  cursor: not-allowed;
}
.page-pill {
  min-width: 54px;
  height: 26px;
  padding: 0 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--ink-2);
  font-size: 10.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.notes-editor {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 18px 14px;
}
.editor-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
}
.editor-bar b {
  font-size: 13.5px;
  letter-spacing: -0.01em;
}
.editor-spinner {
  width: 12px;
  height: 12px;
  border-width: 2px;
}
.editor-title {
  width: 100%;
  border: none;
  background: transparent;
  color: var(--ink);
  font-size: 21px;
  font-weight: 680;
  letter-spacing: -0.03em;
  padding: 4px 2px 8px;
  outline: none;
  border-bottom: 1px solid var(--line);
}
.editor-title::placeholder {
  color: var(--faint);
  font-weight: 600;
}
.editor-content {
  flex: 1;
  min-height: 0;
  width: 100%;
  resize: none;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface-2);
  color: var(--ink-2);
  padding: 12px 13px;
  font-size: 13px;
  line-height: 1.7;
  outline: none;
  transition: border-color 0.15s var(--ease), box-shadow 0.15s var(--ease);
}
.editor-content:focus {
  border-color: var(--brand-line);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.editor-content::placeholder {
  color: var(--faint);
}
.editor-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 10.5px;
  color: var(--faint);
}
.notes-drag-ghost {
  position: fixed;
  z-index: 105;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-radius: 11px;
  border: 1px solid var(--brand-line);
  background: var(--elevated);
  color: var(--ink);
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.36), 0 0 0 3px var(--brand-soft);
  font-size: 12.5px;
  font-weight: 600;
  pointer-events: none;
  transform: rotate(1.2deg);
}
.notes-drag-ghost .icon {
  color: var(--brand);
}
.notes-drag-toast {
  position: fixed;
  left: 50%;
  bottom: 28px;
  z-index: 106;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 14px;
  border-radius: 99px;
  border: 1px solid var(--brand-line);
  background: var(--elevated);
  color: var(--ink-2);
  font-size: 11.5px;
  font-weight: 560;
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.3);
  pointer-events: none;
}
.notes-drag-toast .icon {
  color: var(--brand);
}

.notes-fade-enter-active,
.notes-fade-leave-active {
  transition: opacity 0.2s var(--ease);
}
.notes-fade-enter-from,
.notes-fade-leave-to {
  opacity: 0;
}
.notes-slide-enter-active,
.notes-slide-leave-active {
  transition: transform 0.28s var(--ease), opacity 0.22s var(--ease);
}
.notes-slide-enter-from,
.notes-slide-leave-to {
  transform: translateX(28px);
  opacity: 0;
}

@keyframes note-flash {
  0% {
    border-color: var(--brand);
    box-shadow: 0 0 0 4px var(--brand-soft);
  }
  100% {
    border-color: var(--line);
    box-shadow: none;
  }
}

@media (max-width: 640px) {
  .notes-drawer {
    width: 100vw;
    border-left: none;
  }
  .notes-head {
    padding: 14px 14px 12px;
  }
  .notes-toolbar {
    padding: 12px 14px 8px;
  }
  .notes-hint {
    padding: 0 14px 8px;
  }
  .notes-scroll {
    padding: 2px 10px 12px;
  }
  .notes-foot {
    padding: 10px 12px 12px;
  }
  .note-actions {
    opacity: 1;
    transform: none;
  }
  .notes-new-btn span {
    display: none;
  }
  .notes-new-btn {
    padding: 0 10px;
  }
}
</style>

<style>
body.notes-dragging,
body.notes-dragging * {
  cursor: grabbing !important;
  user-select: none !important;
}
</style>
