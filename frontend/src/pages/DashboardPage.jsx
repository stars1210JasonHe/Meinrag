import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import Sunburst from '@/components/Sunburst'
import RecentStrip from '@/components/RecentStrip'
import CategorySection from '@/components/CategorySection'
import { useTaxonomyHierarchy } from '@/hooks/useTaxonomyHierarchy'
import {
  Search, Upload, MoreVertical, Trash2, Download, RefreshCw,
  FileText, X, MessageSquare, Filter, ChevronUp, ChevronDown, Network,
  PanelLeftClose, PanelLeftOpen,
} from 'lucide-react'
import { toast } from 'sonner'
import { fetchDocuments, fetchTaxonomy, deleteDocument } from '@/lib/api'
import { cn } from '@/lib/utils'
import ContextMenu from '@/components/ContextMenu'
import ConfirmDialog from '@/components/ConfirmDialog'
import SelectionActionBar from '@/components/SelectionActionBar'
import SaveCollectionDialog from '@/components/SaveCollectionDialog'
import { useSelection } from '@/hooks/useSelection'
import { DocCardSkeleton } from '@/components/skeletons'

const USER_ID = 'admin'

// localStorage key: list of collection names user explicitly created via Save
const USER_SAVED_KEY = `meinrag.user_saved_collections.${USER_ID}`

function loadUserSaved() {
  try {
    const raw = localStorage.getItem(USER_SAVED_KEY)
    return new Set(raw ? JSON.parse(raw) : [])
  } catch {
    return new Set()
  }
}

function markUserSaved(name) {
  try {
    const cur = loadUserSaved()
    cur.add(name)
    localStorage.setItem(USER_SAVED_KEY, JSON.stringify([...cur]))
  } catch {
    // ignore
  }
}

// Graph node colors reading live from CSS vars (captured at paint time)
function cssVar(name, fallback = '#5b7ec9') {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  } catch { return fallback }
}

// Shape colors — derived from CSS tokens. Read once at module init via cssVar().
// If theme switches at runtime, ForceGraph2D refresh-on-key handles it.
const DOC_COLOR = cssVar('--signature',     '#6b8fd6')
const DOC_COLOR_DIM = cssVar('--signature-dim', '#4a6cb4')
const FOLDER_COLOR = cssVar('--collection',    '#d4a64a')
const FOLDER_FILL = cssVar('--collection-soft', 'rgba(212,166,74,0.16)')
const FOLDER_TAB_COLOR = cssVar('--collection-dim', '#a8761e')

// Debounce hook — for search input
function useDebounced(value, delay = 300) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const h = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(h)
  }, [value, delay])
  return debounced
}

