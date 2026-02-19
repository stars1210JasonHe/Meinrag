import api, { apiHeaders } from './client'

export async function listSessions(userId) {
  const resp = await api.get('/sessions', { headers: apiHeaders(userId) })
  return resp.data
}

export async function getSessionMessages(sessionId, userId) {
  const resp = await api.get(`/sessions/${sessionId}/messages`, { headers: apiHeaders(userId) })
  return resp.data
}

export async function deleteSession(sessionId, userId) {
  await api.delete(`/sessions/${sessionId}`, { headers: apiHeaders(userId) })
}
