import api, { apiHeaders } from './client'

export async function fetchUsers(userId) {
  const resp = await api.get('/users', { headers: apiHeaders(userId) })
  return resp.data
}

export async function createUser(newUserId, displayName, currentUserId) {
  await api.post('/users', {
    user_id: newUserId,
    display_name: displayName,
  }, { headers: apiHeaders(currentUserId) })
}
