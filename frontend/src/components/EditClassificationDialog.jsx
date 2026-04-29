import { useEffect, useMemo, useRef, useState } from 'react'
import { X, Sparkles, Loader2, Tag } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { patchDocument, reclassifyDocument } from '@/lib/api'

function formatName(s) {
  if (!s) return ''
  return s.split('-').map(w => w[0]?.toUpperCase() + w.slice(1)).join(' ')
}

/**
 * Edit a document's three-layer classification.
 *
 *   • Primary category — single-select from PRIMARY_CATEGORIES
 *   • Sub-tags         — multi-select chips (free-add restricted to taxonomy values
 *                        for the chosen primary, plus any tag the doc already has)
 *   • Collections      — multi-select from existing user collections
 *                        (creating a new one is the SaveCollection flow, not this one)
 *
 * The "Suggest with AI" button calls the reclassify endpoint, which both
 * suggests AND persists. The user can then manually adjust + Save again.
 *
 * Props:
 *   open     : boolean
 *   doc      : { doc_id, filename, primary_category, subtags[], collections[] }
 *   taxonomy : { primary_categories, domain_options, user_collections }
 *   userId   : string — passed through to PATCH/reclassify; defaults to 'admin'
 *   onClose  : (aiRanFlag) => void  — aiRanFlag = true if reclassify mutated server
 *                                     state during this session, so caller can
 *                                     refresh the doc list even on Cancel
 *   onSaved  : (updatedDoc) => void
 */
