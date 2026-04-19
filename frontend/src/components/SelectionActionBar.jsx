import { useState } from 'react'
import { MessageSquare, Network, BookmarkPlus, X, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { useSelection } from '@/hooks/useSelection'

/**
 * Bottom action bar shown when selection count >= 1.
 * Gmail-style floating pill at bottom-center of the screen.
 *
 * Props:
 *   onAsk: () => void            — Phase 4 action (required)
 *   onVisualize: () => void      — Phase 5 action (required)
 *   onSave: () => void           — Phase 6 action (required); disabled until count >= 2
 */
export default function SelectionActionBar({ onAsk, onVisualize, onSave }) {
  const { t } = useTranslation()
  const selection = useSelection()
  const [hoverItems, setHoverItems] = useState(false)

  const count = selection.count
  if (count < 1) return null

  const saveDisabled = count < 2
  const warnLarge = count >= 20

  const handleClear = () => {
    const hadItems = selection.count
    selection.clearWithUndo()
    toast(
      t('selection.cleared', { count: hadItems, defaultValue: `Cleared ${hadItems} item(s)` }),
      {
        action: {
          label: t('selection.undo', { defaultValue: 'Undo' }),
          onClick: () => {
            const ok = selection.undo()
            if (ok) toast.success(t('selection.restored', { defaultValue: 'Selection restored' }))
          },
        },
        duration: 5000,
      }
    )
  }

  const docIds = [...selection.docs]
  const collectionNames = [...selection.collections]
  const previewItems = [
    ...collectionNames.map(c => `📁 ${c}`),
    ...docIds.map(d => d.slice(0, 10) + '…'),
  ].slice(0, 5)

  return (
    <div
      role="toolbar"
      aria-label={t('selection.toolbar', { defaultValue: 'Selection actions' })}
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40
                 flex items-center gap-2 px-3 py-2 rounded-full
                 bg-[color:var(--bg-2,#111115)]/95 backdrop-blur
                 border border-[color:var(--signature,#5b7ec9)]/50
                 shadow-xl shadow-black/30"
    >
      {warnLarge && (
        <div
          className="flex items-center gap-1 px-2 py-0.5 rounded-full
                     bg-amber-500/15 text-amber-400 text-xs font-medium"
          title={t('selection.largeWarning', { defaultValue: 'Large selection — chat may use summary mode' })}
        >
          <AlertTriangle size={12} />
          <span>{count}+</span>
        </div>
      )}

      <span
        className="relative text-sm font-medium text-[color:var(--fg,#f4f2ee)] pl-2 pr-1 cursor-default"
        onMouseEnter={() => setHoverItems(true)}
        onMouseLeave={() => setHoverItems(false)}
      >
        {t('selection.nSelected', { count, defaultValue: `${count} selected` })}
        {hoverItems && previewItems.length > 0 && (
          <span
            className="absolute bottom-full left-0 mb-2 z-50
                       whitespace-nowrap rounded-md px-3 py-2
                       bg-black/90 text-[11px] text-white/90 shadow-lg
                       pointer-events-none"
          >
            {previewItems.map((item, i) => (
              <div key={i}>{item}</div>
            ))}
            {count > previewItems.length && (
              <div className="opacity-60 mt-1">+ {count - previewItems.length} more</div>
            )}
          </span>
        )}
      </span>

      <div className="h-5 w-px bg-white/10 mx-1" />

      <button
        type="button"
        onClick={onAsk}
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full
                   bg-[color:var(--signature,#5b7ec9)] text-white font-medium
                   hover:brightness-110 transition"
        title={t('selection.askTooltip', { defaultValue: 'Ask a question about the selected items' })}
      >
        <MessageSquare size={14} />
        <span>{t('selection.ask', { defaultValue: 'Ask' })}</span>
      </button>

      <button
        type="button"
        onClick={onVisualize}
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full
                   bg-white/5 text-[color:var(--fg,#f4f2ee)] hover:bg-white/10 transition"
        title={t('selection.visualizeTooltip', { defaultValue: 'Show selected items in the graph' })}
      >
        <Network size={14} />
        <span>{t('selection.visualize', { defaultValue: 'Visualize' })}</span>
      </button>

      <button
        type="button"
        onClick={onSave}
        disabled={saveDisabled}
        className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-full
                   bg-white/5 text-[color:var(--fg,#f4f2ee)] hover:bg-white/10
                   disabled:opacity-40 disabled:cursor-not-allowed transition"
        title={saveDisabled
          ? t('selection.saveMinTooltip', { defaultValue: 'Select at least 2 items to save' })
          : t('selection.saveTooltip', { defaultValue: 'Save as a named collection' })}
      >
        <BookmarkPlus size={14} />
        <span>{t('selection.save', { defaultValue: 'Save' })}</span>
      </button>

      <div className="h-5 w-px bg-white/10 mx-1" />

      <button
        type="button"
        onClick={handleClear}
        aria-label={t('selection.clear', { defaultValue: 'Clear selection' })}
        className="p-1.5 rounded-full text-[color:var(--fg-dim,#9a9690)] hover:bg-white/5 hover:text-[color:var(--fg,#f4f2ee)] transition"
        title={t('selection.clear', { defaultValue: 'Clear selection' })}
      >
        <X size={14} />
      </button>
    </div>
  )
}
