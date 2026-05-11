import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Floating legend for the multi-doc chunk graph.
 *
 * Props:
 *   docs            Array<{ doc_id, filename, color, chunkCount }>
 *   focusedDocId    string|null — if set, that doc is "active" and others
 *                    are visually dimmed in the parent canvas
 *   onFocusToggle   (docId) => void — click a row to toggle focus; clicking
 *                    the same docId twice clears focus
 *
 * Placement: parent positions this absolutely (top-right by default).
 */
export default function MultiDocLegend({ docs, focusedDocId, onFocusToggle }) {
  const { t } = useTranslation()

  const totalChunks = useMemo(
    () => docs.reduce((acc, d) => acc + (d.chunkCount || 0), 0),
    [docs],
  )

  if (!docs || docs.length === 0) return null

  return (
    <div
      className="absolute top-3 right-3 z-10 rounded-md border shadow-sm"
      style={{
        background: 'var(--bg-1, #0c0c0f)',
        borderColor: 'var(--border, rgba(255,255,255,0.08))',
        minWidth: 200,
        maxWidth: 320,
      }}
      role="group"
      aria-label={t('multiDoc.legendLabel', { defaultValue: 'Documents in graph' })}
    >
      <div
        className="px-3 py-2 text-xs font-medium"
        style={{
          color: 'var(--fg-dim, #9a9690)',
          borderBottom: '1px solid var(--border, rgba(255,255,255,0.08))',
        }}
      >
        {t('multiDoc.docsHeader', {
          count: docs.length,
          chunks: totalChunks,
          defaultValue: `Docs (${docs.length}) · ${totalChunks} chunks`,
        })}
      </div>
      <ul className="py-1 max-h-[60vh] overflow-y-auto">
        {docs.map(d => {
          const isFocused = focusedDocId === d.doc_id
          const isDimmed = focusedDocId && !isFocused
          return (
            <li key={d.doc_id}>
              <button
                type="button"
                onClick={() => onFocusToggle?.(d.doc_id)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-[var(--bg-2)] focus:outline-none focus:bg-[var(--bg-2)]"
                style={{
                  opacity: isDimmed ? 0.45 : 1,
                  color: 'var(--fg, #f4f2ee)',
                }}
                aria-pressed={isFocused}
                title={d.filename}
              >
                <span
                  className="inline-block rounded-sm flex-shrink-0"
                  style={{
                    width: 12, height: 12,
                    backgroundColor: d.color,
                    boxShadow: isFocused ? '0 0 0 2px var(--signature)' : 'none',
                  }}
                />
                <span className="flex-1 truncate">{d.filename}</span>
                <span style={{ color: 'var(--fg-dim, #9a9690)' }}>{d.chunkCount}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
