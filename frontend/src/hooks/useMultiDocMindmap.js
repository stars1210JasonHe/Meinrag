import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { fetchMultiDocMindmap } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Fetches the synthesised mindmap across N documents.
 *
 * Backend caches to data/mindmaps_multi/<sha16>.json keyed by sorted
 * doc_ids, so the first call for a given doc set takes 15-30 s (LLM)
 * and subsequent calls are instant.
 *
 * `enabled` lets callers gate the query (typically: only fire when the
 * user actually toggles into mindmap mode).
 */
export function useMultiDocMindmap(docIds, { enabled = true } = {}) {
  const ids = useMemo(
    () => (Array.isArray(docIds) ? docIds.filter(Boolean) : []),
    [docIds],
  )
  // Use the sorted-joined form as the query key so the same set in
  // different orders shares a cache entry on the frontend too.
  const idsKey = [...ids].sort().join(',')

  return useQuery({
    queryKey: ['multi-doc-mindmap', idsKey],
    queryFn: () => fetchMultiDocMindmap(ids, USER_ID),
    enabled: enabled && ids.length >= 2,
    staleTime: 30 * 60_000,
    retry: 1,
  })
}
