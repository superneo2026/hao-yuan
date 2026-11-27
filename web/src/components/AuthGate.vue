<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  authSetupMode,
  dismissAccountSetup,
  loginAccount,
  requestPasswordRecovery,
  resetAccountPassword,
  setupAccount,
  state
} from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const setup = computed(() => authSetupMode.value || state.authSetupOpen)
const view = ref('auth')
const username = ref('')
const email = ref('')
const password = ref('')
const confirm = ref('')
const show = ref(false)
const error = ref('')
const submitting = ref(false)
const skipping = ref(false)
const attemptsLeft = ref(null)
const lockSeconds = ref(0)
const unlocked = ref(false)
let lockTimer = null

const recoverIdentity = ref('')
const recoverCode = ref('')
const recoverPassword = ref('')
const recoverConfirm = ref('')
const recoverStep = ref('request')
const recoverMasked = ref('')
const recoverNotice = ref('')
const recoverSending = ref(false)
const recoverResetting = ref(false)
const resendSeconds = ref(0)
let resendTimer = null

const recovering = computed(() => !setup.value && view.value === 'recover')
const emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

const lockCountdown = computed(() => {
  const total = Math.max(0, lockSeconds.value)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})

const maxAttempts = computed(() => Math.max(1, Number(state.auth.maxFailures) || 5))

function stopLockTimer() {
  if (lockTimer) {
    clearInterval(lockTimer)
    lockTimer = null
  }
}

function startLock(seconds) {
  stopLockTimer()
  error.value = ''
  unlocked.value = false
  attemptsLeft.value = 0
  lockSeconds.value = Math.max(1, Math.floor(seconds || 300))
  lockTimer = setInterval(() => {
    lockSeconds.value = Math.max(0, lockSeconds.value - 1)
    if (lockSeconds.value <= 0) {
      stopLockTimer()
      attemptsLeft.value = null
      unlocked.value = true
      password.value = ''
    }
  }, 1000)
}

function stopResend() {
  if (resendTimer) {
    clearInterval(resendTimer)
    resendTimer = null
  }
}

function startResend(seconds) {
  stopResend()
  resendSeconds.value = Math.max(0, Math.floor(seconds || 0))
  if (resendSeconds.value <= 0) return
  resendTimer = setInterval(() => {
    resendSeconds.value = Math.max(0, resendSeconds.value - 1)
    if (resendSeconds.value <= 0) stopResend()
  }, 1000)
}

async function submit() {
  if (submitting.value || lockSeconds.value > 0) return
  error.value = ''
  unlocked.value = false
  const name = username.value.trim()
  if (!name || !password.value) {
    error.value = t('auth.required')
    return
  }
  const mail = email.value.trim()
  if (setup.value && !emailPattern.test(mail)) {
    error.value = t('auth.recoveryEmailInvalid')
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
    if (setup.value) await setupAccount(name, password.value, mail)
    else await loginAccount(name, password.value)
  } catch (err) {
    const data = err.data || {}
    if (data.locked || data.retry_after) {
      startLock(data.retry_after || 300)
    } else if (data.remaining_attempts !== undefined) {
      attemptsLeft.value = data.remaining_attempts
      error.value = t('auth.attemptsLeft', { n: data.remaining_attempts })
    } else {
      error.value = err.message || t('common.error')
    }
  } finally {
    submitting.value = false
  }
}

function openRecover() {
  error.value = ''
  recoverNotice.value = ''
  recoverCode.value = ''
  recoverPassword.value = ''
  recoverConfirm.value = ''
  recoverMasked.value = ''
  recoverStep.value = 'request'
  recoverIdentity.value = username.value.trim()
  view.value = 'recover'
}

function backToLogin() {
  error.value = ''
  recoverNotice.value = ''
  stopResend()
  view.value = 'auth'
}

