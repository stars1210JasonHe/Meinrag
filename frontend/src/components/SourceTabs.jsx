import { useRef, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { X, FileText, FileType2, Download, Pin, PinOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { downloadDocument } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Tab bar for the Chat page main area.
 *
 * Props:
 *   tabs: [{ doc_id, filename, file_type, pinned }]
 *   activeDocId: string | null
 *   onActivate: (doc_id) => void
 *   onClose:    (doc_id) => void  — refused if tab is pinned (hook-side)
 *   onTogglePin:(doc_id) => void  — flips pinned, re-sorts
 */
export default function SourceTabs({ tabs, activeDocId, onActivate, onClose, onTogglePin }) {
  const { t } = useTranslation()
  const scrollRef = useRef(null)
  const activeRef = useRef(null)

  // Ensure active tab is visible on change
  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
    }
  }, [activeDocId])

  if (tabs.length === 0) return null

  return (
    <div
      ref={scrollRef}
      className="flex items-end gap-0.5 overflow-x-auto overflow-y-hidden shrink-0 border-b"
      style={{
        borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
        scrollbarWidth: 'thin',
      }}
    >
      {tabs.map(tab => {
        const active = tab.doc_id === activeDocId
        const Icon = tab.file_type === 'pdf' ? FileText : FileType2
        return (
          <div
            key={tab.doc_id}
            ref={active ? activeRef : null}
            className={cn(
              'group flex items-center gap-1.5 px-3 py-2 text-xs cursor-pointer shrink-0 border-r transition-colors',
              active
                ? 'bg-[var(--bg-1)] border-b-2 border-b-[var(--signature,#5b7ec9)]'
                : 'opacity-60 hover:opacity-100',
            )}
            style={{
              borderRightColor: 'var(--border-strong, rgba(255,255,255,0.14))',
              // Pinned: subtle left accent in signature color so pinned tabs
              // stand out from regular tabs even when inactive.
              borderLeft: tab.pinned ? '2px solid var(--signature, #5b7ec9)' : undefined,
              color: 'var(--fg)',
              maxWidth: 200,
            }}
            onClick={() => onActivate(tab.doc_id)}
            title={tab.pinned ? t('chat.pinnedTabHint', { name: tab.filename, defaultValue: `${tab.filename} (pinned)` }) : tab.filename}
          >
            <Icon size={12} className="shrink-0 opacity-70" />
            <span className="truncate">{tab.filename}</span>
            {/* Pin/unpin button. Solid icon when pinned (always visible),
                outline when not (visible on hover for less clutter). */}
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onTogglePin?.(tab.doc_id)
              }}
              className={cn(
                'shrink-0 p-0.5 rounded hover:bg-white/10',
                tab.pinned ? 'opacity-90' : 'opacity-0 group-hover:opacity-60',
              )}
              aria-label={tab.pinned ? t('chat.unpinTab', { defaultValue: 'Unpin tab' }) : t('chat.pinTab', { defaultValue: 'Pin tab' })}
              title={tab.pinned ? t('chat.unpinTab', { defaultValue: 'Unpin tab' }) : t('chat.pinTab', { defaultValue: 'Pin tab' })}
            >
              {tab.pinned
                ? <Pin size={11} fill="currentColor" style={{ color: 'var(--signature, #5b7ec9)' }} />
                : <PinOff size={11} />}
            </button>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                downloadDocument(tab.doc_id, tab.filename, USER_ID)
                  .catch(err => console.error('Download failed:', err))
              }}
              className="shrink-0 p-0.5 rounded hover:bg-white/10 opacity-50 hover:opacity-100"
              aria-label="Download original file"
              title="Download original file"
            >
              <Download size={11} />
            </button>
            {/* X button hidden when pinned — user must unpin first.
                Standard browser-tab pin semantics. */}
            {!tab.pinned && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onClose(tab.doc_id)
                }}
                className="shrink-0 p-0.5 rounded hover:bg-white/10 opacity-50 hover:opacity-100"
                aria-label="Close tab"
              >
                <X size={11} />
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}
