import { ChevronDown, ChevronRight } from 'lucide-react'

function formatPrimary(p) {
  if (!p) return 'Uncategorized'
  return p.split('-').map(w => w[0]?.toUpperCase() + w.slice(1)).join(' ')
}

/**
 * One collapsible category block on the dashboard.
 *
 * Props:
 *   primaryCategory: string | null   — null renders as "Uncategorized"
 *   docs: Document[]
 *   collapsed: boolean
 *   onToggle: (next: boolean) => void
 *   renderDoc: (doc) => ReactNode    — caller supplies the row renderer
 *                                       (DashboardPage already has DocRow; this
 *                                       avoids prop-drilling its many handlers)
 */
export default function CategorySection({
  primaryCategory,
  docs,
  collapsed,
  onToggle,
  renderDoc,
}) {
  if (!docs || docs.length === 0) return null
  const Chevron = collapsed ? ChevronRight : ChevronDown
  return (
    <div className="border-b" style={{ borderColor: 'var(--border)' }}>
      <button
        type="button"
        onClick={() => onToggle?.(!collapsed)}
        className="w-full flex items-center gap-2 px-5 py-2 transition-colors hover:bg-white/5"
        style={{
          color: 'var(--fg-1)',
          backgroundColor: 'var(--bg-1)',
        }}
      >
        <Chevron size={12} style={{ color: 'var(--fg-faint)' }} />
        <span
          className="text-[11px] uppercase tracking-[0.08em]"
          style={{ fontFamily: 'var(--mono)' }}
        >
          {formatPrimary(primaryCategory)}
        </span>
        <span
          className="ml-auto text-[10px] tabular-nums px-1.5 py-0.5 rounded"
          style={{
            color: 'var(--fg-dim)',
            backgroundColor: 'var(--bg-2)',
            fontFamily: 'var(--mono)',
          }}
        >
          {docs.length}
        </span>
      </button>
      {!collapsed && (
        <div>
          {docs.map(d => renderDoc(d))}
        </div>
      )}
    </div>
  )
}
