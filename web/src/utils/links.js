const SETTINGS_URL_TOKEN = '{{settings_url}}'

export function settingsUrl() {
  try {
    return `${window.location.origin}/#/settings`
  } catch {
    return '/#/settings'
  }
}

export function resolveMessageLinks(text) {
  const value = String(text || '')
  if (!value.includes(SETTINGS_URL_TOKEN)) return value
  return value.split(SETTINGS_URL_TOKEN).join(settingsUrl())
}