function relTime(iso) {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const sec = Math.max(1, Math.floor(diff / 1000))
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h`
  const day = Math.floor(hr / 24)
  if (day < 30) return `${day}d`
  const mo = Math.floor(day / 30)
  if (mo < 12) return `${mo}mo`
  return `${Math.floor(mo / 12)}y`
}

function formatName(name) {
  return String(name).split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { t } = useTranslation()
  // (D-sprint: graphRef/containerRef removed — no force graph on dashboard)

  const [rawSearch, setRawSearch] = useState('')
  const search = useDebounced(rawSearch, 300)
  const [activeFilters, setActiveFilters] = useState([])
  const [showFilters, setShowFilters] = useState(false)
  // (D-sprint: showPanel removed — docs always rendered as category sections)
  const [menuOpen, setMenuOpen] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [domainsCollapsed, setDomainsCollapsed] = useState(() => {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem('meinrag.dashboard.domainsCollapsed') === '1'
  })
  useEffect(() => {
    localStorage.setItem('meinrag.dashboard.domainsCollapsed', domainsCollapsed ? '1' : '0')
  }, [domainsCollapsed])
  // (D-sprint: hoverNode / highlightNodes / highlightLinks / dimensions removed
  //  — those were force-graph-only state)
  // T6: scope is either a primary category OR a user-curated collection.
  // {type: 'category' | 'collection', value: string} | null
  const [selectedScope, setSelectedScope] = useState(null)
  const [contextMenu, setContextMenu] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  // D-sprint: per-category collapse state, persisted in localStorage.
  const [collapsedCategories, setCollapsedCategories] = useState(() => {
    if (typeof localStorage === 'undefined') return new Set()
    try {
      const raw = localStorage.getItem('meinrag.dashboard.collapsedCategories')
      return new Set(raw ? JSON.parse(raw) : [])
    } catch { return new Set() }
  })
  useEffect(() => {
    try {
      localStorage.setItem(
        'meinrag.dashboard.collapsedCategories',
        JSON.stringify(Array.from(collapsedCategories)),
      )
    } catch { /* quota or json — ignore */ }
  }, [collapsedCategories])

  // Multi-select (shift-click nodes to add to selection)
  const selection = useSelection()
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [userSaved, setUserSaved] = useState(() => loadUserSaved())

  // Esc key clears selection (with undo toast)
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape' && selection.count > 0) {
        const count = selection.count
        selection.clearWithUndo()
        toast(
          t('selection.cleared', { count, defaultValue: `Cleared ${count} item(s)` }),
          {
            action: {
              label: t('selection.undo', { defaultValue: 'Undo' }),
              onClick: () => selection.undo(),
            },
            duration: 5000,
          }
        )
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selection, t])

  const { data: documentsData, isLoading } = useQuery({
    queryKey: ['documents', USER_ID],
    queryFn: () => fetchDocuments(USER_ID),
  })
  const documents = documentsData?.documents || (Array.isArray(documentsData) ? documentsData : [])

  const { data: taxonomyData } = useQuery({
    queryKey: ['taxonomy', USER_ID],
    queryFn: () => fetchTaxonomy(USER_ID),
  })

  const deleteMutation = useMutation({
    mutationFn: (docId) => deleteDocument(docId, USER_ID),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['graph-documents', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['taxonomy', USER_ID] })
      toast.success(t('toasts.documentDeleted'))
    },
    onError: (err) => toast.error(t('toasts.deleteFailed', { message: err.message || t('toasts.unknownError') })),
  })

  // T6: Categories — fixed primary categories from taxonomy.json. Counts are
  // computed from the loaded documents (so we only show categories with docs).
  const categoryList = useMemo(() => {
    const primaries = taxonomyData?.primary_categories || []
    const counts = new Map()
    documents.forEach(d => {
      if (d.primary_category) {
        counts.set(d.primary_category, (counts.get(d.primary_category) || 0) + 1)
      }
    })
    const uncategorized = documents.filter(d => !d.primary_category).length
    const list = primaries
      .map(p => ({ name: p, count: counts.get(p) || 0 }))
      .filter(c => c.count > 0)
      .sort((a, b) => b.count - a.count)
    return { list, uncategorized }
  }, [documents, taxonomyData])

  // T6: User-curated collections only — what the user has manually filed into.
  const userCollectionList = useMemo(() => {
    const cols = taxonomyData?.user_collections || []
    return cols.map(col => ({
      name: col,
      count: documents.filter(d => d.collections?.includes(col)).length,
    })).sort((a, b) => b.count - a.count)
  }, [documents, taxonomyData])

  // T6: Subtags actually present in the loaded corpus — drives the chip filter row.
  const availableTags = useMemo(() => {
    const tags = new Set()
    documents.forEach(d => (d.subtags || []).forEach(t => tags.add(t)))
    return [...tags].sort()
  }, [documents])

  const filtered = useMemo(() => {
    let docs = Array.isArray(documents) ? documents : []
    // Sidebar scope: primary category OR user collection
    if (selectedScope) {
      if (selectedScope.type === 'category') {
        docs = docs.filter(d => d.primary_category === selectedScope.value)
      } else if (selectedScope.type === 'uncategorized') {
        docs = docs.filter(d => !d.primary_category)
      } else if (selectedScope.type === 'collection') {
        docs = docs.filter(d => d.collections?.includes(selectedScope.value))
      }
    }
    if (search) {
      const q = search.toLowerCase()
      docs = docs.filter(d =>
        d.filename?.toLowerCase().includes(q) ||
        d.collections?.some(c => c.toLowerCase().includes(q)) ||
        d.subtags?.some(s => s.toLowerCase().includes(q))
      )
    }
    if (activeFilters.length > 0) {
      // Multi-tag chip filter — narrow within the current scope by required subtags
      docs = docs.filter(d => activeFilters.every(f => d.subtags?.includes(f)))
    }
    return docs
  }, [documents, search, selectedScope, activeFilters])

  // D-sprint: hierarchical data for the Sunburst hero.
  const taxonomyTree = useTaxonomyHierarchy(documents, taxonomyData)

  // D-sprint: filtered docs grouped by primary_category, ordered by category count desc.
  const docsByCategory = useMemo(() => {
    const groups = new Map()
    for (const d of filtered) {
      const key = d.primary_category || '__uncategorized__'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(d)
    }
    const ordered = Array.from(groups.entries())
      .map(([key, docs]) => ({
        primaryCategory: key === '__uncategorized__' ? null : key,
        docs: docs.sort((a, b) => {
          const da = a.uploaded_at || ''
          const db = b.uploaded_at || ''
          return db.localeCompare(da)
        }),
      }))
      .sort((a, b) => b.docs.length - a.docs.length)
    return ordered
  }, [filtered])

  // D-sprint: any scope change clears the per-doc subtag refinement.
  // Without this, chips set from a prior context (e.g. sunburst click) would
  // keep narrowing the doc list after the user switches sidebar.
  const setScope = useCallback((next) => {
    setSelectedScope(next)
    setActiveFilters([])
  }, [])

  const toggleCategoryCollapsed = useCallback((catName) => {
    setCollapsedCategories(prev => {
      const next = new Set(prev)
      if (next.has(catName)) next.delete(catName)
      else next.add(catName)
      return next
    })
  }, [])

  // (D-sprint: graphData / paintNode / handleNodeClick / handleNodeHover removed
  //  — those rendered the now-deleted force graph)

  // Map of collection_name -> [docs]
  const docsByCollection = useMemo(() => {
    const m = {}
    for (const d of (documents || [])) {
      for (const c of (d.collections || [])) {
        if (!m[c]) m[c] = []
        m[c].push(d)
      }
    }
    return m
  }, [documents])

  // Expand current selection to unique doc_ids (direct + from collections)
  const selectedDocIds = useMemo(
    () => selection.expandedDocIds(docsByCollection),
    [selection, docsByCollection]
  )

  const handleSelectionAsk = useCallback(() => {
    if (selectedDocIds.length === 0) return
    navigate(`/chat?doc_ids=${selectedDocIds.join(',')}`)
  }, [selectedDocIds, navigate])

  const handleSelectionVisualize = useCallback(() => {
    if (selectedDocIds.length === 0) return
    navigate(`/graph?docs=${selectedDocIds.join(',')}`)
  }, [selectedDocIds, navigate])

  const handleSelectionSave = useCallback(() => {
    if (selectedDocIds.length < 2) return
    setSaveDialogOpen(true)
  }, [selectedDocIds])

  const handleSavedSuccess = useCallback((name) => {
    setSaveDialogOpen(false)
    markUserSaved(name)
    setUserSaved(loadUserSaved())
    selection.clear()
    toast.success(t('selection.saveSuccess', {
      name, defaultValue: `Saved collection "${name}"`,
    }))
    queryClient.invalidateQueries({ queryKey: ['taxonomy', USER_ID] })
    queryClient.invalidateQueries({ queryKey: ['documents', USER_ID] })
    queryClient.invalidateQueries({ queryKey: ['graph-documents', USER_ID] })
  }, [selection, queryClient, t])

  const handleDelete = (docId) => {
    const doc = documents.find(d => d.doc_id === docId)
    setConfirmDelete({ docId, filename: doc?.filename || t('dashboard.thisDocument') })
    setMenuOpen(null)
  }

  const handleDownload = (docId) => {
    const API_BASE = import.meta.env.VITE_API_URL
    window.open(`${API_BASE}/documents/${docId}/download`, '_blank')
    setMenuOpen(null)
  }

  const toggleFilter = (tag) => {
    setActiveFilters(prev => prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag])
  }

  // (D-sprint: handleGraphRightClick removed — was the force-graph context menu)

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    const uploadPromise = (async () => {
      const API_BASE = import.meta.env.VITE_API_URL
      const formData = new FormData()
      formData.append('file', file)
      const resp = await fetch(`${API_BASE}/documents/upload?auto_suggest=true`, {
        method: 'POST',
        headers: { 'X-User-Id': USER_ID },
        body: formData,
      })
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}))
        throw new Error(err.detail || t('toasts.uploadFailedStatus', { status: resp.status }))
      }
      return resp.json()
    })()

    toast.promise(uploadPromise, {
      loading: t('toasts.uploadingFile', { filename: file.name }),
      success: (data) => t('toasts.uploadSuccess', { filename: file.name, chunks: data.chunk_count }),
      error: (err) => t('toasts.uploadFailed', { message: err.message }),
    })

    try {
      await uploadPromise
      queryClient.invalidateQueries({ queryKey: ['documents', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['taxonomy', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['graph-documents', USER_ID] })
    } catch { /* toast shown */ }
    finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  return (
    <div className="flex h-full" style={{ backgroundColor: 'var(--bg)' }}>

      {/* === Left: Domain sidebar (collapsible) === */}
      {domainsCollapsed ? (
        <aside
          className="w-8 shrink-0 flex flex-col items-center border-r py-2 gap-2"
          style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-1)' }}
        >
          <button
            type="button"
            onClick={() => setDomainsCollapsed(false)}
            className="p-1.5 rounded transition-colors hover:bg-white/5"
            title={t('dashboard.expandDomains', { defaultValue: 'Show domains' })}
            aria-label={t('dashboard.expandDomains', { defaultValue: 'Show domains' })}
            style={{ color: 'var(--fg-dim)' }}
          >
            <PanelLeftOpen size={14} />
          </button>
        </aside>
      ) : (
      <aside
        className="w-56 shrink-0 flex flex-col border-r"
        style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-1)' }}
      >
        <div className="px-4 pt-5 pb-2 flex items-center justify-between">
          <span
            className="text-[10px] uppercase tracking-[0.1em]"
            style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
          >
            {t('dashboard.scopes', { defaultValue: 'Scope' })}
          </span>
          <button
            type="button"
            onClick={() => setDomainsCollapsed(true)}
            className="p-1 rounded transition-colors hover:bg-white/5"
            title={t('dashboard.collapseDomains', { defaultValue: 'Hide scope' })}
            aria-label={t('dashboard.collapseDomains', { defaultValue: 'Hide scope' })}
            style={{ color: 'var(--fg-faint)' }}
          >
            <PanelLeftClose size={12} />
          </button>
        </div>
        <div className="flex-1 overflow-auto py-1 px-2">
          <DomainItem
            label={t('common.all')}
            count={documents.length}
            active={!selectedScope}
            onClick={() => setScope(null)}
          />

          {/* Categories — fixed primary categories from taxonomy.json */}
          <div
            className="px-3 pt-3 pb-1 text-[9px] uppercase tracking-[0.1em]"
            style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
          >
            {t('dashboard.categories', { defaultValue: 'Categories' })}
          </div>
          {categoryList.list.length === 0 ? (
            <div
              className="px-3 py-2 text-[11px]"
              style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
            >
              {t('dashboard.noCategories', { defaultValue: 'No categories yet' })}
            </div>
          ) : (
            categoryList.list.map(cat => (
              <DomainItem
                key={`cat:${cat.name}`}
                label={formatName(cat.name)}
                count={cat.count}
                active={selectedScope?.type === 'category' && selectedScope.value === cat.name}
                onClick={() => setScope(
                  selectedScope?.type === 'category' && selectedScope.value === cat.name
                    ? null
                    : { type: 'category', value: cat.name }
                )}
              />
            ))
          )}
          {categoryList.uncategorized > 0 && (
            <DomainItem
              label={t('dashboard.uncategorized', { defaultValue: 'Uncategorized' })}
              count={categoryList.uncategorized}
              active={selectedScope?.type === 'uncategorized'}
              onClick={() => setScope(
                selectedScope?.type === 'uncategorized' ? null : { type: 'uncategorized' }
              )}
            />
          )}

          {/* My Collections — user-curated, may be empty */}
          <div
            className="px-3 pt-4 pb-1 text-[9px] uppercase tracking-[0.1em]"
            style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
          >
            {t('dashboard.collections', { defaultValue: 'My Collections' })}
          </div>
          {userCollectionList.length === 0 ? (
            <div
              className="px-3 py-2 text-[11px]"
              style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
            >
              {t('dashboard.noCollections', { defaultValue: 'None yet — pick docs and save a collection' })}
            </div>
          ) : (
            userCollectionList.map(col => (
              <DomainItem
                key={`col:${col.name}`}
                label={formatName(col.name)}
                count={col.count}
                active={selectedScope?.type === 'collection' && selectedScope.value === col.name}
                onClick={() => setScope(
                  selectedScope?.type === 'collection' && selectedScope.value === col.name
                    ? null
                    : { type: 'collection', value: col.name }
                )}
              />
            ))
          )}
        </div>

        {selectedScope && selectedScope.type !== 'uncategorized' && (
          <div className="p-3 border-t" style={{ borderColor: 'var(--border)' }}>
            <button
              onClick={() => navigate(
                selectedScope.type === 'collection'
                  ? `/chat?collection=${encodeURIComponent(selectedScope.value)}`
                  : `/chat?category=${encodeURIComponent(selectedScope.value)}`
              )}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-[12px] font-medium transition-all hover:scale-[1.02]"
              style={{
                background: 'var(--signature)',
                color: 'var(--bg)',
                boxShadow: '0 0 14px var(--signature-soft)',
                fontFamily: 'var(--sans)',
              }}
            >
              <MessageSquare size={13} />
              {t('nav.chat')}
            </button>
          </div>
        )}
      </aside>
      )}

      {/* === Main: search bar + graph + collapsible panel === */}
      <main className="flex-1 flex flex-col overflow-hidden relative">

        {/* Search bar + filter toggle */}
        <div
          className="flex items-center gap-2 px-5 py-3 border-b"
          style={{ borderColor: 'var(--border)' }}
        >
          <SearchInput
            value={rawSearch}
            onChange={setRawSearch}
            matching={filtered.length}
            total={documents.length}
            showCount={!!search}
          />
          <button
            onClick={() => setShowFilters(f => !f)}
            className="p-2.5 rounded-lg transition-all"
            style={{
              backgroundColor: showFilters ? 'var(--signature)' : 'var(--bg-2)',
              color: showFilters ? 'var(--bg)' : 'var(--fg-dim)',
              border: '1px solid',
              borderColor: showFilters ? 'var(--signature)' : 'var(--border-2)',
              boxShadow: showFilters ? '0 0 12px var(--signature-soft)' : 'none',
            }}
            title={t('dashboard.toggleFilters')}
          >
            <Filter size={14} />
          </button>
          {/* Upload — moved from floating bottom-right to header so it
              doesn't overlap the document list. */}
          <label
            className={cn(
              'flex items-center gap-1.5 px-3 py-2 rounded-lg text-[13px] font-medium cursor-pointer transition-colors shrink-0',
              uploading ? 'opacity-50 pointer-events-none' : '',
            )}
            style={{
              backgroundColor: 'var(--signature)',
              color: '#fff',
              border: '1px solid var(--signature)',
            }}
            title={t('dashboard.upload')}
          >
            {uploading ? <RefreshCw size={14} className="animate-spin" /> : <Upload size={14} />}
            <span>{uploading ? t('dashboard.uploading') : t('dashboard.upload')}</span>
            <input
              type="file"
              className="hidden"
              onChange={handleUpload}
              disabled={uploading}
              accept=".pdf,.docx,.txt,.md,.html,.xlsx,.pptx"
            />
          </label>
        </div>

        {/* Filter chips */}
        {showFilters && availableTags.length > 0 && (
          <div
            className="px-5 py-2.5 flex flex-wrap gap-1.5 border-b"
            style={{ borderColor: 'var(--border)' }}
          >
            {availableTags.map(tag => {
              const isActive = activeFilters.includes(tag)
              return (
                <button
                  key={tag}
                  onClick={() => toggleFilter(tag)}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] transition-all"
                  style={{
                    backgroundColor: isActive ? 'var(--signature)' : 'var(--bg-2)',
                    color: isActive ? 'var(--bg)' : 'var(--fg-dim)',
                    border: '1px solid',
                    borderColor: isActive ? 'var(--signature)' : 'var(--border)',
                    fontFamily: 'var(--mono)',
                    letterSpacing: '0.05em',
                    textTransform: 'uppercase',
                    fontWeight: isActive ? 600 : 400,
                  }}
                >
                  {formatName(tag)}
                  {isActive && <X size={9} />}
                </button>
              )
            })}
            {activeFilters.length > 0 && (
              <button
                onClick={() => setActiveFilters([])}
                className="px-2 py-1 text-[11px] transition-opacity hover:opacity-100 opacity-60"
                style={{
                  color: 'var(--fg-dim)',
                  fontFamily: 'var(--mono)',
                  letterSpacing: '0.05em',
                }}
              >
                {t('common.clear')}
              </button>
            )}
          </div>
        )}

        {/* === Hero band: Sunburst (left) + Stats/Recent (right) === */}
        <div
          className="flex gap-6 px-5 py-5 border-b shrink-0"
          style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg)' }}
        >
          {/* Sunburst */}
          <div className="shrink-0 flex items-center justify-center" style={{ width: 280, height: 280 }}>
            {isLoading ? (
              <div
                className="text-[11px] italic"
                style={{ color: 'var(--fg-faint)', fontFamily: 'var(--display)' }}
              >
                {t('common.loading')}
              </div>
            ) : (
              <Sunburst
                data={taxonomyTree}
                size={280}
                totalDocs={documents.length}
                primaryCategoryOrder={taxonomyData?.primary_categories}
                onSegmentClick={(seg) => {
                  if (seg.layer === 'category') {
                    setScope(
                      selectedScope?.type === 'category' && selectedScope.value === seg.name
                        ? null
                        : { type: 'category', value: seg.name }
                    )
                  } else {
                    // domain / sub-domain — scope to its parent category (seg.path[0]),
                    // then set this single tag as the only active refinement.
                    const parentCategory = seg.path?.[0]
                    const same = activeFilters.length === 1 && activeFilters[0] === seg.name
                      && selectedScope?.type === 'category' && selectedScope.value === parentCategory
                    if (same) {
                      // Click again → release the refinement, keep parent category scope
                      setActiveFilters([])
                    } else {
                      setSelectedScope(parentCategory ? { type: 'category', value: parentCategory } : null)
                      setActiveFilters([seg.name])
                    }
                  }
                }}
              />
            )}
          </div>

          {/* Right: Stats + Recent */}
          <div className="flex-1 min-w-0 flex flex-col gap-4 justify-center">
            {/* Stats */}
            <div
              className="flex gap-6 text-[10px] uppercase"
              style={{
                color: 'var(--fg-faint)',
                fontFamily: 'var(--mono)',
                letterSpacing: '0.08em',
              }}
            >
              <Stat label="Documents" value={documents.length} />
              <Stat label="Categories" value={categoryList.list.length} />
              <Stat label="Collections" value={userCollectionList.length} />
            </div>

            {/* Recent strip */}
            <div className="flex flex-col gap-2 min-w-0">
              <span
                className="text-[10px] uppercase tracking-[0.08em]"
                style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
              >
                {t('dashboard.recentLabel', { defaultValue: 'Recent uploads' })}
              </span>
              <RecentStrip
                documents={documents}
                max={5}
                onDocClick={(doc) => navigate(`/chat?doc=${doc.doc_id}&name=${encodeURIComponent(doc.filename || '')}`)}
              />
            </div>
          </div>
        </div>

        {/* === Doc list grouped by category === */}
        <div className="flex-1 overflow-auto" style={{ backgroundColor: 'var(--bg)' }}>
          {isLoading ? (
            <div className="p-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <DocCardSkeleton key={i} />
              ))}
            </div>
          ) : docsByCategory.length === 0 ? (
            <div
              className="flex flex-col items-center justify-center py-16"
              style={{ color: 'var(--fg-dim)' }}
            >
              <FileText size={36} className="mb-3 opacity-60" />
              <p
                className="text-base mb-1"
                style={{
                  fontFamily: 'var(--display)',
                  fontStyle: 'italic',
                  fontWeight: 400,
                  letterSpacing: '-0.015em',
                }}
              >
                {documents.length === 0 ? t('dashboard.uploadFirst') : t('dashboard.noMatch')}
              </p>
              {documents.length === 0 && (
                <p
                  className="text-[11px] uppercase"
                  style={{
                    fontFamily: 'var(--mono)',
                    letterSpacing: '0.08em',
                    color: 'var(--fg-faint)',
                  }}
                >
                  {t('dashboard.uploadFirstHint')}
                </p>
              )}
            </div>
          ) : (
            docsByCategory.map(group => {
              const catKey = group.primaryCategory || '__uncategorized__'
              return (
                <CategorySection
                  key={catKey}
                  primaryCategory={group.primaryCategory}
                  docs={group.docs}
                  collapsed={collapsedCategories.has(catKey)}
                  onToggle={() => toggleCategoryCollapsed(catKey)}
                  renderDoc={(doc) => (
                    <DocRow
                      key={doc.doc_id}
                      doc={doc}
                      onClick={() => navigate(`/chat?doc=${doc.doc_id}&name=${encodeURIComponent(doc.filename || '')}`)}
                      onViewPdf={(e) => { e.stopPropagation(); navigate(`/pdf/${doc.doc_id}`) }}
                      onMoreClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === doc.doc_id ? null : doc.doc_id) }}
                      menuOpen={menuOpen === doc.doc_id}
                      onDownload={() => handleDownload(doc.doc_id)}
                      onDelete={() => handleDelete(doc.doc_id)}
                      tDownload={t('common.download')}
                      tDelete={t('common.delete')}
                      tViewPdf={t('dashboard.viewPdf')}
                    />
                  )}
                />
              )
            })
          )}
        </div>

        {contextMenu && (
          <ContextMenu x={contextMenu.x} y={contextMenu.y} items={contextMenu.items} onClose={() => setContextMenu(null)} />
        )}

        <ConfirmDialog
          open={confirmDelete != null}
          title={t('confirm.deleteDocumentTitle')}
          message={t('confirm.deleteDocumentMessage', { filename: confirmDelete?.filename })}
          confirmLabel={t('common.delete')}
          danger
          onConfirm={() => {
            deleteMutation.mutate(confirmDelete.docId)
            setConfirmDelete(null)
          }}
          onCancel={() => setConfirmDelete(null)}
        />
      </main>

      {/* Multi-select action bar (floats at bottom of viewport) */}
      <SelectionActionBar
        onAsk={handleSelectionAsk}
        onVisualize={handleSelectionVisualize}
        onSave={handleSelectionSave}
      />

      {/* Save selection as collection dialog */}
      <SaveCollectionDialog
        open={saveDialogOpen}
        count={selectedDocIds.length}
        docIds={selectedDocIds}
        onClose={() => setSaveDialogOpen(false)}
        onSaved={handleSavedSuccess}
      />
    </div>
  )
}

// ============ Subcomponents ============

function Stat({ label, value }) {
  return (
    <div className="flex flex-col items-end gap-0.5">
      <span className="opacity-70">{label}</span>
      <b
        className="text-[15px] tabular-nums"
        style={{ color: 'var(--fg)', fontWeight: 500, letterSpacing: '-0.01em' }}
      >
        {value}
      </b>
    </div>
  )
}

function DomainItem({ label, count, active, onClick }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-[13px] transition-colors relative"
      style={{
        color: active ? 'var(--fg)' : 'var(--fg-dim)',
        backgroundColor: active ? 'var(--bg-3)' : 'transparent',
      }}
      onMouseEnter={e => { if (!active) e.currentTarget.style.backgroundColor = 'var(--bg-2)' }}
      onMouseLeave={e => { if (!active) e.currentTarget.style.backgroundColor = 'transparent' }}
    >
      {active && (
        <span
          aria-hidden
          className="absolute left-0 top-1/2 -translate-y-1/2"
          style={{
            width: 3, height: 14,
            background: 'var(--signature)',
            borderRadius: '0 3px 3px 0',
            boxShadow: '0 0 10px var(--signature-glow)',
          }}
        />
      )}
      <span
        className="shrink-0 w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: active ? 'var(--fg-1)' : 'var(--fg-faint)' }}
      />
      <span className="flex-1 text-left truncate">{label}</span>
      <span
        className="text-[10px] tabular-nums"
        style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
      >
        {count}
      </span>
    </button>
  )
}

function SearchInput({ value, onChange, matching, total, showCount }) {
  return (
    <div
      className="flex-1 flex items-center gap-3 px-4 rounded-lg transition-all"
      style={{
        height: 40,
        background: 'var(--bg-2)',
        border: '1px solid var(--border-2)',
      }}
      onFocus={e => {
        e.currentTarget.style.borderColor = 'var(--signature)'
        e.currentTarget.style.backgroundColor = 'var(--bg-3)'
        e.currentTarget.style.boxShadow = '0 0 0 3px var(--signature-soft)'
      }}
      onBlur={e => {
        e.currentTarget.style.borderColor = 'var(--border-2)'
        e.currentTarget.style.backgroundColor = 'var(--bg-2)'
        e.currentTarget.style.boxShadow = ''
      }}
    >
      <Search size={14} style={{ color: 'var(--fg-faint)' }} className="shrink-0" />
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="Search by title, collection, or keyword…"
        className="flex-1 bg-transparent outline-none text-[13px]"
        style={{
          color: 'var(--fg)',
          fontFamily: 'var(--sans)',
          letterSpacing: '-0.005em',
        }}
      />
      {value && (
        <button
          onClick={() => onChange('')}
          className="text-[10px] px-2 py-0.5 rounded-md transition-colors"
          style={{
            backgroundColor: 'var(--bg)',
            border: '1px solid var(--border-2)',
            color: 'var(--fg-dim)',
            fontFamily: 'var(--mono)',
          }}
          title="Clear"
        >
          esc
        </button>
      )}
      {showCount && (
        <span
          className="text-[11px] pl-3 border-l whitespace-nowrap"
          style={{
            color: 'var(--fg-faint)',
            fontFamily: 'var(--mono)',
            borderColor: 'var(--border-2)',
          }}
        >
          <b style={{ color: 'var(--signature)', fontWeight: 500 }}>{matching}</b> of {total} match
        </span>
      )}
    </div>
  )
}

function DocRow({ doc, onClick, onViewPdf, onMoreClick, menuOpen, onDownload, onDelete, tDownload, tDelete, tViewPdf }) {
  const subtags = Array.isArray(doc.subtags) ? doc.subtags : []
  return (
    <div
      onClick={onClick}
      className="flex items-center gap-3 px-5 py-2.5 cursor-pointer transition-colors group text-[12px] border-b"
      style={{ borderColor: 'var(--border)' }}
      onMouseEnter={e => e.currentTarget.style.backgroundColor = 'var(--bg-2)'}
      onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
    >
      <FileText size={12} className="shrink-0" style={{ color: 'var(--fg-faint)' }} />
      <div className="flex-1 min-w-0 flex items-center gap-2">
        <span
          className="truncate"
          style={{
            color: 'var(--fg-1)',
            fontFamily: 'var(--display)',
            fontSize: 14,
            letterSpacing: '-0.008em',
          }}
        >
          {doc.filename}
        </span>
        {/* T6: subtag chips — searchable metadata, not navigation */}
        {subtags.slice(0, 3).map(tag => (
          <span
            key={tag}
            className="shrink-0 px-1.5 py-0.5 rounded text-[9px] uppercase tracking-[0.05em]"
            style={{
              color: 'var(--fg-faint)',
              backgroundColor: 'var(--bg-2)',
              border: '1px solid var(--border)',
              fontFamily: 'var(--mono)',
            }}
          >
            {tag}
          </span>
        ))}
        {subtags.length > 3 && (
          <span
            className="shrink-0 text-[9px]"
            style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
          >
            +{subtags.length - 3}
          </span>
        )}
      </div>
      <span
        className="shrink-0 text-[10px] tabular-nums"
        style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)', letterSpacing: '0.05em' }}
      >
        {doc.chunk_count} · {relTime(doc.uploaded_at)}
      </span>
      <button
        onClick={onViewPdf}
        className="p-1 rounded transition-opacity opacity-0 group-hover:opacity-70 hover:opacity-100"
        style={{ color: 'var(--fg-dim)' }}
        title={tViewPdf}
      >
        <FileText size={13} />
      </button>
      <div className="relative">
        <button
          onClick={onMoreClick}
          className="p-1 rounded transition-opacity opacity-0 group-hover:opacity-60 hover:opacity-100"
          style={{ color: 'var(--fg-dim)' }}
        >
          <MoreVertical size={11} />
        </button>
        {menuOpen && (
          <div
            className="absolute right-0 bottom-7 z-20 rounded-lg shadow-xl py-1 min-w-[130px]"
            style={{ backgroundColor: 'var(--bg-3)', border: '1px solid var(--border-2)' }}
          >
            <button
              onClick={(e) => { e.stopPropagation(); onDownload() }}
              className="flex items-center gap-2 px-3 py-1.5 text-[12px] w-full transition-colors hover:bg-white/5"
              style={{ color: 'var(--fg-1)' }}
            >
              <Download size={11} /> {tDownload}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onDelete() }}
              className="flex items-center gap-2 px-3 py-1.5 text-[12px] w-full transition-colors hover:bg-white/5"
              style={{ color: 'var(--bad)' }}
            >
              <Trash2 size={11} /> {tDelete}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
