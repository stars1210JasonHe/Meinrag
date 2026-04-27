/**
 * Loading-skeleton primitives. Use during async loads to give the user
 * structure-shaped feedback instead of empty space.
 */

/** A 3-line shimmering paragraph. */
export function ParagraphSkeleton() {
  return (
    <div className="space-y-2 py-1">
      <span className="skeleton-line" style={{ height: 12, width: '94%' }} />
      <span className="skeleton-line" style={{ height: 12, width: '88%' }} />
      <span className="skeleton-line" style={{ height: 12, width: '70%' }} />
    </div>
  )
}

/** A skeleton for a single source-card row (used in the chat sidebar). */
export function SourceCardSkeleton() {
  return (
    <div className="px-3 py-2 border-l-2 border-transparent">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="skeleton-line" style={{ height: 14, width: 22, borderRadius: 4 }} />
        <span className="skeleton-line" style={{ height: 12, width: '55%' }} />
      </div>
      <span className="skeleton-line" style={{ height: 10, width: '88%' }} />
    </div>
  )
}

/** A skeleton row matching the dashboard's doc-card list item. */
export function DocCardSkeleton() {
  return (
    <div className="flex items-center gap-3 p-3 rounded-lg" style={{ backgroundColor: 'var(--bg-1)' }}>
      <span className="skeleton-line" style={{ height: 32, width: 32, borderRadius: 6 }} />
      <div className="flex-1 space-y-1.5">
        <span className="skeleton-line" style={{ height: 12, width: '70%' }} />
        <span className="skeleton-line" style={{ height: 10, width: '40%' }} />
      </div>
    </div>
  )
}
