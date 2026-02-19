import api, { apiHeaders } from './client'

export async function fetchDocuments(userId) {
  const resp = await api.get('/documents', { headers: apiHeaders(userId) })
  return resp.data.documents
}

export async function fetchCollections(userId) {
  const resp = await api.get('/documents/collections', { headers: apiHeaders(userId) })
  return resp.data
}

export async function uploadDocument(file, userId, { collection, autoSuggest } = {}) {
  const formData = new FormData()
  formData.append('file', file)
  const params = new URLSearchParams()
  if (collection && !autoSuggest) params.append('collections', collection)
  if (autoSuggest) params.append('auto_suggest', 'true')
  const resp = await api.post(`/documents/upload?${params.toString()}`, formData, {
    headers: { ...apiHeaders(userId), 'Content-Type': 'multipart/form-data' },
  })
  return resp.data
}

export async function deleteDocument(docId, userId) {
  await api.delete(`/documents/${docId}`, { headers: apiHeaders(userId) })
}

export async function downloadDocument(docId, filename, userId) {
  const resp = await api.get(`/documents/${docId}/download`, {
    headers: apiHeaders(userId),
    responseType: 'blob',
  })
  const url = window.URL.createObjectURL(resp.data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  window.URL.revokeObjectURL(url)
}

export async function patchDocumentCollections(docId, collections, userId) {
  await api.patch(`/documents/${docId}`, { collections }, { headers: apiHeaders(userId) })
}

export async function reclassifyDocument(docId, userId) {
  const resp = await api.post(`/documents/${docId}/reclassify`, null, { headers: apiHeaders(userId) })
  return resp.data
}
