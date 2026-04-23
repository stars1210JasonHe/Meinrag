import { useEffect, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import { fetchDocumentChunks } from '@/lib/api'
import { cn } from '@/lib/utils'

const USER_ID = 'admin'

// Same color palette as PdfViewer.jsx HIGHLIGHT_COLORS (keep in sync)
const HIGHLIGHT_COLORS = [
  { bg: 'rgba(59,130,246,0.18)', border: '#3b82f6' },   // blue
  { bg: 'rgba(245,158,11,0.18)', border: '#f59e0b' },   // amber
  { bg: 'rgba(16,185,129,0.18)', border: '#10b981' },   // emerald
  { bg: 'rgba(236,72,153,0.18)', border: '#ec4899' },   // pink
  { bg: 'rgba(168,85,247,0.18)', border: '#a855f7' },   // violet
]

export { HIGHLIGHT_COLORS }

/**
 * Renders all chunks of a non-PDF doc with anchor navigation.
 *
 * Props:
 *   docId: string — the document id
 *   activeChunkIndex: number | null — chunk to scroll to and highlight
 *   activeSourceColorIndex: number — index into HIGHLIGHT_COLORS for active chunk
 */
export default function TextDocViewer({ docId, activeChunkIndex, activeSourceColorIndex = 0 }) {
  const { t } = useTranslation()
  const containerRef = useRef(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['doc-chunks-all', docId],
    queryFn: () => fetchDocumentChunks(docId, null, USER_ID),
    staleTime: 5 * 60 * 1000,
    enabled: !!docId,
  })

  // Sort chunks by chunk_index so the doc reads in order
  const orderedChunks = useMemo(() => {
    if (!data?.chunks) return []
    return [...data.chunks].sort((a, b) => (a.chunk_index ?? 0) - (b.chunk_index ?? 0))
  }, [data])

  // On active chunk change, scroll into view
  useEffect(() => {
    if (activeChunkIndex == null || !containerRef.current) return
    const el = containerRef.current.querySelector(`#chunk-${activeChunkIndex}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [activeChunkIndex])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full opacity-40">
        <Loader2 className="animate-spin" size={20} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-8 text-sm opacity-60" style={{ color: 'var(--fg)' }}>
        {t('textDocViewer.error', { defaultValue: 'Failed to load document' })}
      </div>
    )
  }

  if (!orderedChunks.length) {
    return (
      <div className="p-8 text-sm opacity-60 text-center" style={{ color: 'var(--fg)' }}>
        {t('textDocViewer.empty', { defaultValue: 'This document has no chunks.' })}
      </div>
    )
  }

  const color = HIGHLIGHT_COLORS[activeSourceColorIndex % HIGHLIGHT_COLORS.length]

  return (
    <div
      ref={containerRef}
      className="h-full overflow-y-auto px-6 py-4 text-sm leading-relaxed max-w-3xl mx-auto"
      style={{ color: 'var(--fg)' }}
    >
      {orderedChunks.map(chunk => {
        const isActive = chunk.chunk_index === activeChunkIndex
        return (
          <div
            key={chunk.chunk_index}
            id={`chunk-${chunk.chunk_index}`}
            className={cn(
              'my-2 px-3 py-2 rounded transition-colors',
              isActive ? 'border-l-4' : 'border-l-4 border-transparent',
            )}
            style={isActive ? {
              backgroundColor: color.bg,
              borderLeftColor: color.border,
            } : {}}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {chunk.content || ''}
            </ReactMarkdown>
          </div>
        )
      })}
    </div>
  )
}
