import { useEffect, useState } from 'react'
import { X, BookmarkPlus, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { saveCollection } from '@/lib/api'

function defaultName() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `selection-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`
}

/**
 * Save-selection modal.
 *
 * Props:
 *   open: boolean
 *   count: number of items that will be saved
 *   docIds: doc_id list to save
 *   onClose: () => void
 *   onSaved: (name) => void          — called on successful save with the collection name
 */
export default function SaveCollectionDialog({ open, count, docIds, onClose, onSaved }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [mode, setMode] = useState('new')
  const [busy, setBusy] = useState(false)
  const [conflict, setConflict] = useState(null) // { existingCount }
  const [error, setError] = useState('')

  useEffect(() => {
    if (open) {
      setName(defaultName())
      setMode('new')
      setConflict(null)
      setError('')
      setBusy(false)
    }
  }, [open])

  if (!open) return null

  const canSubmit = name.trim().length > 0 && !busy && docIds?.length >= 2

  async function handleSave(e) {
    e?.preventDefault?.()
    if (!canSubmit) return
    setBusy(true)
    setError('')
    try {
      const res = await saveCollection(name.trim(), docIds, mode)
      onSaved?.(res.name || name.trim())
    } catch (err) {
      const msg = err?.message || String(err)
      if (msg.includes('409') || msg.toLowerCase().includes('already exists')) {
        // Extract existing count if present in detail
        const m = msg.match(/with (\d+) documents?/i)
        setConflict({ existingCount: m ? parseInt(m[1], 10) : null })
      } else {
        setError(msg)
      }
    } finally {
      setBusy(false)
    }
  }

  async function handleMerge() {
    setBusy(true)
    setError('')
    setConflict(null)
    try {
      const res = await saveCollection(name.trim(), docIds, 'merge')
      onSaved?.(res.name || name.trim())
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSave}
        className="w-[420px] max-w-[90vw] rounded-xl p-5
                   bg-[color:var(--bg-2,#111115)] border border-white/10
                   shadow-2xl"
      >
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <BookmarkPlus size={18} className="text-[color:var(--signature,#5b7ec9)]" />
            <h2 className="text-base font-semibold text-[color:var(--fg,#f4f2ee)]">
              {t('selection.saveTitle', { defaultValue: 'Save as Collection' })}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded hover:bg-white/10 text-[color:var(--fg-dim,#9a9690)]"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>

        <p className="text-xs text-[color:var(--fg-dim,#9a9690)] mb-3">
          {t('selection.saveHelp', {
            count,
            defaultValue: `${count} item(s) will be grouped into a new collection.`,
          })}
        </p>

        <label className="block text-xs font-medium text-[color:var(--fg-dim,#9a9690)] mb-1">
          {t('selection.saveNameLabel', { defaultValue: 'Collection name' })}
        </label>
        <input
          autoFocus
          type="text"
          value={name}
          onChange={(e) => { setName(e.target.value); setConflict(null); setError('') }}
          placeholder="my-selection"
          className="w-full rounded-md px-3 py-2 text-sm
                     bg-[color:var(--bg,#08080a)] border border-white/10
                     text-[color:var(--fg,#f4f2ee)]
                     focus:outline-none focus:border-[color:var(--signature,#5b7ec9)]"
        />
        <p className="text-[10px] text-[color:var(--fg-faint,#5a564f)] mt-1">
          {t('selection.saveNameHint', {
            defaultValue: 'Letters, numbers, hyphens, underscores. Spaces become hyphens.',
          })}
        </p>

        {conflict && (
          <div className="mt-3 p-3 rounded-md border border-amber-500/30 bg-amber-500/10 text-xs">
            <div className="font-medium text-amber-400 mb-1">
              {t('selection.conflictTitle', { defaultValue: 'Name already exists' })}
            </div>
            <div className="text-[color:var(--fg-dim,#9a9690)] mb-2">
              {t('selection.conflictBody', {
                name,
                count: conflict.existingCount ?? '?',
                defaultValue: `Collection "${name}" already has ${conflict.existingCount ?? '?'} documents. Pick a different name, or merge your selection into it.`,
              })}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleMerge}
                disabled={busy}
                className="px-3 py-1 text-xs rounded bg-amber-500/20 hover:bg-amber-500/30 text-amber-300"
              >
                {t('selection.merge', { defaultValue: 'Merge' })}
              </button>
              <button
                type="button"
                onClick={() => setConflict(null)}
                className="px-3 py-1 text-xs rounded bg-white/5 hover:bg-white/10 text-[color:var(--fg,#f4f2ee)]"
              >
                {t('selection.rename', { defaultValue: 'Rename' })}
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="mt-3 p-2 rounded-md border border-red-500/30 bg-red-500/10 text-xs text-red-300">
            {error}
          </div>
        )}

        <div className="flex items-center justify-end gap-2 mt-4">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded-md text-[color:var(--fg-dim,#9a9690)] hover:bg-white/5"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="submit"
            disabled={!canSubmit}
            className="flex items-center gap-2 px-4 py-1.5 text-sm rounded-md
                       bg-[color:var(--signature,#5b7ec9)] text-white font-medium
                       disabled:opacity-40 disabled:cursor-not-allowed
                       hover:brightness-110 transition"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            {t('selection.save', { defaultValue: 'Save' })}
          </button>
        </div>
      </form>
    </div>
  )
}
