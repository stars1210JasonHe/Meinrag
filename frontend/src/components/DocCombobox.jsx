/**
 * DocCombobox — typeahead doc picker with two sections (Collections + Documents).
 *
 * Replaces the legacy <select> on /graph: that worked at <100 docs but became
 * unusable at 1000+. Now backed by GET /documents?search= (G4a), so the matched
 * set is server-paginated and capped at 20 per fetch — works for any corpus size.
 *
 * Props:
 *   value           — the current selection. One of:
 *                       ''                (means "all documents")
 *                       '<doc_id>'        (a specific doc)
 *                       'col:<name>'      (a saved collection)
 *   onChange        — called with the new value (same shape as `value`).
 *   collections     — string[]. Saved collections to show under the "Collections"
 *                     optgroup. Coming from the taxonomy endpoint.
 *   userId          — passed to fetchDocuments for X-User-Id.
 *   labels          — { all, collections, documents, placeholder, allLabel }.
 *                     i18n strings — caller-provided so we don't hardcode locales.
 *   currentLabel    — optional override for the trigger button display when a
 *                     specific doc is selected (we use it to show the filename
 *                     immediately on mount, before /documents fetches).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Search, X, Check, ChevronDown } from 'lucide-react'
import { fetchDocuments } from '@/lib/api'

const RECENT_KEY = 'meinrag.docCombobox.recent'
const RECENT_MAX = 5

function loadRecent() {
  if (typeof localStorage === 'undefined') return []
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr.slice(0, RECENT_MAX) : []
  } catch {
    return []
  }
}

function saveRecent(entry) {
  if (typeof localStorage === 'undefined') return
  try {
    const cur = loadRecent().filter(r => r.doc_id !== entry.doc_id)
    cur.unshift(entry)
    localStorage.setItem(RECENT_KEY, JSON.stringify(cur.slice(0, RECENT_MAX)))
  } catch {
    /* quota / json — ignore */
  }
}

function useDebounced(value, delay = 250) {
  const [d, setD] = useState(value)
  useEffect(() => {
    const h = setTimeout(() => setD(value), delay)
    return () => clearTimeout(h)
  }, [value, delay])
  return d
}

