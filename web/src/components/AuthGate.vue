<script setup>
import { computed, ref } from 'vue'
import { authSetupMode, dismissAccountSetup, loginAccount, setupAccount, state } from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const setup = computed(() => authSetupMode.value || state.authSetupOpen)
const username = ref('')
const password = ref('')
const confirm = ref('')
const show = ref(false)
const error = ref('')
const submitting = ref(false)
const skipping = ref(false)

async function submit() {
  error.value = ''
  const name = username.value.trim()
  if (!name || !password.value) {
    error.value = t('auth.required')
    return
  }
  if (setup.value && password.value !== confirm.value) {
    error.value = t('auth.passwordMismatch')
    return
  }
  if (setup.value && password.value.length < 6) {
    error.value = t('auth.passwordHint')
    return
  }
  submitting.value = true
  try {
    if (setup.value) await setupAccount(name, password.value)
    else await loginAccount(name, password.value)
  } catch (err) {
    error.value = err.message || t('common.error')
  } finally {
    submitting.value = false
  }
}

async function skip() {
  skipping.value = true
  try {
    await dismissAccountSetup()
  } finally {
    skipping.value = false
  }
}
</script>

<template>
  <div class="auth-screen">
    <div class="auth-aurora" />
    <div class="auth-shell">
      <aside class="auth-brand">
        <div class="auth-logo">
          <span class="brand-mark">H</span>
          <div>
            <b>{{ t('app.title') }}</b>
            <span>{{ t('app.tagline') }}</span>
          </div>
        </div>
        <div class="auth-copy">
          <span class="page-kicker">{{ t('auth.protected') }}</span>
          <h1>{{ setup ? t('auth.setupTitle') : t('auth.loginTitle') }}</h1>
          <p>{{ setup ? t('auth.setupSubtitle') : t('auth.loginSubtitle') }}</p>
        </div>
        <ul class="auth-points">
          <li><span class="point-icon"><Icon name="shield" :size="15" /></span><div><b>{{ t('auth.privacy') }}</b><span>{{ t('auth.privacyDesc') }}</span></div></li>
          <li><span class="point-icon"><Icon name="database" :size="15" /></span><div><b>{{ t('auth.localOnly') }}</b><span>{{ t('auth.localOnlyDesc') }}</span></div></li>
          <li><span class="point-icon"><Icon name="key" :size="15" /></span><div><b>{{ t('auth.noRecovery') }}</b><span>{{ t('auth.noRecoveryDesc') }}</span></div></li>
        </ul>
        <span class="auth-foot tiny">{{ t('auth.powered') }}</span>
      </aside>

      <section class="auth-card">
        <div class="auth-card-head">
          <span class="lock-badge"><Icon :name="setup ? 'sparkles' : 'lock'" :size="18" /></span>
          <div>
            <h2>{{ setup ? t('auth.createAccount') : t('auth.welcomeBack') }}</h2>
            <p>{{ setup ? t('auth.usernameHint') : t('auth.enterCredentials') }}</p>
          </div>
        </div>

        <form class="auth-form" @submit.prevent="submit">
          <label class="label" for="auth-username">{{ t('auth.username') }}</label>
          <div class="auth-field">
            <Icon name="user" :size="15" class="field-icon" />
            <input
              id="auth-username"
              v-model="username"
              class="field auth-input"
              :placeholder="t('auth.username')"
              autocomplete="username"
              :disabled="submitting"
            />
          </div>

          <label class="label" for="auth-password">{{ t('auth.password') }}</label>
          <div class="auth-field">
            <Icon name="lock" :size="15" class="field-icon" />
            <input
              id="auth-password"
              v-model="password"
              class="field auth-input"
              :type="show ? 'text' : 'password'"
              :placeholder="t('auth.password')"
              :autocomplete="setup ? 'new-password' : 'current-password'"
              :disabled="submitting"
            />
            <button type="button" class="eye-btn" :title="show ? t('auth.hidePassword') : t('auth.showPassword')" @click="show = !show">
              <Icon :name="show ? 'eye-off' : 'eye'" :size="15" />
            </button>
          </div>

          <template v-if="setup">
            <label class="label" for="auth-confirm">{{ t('auth.confirm') }}</label>
            <div class="auth-field">
              <Icon name="lock" :size="15" class="field-icon" />
              <input
                id="auth-confirm"
                v-model="confirm"
                class="field auth-input"
                :type="show ? 'text' : 'password'"
                :placeholder="t('auth.confirm')"
                autocomplete="new-password"
                :disabled="submitting"
              />
            </div>
          </template>

          <div v-if="error" class="auth-error"><Icon name="alert" :size="14" /> {{ error }}</div>

          <button class="btn primary lg auth-submit" type="submit" :disabled="submitting">
            <span v-if="submitting" class="spinner" style="width: 14px; height: 14px" />
            <Icon v-else :name="setup ? 'shield' : 'log-in'" :size="16" />
            {{ submitting ? (setup ? t('auth.settingUp') : t('auth.signingIn')) : (setup ? t('auth.setup') : t('auth.signIn')) }}
          </button>
        </form>

        <button v-if="setup" class="btn ghost auth-later" type="button" :disabled="skipping || submitting" @click="skip">
          <span v-if="skipping" class="spinner" style="width: 12px; height: 12px" />
          {{ t('auth.later') }}
        </button>
        <p class="auth-note tiny">{{ setup ? t('auth.setupNote') : t('auth.forgot') }}</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.auth-screen { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 24px; overflow-y: auto; background: radial-gradient(1100px 620px at 8% -10%, var(--aurora-1), transparent 60%), radial-gradient(900px 560px at 100% 0%, var(--aurora-2), transparent 55%), var(--bg); }
