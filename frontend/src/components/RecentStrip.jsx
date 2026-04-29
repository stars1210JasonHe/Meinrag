import { FileText } from 'lucide-react'

function relTime(iso) {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  const diff = Date.now() - t
  const m = Math.round(diff / 60000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.round(h / 24)
  if (d < 30) return `${d}d`
  const mo = Math.round(d / 30)
  return `${mo}mo`
}

function formatPrimary(p) {
  if (!p) return ''
  return p.split('-').map(w => w[0]?.toUpperCase() + w.slice(1)).join(' ')
}

export default function RecentStrip({ documents, max = 5, onDocClick }) {
  const recent = (Array.isArray(documents) ? documents : [])
    .slice()
    .sort((a, b) => {
      const da = a.uploaded_at || a.created_at || ''
      const db = b.uploaded_at || b.created_at || ''
      return db.localeCompare(da)
    })
    .slice(0, max)

  if (recent.length === 0) return null

  return (
    <div className="flex gap-2 min-w-0">
      {recent.map(doc => (
        <button
          key={doc.doc_id}
          onClick={() => onDocClick?.(doc)}
          className="flex-1 min-w-0 flex flex-col items-start gap-1 px-3 py-2 rounded-md border text-left transition-colors hover:bg-white/5"
          style={{
            borderColor: 'var(--border)',
            backgroundColor: 'var(--bg-1)',
            maxWidth: 160,
          }}
          title={doc.filename}
        >
          <div className="flex items-center gap-1.5 w-full">
            <FileText size={11} style={{ color: 'var(--fg-faint)', flexShrink: 0 }} />
            <span
              className="truncate"
              style={{
                color: 'var(--fg-1)',
                fontFamily: 'var(--display)',
                fontSize: 12,
                letterSpacing: '-0.005em',
              }}
            >
              {doc.filename}
            </span>
          </div>
          <div className="flex items-center justify-between w-full text-[9px]">
            {doc.primary_category ? (
              <span
                className="px-1.5 py-0.5 rounded"
                style={{
                  color: 'var(--fg-dim)',
                  backgroundColor: 'var(--bg-2)',
                  fontFamily: 'var(--mono)',
                  letterSpacing: '0.04em',
                }}
              >
                {formatPrimary(doc.primary_category)}
              </span>
            ) : (
              <span style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}>—</span>
            )}
            <span style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}>
              {relTime(doc.uploaded_at)}
            </span>
          </div>
        </button>
      ))}
    </div>
  )
}
