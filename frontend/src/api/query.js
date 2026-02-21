import api, { apiHeaders, API_BASE } from './client'

export async function sendQuery(question, { sessionId, topK = 8, collection, docIds, userId, forceWebSearch = false }) {
  const body = { question, session_id: sessionId, top_k: topK, force_web_search: forceWebSearch }
  if (collection) body.collection = collection
  if (docIds) body.doc_ids = docIds
  const resp = await api.post('/query', body, { headers: apiHeaders(userId) })
  return resp.data
}

export async function sendChunkContextQuery(question, { sourceType, docId, chunkIndex, url, sessionId, userId }) {
  const body = {
    question,
    source_type: sourceType,
    session_id: sessionId,
  }
  if (docId) body.doc_id = docId
  if (chunkIndex != null) body.chunk_index = chunkIndex
  if (url) body.url = url
  const resp = await api.post('/query/chunk-context', body, { headers: apiHeaders(userId) })
  return resp.data
}

export async function sendAskAI(question, { userId }) {
  const body = { question }
  const resp = await api.post('/query/ask-ai', body, { headers: apiHeaders(userId) })
  return resp.data
}

/**
 * Stream a query via SSE (POST /query/stream).
 * Uses fetch + ReadableStream since EventSource only supports GET.
 */
export async function sendQueryStream(question, { sessionId, topK = 8, collection, docIds, userId, forceWebSearch = false }, { onSources, onToken, onDone, onError }) {
  const body = { question, session_id: sessionId, top_k: topK, force_web_search: forceWebSearch }
  if (collection) body.collection = collection
  if (docIds) body.doc_ids = docIds

  const response = await fetch(`${API_BASE}/query/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId,
    },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Stream failed' }))
    throw new Error(err.detail || `HTTP ${response.status}`)
  }

  await _consumeSSE(response, { onSources, onToken, onDone, onError })
}

/**
 * Stream an Ask AI response via SSE (POST /query/ask-ai/stream).
 */
export async function sendAskAIStream(question, { userId }, { onToken, onDone, onError }) {
  const response = await fetch(`${API_BASE}/query/ask-ai/stream`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-Id': userId,
    },
    body: JSON.stringify({ question }),
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Stream failed' }))
    throw new Error(err.detail || `HTTP ${response.status}`)
  }

  await _consumeSSE(response, { onToken, onDone, onError })
}

/**
 * Parse SSE events from a fetch Response with ReadableStream.
 */
async function _consumeSSE(response, { onSources, onToken, onDone, onError }) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // Normalize CRLF to LF and parse SSE events (separated by blank lines)
    buffer = buffer.replace(/\r\n/g, '\n')
    const parts = buffer.split('\n\n')
    buffer = parts.pop() // Keep incomplete part

    for (const part of parts) {
      if (!part.trim()) continue
      let eventType = null
      let eventData = null

      for (const line of part.split('\n')) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          eventData = line.slice(6)
        }
      }

      if (!eventType || !eventData) continue

      try {
        const data = JSON.parse(eventData)
        if (eventType === 'sources') onSources?.(data)
        else if (eventType === 'token') onToken?.(data.token)
        else if (eventType === 'done') onDone?.(data)
        else if (eventType === 'error') onError?.(data)
      } catch {
        // Skip malformed events
      }
    }
  }
}
