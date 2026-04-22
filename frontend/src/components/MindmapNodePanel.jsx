import { useTranslation } from 'react-i18next'
import { X, ExternalLink } from 'lucide-react'

/**
 * Dual-purpose panel.
 * - Graph mode: pass `node` (a MindmapGraph node) + `onOpenInPdf`
 * - Tree mode: pass `leaf` (a tree leaf with name + chunk_indices + branch_name)
 *              + `onOpenChunk(chunkIndex)`
 */
export default function MindmapNodePanel({
  node,
  leaf,
  onOpenInPdf,
  onOpenChunk,
  onClose,
}) {
  const { t } = useTranslation()

  if (leaf) {
    return (
      <div className="p-4 border-t border-[var(--border-strong)]">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-medium">{t('mindmap.concept')}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1 rounded hover:bg-[var(--border-strong)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="text-sm font-medium mb-2">{leaf.name}</p>
        {leaf.branch_name && (
          <p className="text-xs opacity-70 mb-3">↳ {leaf.branch_name}</p>
        )}
        <h4 className="text-xs font-medium mb-2 opacity-70 uppercase tracking-wide">
          {t('mindmap.supportingChunks')}
        </h4>
        <div className="space-y-1">
          {(leaf.chunk_indices || []).map(idx => (
            <button
              key={idx}
              type="button"
              onClick={() => onOpenChunk(idx)}
              className="w-full flex items-center justify-between px-2 py-1.5 text-sm rounded hover:bg-[var(--border-strong)] transition"
            >
              <span>{t('mindmap.chunk')} {idx}</span>
              <ExternalLink className="h-3 w-3 opacity-60" />
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (!node) return null

  return (
    <div className="p-4 border-t border-[var(--border-strong)]">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium">
          {t('mindmap.chunk')} {node.chunk_index}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="p-1 rounded hover:bg-[var(--border-strong)]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex gap-2 mb-3 flex-wrap">
        <span className="text-xs px-2 py-0.5 rounded bg-[var(--border-strong)]">
          {node.chunk_type}
        </span>
        {node.section_type && (
          <span className="text-xs px-2 py-0.5 rounded border border-[var(--border-strong)]">
            {node.section_type}
          </span>
        )}
        {node.page != null && (
          <span className="text-xs px-2 py-0.5 rounded border border-[var(--border-strong)]">
            {t('mindmap.page')}{node.page}
          </span>
        )}
      </div>
      <p className="text-sm mb-4 whitespace-pre-wrap opacity-90">
        {node.full_summary || node.label}
      </p>
      <button
        type="button"
        onClick={onOpenInPdf}
        className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded bg-[var(--border-strong)] hover:opacity-80 transition"
      >
        <ExternalLink className="h-4 w-4" />
        {t('mindmap.openInPdf')}
      </button>
    </div>
  )
}