.auth-aurora { position: absolute; inset: 0; pointer-events: none; background: radial-gradient(600px 400px at 70% 110%, var(--aurora-3), transparent 60%); }
.auth-shell { position: relative; width: min(1000px, 100%); display: grid; grid-template-columns: 1.05fr .95fr; border: 1px solid var(--line-strong); border-radius: 26px; background: color-mix(in srgb, var(--surface) 86%, transparent); backdrop-filter: blur(22px); box-shadow: var(--shadow-soft); overflow: hidden; animation: slide-up .3s var(--ease); }
.auth-brand { padding: 34px; display: flex; flex-direction: column; gap: 26px; background: linear-gradient(155deg, color-mix(in srgb, var(--brand) 10%, transparent), transparent 55%); border-right: 1px solid var(--line); }
.auth-logo { display: flex; align-items: center; gap: 11px; }
.auth-logo .brand-mark { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; color: #fff; font-weight: 800; font-size: 18px; background: linear-gradient(140deg, var(--brand), var(--brand-2)); box-shadow: 0 10px 26px rgba(124, 108, 255, .3); }
.auth-logo b { display: block; font-size: 15px; }
.auth-logo span { display: block; font-size: 11.5px; color: var(--muted); }
.auth-copy h1 { margin: 0 0 8px; font-size: clamp(26px, 3vw, 34px); letter-spacing: -.04em; line-height: 1.12; }
.auth-copy p { margin: 0; color: var(--muted); font-size: 13px; max-width: 380px; }
.auth-points { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.auth-points li { display: flex; gap: 10px; align-items: flex-start; }
.point-icon { width: 30px; height: 30px; flex: 0 0 30px; border-radius: 9px; display: grid; place-items: center; background: var(--brand-soft); color: var(--brand); border: 1px solid var(--brand-line); }
.auth-points b { display: block; font-size: 12.5px; }
.auth-points span:not(.point-icon) { display: block; font-size: 11px; color: var(--faint); }
.auth-foot { margin-top: auto; color: var(--faint); letter-spacing: .08em; text-transform: uppercase; }
.auth-card { padding: 34px; display: flex; flex-direction: column; justify-content: center; gap: 18px; background: var(--surface); }
.auth-card-head { display: flex; align-items: center; gap: 11px; }
.lock-badge { width: 42px; height: 42px; flex: 0 0 42px; border-radius: 12px; display: grid; place-items: center; background: var(--brand-soft); color: var(--brand); border: 1px solid var(--brand-line); }
.auth-card-head h2 { margin: 0; font-size: 19px; letter-spacing: -.025em; }
.auth-card-head p { margin: 0; color: var(--muted); font-size: 11.5px; }
.auth-form { display: flex; flex-direction: column; gap: 7px; }
.auth-field { position: relative; display: flex; align-items: center; }
.field-icon { position: absolute; left: 11px; color: var(--faint); pointer-events: none; }
.auth-input { padding-left: 34px; height: 42px; }
.eye-btn { position: absolute; right: 6px; width: 30px; height: 30px; display: grid; place-items: center; border: none; background: transparent; color: var(--faint); border-radius: 7px; }
.eye-btn:hover { color: var(--ink); background: var(--surface-3); }
.auth-error { display: flex; align-items: center; gap: 6px; margin-top: 4px; padding: 8px 10px; border-radius: 9px; color: var(--bad); background: var(--bad-soft); font-size: 11.5px; border: 1px solid color-mix(in srgb, var(--bad) 25%, transparent); }
.auth-submit { width: 100%; margin-top: 8px; }
.auth-note { margin: 0; color: var(--faint); text-align: center; line-height: 1.6; }
.auth-later { width: 100%; color: var(--muted); font-size: 12px; }
@media (max-width: 820px) {
  .auth-shell { grid-template-columns: 1fr; }
  .auth-brand { display: none; }
  .auth-card { padding: 26px 22px; }
  .auth-screen { padding: 16px; }
}
</style>
