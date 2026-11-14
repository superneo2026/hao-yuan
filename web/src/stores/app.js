import { computed, reactive } from 'vue'
import { api, clearAuthToken, setAuthToken } from '../api/client'
import { createSessionStream } from '../api/sse'
import { i18n, setLocale, t } from '../i18n'

const LAST_SESSION = 'hy.lastSession'
const MESSAGE_PAGE = 80
const ACTIVITY_EVENT_LIMIT = 800
const THEME = 'hy.theme.v2'
const SIDEBAR = 'hy.sidebar'
const OPEN_TABS = 'hy.openTabs.v1'

function safeJson(text, fallback) {
  try {
    const value = JSON.parse(text || '')
    return value ?? fallback
  } catch {
    return fallback
  }
}

function sessionIdFromHash() {
  const match = (window.location.hash || '').match(/^#\/s\/([^/?#]+)/)
  if (!match) return ''
  try {
    return decodeURIComponent(match[1])
  } catch {
    return ''
  }
}

export const state = reactive({
  booted: false,
  loading: false,
  connection: 'connecting',
  health: null,
  info: null,
  models: [],
  plugins: [],
  skills: [],
  settings: { gate: { mode: 'ask', allow: [] }, default_workspace: '', theme: 'light' },
  sessions: [],
  currentId: localStorage.getItem(LAST_SESSION) || '',
  openSessionIds: (() => {
    const stored = safeJson(localStorage.getItem(OPEN_TABS), [])
    if (!Array.isArray(stored)) return []
    return [...new Set(stored.filter((id) => typeof id === 'string' && id))]
  })(),
  session: null,
  messages: [],
  hasMoreMessages: false,
  loadingEarlier: false,
  switching: false,
  artifacts: [],
  tree: [],
  changes: [],
  plan: { title: '', steps: [] },
  live: {
    streams: {},
    reasoning: {},
    tools: {},
    toolOrder: [],
    approvals: [],
    route: null,
    skills: [],
    skillHow: '',
    notices: []
  },
  scrollTick: 0,
  toasts: [],
  runs: [],
  activity: { tools: {}, steps: 0, startedAt: 0, endedAt: 0 },
  sidebarCollapsed: localStorage.getItem(SIDEBAR) === '1',
  pluginNavOpen: localStorage.getItem('hy.pluginNav') !== '0',
  remoteNavOpen: localStorage.getItem('hy.remoteNav') !== '0',
  mobileNavOpen: false,
  homeRequested: false,
  notesOpen: false,
  paletteOpen: false,
  newTaskOpen: false,
  theme: localStorage.getItem(THEME) || 'light',
  activeRightTab: 'overview',
  selectedFile: null,
  fileContent: null,
  diffText: '',
  diffPath: '',
  usageToday: null,
  usageDaily: [],
  usageByModel: [],
  supervisor: null,
  orchestrations: [],
  auth: { checked: false, enabled: false, configured: false, active: false, authenticated: false, username: '', maxFailures: 5, lockSeconds: 300, loading: false },
  market: { loading: false, online: false, error: '', centerUrl: '', plugins: [] },
  remote: {
    loading: false,
    enabled: false,
    error: '',
    instance: null,
    keys: [],
    incoming: [],
    outgoing: [],
    current: null
  },
  accountOpen: false,
  authSetupOpen: false,
  workspaceSetupOpen: false,
  busy: { sending: false, loadingFile: false }
})

let sessionStream = null
let sessionPollTimer = null
let requestToken = 0
let refreshTimer = null

export const currentSession = computed(
  () => state.session || state.sessions.find((item) => item.id === state.currentId) || null
)
export const isActive = computed(() =>
  ['running', 'queued', 'waiting_input'].includes(currentSession.value?.status)
)
export const activeApproval = computed(() => {
  if (state.live.approvals.length) return state.live.approvals[0]
  const pending = currentSession.value?.pending
  return pending || null
})
export const activeSkills = computed(() => {
  if (state.live.skills.length) return state.live.skills
  return safeJson(currentSession.value?.skills_used, [])
})
export const liveToolList = computed(() =>
  state.live.toolOrder.map((id) => state.live.tools[id]).filter(Boolean)
)
export const authBlocked = computed(
  () => state.auth.checked && state.auth.enabled && state.auth.configured && !state.auth.authenticated
)
export const authSetupMode = computed(() => state.auth.enabled && !state.auth.configured)
export const tokenCount = computed(() => {
  const session = currentSession.value || {}
  return Number(session.context_tokens || 0) + Number(session.total_prompt || 0) + Number(session.total_completion || 0)
})

export function setTheme(theme, persist = true) {
  state.theme = theme
  document.documentElement.dataset.theme = theme
  localStorage.setItem(THEME, theme)
  if (persist) api.saveSetting('theme', theme).catch(() => {})
}

export function toast(message, type = 'info', ttl = 3600) {
  const id = Math.random().toString(36).slice(2)
  state.toasts.push({ id, message, type })
  setTimeout(() => {
    state.toasts = state.toasts.filter((item) => item.id !== id)
  }, ttl)
}

export function dismissToast(id) {
  state.toasts = state.toasts.filter((item) => item.id !== id)
}

export function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed
  localStorage.setItem(SIDEBAR, state.sidebarCollapsed ? '1' : '0')
}

export function openPalette() {
  state.paletteOpen = true
}
export function closePalette() {
  state.paletteOpen = false
}

