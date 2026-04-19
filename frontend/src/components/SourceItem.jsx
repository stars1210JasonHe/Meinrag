import { FileText, Table2, Image, Calculator, Download } from 'lucide-react'
import { downloadDocument } from '../lib/api'

const TYPE_ICONS = {
  text: FileText,
  table: Table2,
  image: Image,
  formula: Calculator,
}

export { TYPE_ICONS }

function scoreColor(p) {
  // Remap: p=20 → red (hue 0), p=70 → green (hue 120). Matches realistic
  // composite-score range where 65%+ is a genuinely strong match.
  const hue = Math.max(0, Math.min(120, (p - 20) * 2.4))
  return `hsl(${hue} 72% 45%)`
}

export default function SourceItem({ source, index, isActive, onClick }) {
  const Icon = TYPE_ICONS[source.chunk_type] || FileText
  const displayName = source.source_file?.replace(/\.[^.]+$/, '') || 'unknown'
  const heading = source.headings?.split(' > ').pop()
  const detail = source.label || heading || ''
  const isDocument = source.source_type !== 'web' && source.doc_id

  async function handleDownload(e) {
    e.stopPropagation()
    try {
      await downloadDocument(source.doc_id, source.source_file)
    } catch (err) {
      // surface minimally; parent can add toast handling later
      console.error('Download failed:', err)
    }
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onClick(index)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick(index)
        }
      }}
      className={`relative flex items-start gap-2 w-full px-3 py-2.5 pr-9 text-left rounded-lg transition-colors cursor-pointer ${
        isActive
          ? 'bg-white/10 border-l-2 border-[hsl(168_84%_40%)]'
          : 'hover:bg-white/5 border-l-2 border-transparent'
      }`}
    >
      <Icon size={14} className="mt-0.5 shrink-0 opacity-60" />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium truncate" style={{ color: 'hsl(210 40% 98%)' }}>
          {displayName}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          {source.score != null && (
            <span className="text-xs" style={{ color: scoreColor(source.score) }}>
              {Math.round(source.score)}%
            </span>
          )}
          {source.page != null && (
            <span className="text-xs opacity-40">p.{source.page + 1}</span>
          )}
          {detail && (
            <span className="text-xs opacity-50 truncate">{detail}</span>
          )}
        </div>
      </div>
      {isDocument && (
        <button
          type="button"
          onClick={handleDownload}
          className="absolute top-2 right-2 p-1.5 rounded-md opacity-50 hover:opacity-100 hover:bg-white/10 transition"
          title={`Download ${source.source_file}`}
          aria-label={`Download ${source.source_file}`}
        >
          <Download size={12} />
        </button>
      )}
    </div>
  )
}
