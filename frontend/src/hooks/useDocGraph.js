import { useQuery } from '@tanstack/react-query'
import { fetchDocGraph } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Fetches the force-graph data (chunks + edges) for one doc.
 */
export function useDocGraph(docId) {
  return useQuery({
    queryKey: ['doc-graph', docId],
    queryFn: () => fetchDocGraph(docId, USER_ID),
    staleTime: 5 * 60 * 1000,
    enabled: !!docId,
  })
}
