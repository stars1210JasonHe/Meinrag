import { useQuery, useQueries } from '@tanstack/react-query'
import { useMemo } from 'react'
import { fetchGraphNodesMulti, fetchDocMindmap } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Fetches the multi-doc chunk graph (nodes + edges) plus each doc's
 * mindmap palette in parallel.
 *
 * Returns:
 *   - graphData: { nodes, edges }
 *   - paletteByDocId: { [docId]: { tree, palette } }  — used by callers to
 *     resolve doc colour via lib/docPalette.resolveDocColor.
 *   - loading flags for both layers
 *
 * Mindmap palette fetches are best-effort: if a doc has no mindmap cached
 * yet, the call may take 15-25 s. We don't block graph render on it —
 * docs without a palette fall back to a deterministic --mm-hue hash colour.
 */
export function useMultiDocGraph(docIds, { includeIntraDoc = false, enabled = true } = {}) {
  const ids = useMemo(
    () => (Array.isArray(docIds) ? docIds.filter(Boolean) : []),
    [docIds],
  )
  const idsKey = ids.join(',')

  const graphQuery = useQuery({
    queryKey: ['graph-nodes-multi', idsKey, includeIntraDoc],
    queryFn: () => fetchGraphNodesMulti(ids, { includeIntraDoc }, USER_ID),
    enabled: enabled && ids.length > 0,
    staleTime: 5 * 60_000,
  })

  // One mindmap fetch per doc, in parallel. Each may be slow on first hit;
  // we don't await them as a group — react-query renders progressively.
  const paletteQueries = useQueries({
    queries: ids.map(docId => ({
      queryKey: ['doc-mindmap', docId],
      queryFn: () => fetchDocMindmap(docId, USER_ID),
      enabled: enabled && Boolean(docId),
      staleTime: 30 * 60_000,
      retry: 0,  // palette is optional — don't waste retries
    })),
  })

  const paletteByDocId = useMemo(() => {
    const map = {}
    ids.forEach((docId, i) => {
      const q = paletteQueries[i]
      if (q?.data?.tree) map[docId] = q.data
    })
    return map
  }, [ids, paletteQueries.map(q => q.data).join('|')])

  return {
    graphData: graphQuery.data,
    isLoading: graphQuery.isLoading,
    error: graphQuery.error,
    paletteByDocId,
    palettesLoading: paletteQueries.some(q => q.isLoading),
  }
}
