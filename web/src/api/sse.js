export function createSessionStream({ sessionId, afterId = 0, onEvent, onStatus, onEnd }) {
  let source = null
  let closed = false
  let retry = 0
  let timer = null
  let lastId = Number(afterId) || 0

  function normalize(raw) {
    return {
      id: raw.id,
      session_id: raw.session_id || sessionId,
      event: raw.type || raw.event,
      payload: raw.payload || {},
      time: raw.created_at || raw.time,
      run_id: raw.run_id || ''
    }
  }

  function connect() {
    if (closed) return
    onStatus?.('connecting')
    const url = `/api/sessions/${encodeURIComponent(sessionId)}/stream?after_id=${lastId}`
    source = new EventSource(url)
    source.onopen = () => {
      retry = 0
      onStatus?.('connected')
    }
    source.onmessage = (message) => {
      let raw
      try {
        raw = JSON.parse(message.data)
      } catch {
        return
      }
      if (raw.type === 'stream.end') {
        onStatus?.('connected')
        onEnd?.(raw)
        close()
        return
      }
      if (raw.id !== undefined) lastId = Number(raw.id) || lastId
      onEvent?.(normalize(raw))
    }
    source.onerror = () => {
      if (closed) return
      source?.close()
      source = null
      retry += 1
      onStatus?.('connecting')
      timer = setTimeout(connect, Math.min(5000, 400 * retry))
    }
  }

  function close() {
    closed = true
    clearTimeout(timer)
    source?.close()
    source = null
  }

  connect()

  return {
    close,
    get lastId() {
      return lastId
    },
    get closed() {
      return closed
    }
  }
}
