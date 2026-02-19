import api, { apiHeaders } from './client'

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