export function closeNotes() {
  state.notesOpen = false
}
export function toggleNotes() {
  state.notesOpen = !state.notesOpen
}

export function togglePluginNav() {
  state.pluginNavOpen = !state.pluginNavOpen
  localStorage.setItem('hy.pluginNav', state.pluginNavOpen ? '1' : '0')
}

export function toggleRemoteNav() {
  state.remoteNavOpen = !state.remoteNavOpen
  localStorage.setItem('hy.remoteNav', state.remoteNavOpen ? '1' : '0')
}

function persistOpenTabs() {
  try {
    localStorage.setItem(OPEN_TABS, JSON.stringify(state.openSessionIds))
  } catch {
    /* ignore storage errors */
  }
}

function ensureOpenTab(id) {
  if (!id || state.openSessionIds.includes(id)) return
  state.openSessionIds.push(id)
  persistOpenTabs()
}

function dropOpenTab(id) {
  const index = state.openSessionIds.indexOf(id)
  if (index < 0) return
  state.openSessionIds.splice(index, 1)
  persistOpenTabs()
}

function updateSessionInList(patch) {
  if (!patch?.id) return
  const index = state.sessions.findIndex((item) => item.id === patch.id)
  if (index >= 0) {
    state.sessions[index] = { ...state.sessions[index], ...patch }
  }
}

function pushNotice(payload) {
  state.live.notices.unshift({ ...payload, at: Date.now() })
  if (state.live.notices.length > 40) state.live.notices.length = 40
}

function applyEvent(event) {
  const sessionId = event.session_id
  const type = event.event
  const payload = event.payload || {}
  if (event.id !== undefined && state.session && sessionId === state.currentId) {
    state.session.last_event_id = Number(event.id) || state.session.last_event_id || 0
  }
  if (sessionId === '*' || !sessionId) {
    if (type === 'supervisor.snapshot') state.supervisor = payload
    if (type === 'settings.updated') state.settings = { ...state.settings, ...payload }
    return
  }

  if (sessionId !== state.currentId) {
    if (type === 'session.status') updateSessionInList({ id: sessionId, status: payload.status, error: payload.error })
    if (type === 'session.updated') updateSessionInList({ id: sessionId, ...payload })
    if (type === 'session.created') loadSessions()
    if (type === 'message.saved' && payload.role === 'user') {
      const patch = { id: sessionId, updated_at: new Date().toISOString() }
      const listed = state.sessions.find((item) => item.id === sessionId)
      if (listed && !listed.first_question) patch.first_question = payload.content
      updateSessionInList(patch)
    }
    return
  }

  switch (type) {
    case 'session.status': {
      if (state.session) {
        state.session = { ...state.session, status: payload.status, error: payload.error || state.session.error }
      }
      updateSessionInList({ id: sessionId, status: payload.status, error: payload.error })
      if (payload.status === 'running' && !state.activity.startedAt) state.activity.startedAt = Date.now()
      if (payload.status === 'done' || payload.status === 'error') state.activity.endedAt = Date.now()
      if (payload.status === 'done' || payload.status === 'error') scheduleRefresh()
      break
    }
    case 'delta': {
      const id = payload.msg_id || 'live'
      state.live.streams[id] = (state.live.streams[id] || '') + (payload.text || '')
      state.scrollTick++
      break
    }
    case 'reasoning': {
      const id = payload.msg_id || 'live'
      state.live.reasoning[id] = (state.live.reasoning[id] || '') + (payload.text || '')
      break
    }
    case 'message.saved': {
      if (payload.role === 'user') {
        if (!state.messages.some((item) => item.id === payload.msg_id)) {
          state.messages.push({
            id: payload.msg_id,
            role: 'user',
            content: payload.content || '',
            created_at: event.time
          })
        }
        if (state.session && !state.session.first_question) {
          state.session = { ...state.session, first_question: payload.content || '' }
          updateSessionInList({ id: sessionId, first_question: payload.content || '' })
        }
        state.scrollTick++
      } else if (payload.role === 'assistant') {
        if (!state.messages.some((item) => item.id === payload.msg_id)) {
          state.messages.push({
            id: payload.msg_id,
            role: 'assistant',
            content: payload.content || '',
            tool_args: payload.tool_args || '',
            created_at: event.time
          })
        }
        // The saved message renders from state.messages, so drop this step's live token
        // buffers. Keying on payload.msg_id alone left stale buffers whenever the streaming
        // id differed, which rendered the same reply twice until the next refresh.
        state.live.streams = {}
        state.live.reasoning = {}
        state.scrollTick++
      }
      break
    }
    case 'tool.start': {
      const id = payload.call_id || `${payload.tool}-${Date.now()}`
      state.live.tools[id] = {
        call_id: id,
        tool: payload.tool,
        args: payload.args || {},
        status: 'running',
        started: Date.now()
      }
      if (!state.live.toolOrder.includes(id)) state.live.toolOrder.push(id)
      state.activity.tools[id] = {
        ...(state.activity.tools[id] || {}),
        call_id: id,
        tool: payload.tool,
        args: payload.args || {},
        status: 'running',
        startedAt: Date.now()
      }
      state.activity.steps = Math.max(state.activity.steps, state.live.toolOrder.length)
      if (!state.activity.startedAt) state.activity.startedAt = Date.now()
      state.scrollTick++
      break
    }
    case 'tool.end': {
      const id = payload.call_id
      const item = state.live.tools[id]
      if (item) {
        state.live.tools[id] = {
          ...item,
          status: payload.ok ? 'done' : 'error',
          summary: payload.summary,
          error: payload.error,
          ms: payload.ms
        }
      }
      state.activity.tools[id] = {
        ...(state.activity.tools[id] || {}),
        call_id: id,
        tool: payload.tool,
        ok: payload.ok,
        summary: payload.summary,
        error: payload.error,
        ms: payload.ms,
        status: payload.ok ? 'done' : 'error',
        endedAt: Date.now()
      }
      break
    }
    case 'approval.required': {
      const exists = state.live.approvals.some((item) => item.approval_id === payload.approval_id)
      if (!exists) {
        state.live.approvals.push(payload)
        toast(t('approval.needed', { tool: payload.tool }), 'warn', 6000)
      }
      break
    }
    case 'approval.resolved': {
      state.live.approvals = state.live.approvals.filter((item) => item.approval_id !== payload.approval_id)
      if (state.session) state.session.pending = null
      break
    }
    case 'plan.updated': {
      state.plan = payload
      if (state.session) state.session.plan = JSON.stringify(payload)
      break
    }
    case 'skills.matched': {
      state.live.skills = payload.skills || []
      state.live.skillHow = payload.how || ''
      break
    }
    case 'route': {
      state.live.route = payload
      break
    }
    case 'usage': {
      if (state.session && payload.session_total) {
        state.session = {
          ...state.session,
          context_tokens: payload.session_total.context_tokens,
          total_prompt: payload.session_total.prompt,
          total_completion: payload.session_total.completion,
          cost_est: payload.session_total.cost_est
        }
      }
      break
    }
    case 'artifact.created': {
      loadArtifacts()
      break
    }
    case 'done': {
      if (state.session) state.session = { ...state.session, status: 'done' }
      scheduleRefresh()
      break
    }
    case 'error': {
      toast(t('toast.taskFailed', { message: payload.message || t('status.error') }), 'bad', 7000)
      scheduleRefresh()
      break
    }
    case 'session.cleared': {
      state.messages = []
      state.artifacts = []
      state.live.streams = {}
      state.live.reasoning = {}
      state.live.tools = {}
      state.live.toolOrder = []
      state.activity = { tools: {}, steps: 0, startedAt: 0, endedAt: 0 }
      break
    }
    case 'session.updated': {
      if (state.session) state.session = { ...state.session, ...payload }
      updateSessionInList({ id: sessionId, ...payload })
      break
    }
    case 'session.created': {
      loadSessions()
      break
    }
    case 'session.hidden': {
      loadSessions()
      break
    }
    case 'context.compact':
      pushNotice({ kind: 'context', text: t('notice.contextCompacted', { count: payload.messages || payload.compacted || 0 }) })
      break
    case 'repair.loop':
      pushNotice({ kind: 'repair', text: t('notice.repairLoop', { count: payload.failures, seen: payload.seen }) })
      break
    case 'verify.nudge':
      pushNotice({ kind: 'verify', text: t('notice.verify') })
      break
    case 'output.truncated':
      pushNotice({ kind: 'context', text: t('notice.truncated') })
      break
    case 'checkpoint.rollover':
      pushNotice({ kind: 'checkpoint', text: t('notice.checkpoint', { segment: payload.segment }) })
      break
    case 'instruction.merged':
      pushNotice({ kind: 'merge', text: t('notice.merge', { count: payload.count }) })
      break
    case 'session.resume':
      pushNotice({ kind: 'resume', text: t('notice.resumed') })
      break
    case 'model.fallback':
      pushNotice({ kind: 'model', text: t('notice.modelFallback', { fallbacks: (payload.fallbacks || []).join(', ') }) })
      break
    default:
      break
  }
}

