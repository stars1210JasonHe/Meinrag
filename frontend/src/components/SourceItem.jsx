import { FileText, Table2, Image, Calculator } from 'lucide-react'

const TYPE_ICONS = {
  text: FileText,
  table: Table2,
  image: Image,
  formula: Calculator,
}

export { TYPE_ICONS }

export default function SourceItem({ source, index, onClick }) {
  const Icon = TYPE_ICONS[source.chunk_type] || FileText
  const displayName = source.source_file?.replace(/\.[^.]+$/, '') || 'unknown'
  const heading = source.headings?.split(' > ').pop()
  const detail = source.label || heading || ''

  return (
    <button
      onClick={() => onClick(index)}
      className="flex items-start gap-2 w-full px-3 py-2.5 text-left rounded-lg transition-colors hover:bg-white/5"
    >
      <Icon size={14} className="mt-0.5 shrink-0 opacity-60" />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium truncate" style={{ color: 'hsl(210 40% 98%)' }}>
          {displayName}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          {source.score != null && (
            <span className="text-xs" style={{ color: 'hsl(168 84% 40%)' }}>
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
