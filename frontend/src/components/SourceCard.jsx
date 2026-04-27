import { FileText, Table2, Image, Calculator } from 'lucide-react'
import { HIGHLIGHT_COLORS } from './TextDocViewer'

const TYPE_ICONS = {
  text: FileText,
  table: Table2,
  image: Image,
  formula: Calculator,
}

/**
 * Compact source card for the chat sidebar's "Sources" list.
 *
 * Props:
 *   source: the source object ({doc_id, source_file, chunk_index, chunk_type,
 *           page, content, summary})
 *   index: 0-based position in the sources array (matches [N] minus 1)
 *   isActive: bool — is this the currently selected source (for visual state)
 *   onClick: () => void
 */
export default function SourceCard({ source, index, isActive, onClick }) {
  const Icon = TYPE_ICONS[source.chunk_type] || FileText
  const color = HIGHLIGHT_COLORS[index % HIGHLIGHT_COLORS.length]
  const preview = (source.summary || source.content || '').trim().replace(/\s+/g, ' ').slice(0, 80)
  const pageLabel = source.page != null ? `p.${source.page + 1}` : null
  const filename = (source.source_file || source.doc_id || '?').replace(/\.[^.]+$/, '')

  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2 border-l-2 transition-colors source-card"
      data-active={isActive ? 'true' : 'false'}
      style={{
        borderLeftColor: isActive ? color.border : 'transparent',
        color: 'var(--fg)',
      }}
    >
      <div className="flex items-center gap-1.5 mb-1">
        <span
          className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: color.bg,
            color: color.border,
          }}
        >
          [{index + 1}]
        </span>
        <Icon size={11} className="opacity-50 shrink-0" />
        <span className="text-xs truncate flex-1 opacity-80">{filename}</span>
        {typeof source.score === 'number' && (
          <span
            className="text-[10px] font-medium px-1.5 py-0.5 rounded shrink-0 tabular-nums"
            style={{
              backgroundColor: 'var(--bg-3)',
              color: 'var(--fg-1)',
            }}
            title={`Retrieval score: ${source.score.toFixed(1)} / 100`}
          >
            {Math.round(source.score)}%
          </span>
        )}
        {pageLabel && (
          <span className="text-[10px] opacity-40 shrink-0">{pageLabel}</span>
        )}
      </div>
      {preview && (
        <p className="text-[11px] opacity-50 line-clamp-2 leading-snug">
          {preview}
        </p>
      )}
    </button>
  )
}
