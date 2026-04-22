import { useQuery } from '@tanstack/react-query'
import { fetchMindmap } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Fetches the hierarchical mind map tree for one doc.
 * LLM-derived, cached on the backend per-doc.
 */
export function useMindmap(docId) {
  return useQuery({
    queryKey: ['mindmap', docId],
    queryFn: () => fetchMindmap(docId, USER_ID),
    staleTime: 5 * 60 * 1000,
    enabled: !!docId,
  })
}
