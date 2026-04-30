import { useEffect, useRef } from 'react'
import { X, FileText } from 'lucide-react'
import { useTranslation } from 'react-i18next'

/**
 * Click-toggle popover that lists currently-selected documents with a × to
 * remove individually. Sits above the SelectionActionBar.
 *
 * Props:
 *   selectedDocs : [{ doc_id, filename }]
 *   onRemove     : (doc_id) => void
 *   onClose      : () => void
 */
export default function SelectedDocsPopover({ selectedDocs, onRemove, onClose }) {
  const { t } = useTranslation()
  const ref = useRef(null)

  // Outside-click dismissal — but allow clicks inside the popover or on the
  // count button (which lives in SelectionActionBar; toggling the same button
  // would re-open immediately if we didn't ignore those clicks).
  useEffect(() => {
    const onDown = (e) => {
      if (!ref.current) return
      if (ref.current.contains(e.target)) return
      if (e.target.closest?.('[data-peek-trigger]')) return
      onClose?.()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [onClose])

  // ESC dismissal — capture phase + stopImmediatePropagation so the
  // DashboardPage's window-level ESC handler (which clears the entire
  // selection with undo) doesn't also fire while the popover is just
  // closing.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.stopImmediatePropagation()
        onClose?.()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onClose])

  if (!selectedDocs || selectedDocs.length === 0) return null

  return (
    <div
      ref={ref}
      role="dialog"
      aria-label={t('selection.peekTitle', { defaultValue: 'Selected documents' })}
      className="fixed bottom-24 left-1/2 -translate-x-1/2 z-50
                 w-[420px] max-w-[92vw] rounded-lg shadow-xl shadow-black/30
                 bg-[color:var(--bg-2,#111115)]/95 backdrop-blur
                 border border-[color:var(--border,#2a2a2e)]"
    >
      <div
        className="px-4 pt-3 pb-2 text-[11px] uppercase tracking-[0.08em] border-b"
        style={{
          color: 'var(--fg-faint)',
          fontFamily: 'var(--mono)',
          borderColor: 'var(--border)',
        }}
      >
        {t('selection.peekTitle', { defaultValue: 'Selected documents' })} · {selectedDocs.length}
      </div>
      <div className="max-h-60 overflow-y-auto py-1">
        {selectedDocs.map((doc) => (
          <div
            key={doc.doc_id}
            className="group flex items-center gap-2 px-4 py-1.5 transition-colors hover:bg-white/5"
          >
            <FileText size={11} className="shrink-0" style={{ color: 'var(--fg-faint)' }} />
            <span
              className="flex-1 truncate text-[12px]"
              style={{ color: 'var(--fg-1)', fontFamily: 'var(--display)' }}
              title={doc.filename}
            >
              {doc.filename || doc.doc_id}
            </span>
            <button
              type="button"
              onClick={() => onRemove?.(doc.doc_id)}
              aria-label={t('selection.peekRemove', { defaultValue: 'Remove from selection' })}
              title={t('selection.peekRemove', { defaultValue: 'Remove from selection' })}
              className="p-1 rounded transition-opacity opacity-40 hover:opacity-100"
              style={{ color: 'var(--fg-dim)' }}
            >
              <X size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