function stopSessionStream() {
  if (sessionStream) {
    sessionStream.close()
    sessionStream = null
  }
}

function startSessionStream(sessionId, afterId = 0) {
  stopSessionStream()
  if (!sessionId) return
  state.connection = 'connecting'
  sessionStream = createSessionStream({
    sessionId,
    afterId,
    onEvent: applyEvent,
    onStatus: (value) => {
      state.connection = value === 'connected' ? 'connected' : 'connecting'
    },
    onEnd: (event) => {
      sessionStream = null
      state.connection = 'connected'
      if (['done', 'error'].includes(event.status)) {
        scheduleRefresh()
        loadSessions().catch(() => {})
      }
    }
  })
}

function scheduleRefresh() {
  clearTimeout(refreshTimer)
  refreshTimer = setTimeout(() => refreshCurrent(), 220)
}

let activityToken = 0
export async function loadActivity(sessionId) {
  if (!sessionId) return
  const token = ++activityToken
  try {
    // Only the most recent run's recent events matter for the activity summary.
    // Replaying the whole session (thousands of events) was a major switch cost.
    const events = await api.events(sessionId, 0, {
      run_id: state.runs?.[0]?.id || '',
      tail: true,
      limit: ACTIVITY_EVENT_LIMIT
    })
    if (token !== activityToken || !Array.isArray(events)) return
    if (state.currentId !== sessionId) return
    const tools = {}
    let steps = 0
    let startedAt = 0
    let endedAt = 0
    const stamp = (value) => {
      const t = Date.parse(String(value || '').replace(' ', 'T'))
      return Number.isFinite(t) ? t : 0
    }
    for (const event of events) {
      const payload = event.payload || {}
      const at = stamp(event.created_at)
      if (event.type === 'tool.start') {
        steps++
        const id = payload.call_id
        if (!id) continue
        tools[id] = {
          ...(tools[id] || {}),
          call_id: id,
          tool: payload.tool,
          args: payload.args || {},
          status: 'running',
          startedAt: at
        }
        if (!startedAt && at) startedAt = at
      } else if (event.type === 'tool.end') {
        const id = payload.call_id
        if (!id) continue
        tools[id] = {
          ...(tools[id] || {}),
          call_id: id,
          tool: payload.tool,
          ok: payload.ok,
          summary: payload.summary,
          error: payload.error,
          ms: payload.ms,
          status: payload.ok ? 'done' : 'error',
          endedAt: at
        }
        if (at > endedAt) endedAt = at
      } else if (event.type === 'session.status') {
        if (payload.status === 'running' && !startedAt && at) startedAt = at
        if ((payload.status === 'done' || payload.status === 'error') && at) endedAt = at
      }
    }
    const merged = { ...tools }
    for (const [id, item] of Object.entries(state.activity.tools || {})) {
      merged[id] = { ...(tools[id] || {}), ...item }
    }
    state.activity = {
      tools: merged,
      steps: Math.max(steps, state.activity.steps || 0),
      startedAt: startedAt || state.activity.startedAt || 0,
      endedAt: Math.max(endedAt, state.activity.endedAt || 0)
    }
  } catch {
    /* activity timeline is best-effort */
  }
}

