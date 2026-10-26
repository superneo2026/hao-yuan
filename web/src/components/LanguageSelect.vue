<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { i18n, localeOptions, setLocale, t } from '../i18n'
import Icon from './Icon.vue'

const props = defineProps({
  compact: { type: Boolean, default: false },
  dropUp: { type: Boolean, default: false }
})

const open = ref(false)
const root = ref(null)
const current = computed(() => localeOptions.find((item) => item.id === i18n.locale) || localeOptions[0])

function choose(id) {
  setLocale(id)
  open.value = false
}

function onDocumentClick(event) {
  if (root.value && !root.value.contains(event.target)) open.value = false
}

onMounted(() => document.addEventListener('mousedown', onDocumentClick))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocumentClick))
</script>

<template>
  <div ref="root" class="language-select" :class="{ compact }">
    <button class="lang-button" :title="t('nav.language')" @click="open = !open">
      <Icon name="globe" :size="15" />
      <span v-if="!compact" class="lang-label">{{ current.label }}</span>
      <span v-else class="lang-short">{{ current.short }}</span>
      <Icon name="chevron-down" :size="11" class="lang-caret" />
    </button>
    <div v-if="open" class="lang-menu" :class="{ up: dropUp }">
      <button
        v-for="option in localeOptions"
        :key="option.id"
        class="lang-option"
        :class="{ active: option.id === i18n.locale }"
        @click="choose(option.id)"
      >
        <span class="lang-option-short">{{ option.short }}</span>
        <span class="lang-option-label">{{ option.label }}</span>
        <Icon v-if="option.id === i18n.locale" name="check" :size="14" class="lang-check" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.language-select { position: relative; }
.lang-button {
  display: inline-flex; align-items: center; gap: 6px;
  height: 28px; padding: 0 8px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--surface-2); color: var(--muted);
  font-size: 11.5px; transition: all .15s var(--ease); white-space: nowrap;
}
.lang-button:hover { color: var(--ink); border-color: var(--line-strong); background: var(--surface-3); }
.lang-short { font-weight: 650; font-size: 10.5px; letter-spacing: .02em; }
.lang-caret { color: var(--faint); }
.lang-menu {
  position: absolute; right: 0; top: calc(100% + 6px); z-index: 90;
  min-width: 158px; padding: 5px;
  background: var(--elevated); border: 1px solid var(--line-strong);
  border-radius: 11px; box-shadow: var(--shadow-soft);
  animation: slide-up .14s var(--ease);
}
.lang-menu.up { top: auto; bottom: calc(100% + 6px); }
.lang-option {
  width: 100%; display: flex; align-items: center; gap: 8px;
  padding: 7px 8px; border-radius: 7px; border: none; background: transparent;
  color: var(--ink-2); text-align: left; font-size: 12px;
}
.lang-option:hover { background: var(--surface-2); color: var(--ink); }
.lang-option.active { background: var(--brand-soft); color: var(--brand); }
.lang-option-short {
  width: 24px; height: 20px; border-radius: 5px; display: grid; place-items: center;
  background: var(--surface-3); color: var(--muted); font-size: 9.5px; font-weight: 650;
}
.lang-option.active .lang-option-short { background: color-mix(in srgb, var(--brand) 15%, transparent); color: var(--brand); }
.lang-option-label { flex: 1; }
.lang-check { color: var(--brand); }
.compact .lang-button { width: 32px; justify-content: center; padding: 0; }
.compact .lang-caret { display: none; }
@media (max-width: 860px) {
  .lang-label, .lang-caret { display: none; }
  .lang-button { width: 32px; justify-content: center; padding: 0; }
}
@media (max-width: 640px) {
  .lang-button { width: 44px; gap: 4px; }
}
</style>
