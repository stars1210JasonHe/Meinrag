import { useQuery } from '@tanstack/react-query'
import { fetchDocMindmap } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Fetches the LLM-derived mind map tree for a document.
 *
 * Backend caches to data/mindmaps/{doc_id}.json, so the first call
 * takes 10-30 s and subsequent calls are instant. `enabled` lets the
 * parent gate the query (e.g. only fire when the user actually toggles
 * to mindmap mode, not on every GraphPage visit).
 */
export function useDocMindmap(docId, { enabled = true } = {}) {
  return useQuery({
    queryKey: ['doc-mindmap', docId],
    queryFn: () => fetchDocMindmap(docId, USER_ID),
    enabled: Boolean(docId) && enabled,
    staleTime: 30 * 60_000,
    retry: 1,
  })
}
