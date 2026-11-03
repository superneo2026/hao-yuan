import { getAuthToken, getRemoteToken } from './client'

export function createSocket({ onEvent, onStatus }) {
  let socket = null
  let closedByUser = false
  let retry = 0
  let timer = null
  let heartbeat = null
  const queue = []

  function status(value) {
    onStatus?.(value)
  }

  function connect() {
    if (closedByUser) return
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const token = getAuthToken()
    const remoteToken = getRemoteToken()
    const params = []
    if (token) params.push(`token=${encodeURIComponent(token)}`)
    if (remoteToken) params.push(`remote_token=${encodeURIComponent(remoteToken)}`)
    const url = `${protocol}://${location.host}/ws${params.length ? `?${params.join('&')}` : ''}`
    status('connecting')
    try {
      socket = new WebSocket(url)
    } catch {
      schedule()
      return
    }
    socket.onopen = () => {
      retry = 0
      status('connected')
      while (queue.length) {
        const payload = queue.shift()
        socket.send(payload)
      }
      clearInterval(heartbeat)
      heartbeat = setInterval(() => send({ type: 'ping' }), 20000)
    }
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data)
        if (event.event === 'pong') return
        onEvent?.(event)
      } catch {
        /* ignore malformed frames */
      }
    }
    socket.onclose = () => {
      clearInterval(heartbeat)
      status('disconnected')
      schedule()
    }
    socket.onerror = () => {
      try { socket.close() } catch { /* ignore */ }
    }
  }

  function schedule() {
    if (closedByUser) return
    clearTimeout(timer)
    retry += 1
    const delay = Math.min(12000, 500 * Math.pow(1.7, Math.min(retry, 7)))
    timer = setTimeout(connect, delay)
  }

  function send(payload) {
    const data = JSON.stringify(payload)
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(data)
      return true
    }
    if (queue.length < 50) queue.push(data)
    return false
  }

  function close() {
    closedByUser = true
    clearTimeout(timer)
    clearInterval(heartbeat)
    try { socket?.close() } catch { /* ignore */ }
  }

  connect()
  return { send, close, status: () => status }
}