export default function DocCombobox({
  value,
  onChange,
  collections = [],
  userId,
  labels,
  currentLabel,
}) {
  const [open, setOpen] = useState(false)
  const [rawSearch, setRawSearch] = useState('')
  const search = useDebounced(rawSearch, 250)
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [recent, setRecent] = useState(() => loadRecent())

  const containerRef = useRef(null)
  const inputRef = useRef(null)

  // Fetch results whenever the (debounced) search changes — including when
  // search is empty, in which case the server returns the unfiltered list
  // (limited to 20 most-recent uploads). Race-safe via cancel flag.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    fetchDocuments(userId, { search: search || undefined, limit: 20 })
      .then(data => {
        if (cancelled) return
        const docs = data?.documents || (Array.isArray(data) ? data : [])
        setResults(docs)
      })
      .catch(() => {
        if (cancelled) return
        setResults([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [search, open, userId])

  // Close on outside click or Escape.
  useEffect(() => {
    if (!open) return
    const onClick = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setOpen(false)
        setRawSearch('')
      }
    }
    window.addEventListener('mousedown', onClick)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Auto-focus the search input when opened.
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  // Trigger label: show selection if any, else fall back to the "all" label.
  const triggerLabel = useMemo(() => {
    if (!value) return labels.allLabel
    if (value.startsWith('col:')) return value.slice(4)
    if (currentLabel) return currentLabel
    const found = results.find(d => d.doc_id === value)
    if (found) return found.filename
    const recentMatch = recent.find(r => r.doc_id === value)
    if (recentMatch) return recentMatch.filename
    return value
  }, [value, results, recent, currentLabel, labels.allLabel])

  const pick = (newValue, displayName) => {
    onChange(newValue)
    setOpen(false)
    setRawSearch('')
    if (newValue && !newValue.startsWith('col:') && displayName) {
      const entry = { doc_id: newValue, filename: displayName }
      saveRecent(entry)
      setRecent(loadRecent())
    }
  }

  const filteredCollections = collections.filter(c =>
    !rawSearch || c.toLowerCase().includes(rawSearch.toLowerCase())
  )
  const filteredRecent = recent.filter(r =>
    !rawSearch || r.filename.toLowerCase().includes(rawSearch.toLowerCase())
  )

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="text-xs rounded px-2 py-1 outline-none flex items-center gap-1.5 max-w-[260px]"
        style={{
          backgroundColor: 'var(--border-strong, rgba(255,255,255,0.14))',
          color: 'var(--fg, #f4f2ee)',
          border: '1px solid var(--border-strong, rgba(255,255,255,0.18))',
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="truncate">{triggerLabel}</span>
        <ChevronDown size={12} className="opacity-60 shrink-0" />
      </button>

      {open && (
        <div
          className="absolute left-0 mt-1 z-50 w-[320px] max-h-[380px] flex flex-col rounded-md shadow-lg overflow-hidden"
          style={{
            backgroundColor: 'var(--bg-2, #13131a)',
            border: '1px solid var(--border-strong, rgba(255,255,255,0.18))',
          }}
          role="listbox"
        >
          <div className="flex items-center gap-2 px-2 py-1.5 border-b"
               style={{ borderColor: 'var(--border, rgba(255,255,255,0.05))' }}>
            <Search size={14} className="opacity-50 shrink-0" style={{ color: 'var(--fg, #f4f2ee)' }} />
            <input
              ref={inputRef}
              type="text"
              value={rawSearch}
              onChange={e => setRawSearch(e.target.value)}
              placeholder={labels.placeholder}
              className="flex-1 bg-transparent outline-none text-xs"
              style={{ color: 'var(--fg, #f4f2ee)' }}
            />
            {rawSearch && (
              <button onClick={() => setRawSearch('')} className="opacity-40 hover:opacity-100">
                <X size={12} style={{ color: 'var(--fg, #f4f2ee)' }} />
              </button>
            )}
          </div>

          <div className="overflow-y-auto flex-1">
            {/* "All documents" option always visible */}
            <button
              type="button"
              onClick={() => pick('', null)}
              className="w-full text-left px-3 py-1.5 text-xs flex items-center justify-between hover:opacity-80"
              style={{ color: 'var(--fg, #f4f2ee)' }}
            >
              <span>{labels.allLabel}</span>
              {!value && <Check size={12} className="opacity-70" />}
            </button>

            {filteredCollections.length > 0 && (
              <div className="border-t pt-1" style={{ borderColor: 'var(--border, rgba(255,255,255,0.05))' }}>
                <div className="px-3 py-1 text-[10px] uppercase tracking-wide opacity-50"
                     style={{ color: 'var(--fg-dim, #9a9690)' }}>
                  {labels.collections}
                </div>
                {filteredCollections.map(c => {
                  const v = `col:${c}`
                  return (
                    <button
                      key={v}
                      type="button"
                      onClick={() => pick(v, null)}
                      className="w-full text-left px-3 py-1.5 text-xs flex items-center justify-between hover:opacity-80"
                      style={{ color: 'var(--fg, #f4f2ee)' }}
                    >
                      <span className="truncate">{c}</span>
                      {value === v && <Check size={12} className="opacity-70 shrink-0" />}
                    </button>
                  )
                })}
              </div>
            )}

            {!rawSearch && filteredRecent.length > 0 && (
              <div className="border-t pt-1" style={{ borderColor: 'var(--border, rgba(255,255,255,0.05))' }}>
                <div className="px-3 py-1 text-[10px] uppercase tracking-wide opacity-50"
                     style={{ color: 'var(--fg-dim, #9a9690)' }}>
                  {labels.recent || 'Recent'}
                </div>
                {filteredRecent.map(r => (
                  <button
                    key={`recent:${r.doc_id}`}
                    type="button"
                    onClick={() => pick(r.doc_id, r.filename)}
                    className="w-full text-left px-3 py-1.5 text-xs flex items-center justify-between hover:opacity-80"
                    style={{ color: 'var(--fg, #f4f2ee)' }}
                  >
                    <span className="truncate">{r.filename}</span>
                    {value === r.doc_id && <Check size={12} className="opacity-70 shrink-0" />}
                  </button>
                ))}
              </div>
            )}

            <div className="border-t pt-1" style={{ borderColor: 'var(--border, rgba(255,255,255,0.05))' }}>
              <div className="px-3 py-1 text-[10px] uppercase tracking-wide opacity-50"
                   style={{ color: 'var(--fg-dim, #9a9690)' }}>
                {labels.documents}
                {loading && <span className="ml-1 opacity-60">…</span>}
              </div>
              {results.length === 0 && !loading && (
                <div className="px-3 py-2 text-xs opacity-50"
                     style={{ color: 'var(--fg-dim, #9a9690)' }}>
                  {labels.noResults || 'No matches'}
                </div>
              )}
              {results.map(d => (
                <button
                  key={d.doc_id}
                  type="button"
                  onClick={() => pick(d.doc_id, d.filename)}
                  className="w-full text-left px-3 py-1.5 text-xs flex items-center justify-between hover:opacity-80"
                  style={{ color: 'var(--fg, #f4f2ee)' }}
                >
                  <span className="truncate">{d.filename}</span>
                  {value === d.doc_id && <Check size={12} className="opacity-70 shrink-0" />}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
