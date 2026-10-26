const BASE = import.meta.env.VITE_API_BASE || ''

async function request(path, options = {}) {
  const response = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })
  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  if (!response.ok) {
    const message = payload?.message || payload?.detail || `HTTP ${response.status}`
    throw new Error(message)
  }
  if (payload && typeof payload.code === 'number' && payload.code !== 200) {
    throw new Error(payload.message || 'Request failed')
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
  clearSession: (id) => request(`/api/sessions/${id}/clear`, { method: 'POST' }),
  messages: (id) => request(`/api/sessions/${id}/messages`),
  sendMessage: (id, content) => request(`/api/sessions/${id}/messages`, { method: 'POST', body: JSON.stringify({ content }) }),
  events: (id, afterId = 0) => request(`/api/sessions/${id}/events${qs({ after_id: afterId })}`),
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
  togglePlugin: (name, enabled) => request(`/api/plugins/${name}/toggle`, { method: 'POST', body: JSON.stringify({ enabled }) }),

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