function clearCurrentSession() {
  stopSessionStream()
  requestToken++
  state.currentId = ''
  state.session = null
  state.messages = []
  state.hasMoreMessages = false
  state.loadingEarlier = false
  state.switching = false
  state.artifacts = []
  state.plan = { title: '', steps: [] }
  state.live.approvals = []
  state.runs = []
  state.activity = { tools: {}, steps: 0, startedAt: 0, endedAt: 0 }
  localStorage.removeItem(LAST_SESSION)
}

export function requestAccountSetup() {
  state.authSetupOpen = true
}

export function dismissAccountSetup() {
  state.authSetupOpen = false
}

export function dismissWorkspaceSetup() {
  state.workspaceSetupOpen = false
}

export function requestWorkspaceSetup() {
  state.workspaceSetupOpen = true
}

export async function checkAuth() {
  try {
    const data = await api.authStatus()
    applyAuth(data)
  } catch {
    applyAuth({ checked: true, enabled: false, configured: false, active: false, authenticated: false, username: '', max_failures: 5 })
  }
  return state.auth
}

function applyAuth(data) {
  state.auth = {
    checked: true,
    enabled: !!data.enabled,
    configured: !!data.configured,
    active: !!data.active,
    authenticated: !!data.authenticated,
    username: data.username || '',
    maxFailures: Number(data.max_failures) || 5,
    lockSeconds: Number(data.lock_seconds) || 300,
    loading: false
  }
}

export function markUnauthorized() {
  clearAuthToken()
  state.auth = { ...state.auth, checked: true, enabled: true, configured: true, active: true, authenticated: false, loading: false }
  state.booted = true
  state.loading = false
  state.accountOpen = false
  state.authSetupOpen = false
  state.sessions = []
  state.session = null
  state.messages = []
  state.artifacts = []
  state.plugins = []
  state.skills = []
}

export async function loginAccount(username, password) {
  state.auth.loading = true
  try {
    const data = await api.authLogin({ username, password })
    if (data.token) setAuthToken(data.token)
    applyAuth(data)
    state.booted = false
    await boot()
    return data
  } finally {
    state.auth.loading = false
  }
}

export async function setupAccount(username, password) {
  state.auth.loading = true
  try {
    const data = await api.authSetup({ username, password })
    if (data.token) setAuthToken(data.token)
    state.authSetupOpen = false
    applyAuth(data)
    state.booted = false
    await boot()
    return data
  } finally {
    state.auth.loading = false
  }
}

export async function changeAccount(body) {
  const data = await api.authChange(body)
  if (data.token) setAuthToken(data.token)
  applyAuth(data)
  toast(t('auth.changed'), 'good')
  return data
}

export async function saveAuthPolicy(maxFailures) {
  const data = await api.authPolicy({ max_failures: maxFailures })
  applyAuth(data)
  toast(t('auth.policySaved'), 'good')
  return data
}

export async function logoutAccount() {
  try {
    await api.authLogout()
  } catch {
    /* ignore network errors on logout */
  }
  clearAuthToken()
  state.auth = { ...state.auth, authenticated: false, active: state.auth.enabled && state.auth.configured }
  state.accountOpen = false
  state.booted = true
  state.sessions = []
  state.session = null
  state.messages = []
  state.artifacts = []
  state.plugins = []
  state.skills = []
  toast(t('auth.loggedOut'), 'info')
}

