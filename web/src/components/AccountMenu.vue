<script setup>
import { computed } from 'vue'
import { state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const name = computed(() => state.auth.username || t('auth.account'))
const initial = computed(() => (state.auth.username || 'H').slice(0, 1).toUpperCase())
</script>

<template>
  <button class="account-menu" :title="t('auth.changeTitle')" @click="state.accountOpen = true">
    <span class="avatar-wrap">
      <span class="avatar">{{ initial }}</span>
      <span class="avatar-dot" />
    </span>
    <span class="account-copy">
      <b>{{ name }}</b>
      <span>{{ t('auth.protectedBadge') }}</span>
    </span>
    <Icon name="chevron-down" :size="13" class="account-caret" />
  </button>
</template>

<style scoped>
.account-menu {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  height: 38px;
  padding: 0 10px 0 5px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-2) 78%, transparent);
  color: var(--ink-2);
  transition: all .18s var(--ease);
}
.account-menu:hover {
  border-color: var(--brand-line);
  background: var(--brand-soft);
  box-shadow: 0 8px 24px color-mix(in srgb, var(--brand) 12%, transparent);
  transform: translateY(-1px);
}
.avatar-wrap { position: relative; width: 30px; height: 30px; flex: 0 0 30px; }
.avatar {
  width: 30px; height: 30px;
  display: grid; place-items: center;
  border-radius: 10px;
  background: linear-gradient(140deg, var(--brand), var(--brand-2));
  color: #fff;
  font-size: 12.5px;
  font-weight: 750;
  letter-spacing: -.02em;
  box-shadow: 0 6px 16px color-mix(in srgb, var(--brand) 32%, transparent);
}
.avatar-dot {
  position: absolute; right: -1px; bottom: -1px;
  width: 9px; height: 9px; border-radius: 50%;
  background: var(--good);
  border: 2px solid var(--surface);
}
.account-copy { display: flex; flex-direction: column; align-items: flex-start; line-height: 1.15; min-width: 0; max-width: 120px; }
.account-copy b { font-size: 11.5px; font-weight: 650; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 120px; }
.account-copy span { font-size: 9px; letter-spacing: .08em; text-transform: uppercase; color: var(--good); font-weight: 650; }
.account-caret { color: var(--faint); }
@media (max-width: 720px) {
  .account-copy, .account-caret { display: none; }
  .account-menu { padding: 0 4px; border-color: transparent; background: transparent; }
  .account-menu:hover { background: var(--brand-soft); }
}
</style>
