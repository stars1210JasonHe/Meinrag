import { useQuery } from '@tanstack/react-query'
import { fetchMindmap } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Fetches the mindmap graph for a single document.
 * Caches for 5 minutes — mind maps rarely change for a given doc.
 */
export function useMindmap(docId) {
  return useQuery({
    queryKey: ['mindmap', docId],
    queryFn: () => fetchMindmap(docId, USER_ID),
    staleTime: 5 * 60 * 1000,
    enabled: !!docId,
  })
}