export async function boot() {
  if (state.booted) return
  setLocale(i18n.locale, false)
  setTheme(state.theme, false)
  state.loading = true
  if (!state.auth.checked) await checkAuth()
  if (state.auth.enabled && state.auth.configured && !state.auth.authenticated) {
    state.loading = false
    state.booted = true
    return
  }
  try {
    const [health, models, plugins, skills, settings] = await Promise.all([
      api.health(),
      api.models(),
      api.plugins(),
      api.skills(),
      api.settings()
    ])
    state.health = health
    state.models = models.providers || models || []
    state.plugins = plugins
    state.skills = skills
    state.settings = { ...state.settings, ...settings }
    await loadRemoteManagement()
    await loadSessions()
    const routed = sessionIdFromHash()
    if (routed && state.sessions.some((item) => item.id === routed)) {
      await selectSession(routed, false)
    } else if (state.currentId && state.sessions.some((item) => item.id === state.currentId)) {
      await selectSession(state.currentId, false)
    } else if (state.sessions.length) {
      const visible = state.sessions.find((item) => !item.hidden)
      if (visible) await selectSession(visible.id, false)
    }
    if (!state.settings.default_workspace) state.workspaceSetupOpen = true
    loadUsage().catch(() => {})
    loadSupervisor().catch(() => {})
    state.connection = 'connected'
    if (!sessionPollTimer) {
      sessionPollTimer = setInterval(() => {
        loadSessions().catch(() => {})
      }, 8000)
    }
  } catch (error) {
    state.connection = 'disconnected'
    toast(t('toast.apiUnreachable', { message: error.message }), 'bad', 8000)
  } finally {
    state.loading = false
    state.booted = true
  }
}

export async function loadSessions() {
  const sessions = await api.sessions(true)
  state.sessions = sessions
  const valid = new Set(sessions.map((item) => item.id))
  const nextTabs = state.openSessionIds.filter((id) => valid.has(id))
  if (nextTabs.length !== state.openSessionIds.length) {
    state.openSessionIds = nextTabs
    persistOpenTabs()
  }
  return sessions
}

export async function selectSession(id, navigate = true) {
  if (!id) return
  stopSessionStream()
  state.currentId = id
  localStorage.setItem(LAST_SESSION, id)
  ensureOpenTab(id)
  const token = ++requestToken
  state.live.streams = {}
  state.live.reasoning = {}
  state.live.tools = {}
  state.live.toolOrder = []
  state.live.approvals = []
  state.live.notices = []
  state.live.route = null
  state.live.skills = []
  state.runs = []
  state.activity = { tools: {}, steps: 0, startedAt: 0, endedAt: 0 }
  state.selectedFile = null
  state.fileContent = null
  state.diffText = ''
  state.activeRightTab = 'overview'
  // Paint the target session immediately (title/status/tab) and release the
  // previous session's DOM before the network round-trips finish. Long sessions
  // can carry hundreds of messages; keeping them mounted makes switching lag.
  const listed = state.sessions.find((item) => item.id === id)
  state.session = listed ? { ...listed } : null
  state.messages = []
  state.hasMoreMessages = false
  state.loadingEarlier = false
  state.switching = true
  try {
    // Fetch the session, a bounded window of messages, and artifacts in parallel
    // instead of three sequential round-trips.
    const [detail, messages, artifacts] = await Promise.all([
      api.session(id),
      api.messages(id, { limit: MESSAGE_PAGE }),
      api.artifacts(id)
    ])
    if (token !== requestToken) return
    state.session = detail.session
    state.session.pending = detail.session.pending
    state.runs = detail.runs || []
    if (!state.session.first_question && listed?.first_question) {
      state.session.first_question = listed.first_question
    }
    state.plan = safeJson(detail.session.plan, { title: '', steps: [] })
    if (detail.session.pending) state.live.approvals = [detail.session.pending]
    updateSessionInList(detail.session)
    const rows = messages || []
    state.messages = rows
    state.hasMoreMessages = rows.length >= MESSAGE_PAGE
    state.artifacts = artifacts
    state.switching = false
    state.scrollTick++
    loadActivity(id).catch(() => {})
    startSessionStream(id, detail.session.last_event_id || 0)
    if (detail.session.workspace) {
      Promise.all([loadTree(), loadChanges()]).catch(() => {})
    } else {
      state.tree = []
      state.changes = []
    }
  } catch (error) {
    if (token !== requestToken) return
    state.switching = false
    toast(error.message, 'bad')
  }
}

export async function loadEarlierMessages() {
  const id = state.currentId
  if (!id || state.loadingEarlier || !state.hasMoreMessages) return
  const first = state.messages.find((item) => item.seq !== undefined && item.seq !== null)
  const before = first ? Number(first.seq) : 0
  if (!before) {
    state.hasMoreMessages = false
    return
  }
  const token = requestToken
  state.loadingEarlier = true
  try {
    const older = await api.messages(id, { limit: MESSAGE_PAGE, before })
    if (token !== requestToken || state.currentId !== id) return
    if (!older || !older.length) {
      state.hasMoreMessages = false
      return
    }
    state.messages = [...older, ...state.messages]
    state.hasMoreMessages = older.length >= MESSAGE_PAGE
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    if (token === requestToken) state.loadingEarlier = false
  }
}

export async function closeSessionTab(id) {
  const index = state.openSessionIds.indexOf(id)
  if (index < 0) return
  state.openSessionIds.splice(index, 1)
  persistOpenTabs()
  if (state.currentId !== id) return
  const nextId = state.openSessionIds[index] || state.openSessionIds[index - 1] || ''
  if (nextId) await selectSession(nextId)
  else clearCurrentSession()
}

export function reorderSessionTabs(fromId, toId, edge = 'before') {
  if (!fromId || !toId || fromId === toId) return
  const from = state.openSessionIds.indexOf(fromId)
  if (from < 0) return
  state.openSessionIds.splice(from, 1)
  let target = state.openSessionIds.indexOf(toId)
  if (target < 0) {
    state.openSessionIds.splice(Math.min(from, state.openSessionIds.length), 0, fromId)
    persistOpenTabs()
    return
  }
  if (edge === 'after') target += 1
  state.openSessionIds.splice(target, 0, fromId)
  persistOpenTabs()
}

