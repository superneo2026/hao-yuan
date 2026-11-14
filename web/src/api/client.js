const BASE = import.meta.env.VITE_API_BASE || ''
const AUTH_TOKEN_KEY = 'hy.authToken'
const REMOTE_TOKEN_KEY = 'hy.remoteToken'

function captureRemoteToken() {
  try {
    const url = new URL(window.location.href)
    const token = url.searchParams.get('hy_remote_token')
    if (!token) return
    sessionStorage.setItem(REMOTE_TOKEN_KEY, token)
    url.searchParams.delete('hy_remote_token')
    const next = `${url.pathname}${url.search}${url.hash}`
    window.history.replaceState(window.history.state, '', next || '/')
  } catch {
    /* remote token capture is best-effort */
  }
}

captureRemoteToken()

export function getRemoteToken() {
  try {
    return sessionStorage.getItem(REMOTE_TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function getAuthToken() {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setAuthToken(token) {
  try {
    if (token) localStorage.setItem(AUTH_TOKEN_KEY, token)
    else localStorage.removeItem(AUTH_TOKEN_KEY)
  } catch {
    /* storage is best-effort */
  }
}

export function clearAuthToken() {
  setAuthToken('')
}

async function request(path, options = {}) {
  const headers = { ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }), ...(options.headers || {}) }
  const token = getAuthToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const remoteToken = getRemoteToken()
  if (remoteToken) headers['X-HaoYuan-Remote'] = remoteToken
  const response = await fetch(BASE + path, { ...options, headers })
  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  if (response.status === 401) {
    clearAuthToken()
    window.dispatchEvent(new CustomEvent('hy:unauthorized'))
  }
  if (!response.ok) {
    const message = payload?.message || payload?.detail || `HTTP ${response.status}`
    const error = new Error(message)
    error.code = payload?.code ?? response.status
    error.data = payload?.data
    throw error
  }
  if (payload && typeof payload.code === 'number' && payload.code !== 200) {
    const error = new Error(payload.message || 'Request failed')
    error.code = payload.code
    error.data = payload.data
    throw error
  }
  return payload?.data !== undefined ? payload.data : payload
}

function qs(params = {}) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  })
  const text = query.toString()
  return text ? `?${text}` : ''
}