async function requestCode() {
  if (recoverSending.value || resendSeconds.value > 0) return
  error.value = ''
  recoverNotice.value = ''
  const identity = recoverIdentity.value.trim()
  if (!identity) {
    error.value = t('auth.required')
    return
  }
  recoverSending.value = true
  try {
    const data = await requestPasswordRecovery(identity)
    recoverMasked.value = data.email || ''
    recoverStep.value = 'confirm'
    recoverNotice.value = t('auth.recoverSent', { email: data.email || '' })
    startResend(data.resend_after || 60)
  } catch (err) {
    const data = err.data || {}
    if (data.reason === 'email_not_configured') error.value = t('auth.recoverNotConfigured')
    else if (data.reason === 'no_recovery_email') error.value = t('auth.recoverNoEmail')
    else if (data.reason === 'mismatch') error.value = t('auth.recoverMismatch')
    else error.value = err.message || t('common.error')
    if (data.retry_after) startResend(data.retry_after)
  } finally {
    recoverSending.value = false
  }
}

async function resetPassword() {
  if (recoverResetting.value) return
  error.value = ''
  if (!recoverCode.value.trim()) {
    error.value = t('auth.recoverCodeRequired')
    return
  }
  if (recoverPassword.value.length < 6) {
    error.value = t('auth.passwordHint')
    return
  }
  if (recoverPassword.value !== recoverConfirm.value) {
    error.value = t('auth.passwordMismatch')
    return
  }
  recoverResetting.value = true
  try {
    await resetAccountPassword(recoverCode.value.trim(), recoverPassword.value)
  } catch (err) {
    const data = err.data || {}
    if (data.reason === 'expired') error.value = t('auth.recoverCodeExpired')
    else if (data.reason === 'too_many') error.value = t('auth.recoverTooMany')
    else if (data.reason === 'email_not_configured') error.value = t('auth.recoverNotConfigured')
    else if (data.remaining_attempts !== undefined) error.value = t('auth.recoverCodeInvalid', { n: data.remaining_attempts })
    else error.value = err.message || t('common.error')
  } finally {
    recoverResetting.value = false
  }
}

