import axios from 'axios'

if (!import.meta.env.VITE_API_URL) {
  console.error('VITE_API_URL is not set. Create frontend/.env with VITE_API_URL=http://localhost:<PORT>')
}

export const API_BASE = import.meta.env.VITE_API_URL

const api = axios.create({
  baseURL: API_BASE,
})

export function apiHeaders(userId) {
  return { 'X-User-Id': userId }
}

export default api
