import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

// Must match MindmapGraph.jsx constants exactly.
const NODE_COLORS = {
  text: '#3b82f6',
  table: '#f59e0b',
  formula: '#a855f7',
  image: '#10b981',
}

const EDGE_COLORS = {
  follows: '#64748b',
  co_located: '#6366f1',
  describes: '#10b981',
  references: '#f59e0b',
  similar_to: '#ec4899',
}

export default function MindmapLegend({
  stats,
  enabledEdgeTypes,
  onToggleEdgeType,
}) {
  const { t } = useTranslation()
  if (!stats) return null

  return (
    <div className="p-4 space-y-5">
      <section>
        <h4
          className="text-xs font-medium mb-2 uppercase tracking-wide"
          style={{ color: 'var(--fg-dim, #9a9690)' }}
        >
          {t('mindmap.nodeTypes')}
        </h4>
        <div className="space-y-1.5 text-xs">
          {Object.entries(stats.chunks_by_type || {}).map(([type, count]) => (
            <div key={type} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span
                  className="w-2.5 h-2.5 rounded-full inline-block"
                  style={{ backgroundColor: NODE_COLORS[type] || '#999999' }}
                />
                <span className="capitalize" style={{ color: 'var(--fg, #f4f2ee)' }}>
                  {t(`nodeType.${type}`, { defaultValue: type })}
                </span>
              </div>
              <span style={{ color: 'var(--fg-dim, #9a9690)' }}>{count}</span>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h4
          className="text-xs font-medium mb-2 uppercase tracking-wide"
          style={{ color: 'var(--fg-dim, #9a9690)' }}
        >
          {t('mindmap.edgeTypes')}
        </h4>
        <div className="space-y-1.5">
          {Object.entries(stats.edges_by_type || {}).map(([type, count]) => {
            const enabled = enabledEdgeTypes.has(type)
            return (
              <button
                key={type}
                onClick={() => onToggleEdgeType(type)}
                aria-label={type}
                aria-pressed={enabled}
                className={cn(
                  'w-full flex items-center justify-between px-2 py-1 rounded text-xs transition-opacity',
                  enabled ? 'opacity-100' : 'opacity-40'
                )}
                style={{
                  backgroundColor: enabled
                    ? 'var(--border-strong, rgba(255,255,255,0.14))'
                    : 'transparent',
                  color: 'var(--fg, #f4f2ee)',
                }}
              >
                <span className="flex items-center gap-2">
                  <span
                    className="w-3 h-0.5 inline-block rounded"
                    style={{ backgroundColor: EDGE_COLORS[type] || '#999999' }}
                  />
                  <span>{t(`edgeType.${type}`, { defaultValue: type.replace('_', ' ') })}</span>
                </span>
                <span style={{ color: 'var(--fg-dim, #9a9690)' }}>{count}</span>
              </button>
            )
          })}
        </div>
      </section>
    </div>
  )
}