export async function refreshCurrent() {
  if (!state.currentId) return
  try {
    const detail = await api.session(state.currentId)
    state.session = detail.session
    updateSessionInList(detail.session)
    state.plan = safeJson(detail.session.plan, { title: '', steps: [] })
    const limit = Math.max(MESSAGE_PAGE, state.messages.length)
    const [messages, artifacts] = await Promise.all([
      api.messages(state.currentId, { limit }),
      api.artifacts(state.currentId)
    ])
    state.messages = messages
    state.artifacts = artifacts
    if (detail.session.workspace) loadChanges().catch(() => {})
    if (['done', 'error', 'idle'].includes(detail.session.status)) {
      state.live.streams = {}
      state.live.reasoning = {}
      state.live.tools = {}
      state.live.toolOrder = []
      state.live.approvals = []
    }
    state.scrollTick++
  } catch {
    /* ignore transient refresh errors */
  }
}

function parseListValue(value) {
  if (Array.isArray(value)) return [...value]
  if (typeof value === 'string' && value) {
    try {
      const parsed = JSON.parse(value)
      return Array.isArray(parsed) ? parsed : []
    } catch {
      return []
    }
  }
  return []
}

export function recentSessionSettings() {
  const seen = new Set()
  const candidates = []
  for (const item of [state.session, ...state.sessions]) {
    if (!item || !item.id || item.hidden || seen.has(item.id)) continue
    seen.add(item.id)
    candidates.push(item)
  }
  candidates.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')))
  return candidates[0] || null
}

export async function startNewTask() {
  const recent = recentSessionSettings()
  const workspace = String(recent?.workspace || state.settings.default_workspace || '').trim()
  if (!recent || !workspace) {
    state.newTaskOpen = true
    return null
  }
  try {
    return await createSession({
      kind: recent.kind || 'auto',
      workspace,
      provider: recent.provider || '',
      model: recent.model || '',
      thinking: recent.thinking || '',
      gate_mode: recent.gate_mode || '',
      gate_allow: parseListValue(recent.gate_allow),
      skills: parseListValue(recent.skills)
    })
  } catch (error) {
    toast(error.message, 'bad')
    state.newTaskOpen = true
    return null
  }
}

export async function createSession(payload = {}) {
  const workspace = payload.workspace ?? state.settings.default_workspace ?? ''
  const body = {
    kind: payload.kind || 'auto',
    title: payload.title || '',
    provider: payload.provider || '',
    model: payload.model || '',
    workspace,
    thinking: payload.thinking || '',
    gate_mode: payload.gate_mode || '',
    gate_allow: payload.gate_allow || [],
    skills: payload.skills || []
  }
  const session = await api.createSession(body)
  state.sessions.unshift(session)
  await selectSession(session.id)
  return session
}

export async function sendMessage(content) {
  const text = (content || '').trim()
  if (!text || state.busy.sending) return
  let session = currentSession.value
  if (!session) {
    session = await createSession({ kind: 'auto' })
  }
  const streamAfterId = sessionStream?.lastId ?? state.session?.last_event_id ?? 0
  const firstQuestion = !session.first_question
  state.busy.sending = true
  try {
    const result = await api.sendMessage(session.id, text, i18n.locale)
    if (firstQuestion) {
      if (state.session && !state.session.first_question) {
        state.session = { ...state.session, first_question: text }
      }
      const listed = state.sessions.find((item) => item.id === session.id)
      if (listed && !listed.first_question) {
        updateSessionInList({ id: session.id, first_question: text })
      }
    }
    startSessionStream(session.id, streamAfterId)
    if (!state.messages.some((item) => item.id === result.msg_id)) {
      state.messages.push({ id: result.msg_id, role: 'user', content: text, created_at: new Date().toISOString() })
    }
    if (!result.appended) {
      state.session = { ...state.session, status: 'queued' }
    }
    state.scrollTick++
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    state.busy.sending = false
  }
}

export async function stopSession() {
  if (!state.currentId) return
  try {
    await api.cancel(state.currentId)
    toast(t('toast.stopRequested'), 'info')
  } catch (error) {
    toast(error.message, 'bad')
  }
}

export async function resumeSession() {
  if (!state.currentId) return
  try {
    const result = await api.resume(state.currentId)
    if (!result.resumed) toast(t('toast.nothingToResume'), 'warn')
  } catch (error) {
    toast(error.message, 'bad')
  }
}

export async function answerQuestion(answer) {
  return approveCurrent(true, String(answer ?? '').trim())
}

export async function approveCurrent(approved, reason = '') {
  const approval = activeApproval.value
  if (!approval) return
  try {
    await api.resolveApproval(approval.approval_id, approved, reason)
    state.live.approvals = state.live.approvals.filter((item) => item.approval_id !== approval.approval_id)
    if (state.session) state.session.pending = null
  } catch (error) {
    toast(error.message, 'bad')
  }
}

export async function hideSession(id) {
  const target = id || state.currentId
  if (!target) return
  await api.hideSession(target)
  dropOpenTab(target)
  await loadSessions()
  if (state.currentId !== target) return
  const openTab = state.openSessionIds.find((tabId) => state.sessions.some((item) => item.id === tabId))
  const visible = openTab || state.sessions.find((item) => !item.hidden)?.id || ''
  if (visible) await selectSession(visible)
  else clearCurrentSession()
}

