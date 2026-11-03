<script setup>
import { computed, ref } from 'vue'
import { changeAccount, logoutAccount, saveAuthPolicy, state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const emit = defineEmits(['close'])

const current = ref('')
const username = ref(state.auth.username || '')
const password = ref('')
const confirm = ref('')
const show = ref(false)
const loading = ref(false)
const error = ref('')
const maxFailures = ref(Number(state.auth.maxFailures) || 5)
const policySaving = ref(false)

const nameChanged = computed(() => username.value.trim() && username.value.trim() !== state.auth.username)

async function save() {
  error.value = ''
  if (!current.value) {
    error.value = t('auth.currentRequired')
    return
  }
  if (password.value && password.value !== confirm.value) {
    error.value = t('auth.passwordMismatch')
    return
  }
  if (password.value && password.value.length < 6) {
    error.value = t('auth.passwordHint')
    return
  }
  if (!nameChanged.value && !password.value) {
    error.value = t('auth.nothingChanged')
    return
  }
  loading.value = true
  try {
    await changeAccount({
      current_password: current.value,
      username: nameChanged.value ? username.value.trim() : '',
      new_password: password.value
    })
    emit('close')
  } catch (err) {
    error.value = err.message || t('common.error')
  } finally {
    loading.value = false
  }
}

async function savePolicy() {
  error.value = ''
  const value = Number(maxFailures.value)
  if (!Number.isInteger(value) || value < 1 || value > 20) {
    error.value = t('auth.policyRange')
    return
  }
  policySaving.value = true
  try {
    await saveAuthPolicy(value)
    maxFailures.value = value
  } catch (err) {
    error.value = err.message || t('common.error')
  } finally {
    policySaving.value = false
  }
}

async function signOut() {
  loading.value = true
  try {
    await logoutAccount()
    emit('close')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="modal account-modal">
      <div class="modal-head">
        <span class="account-avatar"><Icon name="user" :size="18" /></span>
        <div style="flex: 1; min-width: 0">
          <h3>{{ t('auth.changeTitle') }}</h3>
          <span class="tiny faint">{{ state.auth.username }}</span>
        </div>
        <span class="badge good"><Icon name="shield" :size="12" /> {{ t('auth.protectedBadge') }}</span>
        <button class="icon-btn" @click="emit('close')"><Icon name="close" :size="15" /></button>
      </div>

      <div class="modal-body account-body">
        <div class="account-banner">
          <span class="banner-icon"><Icon name="lock" :size="16" /></span>
          <div>
            <b>{{ t('auth.accountProtected') }}</b>
            <span>{{ t('auth.accountProtectedDesc') }}</span>
          </div>
        </div>

        <div class="policy-card">
          <div class="policy-head">
            <span class="policy-icon"><Icon name="shield" :size="16" /></span>
            <div>
              <b>{{ t('auth.policyTitle') }}</b>
              <span>{{ t('auth.policyDesc') }}</span>
            </div>
          </div>
          <div class="policy-row">
            <input id="ac-max" v-model.number="maxFailures" class="field policy-input" type="number" min="1" max="20" />
            <span class="tiny muted">{{ t('auth.attemptsUnit') }}</span>
            <span class="spacer" />
            <div class="policy-chips">
              <button
                v-for="n in [3, 5, 10]"
                :key="n"
                type="button"
                class="policy-chip"
                :class="{ active: Number(maxFailures) === n }"
                @click="maxFailures = n"
              >
                {{ n }}
              </button>
            </div>
            <button class="btn sm primary" :disabled="policySaving" @click="savePolicy">
              <span v-if="policySaving" class="spinner" style="width: 11px; height: 11px" />
              {{ t('auth.savePolicy') }}
            </button>
          </div>
        </div>

        <label class="label" for="ac-current">{{ t('auth.currentPassword') }}</label>
        <div class="account-field">
          <Icon name="lock" :size="15" class="field-icon" />
          <input
            id="ac-current"
            v-model="current"
            class="field account-input"
            :type="show ? 'text' : 'password'"
            :placeholder="t('auth.currentPassword')"
            autocomplete="current-password"
          />
          <button type="button" class="eye-btn" @click="show = !show">
            <Icon :name="show ? 'eye-off' : 'eye'" :size="15" />
          </button>
        </div>

        <div class="divider" />

        <label class="label" for="ac-name">{{ t('auth.newUsername') }}</label>
        <div class="account-field">
          <Icon name="user" :size="15" class="field-icon" />
          <input id="ac-name" v-model="username" class="field account-input" :placeholder="t('auth.username')" autocomplete="username" />
        </div>

        <label class="label" for="ac-pass">{{ t('auth.newPassword') }}</label>
        <div class="account-field">
          <Icon name="key" :size="15" class="field-icon" />
          <input
            id="ac-pass"
            v-model="password"
            class="field account-input"
            :type="show ? 'text' : 'password'"
            :placeholder="t('auth.leaveBlank')"
            autocomplete="new-password"
          />
        </div>

        <label class="label" for="ac-confirm">{{ t('auth.confirmNewPassword') }}</label>
        <div class="account-field">
          <Icon name="key" :size="15" class="field-icon" />
          <input
            id="ac-confirm"
            v-model="confirm"
            class="field account-input"
            :type="show ? 'text' : 'password'"
            :placeholder="t('auth.confirmNewPassword')"
            autocomplete="new-password"
          />
        </div>

        <div v-if="error" class="auth-error"><Icon name="alert" :size="14" /> {{ error }}</div>
      </div>

      <div class="modal-foot">
        <button class="btn danger" :disabled="loading" @click="signOut"><Icon name="log-out" :size="14" /> {{ t('auth.logout') }}</button>
        <span class="spacer" />
        <button class="btn" @click="emit('close')">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="loading" @click="save">
          <span v-if="loading" class="spinner" style="width: 12px; height: 12px" />
          {{ t('common.save') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.account-modal { width: min(520px, calc(100vw - 32px)); }
.account-avatar { width: 36px; height: 36px; flex: 0 0 36px; border-radius: 10px; display: grid; place-items: center; background: var(--brand-soft); color: var(--brand); border: 1px solid var(--brand-line); }
.account-body { display: flex; flex-direction: column; gap: 7px; }
.account-banner { display: flex; gap: 10px; align-items: center; padding: 11px 12px; border-radius: 11px; background: var(--good-soft); border: 1px solid color-mix(in srgb, var(--good) 24%, transparent); margin-bottom: 8px; }
.banner-icon { width: 32px; height: 32px; flex: 0 0 32px; border-radius: 9px; display: grid; place-items: center; background: color-mix(in srgb, var(--good) 14%, transparent); color: var(--good); }
.account-banner b { display: block; font-size: 12.5px; }
.account-banner span { display: block; font-size: 10.5px; color: var(--muted); }
.policy-card { padding: 12px; margin-bottom: 9px; border-radius: 12px; border: 1px solid var(--line); background: var(--surface-2); }
.policy-head { display: flex; align-items: center; gap: 9px; margin-bottom: 10px; }
.policy-icon { width: 32px; height: 32px; flex: 0 0 32px; border-radius: 9px; display: grid; place-items: center; background: var(--brand-soft); color: var(--brand); border: 1px solid var(--brand-line); }
.policy-head b { display: block; font-size: 12.5px; }
.policy-head span { display: block; font-size: 10.5px; color: var(--muted); }
.policy-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.policy-input { width: 68px; height: 32px; padding: 0 8px; text-align: center; font-family: var(--font-mono); font-weight: 650; }
.policy-chips { display: flex; gap: 4px; }
.policy-chip { height: 26px; padding: 0 9px; border-radius: 7px; border: 1px solid var(--line); background: var(--surface); color: var(--muted); font-size: 11px; }
.policy-chip:hover { border-color: var(--line-strong); color: var(--ink); }
.policy-chip.active { color: var(--brand); border-color: var(--brand-line); background: var(--brand-soft); }
.account-field { position: relative; display: flex; align-items: center; margin-bottom: 8px; }
.field-icon { position: absolute; left: 11px; color: var(--faint); pointer-events: none; }
.account-input { padding-left: 34px; height: 40px; }
.eye-btn { position: absolute; right: 6px; width: 30px; height: 30px; display: grid; place-items: center; border: none; background: transparent; color: var(--faint); border-radius: 7px; }
.eye-btn:hover { color: var(--ink); background: var(--surface-3); }
.auth-error { display: flex; align-items: center; gap: 6px; margin-top: 4px; padding: 8px 10px; border-radius: 9px; color: var(--bad); background: var(--bad-soft); font-size: 11.5px; border: 1px solid color-mix(in srgb, var(--bad) 25%, transparent); }
</style>
