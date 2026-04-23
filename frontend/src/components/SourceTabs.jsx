import { useRef, useEffect } from 'react'
import { X, FileText, FileType2 } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Tab bar for the Chat page main area.
 *
 * Props:
 *   tabs: [{ doc_id, filename, file_type }]
 *   activeDocId: string | null
 *   onActivate: (doc_id) => void
 *   onClose: (doc_id) => void
 */
export default function SourceTabs({ tabs, activeDocId, onActivate, onClose }) {
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
              'flex items-center gap-1.5 px-3 py-2 text-xs cursor-pointer shrink-0 border-r transition-colors',
              active
                ? 'bg-[var(--bg-1)] border-b-2 border-b-[var(--signature,#5b7ec9)]'
                : 'opacity-60 hover:opacity-100',
            )}
            style={{
              borderRightColor: 'var(--border-strong, rgba(255,255,255,0.14))',
              color: 'var(--fg)',
              maxWidth: 200,
            }}
            onClick={() => onActivate(tab.doc_id)}
            title={tab.filename}
          >
            <Icon size={12} className="shrink-0 opacity-70" />
            <span className="truncate">{tab.filename}</span>
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
          </div>
        )
      })}
    </div>
  )
}