onBeforeUnmount(() => {
  stopLockTimer()
  stopResend()
})

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
          <h1>{{ setup ? t('auth.setupTitle') : recovering ? t('auth.recoverTitle') : t('auth.loginTitle') }}</h1>
          <p>{{ setup ? t('auth.setupSubtitle') : recovering ? t('auth.recoverSubtitle') : t('auth.loginSubtitle') }}</p>
        </div>
        <ul class="auth-points">
          <li><span class="point-icon"><Icon name="shield" :size="15" /></span><div><b>{{ t('auth.privacy') }}</b><span>{{ t('auth.privacyDesc') }}</span></div></li>
          <li><span class="point-icon"><Icon name="database" :size="15" /></span><div><b>{{ t('auth.localOnly') }}</b><span>{{ t('auth.localOnlyDesc') }}</span></div></li>
          <li><span class="point-icon"><Icon name="send" :size="15" /></span><div><b>{{ t('auth.emailRecovery') }}</b><span>{{ t('auth.emailRecoveryDesc') }}</span></div></li>
        </ul>
        <span class="auth-foot tiny">{{ t('auth.powered') }}</span>
      </aside>

      <section class="auth-card">
        <div class="auth-card-head">
          <span class="lock-badge"><Icon :name="setup ? 'sparkles' : recovering ? 'key' : 'lock'" :size="18" /></span>
          <div>
            <h2>{{ setup ? t('auth.createAccount') : recovering ? t('auth.recoverTitle') : t('auth.welcomeBack') }}</h2>
            <p>{{ setup ? t('auth.usernameHint') : recovering ? t('auth.recoverSubtitle') : t('auth.enterCredentials') }}</p>
          </div>
        </div>

        <form v-if="!recovering" class="auth-form" @submit.prevent="submit">
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

          <template v-if="setup">
            <label class="label" for="auth-email">{{ t('auth.recoveryEmail') }}</label>
            <div class="auth-field">
              <Icon name="send" :size="15" class="field-icon" />
              <input
                id="auth-email"
                v-model="email"
                class="field auth-input"
                type="email"
                :placeholder="t('auth.recoveryEmailHint')"
                autocomplete="email"
                :disabled="submitting"
              />
            </div>
          </template>

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

          <div v-if="!setup" class="auth-inline">
            <button type="button" class="auth-link" @click="openRecover">{{ t('auth.forgotPassword') }}</button>
          </div>

          <div v-if="lockSeconds > 0" class="auth-lock">
            <span class="auth-lock-icon"><Icon name="lock" :size="16" /></span>
            <div>
              <b>{{ t('auth.lockedTitle') }}</b>
              <span>{{ t('auth.lockedCountdown', { time: lockCountdown }) }}</span>
            </div>
          </div>
          <div v-else-if="error" class="auth-error"><Icon name="alert" :size="14" /> {{ error }}</div>
          <div v-else-if="unlocked" class="auth-unlocked"><Icon name="check" :size="14" /> {{ t('auth.unlocked') }}</div>

          <div v-if="attemptsLeft !== null && lockSeconds === 0" class="auth-attempts">
            <span class="attempts-dots">
              <i v-for="n in maxAttempts" :key="n" :class="{ used: n > attemptsLeft }" />
            </span>
            <span>{{ t('auth.attemptsHint', { n: maxAttempts }) }}</span>
          </div>

          <button class="btn primary lg auth-submit" type="submit" :disabled="submitting || lockSeconds > 0">
            <span v-if="submitting" class="spinner" style="width: 14px; height: 14px" />
            <Icon v-else :name="lockSeconds > 0 ? 'lock' : setup ? 'shield' : 'log-in'" :size="16" />
            {{
              lockSeconds > 0
                ? t('auth.lockedButton', { time: lockCountdown })
                : submitting
                  ? (setup ? t('auth.settingUp') : t('auth.signingIn'))
                  : (setup ? t('auth.setup') : t('auth.signIn'))
            }}
          </button>
        </form>

        <form v-else class="auth-form" @submit.prevent="recoverStep === 'request' ? requestCode() : resetPassword()">
          <label class="label" for="recover-identity">{{ t('auth.recoverIdentity') }}</label>
          <div class="auth-field">
            <Icon name="user" :size="15" class="field-icon" />
            <input
              id="recover-identity"
              v-model="recoverIdentity"
              class="field auth-input"
              :placeholder="t('auth.recoverIdentityPlaceholder')"
              :disabled="recoverStep === 'confirm' || recoverSending"
            />
          </div>

          <template v-if="recoverStep === 'confirm'">
            <label class="label" for="recover-code">{{ t('auth.recoverCode') }}</label>
            <div class="auth-field">
              <Icon name="key" :size="15" class="field-icon" />
              <input
                id="recover-code"
                v-model="recoverCode"
                class="field auth-input"
                inputmode="numeric"
                maxlength="6"
                :placeholder="t('auth.recoverCodePlaceholder')"
                :disabled="recoverResetting"
              />
            </div>

            <label class="label" for="recover-password">{{ t('auth.recoverNewPassword') }}</label>
            <div class="auth-field">
              <Icon name="lock" :size="15" class="field-icon" />
              <input
                id="recover-password"
                v-model="recoverPassword"
                class="field auth-input"
                :type="show ? 'text' : 'password'"
                :placeholder="t('auth.recoverNewPassword')"
                autocomplete="new-password"
                :disabled="recoverResetting"
              />
              <button type="button" class="eye-btn" @click="show = !show">
                <Icon :name="show ? 'eye-off' : 'eye'" :size="15" />
              </button>
            </div>

            <label class="label" for="recover-confirm">{{ t('auth.recoverConfirm') }}</label>
            <div class="auth-field">
              <Icon name="lock" :size="15" class="field-icon" />
              <input
                id="recover-confirm"
                v-model="recoverConfirm"
                class="field auth-input"
                :type="show ? 'text' : 'password'"
                :placeholder="t('auth.recoverConfirm')"
                autocomplete="new-password"
                :disabled="recoverResetting"
              />
            </div>

            <div class="auth-inline">
              <button type="button" class="auth-link" :disabled="recoverSending || resendSeconds > 0" @click="requestCode">
                {{ resendSeconds > 0 ? t('auth.recoverResendCountdown', { s: resendSeconds }) : t('auth.recoverResend') }}
              </button>
            </div>
          </template>

          <div v-if="error" class="auth-error"><Icon name="alert" :size="14" /> {{ error }}</div>
          <div v-else-if="recoverNotice" class="auth-unlocked"><Icon name="check" :size="14" /> {{ recoverNotice }}</div>

          <button class="btn primary lg auth-submit" type="submit" :disabled="recoverSending || recoverResetting">
            <span v-if="recoverSending || recoverResetting" class="spinner" style="width: 14px; height: 14px" />
            <Icon v-else :name="recoverStep === 'request' ? 'send' : 'key'" :size="16" />
            {{
              recoverStep === 'request'
                ? (recoverSending ? t('auth.recoverSending') : t('auth.recoverSend'))
                : (recoverResetting ? t('auth.recoverResetting') : t('auth.recoverReset'))
            }}
          </button>
        </form>

        <button v-if="setup" class="btn ghost auth-later" type="button" :disabled="skipping || submitting" @click="skip">
          <span v-if="skipping" class="spinner" style="width: 12px; height: 12px" />
          {{ t('auth.later') }}
        </button>
        <button v-else-if="recovering" class="btn ghost auth-later" type="button" @click="backToLogin">
          {{ t('auth.recoverBack') }}
        </button>
        <p v-if="setup" class="auth-note tiny">{{ t('auth.setupNote') }}</p>
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
.auth-inline { display: flex; justify-content: flex-end; margin-top: 2px; }
.auth-link { border: none; background: transparent; color: var(--brand); font-size: 11.5px; font-weight: 600; padding: 0; cursor: pointer; }
.auth-link:hover { text-decoration: underline; }
.auth-link:disabled { color: var(--faint); cursor: default; text-decoration: none; }
.auth-error { display: flex; align-items: center; gap: 6px; margin-top: 4px; padding: 8px 10px; border-radius: 9px; color: var(--bad); background: var(--bad-soft); font-size: 11.5px; border: 1px solid color-mix(in srgb, var(--bad) 25%, transparent); }
.auth-lock { display: flex; align-items: center; gap: 9px; margin-top: 4px; padding: 10px 11px; border-radius: 10px; color: var(--bad); background: var(--bad-soft); border: 1px solid color-mix(in srgb, var(--bad) 30%, transparent); }
.auth-lock-icon { width: 32px; height: 32px; flex: 0 0 32px; display: grid; place-items: center; border-radius: 9px; background: color-mix(in srgb, var(--bad) 15%, transparent); color: var(--bad); }
.auth-lock b { display: block; font-size: 12px; }
.auth-lock span:not(.auth-lock-icon) { display: block; font-size: 11px; color: color-mix(in srgb, var(--bad) 80%, var(--ink)); font-family: var(--font-mono); letter-spacing: .03em; }
.auth-unlocked { display: flex; align-items: center; gap: 6px; margin-top: 4px; padding: 8px 10px; border-radius: 9px; color: var(--good); background: var(--good-soft); border: 1px solid color-mix(in srgb, var(--good) 25%, transparent); font-size: 11.5px; }
.auth-attempts { display: flex; align-items: center; gap: 8px; margin-top: 4px; color: var(--bad); font-size: 10.5px; font-weight: 600; letter-spacing: .01em; }
.attempts-dots { display: inline-flex; gap: 3px; }
.attempts-dots i { width: 7px; height: 7px; border-radius: 50%; background: var(--surface-3); border: 1px solid var(--line-strong); }
.attempts-dots i.used { background: var(--bad); border-color: var(--bad); box-shadow: 0 0 8px color-mix(in srgb, var(--bad) 50%, transparent); }
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
