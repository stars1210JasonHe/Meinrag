import { FileText, Table2, Image, Calculator } from 'lucide-react'

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

  return (
    <button
      onClick={() => onClick(index)}
      className={`flex items-start gap-2 w-full px-3 py-2.5 text-left rounded-lg transition-colors ${
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
    </button>
  )
}
