import { computed, reactive } from 'vue'
import { api } from '../api/client'
import { createSessionStream } from '../api/sse'
import { i18n, setLocale, t } from '../i18n'

const LAST_SESSION = 'hy.lastSession'
const THEME = 'hy.theme.v2'
const SIDEBAR = 'hy.sidebar'

function safeJson(text, fallback) {
  try {
    const value = JSON.parse(text || '')
    return value ?? fallback
  } catch {
    return fallback
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
  session: null,
  messages: [],
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
  sidebarCollapsed: localStorage.getItem(SIDEBAR) === '1',
  mobileNavOpen: false,
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
      updateSessionInList({ id: sessionId, updated_at: new Date().toISOString() })
    }
    return
  }

  switch (type) {
    case 'session.status': {
      if (state.session) {
        state.session = { ...state.session, status: payload.status, error: payload.error || state.session.error }
      }
      updateSessionInList({ id: sessionId, status: payload.status, error: payload.error })
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
        const id = payload.msg_id
        delete state.live.streams[id]
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
      break
    }
    case 'session.updated': {
      if (state.session) state.session = { ...state.session, ...payload }
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

export async function boot() {
  if (state.booted) return
  setLocale(i18n.locale, false)
  setTheme(state.theme, false)
  state.loading = true
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
    await loadSessions()
    if (state.currentId && state.sessions.some((item) => item.id === state.currentId)) {
      await selectSession(state.currentId, false)
    } else if (state.sessions.length) {
      const visible = state.sessions.find((item) => !item.hidden)
      if (visible) await selectSession(visible.id, false)
    }
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
  return sessions
}

export async function selectSession(id, navigate = true) {
  if (!id) return
  stopSessionStream()
  state.currentId = id
  localStorage.setItem(LAST_SESSION, id)
  const token = ++requestToken
  state.live.streams = {}
  state.live.reasoning = {}
  state.live.tools = {}
  state.live.toolOrder = []
  state.live.approvals = []
  state.live.notices = []
  state.live.route = null
  state.live.skills = []
  state.selectedFile = null
  state.fileContent = null
  state.diffText = ''
  state.activeRightTab = 'overview'
  try {
    const detail = await api.session(id)
    if (token !== requestToken) return
    state.session = detail.session
    state.session.pending = detail.session.pending
    state.plan = safeJson(detail.session.plan, { title: '', steps: [] })
    if (detail.session.pending) state.live.approvals = [detail.session.pending]
    updateSessionInList(detail.session)
    const [messages, artifacts] = await Promise.all([api.messages(id), api.artifacts(id)])
    if (token !== requestToken) return
    state.messages = messages
    state.artifacts = artifacts
    state.scrollTick++
    startSessionStream(id, detail.session.last_event_id || 0)
    if (detail.session.workspace) {
      Promise.all([loadTree(), loadChanges()]).catch(() => {})
    } else {
      state.tree = []
      state.changes = []
    }
  } catch (error) {
    toast(error.message, 'bad')
  }
}

export async function refreshCurrent() {
  if (!state.currentId) return
  try {
    const detail = await api.session(state.currentId)
    state.session = detail.session
    updateSessionInList(detail.session)
    state.plan = safeJson(detail.session.plan, { title: '', steps: [] })
    const [messages, artifacts] = await Promise.all([api.messages(state.currentId), api.artifacts(state.currentId)])
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
  state.busy.sending = true
  try {
    const result = await api.sendMessage(session.id, text)
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
  await loadSessions()
  if (state.currentId === target) {
    const next = state.sessions.find((item) => !item.hidden)
    if (next) await selectSession(next.id)
    else {
      state.currentId = ''
      state.session = null
      state.messages = []
      localStorage.removeItem(LAST_SESSION)
    }
  }
}

export async function purgeSession(id) {
  const target = id || state.currentId
  if (!target) return
  await api.purgeSession(target)
  toast(t('toast.sessionDeleted'), 'good')
  await loadSessions()
  if (state.currentId === target) {
    state.currentId = ''
    state.session = null
    state.messages = []
    localStorage.removeItem(LAST_SESSION)
  }
}

export async function clearMessages() {
  if (!state.currentId) return
  await api.clearSession(state.currentId)
  state.messages = []
  state.artifacts = []
  toast(t('toast.conversationCleared'), 'good')
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

export async function togglePlugin(name, enabled) {
  const result = await api.togglePlugin(name, enabled)
  await loadPlugins()
  toast(t('toast.pluginSaved'), 'warn', 7000)
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
  window.location.hash = '#/'
  selectSession(sessionId)
}
