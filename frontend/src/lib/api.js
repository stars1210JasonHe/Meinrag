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

// Documents.
//
// `opts` (all optional):
//   - search: string — server-side smart search. Short queries (<= 3 words /
//     <= 20 chars) hit SQL ILIKE; longer queries are routed through the
//     chunk-summary FAISS index for semantic matching.
//   - collection: string — restrict to a saved collection.
//   - limit, offset: pagination. Server clamps limit to <= 200.
export const fetchDocuments = (userId, opts = {}) => {
  const params = new URLSearchParams()
  if (opts.search) params.set('search', opts.search)
  if (opts.collection) params.set('collection', opts.collection)
  if (opts.limit != null) params.set('limit', String(opts.limit))
  if (opts.offset != null) params.set('offset', String(opts.offset))
  const qs = params.toString()
  return apiFetch(`/documents${qs ? '?' + qs : ''}`, { headers: headers(userId) })
}

// Three-layer taxonomy: primary_categories + domain_options + user_collections.
// Sole replacement for the now-removed GET /documents/collections endpoint.
export const fetchTaxonomy = (userId) =>
  apiFetch('/documents/taxonomy', { headers: headers(userId) })

export const deleteDocument = (docId, userId) =>
  apiFetch(`/documents/${docId}`, { method: 'DELETE', headers: headers(userId) })

// Update one or more of (primary_category, subtags, collections). Any field
// omitted / undefined is left unchanged on the server (partial update).
export const patchDocument = (docId, patch, userId) =>
  apiFetch(`/documents/${docId}`, {
    method: 'PATCH',
    headers: headers(userId),
    body: JSON.stringify(patch),
  })

// Run AI re-classification on the doc — returns + persists the new
// {primary_category, subtags} immediately. Use as the "Suggest with AI"
// button in the edit-classification dialog.
export const reclassifyDocument = (docId, userId) =>
  apiFetch(`/documents/${docId}/reclassify`, {
    method: 'POST',
    headers: headers(userId),
  })

export const fetchDocumentChunks = (docId, page, userId) => {
  const params = page != null ? `?page=${page}` : ''
  return apiFetch(`/documents/${docId}/chunks${params}`, { headers: headers(userId) })
}

// Save a selection as a named collection.
// mode: "new" (refuse on conflict with 409) | "merge" (add to existing)
export const saveCollection = (name, docIds, mode = "new", userId) =>
  apiFetch('/documents/collections/save', {
    method: 'POST',
    headers: headers(userId),
    body: JSON.stringify({ name, doc_ids: docIds, mode }),
  })

// Download original source file — bypasses apiFetch since we need blob, not JSON
export async function downloadDocument(docId, filename, userId) {
  const resp = await fetch(`${API_BASE}/documents/${docId}/download`, {
    headers: { 'X-User-Id': userId || 'admin' },
  })
  if (!resp.ok) {
    const err = await resp.text().catch(() => resp.statusText)
    throw new Error(`Download ${resp.status}: ${err}`)
  }
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || `document-${docId}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// Graph
export const fetchGraphDocuments = (userId) =>
  apiFetch('/graph/documents', { headers: headers(userId) })

export const fetchGraphNodes = (docId, edgeTypes, userId) => {
  const params = `?doc_id=${docId}&edge_types=${edgeTypes || 'follows,co_located,describes,references,similar_to'}`
  return apiFetch(`/graph/nodes${params}`, { headers: headers(userId) })
}

// Multi-doc chunk-level graph (new in 2026-05-11). Returns chunks + edges
// from N user-owned docs in one call. The backend silently drops docs the
// user doesn't own and caps at MULTI_DOC_MAX=10.
export const fetchGraphNodesMulti = (docIds, opts = {}, userId) => {
  const { edgeTypes = 'similar_to', includeIntraDoc = false } = opts
  const ids = Array.isArray(docIds) ? docIds.join(',') : docIds
  const params = new URLSearchParams({
    doc_ids: ids,
    edge_types: edgeTypes,
    include_intra_doc: includeIntraDoc ? 'true' : 'false',
  })
  return apiFetch(`/graph/nodes-multi?${params.toString()}`, { headers: headers(userId) })
}

export const fetchGraphNeighbors = (docId, chunkIndex, hops, userId) =>
  apiFetch(`/graph/neighbors?doc_id=${docId}&chunk_index=${chunkIndex}&hops=${hops || 1}`, { headers: headers(userId) })

// Mindmap
export const fetchDocMindmap = (docId, userId) =>
  apiFetch(`/documents/${docId}/mindmap`, { headers: headers(userId) })

// Multi-doc mindmap — synthesised tree across N docs (added 2026-05-12).
// First call per doc-id set takes 15-30 s (LLM); cache returns instant.
export const fetchMultiDocMindmap = (docIds, userId) => {
  const ids = Array.isArray(docIds) ? docIds.join(',') : docIds
  return apiFetch(`/graph/mindmap-multi?doc_ids=${encodeURIComponent(ids)}`,
                  { headers: headers(userId) })
}

// Query
export const sendQuery = (question, options, userId) =>
  apiFetch('/query', {
    method: 'POST',
    headers: headers(userId),
    body: JSON.stringify({ question, ...options }),
  })

// Corpus stats
export const fetchCorpusStats = (userId) =>
  apiFetch('/documents/stats', { headers: headers(userId) })

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