export async function purgeSession(id) {
  const target = id || state.currentId
  if (!target) return
  await api.purgeSession(target)
  toast(t('toast.sessionDeleted'), 'good')
  dropOpenTab(target)
  await loadSessions()
  if (state.currentId !== target) return
  const next = state.openSessionIds.find((tabId) => state.sessions.some((item) => item.id === tabId)) || ''
  if (next) await selectSession(next)
  else clearCurrentSession()
}

export async function clearMessages() {
  if (!state.currentId) return
  await api.clearSession(state.currentId)
  state.messages = []
  state.artifacts = []
  toast(t('toast.conversationCleared'), 'good')
}

export async function purgeAllSessions() {
  const result = await api.purgeAllSessions()
  state.openSessionIds = []
  persistOpenTabs()
  clearCurrentSession()
  await loadSessions()
  toast(t('toast.allSessionsDeleted', { count: result?.purged ?? 0 }), 'good')
  return result
}

export async function renameSession(title) {
  if (!state.currentId || !title) return
  await api.patchSession(state.currentId, { title })
  state.session = { ...state.session, title }
  updateSessionInList({ id: state.currentId, title })
}

export async function patchSession(body) {
  if (!state.currentId) return
  try {
    const updated = await api.patchSession(state.currentId, body)
    state.session = { ...state.session, ...updated }
    updateSessionInList(updated)
    return updated
  } catch (error) {
    toast(error.message, 'bad')
    throw error
  }
}

export async function loadTree() {
  const workspace = currentSession.value?.workspace
  if (!workspace) {
    state.tree = []
    return
  }
  const result = await api.tree(workspace)
  state.tree = result.items || []
}

export async function loadChanges() {
  const workspace = currentSession.value?.workspace
  if (!workspace) {
    state.changes = []
    return
  }
  state.changes = await api.changes(workspace)
}

export async function openFile(path) {
  const workspace = currentSession.value?.workspace
  if (!workspace) return
  state.busy.loadingFile = true
  state.activeRightTab = 'files'
  try {
    state.fileContent = await api.file(workspace, path)
    state.selectedFile = path
  } catch (error) {
    toast(error.message, 'bad')
  } finally {
    state.busy.loadingFile = false
  }
}

export async function openDiff(path = '') {
  const workspace = currentSession.value?.workspace
  if (!workspace) return
  try {
    const result = await api.diff(workspace, path)
    state.diffText = result.diff || ''
    state.diffPath = path || '(all changes)'
    state.activeRightTab = 'changes'
  } catch (error) {
    toast(error.message, 'bad')
  }
}

export async function loadArtifacts() {
  if (!state.currentId) return
  state.artifacts = await api.artifacts(state.currentId)
}

export async function loadSkills() {
  state.skills = await api.skills()
  return state.skills
}

export async function saveSkill(body, originalName = '') {
  if (originalName) await api.updateSkill(originalName, body)
  else await api.createSkill(body)
  await loadSkills()
  toast(t('toast.skillSaved'), 'good')
}

export async function deleteSkill(name) {
  await api.deleteSkill(name)
  await loadSkills()
  toast(t('toast.skillDeleted'), 'good')
}

export async function loadPlugins() {
  state.plugins = await api.plugins()
  return state.plugins
}

function remotePluginReady() {
  const plugin = state.plugins.find((item) => item.name === 'remote-management')
  return !!(plugin && plugin.enabled && plugin.loaded && !plugin.error)
}

export async function loadRemoteManagement() {
  if (!remotePluginReady()) {
    state.remote = { loading: false, enabled: false, error: '', instance: null, keys: [], incoming: [], outgoing: [], current: null }
    return state.remote
  }
  state.remote.loading = true
  try {
    const data = await api.remoteOverview()
    state.remote = {
      loading: false,
      enabled: true,
      error: '',
      instance: data.instance || null,
      keys: data.keys || [],
      incoming: data.incoming || [],
      outgoing: data.outgoing || [],
      current: state.remote.current
    }
  } catch (error) {
    state.remote = {
      ...state.remote,
      loading: false,
      enabled: error.code !== 404,
      error: error.message || ''
    }
  }
  return state.remote
}

export async function saveRemoteSettings(body) {
  const data = await api.remoteSettings(body)
  await loadRemoteManagement()
  toast(t('remote.settingsSaved'), 'good')
  return data
}

export async function createRemoteKey(label) {
  const data = await api.remoteCreateKey({ label })
  await loadRemoteManagement()
  toast(t('remote.keyCreated'), 'good')
  return data
}

export async function deleteRemoteKey(id) {
  await api.remoteDeleteKey(id)
  await loadRemoteManagement()
  toast(t('remote.keyDeleted'), 'info')
}

export async function remoteIncomingAction(id, action) {
  const data = await api.remoteIncomingAction(id, action)
  await loadRemoteManagement()
  return data
}

export async function deleteRemoteIncoming(id) {
  await api.remoteDeleteIncoming(id)
  await loadRemoteManagement()
  toast(t('remote.requestDeleted'), 'info')
}

export async function addRemoteSystem(body) {
  const data = await api.remoteAddSystem(body)
  await loadRemoteManagement()
  toast(t('remote.requestSent'), 'good')
  return data
}