export async function supervisorChatStream({ message, chatId = '', model = '', onEvent, signal }) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getAuthToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const remoteToken = getRemoteToken()
  if (remoteToken) headers['X-HaoYuan-Remote'] = remoteToken
  const response = await fetch(`${BASE}/api/supervisor/chat/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ message, chat_id: chatId, model }),
    signal
  })
  if (response.status === 401) {
    clearAuthToken()
    window.dispatchEvent(new CustomEvent('hy:unauthorized'))
  }
  if (!response.ok || !response.body) {
    let detail = `HTTP ${response.status}`
    try {
      const payload = await response.json()
      detail = payload?.message || payload?.detail || detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      const chunk = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      let event = 'message'
      let data = ''
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (data) {
        try {
          onEvent?.(event, JSON.parse(data))
        } catch {
          /* skip malformed frames */
        }
      }
      boundary = buffer.indexOf('\n\n')
    }
  }
}

export const api = {
  health: () => request('/api/health'),
  info: () => request('/api/info'),
  models: () => request('/api/models'),
  agents: () => request('/api/agents'),
  tools: () => request('/api/tools'),

  sessions: (includeHidden = true) => request(`/api/sessions${qs({ include_hidden: includeHidden })}`),
  session: (id) => request(`/api/sessions/${id}`),
  createSession: (body) => request('/api/sessions', { method: 'POST', body: JSON.stringify(body) }),
  patchSession: (id, body) => request(`/api/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  hideSession: (id) => request(`/api/sessions/${id}`, { method: 'DELETE' }),
  unhideSession: (id) => request(`/api/sessions/${id}/unhide`, { method: 'POST' }),
  purgeSession: (id) => request(`/api/sessions/${id}/purge`, { method: 'DELETE' }),
  purgeAllSessions: () => request('/api/sessions', { method: 'DELETE' }),
  clearSession: (id) => request(`/api/sessions/${id}/clear`, { method: 'POST' }),
  messages: (id, { limit = 0, before = 0 } = {}) => request(`/api/sessions/${id}/messages${qs({ limit, before })}`),
  sendMessage: (id, content, locale = '') => request(`/api/sessions/${id}/messages`, { method: 'POST', body: JSON.stringify({ content, locale }) }),
  events: (id, afterId = 0, { limit = 2000, run_id = '', tail = false } = {}) => request(`/api/sessions/${id}/events${qs({ after_id: afterId, limit, run_id, tail: tail ? 1 : '' })}`),
  cancel: (id) => request(`/api/sessions/${id}/cancel`, { method: 'POST' }),
  resume: (id) => request(`/api/sessions/${id}/resume`, { method: 'POST' }),
  confirm: (id, callId, ok) => request(`/api/sessions/${id}/confirm`, { method: 'POST', body: JSON.stringify({ call_id: callId, ok }) }),
  artifacts: (id) => request(`/api/sessions/${id}/artifacts`),

  approvals: (status = 'pending') => request(`/api/approvals${qs({ status })}`),
  resolveApproval: (id, approved, reason = '') => request(`/api/approvals/${id}/resolve`, { method: 'POST', body: JSON.stringify({ approved, reason }) }),

  skills: () => request('/api/skills'),
  skill: (name) => request(`/api/skills/${name}`),
  createSkill: (body) => request('/api/skills', { method: 'POST', body: JSON.stringify(body) }),
  updateSkill: (name, body) => request(`/api/skills/${name}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteSkill: (name) => request(`/api/skills/${name}`, { method: 'DELETE' }),

  plugins: () => request('/api/plugins'),
  pluginContributions: () => request('/api/plugins/contributions'),

  notes: (page = 1, pageSize = 8, q = '') => request(`/api/notes${qs({ page, page_size: pageSize, q })}`),
  note: (id) => request(`/api/notes/${encodeURIComponent(id)}`),
  createNote: (body) => request('/api/notes', { method: 'POST', body: JSON.stringify(body) }),
  updateNote: (id, body) => request(`/api/notes/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteNote: (id) => request(`/api/notes/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  reorderNote: (noteId, targetIndex) => request('/api/notes/reorder', { method: 'PUT', body: JSON.stringify({ note_id: noteId, target_index: targetIndex }) }),

  remoteOverview: () => request('/api/remote-management/overview'),
  remoteSettings: (body) => request('/api/remote-management/settings', { method: 'PUT', body: JSON.stringify(body) }),
  remoteCreateKey: (body) => request('/api/remote-management/keys', { method: 'POST', body: JSON.stringify(body) }),
  remoteDeleteKey: (id) => request(`/api/remote-management/keys/${id}`, { method: 'DELETE' }),
  remoteIncomingAction: (id, action) => request(`/api/remote-management/incoming/${id}/${action}`, { method: 'POST' }),
  remoteDeleteIncoming: (id) => request(`/api/remote-management/incoming/${id}`, { method: 'DELETE' }),
  remoteAddSystem: (body) => request('/api/remote-management/systems', { method: 'POST', body: JSON.stringify(body) }),
  remoteRefreshSystems: () => request('/api/remote-management/systems/refresh', { method: 'POST' }),
  remoteSystem: (id) => request(`/api/remote-management/systems/${id}`),
  remoteRefreshSystem: (id) => request(`/api/remote-management/systems/${id}/refresh`, { method: 'POST' }),
  remoteSystemAction: (id, action) => request(`/api/remote-management/systems/${id}/${action}`, { method: 'POST' }),
  remoteDeleteSystem: (id) => request(`/api/remote-management/systems/${id}`, { method: 'DELETE' }),
  togglePlugin: (name, enabled) => request(`/api/plugins/${name}/toggle`, { method: 'POST', body: JSON.stringify({ enabled }) }),
  marketplace: (center = '') => request(`/api/marketplace/plugins${qs({ center })}`),
  installPlugin: (body) => request('/api/marketplace/install', { method: 'POST', body: JSON.stringify(body) }),
  uploadPlugin: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/plugins/upload', { method: 'POST', body: form })
  },
  uninstallPlugin: (name) => request(`/api/plugins/${name}`, { method: 'DELETE' }),

  authStatus: () => request('/api/auth/status'),
  authSetup: (body) => request('/api/auth/setup', { method: 'POST', body: JSON.stringify(body) }),
  authLogin: (body) => request('/api/auth/login', { method: 'POST', body: JSON.stringify(body) }),
  authLogout: () => request('/api/auth/logout', { method: 'POST' }),
  authChange: (body) => request('/api/auth/change', { method: 'POST', body: JSON.stringify(body) }),
  authPolicy: (body) => request('/api/auth/policy', { method: 'PUT', body: JSON.stringify(body) }),

  settings: () => request('/api/settings'),
  saveGate: (mode, allow) => request('/api/settings/gate', { method: 'PUT', body: JSON.stringify({ mode, allow }) }),
  saveWorkspace: (workspace) => request('/api/settings/workspace', { method: 'PUT', body: JSON.stringify({ workspace }) }),
  saveSetting: (key, value) => request(`/api/settings/${key}`, { method: 'PUT', body: JSON.stringify({ value }) }),

  fsList: (path = '') => request(`/api/fs/list${qs({ path })}`),
  tree: (workspace, maxEntries = 2500) => request(`/api/workspace/tree${qs({ workspace, max_entries: maxEntries })}`),
  file: (workspace, path) => request(`/api/workspace/file${qs({ workspace, path })}`),
  changes: (workspace) => request(`/api/workspace/changes${qs({ workspace })}`),
  diff: (workspace, path = '') => request(`/api/workspace/diff${qs({ workspace, path })}`),

  usageToday: () => request('/api/usage/today'),
  usageDaily: (days = 14) => request(`/api/usage/daily${qs({ days })}`),
  usageByModel: () => request('/api/usage/by-model'),

  supervisorOverview: () => request('/api/supervisor/overview'),
  supervisorConsole: (page = 1) => request(`/api/supervisor/console${qs({ page })}`),
  supervisorAct: (sessionId, action) => request('/api/supervisor/act', { method: 'POST', body: JSON.stringify({ session_id: sessionId, action }) }),
  supervisorChat: (message, chatId = '', model = '') => request('/api/supervisor/chat', { method: 'POST', body: JSON.stringify({ message, chat_id: chatId, model }) }),
  supervisorChats: () => request('/api/supervisor/chats'),
  supervisorMessages: (chatId) => request(`/api/supervisor/chats/${encodeURIComponent(chatId)}/messages`),
  supervisorCreateChat: () => request('/api/supervisor/chats', { method: 'POST' }),
  supervisorDeleteChat: (chatId) => request(`/api/supervisor/chats/${encodeURIComponent(chatId)}`, { method: 'DELETE' }),

  orchestrations: () => request('/api/orchestrations'),
  orchestration: (id) => request(`/api/orchestrations/${id}`),
  createOrchestration: (body) => request('/api/orchestrations', { method: 'POST', body: JSON.stringify(body) }),
  advanceOrchestration: (id) => request(`/api/orchestrations/${id}/advance`, { method: 'POST' }),
  mergeOrchestration: (id) => request(`/api/orchestrations/${id}/merge`, { method: 'POST' })
}

export function artifactUrl(id) {
  return `${BASE}/api/artifacts/${id}/file`
}

export function textArtifactUrl(id, download = false) {
  return `${BASE}/api/artifacts/${id}/file${download ? '?download=true' : ''}`
}
