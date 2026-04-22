import { useTranslation } from 'react-i18next'
import { X, ExternalLink, FileText, Table2, Image, Calculator } from 'lucide-react'

// Must match MindmapGraph.jsx / GraphPage.jsx constants exactly.
const TYPE_COLORS = {
  text: '#3b82f6',
  table: '#f59e0b',
  formula: '#a855f7',
  image: '#10b981',
}

const TYPE_ICONS = { text: FileText, table: Table2, image: Image, formula: Calculator }

export default function MindmapNodePanel({ node, onOpenInPdf, onClose }) {
  const { t } = useTranslation()
  if (!node) return null

  const Icon = TYPE_ICONS[node.chunk_type] || FileText

  return (
    <div
      className="p-4 border-t"
      style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon size={16} style={{ color: TYPE_COLORS[node.chunk_type] || TYPE_COLORS.text }} />
          <h3 className="text-sm font-medium truncate" style={{ color: 'var(--fg, #f4f2ee)' }}>
            {t('mindmap.chunk')} {node.chunk_index}
          </h3>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="opacity-40 hover:opacity-100 shrink-0"
          style={{ color: 'var(--fg, #f4f2ee)' }}
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex gap-1.5 mb-3 flex-wrap">
        <span
          className="text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wide"
          style={{
            backgroundColor: 'var(--border-strong, rgba(255,255,255,0.14))',
            color: 'var(--fg, #f4f2ee)',
          }}
        >
          {node.chunk_type}
        </span>
        {node.section_type && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded border"
            style={{
              borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
              color: 'var(--fg-dim, #9a9690)',
            }}
          >
            {node.section_type}
          </span>
        )}
        {node.page != null && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded border"
            style={{
              borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
              color: 'var(--fg-dim, #9a9690)',
            }}
          >
            {t('mindmap.page')}{node.page}
          </span>
        )}
      </div>

      <p
        className="text-xs mb-4 whitespace-pre-wrap leading-relaxed"
        style={{ color: 'var(--fg-1, #d4d0ca)' }}
      >
        {node.full_summary || node.label}
      </p>

      <button
        onClick={onOpenInPdf}
        className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded text-xs"
        style={{
          backgroundColor: 'var(--border-strong, rgba(255,255,255,0.14))',
          color: 'var(--fg, #f4f2ee)',
        }}
      >
        <ExternalLink size={12} />
        {t('mindmap.openInPdf')}
      </button>
    </div>
  )
}