export async function refreshRemoteSystems() {
  const data = await api.remoteRefreshSystems()
  state.remote.outgoing = data || []
  return data
}

export async function loadRemoteSystem(id) {
  const data = await api.remoteSystem(id)
  state.remote.current = data
  return data
}

export async function refreshRemoteSystem(id) {
  const data = await api.remoteRefreshSystem(id)
  state.remote.current = data
  await loadRemoteManagement()
  return data
}

export async function remoteSystemAction(id, action) {
  const data = await api.remoteSystemAction(id, action)
  state.remote.current = data
  await loadRemoteManagement()
  return data
}

export async function deleteRemoteSystem(id) {
  await api.remoteDeleteSystem(id)
  state.remote.current = null
  await loadRemoteManagement()
  toast(t('remote.systemRemoved'), 'info')
}

export async function togglePlugin(name, enabled) {
  const result = await api.togglePlugin(name, enabled)
  await loadPlugins()
  if (name === 'user-account') await checkAuth()
  if (name === 'remote-management') await loadRemoteManagement()
  toast(result.message || t('toast.pluginSaved'), result.restart_required ? 'warn' : 'good', 7000)
  return result
}

const DEFAULT_CENTER_URL = 'https://hao-yuan.conductorer.com'
const LEGACY_CENTER_URLS = ['http://129.226.222.76:8042', 'http://127.0.0.1:8180']

function storedCenterUrl() {
  const stored = (localStorage.getItem('hy.pluginCenterUrl') || '').trim()
  if (LEGACY_CENTER_URLS.includes(stored)) {
    localStorage.setItem('hy.pluginCenterUrl', DEFAULT_CENTER_URL)
    return DEFAULT_CENTER_URL
  }
  return stored
}

export async function loadMarketplace(center = '') {
  const target = (center || storedCenterUrl() || DEFAULT_CENTER_URL).trim()
  state.market.loading = true
  try {
    const data = await api.marketplace(target)
    const resolved = data.center_url || target || ''
    if (resolved) localStorage.setItem('hy.pluginCenterUrl', resolved)
    state.market = {
      loading: false,
      online: !!data.online,
      error: data.error || '',
      centerUrl: resolved,
      plugins: data.plugins || []
    }
  } catch (error) {
    state.market = { loading: false, online: false, error: error.message, centerUrl: target, plugins: [] }
  }
  return state.market
}

export async function installPluginFromCenter(plugin) {
  const data = await api.installPlugin({ name: plugin.name, center_url: state.market.centerUrl })
  await Promise.all([loadPlugins(), loadMarketplace()])
  await checkAuth()
  await loadRemoteManagement()
  toast(data.message || t('plugins.installSuccess'), 'good', 6500)
  return data
}

export async function uploadPluginPackage(file) {
  const data = await api.uploadPlugin(file)
  await Promise.all([loadPlugins(), loadMarketplace()])
  await checkAuth()
  await loadRemoteManagement()
  toast(data.message || t('plugins.uploadSuccess'), 'good', 6500)
  return data
}

export async function uninstallPluginByName(name) {
  const data = await api.uninstallPlugin(name)
  await Promise.all([loadPlugins(), loadMarketplace()])
  await checkAuth()
  await loadRemoteManagement()
  toast(t('plugins.uninstalled'), 'info')
  return data
}

export async function loadSettings() {
  state.settings = await api.settings()
  return state.settings
}

export async function saveGate(mode, allow) {
  const result = await api.saveGate(mode, allow)
  state.settings = { ...state.settings, gate: result }
  toast(t('settings.policySaved'), 'good')
}

export async function saveDefaultWorkspace(workspace) {
  const result = await api.saveWorkspace(workspace)
  state.settings = { ...state.settings, default_workspace: result.workspace }
  toast(t('settings.workspaceSaved'), 'good')
}

export async function saveSetting(key, value) {
  await api.saveSetting(key, value)
  state.settings = { ...state.settings, [key]: value }
}

export async function loadUsage() {
  const [today, daily, byModel] = await Promise.all([api.usageToday(), api.usageDaily(14), api.usageByModel()])
  state.usageToday = today
  state.usageDaily = daily
  state.usageByModel = byModel
}

export async function loadSupervisor() {
  state.supervisor = await api.supervisorOverview()
  return state.supervisor
}

export async function supervisorAct(sessionId, action) {
  const result = await api.supervisorAct(sessionId, action)
  toast(result.ok ? t('toast.actionDone') : t('toast.actionFailed'), result.ok ? 'good' : 'warn')
  await loadSupervisor()
}

export async function supervisorChat(message, chatId = '') {
  return api.supervisorChat(message, chatId)
}

export async function loadOrchestrations() {
  state.orchestrations = await api.orchestrations()
  return state.orchestrations
}

export async function createOrchestration(body) {
  const data = await api.createOrchestration(body)
  await loadOrchestrations()
  return data
}

export async function advanceOrchestration(id) {
  const data = await api.advanceOrchestration(id)
  await loadOrchestrations()
  return data
}

export async function mergeOrchestration(id) {
  const data = await api.mergeOrchestration(id)
  await loadOrchestrations()
  return data
}

export function navigateTo(sessionId) {
  state.currentId = sessionId
  localStorage.setItem(LAST_SESSION, sessionId)
  window.location.hash = `#/s/${encodeURIComponent(sessionId)}`
  selectSession(sessionId, false)
}
