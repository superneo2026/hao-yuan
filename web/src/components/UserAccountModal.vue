<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  changeAccount,
  fetchMailSettings,
  logoutAccount,
  saveAuthPolicy,
  saveMailSettings,
  sendTestMail,
  state
} from '../stores/app'
import { t } from '../i18n'
import Icon from './Icon.vue'

const emit = defineEmits(['close'])

const current = ref('')
const username = ref(state.auth.username || '')
const email = ref('')
const password = ref('')
const confirm = ref('')
const show = ref(false)
const loading = ref(false)
const error = ref('')
const maxFailures = ref(Number(state.auth.maxFailures) || 5)
const policySaving = ref(false)

const nameChanged = computed(() => username.value.trim() && username.value.trim() !== state.auth.username)
const emailChanged = computed(() => Boolean(email.value.trim()))

const SMTP_PRESETS = {
  custom: { host: '', port: 465, security: 'ssl' },
  gmail: { host: 'smtp.gmail.com', port: 465, security: 'ssl' },
  qq: { host: 'smtp.qq.com', port: 465, security: 'ssl' }
}
const providerOptions = ['custom', 'gmail', 'qq']

const mail = reactive({
  provider: 'custom',
  host: '',
  port: 465,
  username: '',
  password: '',
  sender: '',
  security: 'ssl',
  hasPassword: false,
  configured: false,
  envManaged: false
})
const mailSaving = ref(false)
const mailTesting = ref(false)
const mailNotice = ref('')

const providerHint = computed(() => {
  if (mail.provider === 'gmail') return t('auth.smtpGmailHint')
  if (mail.provider === 'qq') return t('auth.smtpQqHint')
  return t('auth.smtpCustomHint')
})

function detectProvider(host) {
  const value = (host || '').toLowerCase()
  if (value === 'smtp.gmail.com') return 'gmail'
  if (value === 'smtp.qq.com') return 'qq'
  return 'custom'
}

function applyProvider(name) {
  mail.provider = name
  const preset = SMTP_PRESETS[name]
  if (name !== 'custom' && preset) {
    mail.host = preset.host
    mail.port = preset.port
    mail.security = preset.security
  }
}

onMounted(loadMail)

async function loadMail() {
  try {
    const data = await fetchMailSettings()
    Object.assign(mail, {
      provider: data.provider || detectProvider(data.host),
      host: data.host || '',
      port: data.port || 465,
      username: data.username || '',
      password: '',
      sender: data.sender || '',
      security: data.security || 'ssl',
      hasPassword: !!data.has_password,
      configured: !!data.configured,
      envManaged: !!data.env_managed
    })
  } catch {
    /* ignore mail config load errors */
  }
}

async function saveMail() {
  error.value = ''
  mailNotice.value = ''
  if (!mail.host.trim() || !mail.sender.trim()) {
    error.value = t('auth.emailServiceRequired')
    return
  }
  mailSaving.value = true
  try {
    const data = await saveMailSettings({
      provider: mail.provider,
      host: mail.host.trim(),
      port: Number(mail.port) || 465,
      username: mail.username.trim(),
      password: mail.password,
      sender: mail.sender.trim(),
      security: mail.security
    })
    Object.assign(mail, {
      provider: data.provider || mail.provider,
      host: data.host || '',
      port: data.port || 465,
      username: data.username || '',
      password: '',
      sender: data.sender || '',
      security: data.security || 'ssl',
      hasPassword: !!data.has_password,
      configured: !!data.configured,
      envManaged: !!data.env_managed
    })
    mailNotice.value = t('auth.smtpSaved')
  } catch (err) {
    error.value = err.message || t('common.error')
  } finally {
    mailSaving.value = false
  }
}