export default function EditClassificationDialog({ open, doc, taxonomy, userId = 'admin', onClose, onSaved }) {
  const { t } = useTranslation()

  const [primary, setPrimary] = useState(null)
  const [subtags, setSubtags] = useState([])
  const [collections, setCollections] = useState([])
  const [busy, setBusy] = useState(false)
  const [aiBusy, setAiBusy] = useState(false)
  const [error, setError] = useState('')
  // Track whether the AI-suggest endpoint persisted changes during this open
  // session, so onClose can tell the parent to invalidate the doc cache even
  // when the user cancels.
  const aiRanRef = useRef(false)

  // Reset to doc state on open
  useEffect(() => {
    if (open && doc) {
      setPrimary(doc.primary_category || null)
      setSubtags(Array.isArray(doc.subtags) ? doc.subtags : [])
      setCollections(Array.isArray(doc.collections) ? doc.collections : [])
      setError('')
      setBusy(false)
      setAiBusy(false)
      aiRanRef.current = false
    }
  }, [open, doc])

  // Cancel/close — let parent know whether to invalidate caches
  const handleClose = () => onClose?.(aiRanRef.current)

  // ESC closes the dialog
  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') handleClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  // Available subtags = domains for chosen primary, OR all-tags if no primary picked.
  // Always include any tag the doc currently has (legacy / preserved selection).
  const availableSubtags = useMemo(() => {
    if (!taxonomy) return []
    const opts = taxonomy.domain_options || {}
    const set = new Set()
    if (primary && opts[primary]) {
      opts[primary].forEach(s => set.add(s))
    } else {
      Object.values(opts).forEach(arr => arr.forEach(s => set.add(s)))
    }
    subtags.forEach(s => set.add(s))
    return Array.from(set).sort()
  }, [taxonomy, primary, subtags])

  if (!open || !doc) return null

  const toggleSubtag = (tag) => {
    setSubtags(prev => prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag])
  }
  const toggleCollection = (col) => {
    setCollections(prev => prev.includes(col) ? prev.filter(c => c !== col) : [...prev, col])
  }

  async function handleAiSuggest() {
    setAiBusy(true)
    setError('')
    try {
      const res = await reclassifyDocument(doc.doc_id, userId)
      aiRanRef.current = true   // server state was mutated; flag for cache invalidation on close
      setPrimary(res.primary_category || null)
      setSubtags(Array.isArray(res.subtags) ? res.subtags : [])
      if (Array.isArray(res.collections)) setCollections(res.collections)
    } catch (e) {
      setError(e?.message || String(e))
    } finally {
      setAiBusy(false)
    }
  }

  async function handleSave(e) {
    e?.preventDefault?.()
    setBusy(true)
    setError('')
    try {
      const updated = await patchDocument(
        doc.doc_id,
        { primary_category: primary, subtags, collections },
        userId,
      )
      onSaved?.(updated)
    } catch (err) {
      setError(err?.message || String(err))
    } finally {
      setBusy(false)
    }
  }

  const userCollections = taxonomy?.user_collections || []
  const primaryOptions = taxonomy?.primary_categories || []

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onClick={handleClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={handleSave}
        className="w-[520px] max-w-[92vw] max-h-[85vh] overflow-auto rounded-xl p-5 bg-[color:var(--bg-2,#111115)] border border-white/10 shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-start justify-between mb-1">
          <div className="flex items-center gap-2">
            <Tag size={17} className="text-[color:var(--signature,#5b7ec9)]" />
            <h2 className="text-base font-semibold text-[color:var(--fg,#f4f2ee)]">
              {t('editClass.title', { defaultValue: 'Edit classification' })}
            </h2>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="p-1 rounded hover:bg-white/10 text-[color:var(--fg-dim,#9a9690)]"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </div>
        <p className="text-xs text-[color:var(--fg-dim,#9a9690)] truncate mb-4" title={doc.filename}>
          {doc.filename}
        </p>

        {/* AI suggest button */}
        <button
          type="button"
          onClick={handleAiSuggest}
          disabled={aiBusy || busy}
          className="w-full mb-4 flex items-center justify-center gap-2 px-3 py-2 rounded-md text-sm bg-[color:var(--bg,#08080a)] border border-white/10 text-[color:var(--fg,#f4f2ee)] hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {aiBusy ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} className="text-[color:var(--signature,#5b7ec9)]" />}
          {t('editClass.aiSuggest', { defaultValue: 'Suggest with AI' })}
        </button>

        {/* Primary category */}
        <label className="block text-xs font-medium text-[color:var(--fg-dim,#9a9690)] mb-1.5">
          {t('editClass.primaryCategory', { defaultValue: 'Primary category' })}
        </label>
        <select
          value={primary || ''}
          onChange={(e) => {
            const next = e.target.value || null
            setPrimary(next)
            // Drop subtags that no longer fit the new primary's domain options
            if (next && taxonomy?.domain_options?.[next]) {
              const allowed = new Set(taxonomy.domain_options[next])
              setSubtags(prev => prev.filter(s => allowed.has(s)))
            }
          }}
          className="w-full rounded-md px-3 py-2 text-sm mb-4 bg-[color:var(--bg,#08080a)] border border-white/10 text-[color:var(--fg,#f4f2ee)] focus:outline-none focus:border-[color:var(--signature,#5b7ec9)]"
        >
          <option value="">— {t('dashboard.uncategorized', { defaultValue: 'Uncategorized' })} —</option>
          {primaryOptions.map(p => (
            <option key={p} value={p}>{formatName(p)}</option>
          ))}
        </select>

        {/* Sub-tags */}
        <label className="block text-xs font-medium text-[color:var(--fg-dim,#9a9690)] mb-1.5">
          {t('editClass.subtags', { defaultValue: 'Sub-tags' })}
        </label>
        {availableSubtags.length === 0 ? (
          <p className="text-[11px] text-[color:var(--fg-faint,#5a564f)] italic mb-4">
            {t('editClass.noSubtags', { defaultValue: 'No subtags available — pick a primary category first.' })}
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5 mb-4">
            {availableSubtags.map(tag => {
              const active = subtags.includes(tag)
              return (
                <button
                  type="button"
                  key={tag}
                  onClick={() => toggleSubtag(tag)}
                  className="px-2 py-1 rounded text-[11px] uppercase tracking-[0.04em] transition"
                  style={{
                    fontFamily: 'var(--mono)',
                    backgroundColor: active ? 'var(--signature)' : 'var(--bg)',
                    color: active ? 'var(--bg)' : 'var(--fg-dim)',
                    border: '1px solid',
                    borderColor: active ? 'var(--signature)' : 'var(--border)',
                    fontWeight: active ? 600 : 400,
                  }}
                >
                  {tag}
                </button>
              )
            })}
          </div>
        )}

        {/* Collections (user-curated) */}
        <label className="block text-xs font-medium text-[color:var(--fg-dim,#9a9690)] mb-1.5">
          {t('editClass.collections', { defaultValue: 'Collections (optional)' })}
        </label>
        {userCollections.length === 0 ? (
          <p className="text-[11px] text-[color:var(--fg-faint,#5a564f)] italic mb-4">
            {t('editClass.noCollections', { defaultValue: 'No collections yet — create one from a multi-doc selection on the dashboard.' })}
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5 mb-4">
            {userCollections.map(col => {
              const active = collections.includes(col)
              return (
                <button
                  type="button"
                  key={col}
                  onClick={() => toggleCollection(col)}
                  className="px-2.5 py-1 rounded text-[11px] transition"
                  style={{
                    fontFamily: 'var(--mono)',
                    backgroundColor: active ? 'var(--signature)' : 'var(--bg)',
                    color: active ? 'var(--bg)' : 'var(--fg-dim)',
                    border: '1px solid',
                    borderColor: active ? 'var(--signature)' : 'var(--border)',
                    fontWeight: active ? 600 : 400,
                  }}
                >
                  {formatName(col)}
                </button>
              )
            })}
          </div>
        )}

        {error && (
          <div role="alert" className="mb-3 p-2 rounded-md border border-red-500/30 bg-red-500/10 text-xs text-red-300">
            {error}
          </div>
        )}

        {/* Footer actions */}
        <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/5">
          <button
            type="button"
            onClick={handleClose}
            className="px-3 py-1.5 text-sm rounded-md text-[color:var(--fg-dim,#9a9690)] hover:bg-white/5"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          <button
            type="submit"
            disabled={busy || aiBusy}
            className="flex items-center gap-2 px-4 py-1.5 text-sm rounded-md bg-[color:var(--signature,#5b7ec9)] text-white font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            {t('common.save', { defaultValue: 'Save' })}
          </button>
        </div>
      </form>
    </div>
  )
}
