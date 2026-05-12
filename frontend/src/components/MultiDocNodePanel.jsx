import { FileText, Table2, Image, Calculator, ExternalLink, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

const TYPE_ICONS = {
  text: FileText,
  table: Table2,
  image: Image,
  formula: Calculator,
}

/**
 * Bottom-sheet detail panel for a clicked chunk node in the multi-doc graph.
 * Mirrors the single-doc NodePanel in GraphPage.jsx so users have a
 * consistent interaction model, but adds:
 *   - filename + doc colour swatch in the header (doc identity is the
 *     whole point of the multi-doc view)
 *   - "Open in PDF" routes to the chunk's parent doc (not "the current
 *     doc" — there's no single current doc here)
 *
 * Props:
 *   node          — the clicked chunk node (or null to hide)
 *   filename      — display name for the chunk's parent doc
 *   docColor      — colour for the swatch (matches the canvas node)
 *   onOpenChunk   — () => void; routes to /chat with chunk pre-filled
 *   onClose       — () => void
 */
export default function MultiDocNodePanel({
  node,
  filename,
  docColor,
  onOpenChunk,
  onClose,
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  if (!node) return null

  const Icon = TYPE_ICONS[node.chunk_type] || FileText
  const docId = node.doc_id

  return (
    <div
      className="border-t px-4 py-3"
      style={{
        borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
        backgroundColor: 'var(--bg-1, #0c0c0f)',
      }}
    >
      {/* Header: doc-colour swatch + filename + chunk identity + close */}
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          {/* Doc-identity swatch — same colour as the canvas node so the
              user can mentally connect "I clicked this dot" to "this is
              from doc X". Small inline-block; non-shrinkable. */}
          <span
            aria-hidden
            className="inline-block rounded-sm shrink-0"
            style={{ width: 12, height: 12, backgroundColor: docColor || 'var(--fg-dim)' }}
          />
          <Icon
            size={16}
            className="shrink-0"
            style={{ color: 'var(--fg-dim, #9a9690)' }}
          />
          <span
            className="text-sm font-medium truncate"
            style={{ color: 'var(--fg, #f4f2ee)' }}
            title={filename}
          >
            {filename}
          </span>
          <span
            className="text-xs whitespace-nowrap"
            style={{ color: 'var(--fg-dim, #9a9690)' }}
          >
            · chunk #{node.chunk_index} · {node.chunk_type || 'text'}
          </span>
        </div>
        <button
          onClick={onClose}
          className="opacity-40 hover:opacity-100 shrink-0 ml-2"
          style={{ color: 'var(--fg, #f4f2ee)' }}
          aria-label={t('common.close', { defaultValue: 'Close' })}
        >
          <X size={14} />
        </button>
      </div>

      {/* Summary (italic, lighter) + content preview */}
      {node.summary_preview && (
        <p
          className="text-xs mb-2 leading-relaxed italic"
          style={{ color: 'var(--fg-1, #d4d0ca)' }}
        >
          {node.summary_preview}
        </p>
      )}
      {node.content_preview && (
        <p
          className="text-xs mb-3 leading-relaxed"
          style={{ color: 'var(--fg-dim, #9a9690)' }}
        >
          {node.content_preview}
        </p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={onOpenChunk}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs"
          style={{
            backgroundColor: 'var(--border-strong, rgba(255,255,255,0.14))',
            color: 'var(--fg, #f4f2ee)',
          }}
        >
          <ExternalLink size={12} /> {t('graph.openChunk', { defaultValue: 'Open chunk' })}
        </button>
        <button
          onClick={() => navigate(`/pdf/${docId}`)}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs"
          style={{
            backgroundColor: 'transparent',
            color: 'var(--fg-dim, #9a9690)',
            border: '1px solid var(--border-strong, rgba(255,255,255,0.14))',
          }}
          title={t('dashboard.openInPdf', { defaultValue: 'Open in PDF' })}
        >
          <ExternalLink size={12} /> {t('dashboard.openInPdf', { defaultValue: 'Open in PDF' })}
        </button>
        {node.page != null && (
          <span
            className="text-xs opacity-40"
            style={{ color: 'var(--fg, #f4f2ee)' }}
          >
            {t('graph.page', { num: node.page + 1, defaultValue: `p.${node.page + 1}` })}
          </span>
        )}
      </div>
    </div>
  )
}
