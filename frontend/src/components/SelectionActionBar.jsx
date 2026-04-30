import { useState, useEffect, useMemo } from 'react'
import { MessageSquare, Network, BookmarkPlus, X, AlertTriangle, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { useSelection } from '@/hooks/useSelection'
import SelectedDocsPopover from '@/components/SelectedDocsPopover'

/**
 * Bottom action bar shown when selection count >= 1.
 * Gmail-style floating pill at bottom-center of the screen.
 *
 * Props:
 *   onAsk: () => void            — Phase 4 action (required)
 *   onVisualize: () => void      — Phase 5 action (required)
 *   onSave: () => void           — Phase 6 action (required); disabled until count >= 2
 *   documents: Array              — full doc list; required for the peek popover
 *                                   to look up filenames for selections that
 *                                   aren't currently visible (cross-search case).
 */
const HINT_KEY = 'meinrag.multiselect.hinted'

export default function SelectionActionBar({ onAsk, onVisualize, onSave, documents = [] }) {
  const { t } = useTranslation()
  const selection = useSelection()
  const [peekOpen, setPeekOpen] = useState(false)
  const [showHint, setShowHint] = useState(() => {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem(HINT_KEY) !== '1'
  })

  // Auto-dismiss the hint after 8 s; click ✕ also dismisses.
  useEffect(() => {
    if (!showHint || selection.count < 1) return
    const timer = setTimeout(() => dismissHint(), 8000)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showHint, selection.count])

  const dismissHint = () => {
    setShowHint(false)
    try { localStorage.setItem(HINT_KEY, '1') } catch { /* ignore */ }
  }

  // Selected docs hydrated with filenames from the full doc list — required so
  // the peek popover can name docs that aren't in the current search filter.
  // MUST be called before any early-return to obey React rules-of-hooks.
  const selectedDocs = useMemo(
    () => documents.filter(d => selection.hasDoc(d.doc_id)),
    [documents, selection.docs],
  )

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

  return (
    <>
      {showHint && (
        <div
          role="status"
          className="fixed bottom-24 left-1/2 -translate-x-1/2 z-40
                     flex items-start gap-2 px-3.5 py-2.5 rounded-lg
                     max-w-[420px] text-[12px] leading-snug
                     bg-[color:var(--bg-2,#111115)]/95 backdrop-blur
                     border border-[color:var(--signature,#5b7ec9)]
                     shadow-xl shadow-black/30 animate-in fade-in"
          style={{ color: 'var(--fg)' }}
        >
          <Sparkles size={14} style={{ color: 'var(--signature)', marginTop: 2 }} />
          <div className="flex-1">
            <div className="font-medium mb-0.5">
              {t('selection.hintTitle', { defaultValue: 'Selection actions' })}
            </div>
            <div className="opacity-70">
              {t('selection.hintBody', { defaultValue: 'Ask AI about your selection, visualize as a graph, or save as a named collection.' })}
            </div>
          </div>
          <button
            type="button"
            onClick={dismissHint}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="opacity-50 hover:opacity-100 shrink-0 -mr-1"
          >
            <X size={12} />
          </button>
        </div>
      )}
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

      <button
        type="button"
        data-peek-trigger
        onClick={() => setPeekOpen(p => !p)}
        className="text-sm font-medium text-[color:var(--fg,#f4f2ee)] pl-2 pr-1 hover:underline decoration-dotted underline-offset-4"
        title={t('selection.peekTitle', { defaultValue: 'Selected documents' })}
        aria-expanded={peekOpen}
      >
        {t('selection.nSelected', { count, defaultValue: `${count} selected` })}
      </button>

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

      {peekOpen && (
        <SelectedDocsPopover
          selectedDocs={selectedDocs}
          onRemove={(docId) => selection.toggleDoc(docId)}
          onClose={() => setPeekOpen(false)}
        />
      )}
    </>
  )
}