async function testMail() {
  error.value = ''
  mailNotice.value = ''
  mailTesting.value = true
  try {
    await sendTestMail('')
    mailNotice.value = t('auth.smtpTestSent')
  } catch (err) {
    error.value = err.message || t('common.error')
  } finally {
    mailTesting.value = false
  }
}

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
  if (!nameChanged.value && !password.value && !emailChanged.value) {
    error.value = t('auth.nothingChanged')
    return
  }
  if (emailChanged.value && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim())) {
    error.value = t('auth.recoveryEmailInvalid')
    return
  }
  loading.value = true
  try {
    await changeAccount({
      current_password: current.value,
      username: nameChanged.value ? username.value.trim() : '',
      new_password: password.value,
      email: emailChanged.value ? email.value.trim() : ''
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

        <div class="policy-card">
          <div class="policy-head">
            <span class="policy-icon"><Icon name="send" :size="16" /></span>
            <div>
              <b>{{ t('auth.recoveryEmailTitle') }}</b>
              <span>{{ t('auth.recoveryEmailDesc') }}</span>
            </div>
            <span class="badge" :class="state.auth.hasRecoveryEmail ? 'good' : 'warn'" style="margin-left: auto">
              {{ state.auth.hasRecoveryEmail ? state.auth.recoveryEmail : t('auth.recoveryEmailNotSet') }}
            </span>
          </div>
          <div class="account-field" style="margin-bottom: 0">
            <Icon name="send" :size="15" class="field-icon" />
            <input
              id="ac-email"
              v-model="email"
              class="field account-input"
              type="email"
              :placeholder="t('auth.recoveryEmailHint')"
              autocomplete="email"
            />
          </div>
          <p class="tiny faint" style="margin: 8px 0 0">{{ t('auth.recoveryEmailUpdateHint') }}</p>
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

        <div class="policy-card">
          <div class="policy-head">
            <span class="policy-icon"><Icon name="send" :size="16" /></span>
            <div>
              <b>{{ t('auth.emailServiceTitle') }}</b>
              <span>{{ t('auth.emailServiceDesc') }}</span>
            </div>
            <span class="badge" :class="mail.configured ? 'good' : 'warn'" style="margin-left: auto">
              {{ mail.configured ? t('auth.smtpConfigured') : t('auth.smtpNotConfigured') }}
            </span>
          </div>

          <label class="label" for="mail-provider">{{ t('auth.smtpProvider') }}</label>
          <select id="mail-provider" v-model="mail.provider" class="field" @change="applyProvider(mail.provider)">
            <option value="custom">{{ t('auth.smtpProviderCustom') }}</option>
            <option value="gmail">{{ t('auth.smtpProviderGmail') }}</option>
            <option value="qq">{{ t('auth.smtpProviderQq') }}</option>
          </select>
          <p class="tiny faint smtp-hint">{{ providerHint }}</p>

          <div class="mail-grid">
            <input v-model="mail.host" class="field" :placeholder="t('auth.smtpHost')" />
            <input v-model.number="mail.port" class="field" type="number" :placeholder="t('auth.smtpPort')" />
            <input v-model="mail.sender" class="field" type="email" :placeholder="t('auth.smtpSender')" />
            <select v-model="mail.security" class="field">
              <option value="ssl">{{ t('auth.smtpSecuritySsl') }}</option>
              <option value="starttls">{{ t('auth.smtpSecurityStarttls') }}</option>
              <option value="none">{{ t('auth.smtpSecurityNone') }}</option>
            </select>
            <input v-model="mail.username" class="field" :placeholder="t('auth.smtpUser')" autocomplete="off" />
            <input
              v-model="mail.password"
              class="field"
              type="password"
              :placeholder="mail.hasPassword ? t('auth.smtpPasswordKeep') : t('auth.smtpPassword')"
              autocomplete="new-password"
            />
          </div>
          <p v-if="mail.envManaged" class="tiny faint" style="margin: 8px 0 0">{{ t('auth.smtpEnvManaged') }}</p>
          <div class="mail-actions">
            <button class="btn sm primary" type="button" :disabled="mailSaving" @click="saveMail">
              <span v-if="mailSaving" class="spinner" style="width: 11px; height: 11px" />
              {{ t('auth.smtpSave') }}
            </button>
            <button class="btn sm" type="button" :disabled="mailTesting || !mail.configured" @click="testMail">
              <span v-if="mailTesting" class="spinner" style="width: 11px; height: 11px" />
              {{ t('auth.smtpTest') }}
            </button>
          </div>
        </div>

        <div v-if="error" class="auth-error"><Icon name="alert" :size="14" /> {{ error }}</div>
        <div v-else-if="mailNotice" class="auth-ok"><Icon name="check" :size="14" /> {{ mailNotice }}</div>
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
.auth-ok { display: flex; align-items: center; gap: 6px; margin-top: 4px; padding: 8px 10px; border-radius: 9px; color: var(--good); background: var(--good-soft); font-size: 11.5px; border: 1px solid color-mix(in srgb, var(--good) 25%, transparent); }
.smtp-hint { margin: 4px 0 9px; line-height: 1.5; }
.mail-grid { display: grid; grid-template-columns: 3fr 2fr; gap: 6px; }
.mail-grid .field { height: 34px; }
.mail-actions { display: flex; gap: 8px; margin-top: 10px; }
</style>
