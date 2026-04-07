import { QueryClient } from '@tanstack/react-query'

const API_BASE = import.meta.env.VITE_API_URL

if (!API_BASE) {
  console.error('VITE_API_URL is not set. Create frontend/.env with VITE_API_URL=http://localhost:<PORT>')
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
})

function headers(userId) {
  return {
    'X-User-Id': userId || 'admin',
    'Content-Type': 'application/json',
  }
}

async function apiFetch(path, options = {}) {
  const resp = await fetch(`${API_BASE}${path}`, options)
  if (!resp.ok) {
    const err = await resp.text().catch(() => resp.statusText)
    throw new Error(`API ${resp.status}: ${err}`)
  }
  return resp.json()
}

// Documents
export const fetchDocuments = (userId) =>
  apiFetch('/documents', { headers: headers(userId) })

export const fetchCollections = (userId) =>
  apiFetch('/documents/collections', { headers: headers(userId) })

export const deleteDocument = (docId, userId) =>
  apiFetch(`/documents/${docId}`, { method: 'DELETE', headers: headers(userId) })

export const fetchDocumentChunks = (docId, page, userId) => {
  const params = page != null ? `?page=${page}` : ''
  return apiFetch(`/documents/${docId}/chunks${params}`, { headers: headers(userId) })
}

// Graph
export const fetchGraphDocuments = (userId) =>
  apiFetch('/graph/documents', { headers: headers(userId) })

export const fetchGraphNodes = (docId, edgeTypes, userId) => {
  const params = `?doc_id=${docId}&edge_types=${edgeTypes || 'follows,co_located,describes,references,similar_to'}`
  return apiFetch(`/graph/nodes${params}`, { headers: headers(userId) })
}

export const fetchGraphNeighbors = (docId, chunkIndex, hops, userId) =>
  apiFetch(`/graph/neighbors?doc_id=${docId}&chunk_index=${chunkIndex}&hops=${hops || 1}`, { headers: headers(userId) })

// Query
export const sendQuery = (question, options, userId) =>
  apiFetch('/query', {
    method: 'POST',
    headers: headers(userId),
    body: JSON.stringify({ question, ...options }),
  })

// Sessions
export const fetchSessions = (userId, scopeType, scopeValue) => {
  let params = ''
  if (scopeType && scopeValue) params = `?scope_type=${encodeURIComponent(scopeType)}&scope_value=${encodeURIComponent(scopeValue)}`
  else if (scopeType === 'global') params = '?scope_type=global'
  return apiFetch(`/sessions${params}`, { headers: headers(userId) })
}

export const fetchSessionMessages = (sessionId, userId) =>
  apiFetch(`/sessions/${sessionId}/messages`, { headers: headers(userId) })

// Users
export const fetchUsers = () => apiFetch('/users')

// Health
export const fetchHealth = () => apiFetch('/health')
