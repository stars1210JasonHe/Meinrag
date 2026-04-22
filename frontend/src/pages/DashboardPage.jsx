import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ForceGraph2D from 'react-force-graph-2d'
import {
  Search, Upload, MoreVertical, Trash2, Download, RefreshCw,
  FileText, X, MessageSquare, Filter, ChevronUp, ChevronDown, Network, Brain,
} from 'lucide-react'
import { toast } from 'sonner'
import { fetchDocuments, fetchCollections, fetchGraphDocuments, deleteDocument } from '@/lib/api'
import { cn } from '@/lib/utils'
import ContextMenu from '@/components/ContextMenu'
import ConfirmDialog from '@/components/ConfirmDialog'
import SelectionActionBar from '@/components/SelectionActionBar'
import SaveCollectionDialog from '@/components/SaveCollectionDialog'
import { useSelection } from '@/hooks/useSelection'

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

// Shape colors — matched to GraphPage's document color + Windows-folder-yellow for domains
const DOC_COLOR = '#6366f1'        // indigo (same as GraphPage's document node)
const DOC_COLOR_DIM = '#4f52c5'
const FOLDER_COLOR = '#f0b72a'     // warm yellow (Windows folder)
const FOLDER_FILL = '#f0b72a22'    // translucent yellow fill
const FOLDER_TAB_COLOR = '#c99018'

// Graph node colors reading live from CSS vars (captured at paint time)
function cssVar(name, fallback = '#5b7ec9') {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  } catch { return fallback }
}

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
  const graphRef = useRef(null)
  const containerRef = useRef(null)

  const [rawSearch, setRawSearch] = useState('')
  const search = useDebounced(rawSearch, 300)
  const [activeFilters, setActiveFilters] = useState([])
  const [showFilters, setShowFilters] = useState(false)
  const [showPanel, setShowPanel] = useState(false)
  const [menuOpen, setMenuOpen] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [hoverNode, setHoverNode] = useState(null)
  const [highlightNodes, setHighlightNodes] = useState(new Set())
  const [highlightLinks, setHighlightLinks] = useState(new Set())
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 })
  const [selectedDomain, setSelectedDomain] = useState(null)
  const [contextMenu, setContextMenu] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)

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

  const { data: collectionsData } = useQuery({
    queryKey: ['collections', USER_ID],
    queryFn: () => fetchCollections(USER_ID),
  })

  const { data: graphEdges } = useQuery({
    queryKey: ['graph-documents', USER_ID],
    queryFn: () => fetchGraphDocuments(USER_ID),
  })

  const deleteMutation = useMutation({
    mutationFn: (docId) => deleteDocument(docId, USER_ID),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['graph-documents', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['collections', USER_ID] })
      toast.success(t('toasts.documentDeleted'))
    },
    onError: (err) => toast.error(t('toasts.deleteFailed', { message: err.message || t('toasts.unknownError') })),
  })

  // Measure container for graph sizing
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => setDimensions({ width: el.clientWidth, height: el.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Sync domain → filter
  useEffect(() => {
    setActiveFilters(selectedDomain ? [selectedDomain] : [])
  }, [selectedDomain])

  const availableTags = useMemo(() => {
    if (!collectionsData) return []
    const tags = new Set()
    collectionsData.taxonomy_categories?.forEach(c => tags.add(c))
    collectionsData.existing_collections?.forEach(c => tags.add(c))
    return [...tags].sort()
  }, [collectionsData])

  const collectionList = useMemo(() => {
    const cols = collectionsData?.existing_collections || []
    return cols.map(col => ({
      name: col,
      count: documents.filter(d => d.collections?.includes(col)).length,
    })).sort((a, b) => b.count - a.count)
  }, [documents, collectionsData])

  const filtered = useMemo(() => {
    let docs = Array.isArray(documents) ? documents : []
    if (search) {
      const q = search.toLowerCase()
      docs = docs.filter(d =>
        d.filename?.toLowerCase().includes(q) ||
        d.collections?.some(c => c.toLowerCase().includes(q))
      )
    }
    if (activeFilters.length > 0) {
      docs = docs.filter(d => activeFilters.some(f => d.collections?.includes(f)))
    }
    return docs
  }, [documents, search, activeFilters])

  const displayedDocs = useMemo(() => {
    const allDocs = Array.isArray(documents) ? documents : []
    if (search) return filtered.slice(0, 50)
    if (selectedDomain) return filtered
    const sorted = [...allDocs].sort((a, b) => {
      const da = a.uploaded_at || a.created_at || ''
      const db = b.uploaded_at || b.created_at || ''
      return db.localeCompare(da)
    })
    return sorted.slice(0, 20)
  }, [documents, filtered, search, selectedDomain])

  // Build graph data
  const graphData = useMemo(() => {
    const docs = Array.isArray(documents) ? documents : []
    if (docs.length === 0) return { nodes: [], links: [] }

    const nodes = []
    const links = []
    const collectionSet = new Set()
    const searchLower = search.toLowerCase()
    const filteredIds = new Set(filtered.map(d => d.doc_id))

    // Collect counts to size collection nodes
    const collectionCounts = {}

    for (const d of docs) {
      const matchesSearch = !search ||
        d.filename?.toLowerCase().includes(searchLower) ||
        d.collections?.some(c => c.toLowerCase().includes(searchLower))
      const matchesFilter = activeFilters.length === 0 || filteredIds.has(d.doc_id)

      // Size documents by chunk count: sqrt scale to avoid huge outliers
      const chunkSize = Math.max(1, Math.sqrt(d.chunk_count || 1))

      nodes.push({
        id: `doc:${d.doc_id}`,
        label: d.filename?.replace(/\.[^.]+$/, '').slice(0, 30) || d.doc_id,
        val: 2 + chunkSize * 0.8,
        _type: 'document',
        _data: d,
        _chunks: d.chunk_count || 0,
        _dimmed: (search && !matchesSearch) || (activeFilters.length > 0 && !matchesFilter),
      })

      for (const c of (d.collections || [])) {
        collectionCounts[c] = (collectionCounts[c] || 0) + 1
        collectionSet.add(c)
        links.push({ source: `col:${c}`, target: `doc:${d.doc_id}`, _type: 'belongs_to' })
      }
    }

    for (const c of collectionSet) {
      const matchesSearch = !search || c.toLowerCase().includes(searchLower)
      const matchesFilter = activeFilters.length === 0 || activeFilters.includes(c)
      const count = collectionCounts[c] || 0
      // Size collections by member count
      nodes.push({
        id: `col:${c}`,
        label: formatName(c),
        val: 4 + Math.sqrt(count) * 1.2,
        _type: 'collection',
        _count: count,
        _dimmed: (search && !matchesSearch) || (activeFilters.length > 0 && !matchesFilter),
      })
    }

    if (graphEdges?.edges) {
      for (const e of graphEdges.edges) {
        links.push({
          source: `doc:${e.source_doc_id}`,
          target: `doc:${e.target_doc_id}`,
          _type: 'similar_to',
        })
      }
    }

    const nodeIds = new Set(nodes.map(n => n.id))
    const validLinks = links.filter(l => nodeIds.has(l.source) && nodeIds.has(l.target))

    return { nodes: nodes.map(n => ({ ...n })), links: validLinks.map(l => ({ ...l })) }
  }, [documents, filtered, search, activeFilters, graphEdges])

  // Tune force simulation — cleaner layout when collections >> documents
  useEffect(() => {
    const g = graphRef.current
    if (!g || !g.d3Force) return
    try {
      const charge = g.d3Force('charge')
      if (charge?.strength) charge.strength(n => n._type === 'collection' ? -260 : -90)
      const link = g.d3Force('link')
      if (link?.distance) link.distance(l => l._type === 'similar_to' ? 80 : 35)
      if (link?.strength) link.strength(0.7)
      const collide = g.d3Force('collide')
      if (collide?.radius) collide.radius(n => Math.sqrt(n.val || 3) * 2.2 + 6)
      if (g.d3ReheatSimulation) g.d3ReheatSimulation()
    } catch (e) {
      console.warn('[Dashboard] force tune failed:', e)
    }
  }, [graphData])

  // Custom node paint — file/folder shapes w/ hover highlight
  const paintNode = useCallback((node, ctx) => {
    // Guard: simulation may not have set coordinates yet
    if (typeof node.x !== 'number' || typeof node.y !== 'number' ||
        !isFinite(node.x) || !isFinite(node.y)) return

    const s = Math.max(3, Math.sqrt(node.val || 3) * 2.2)  // size baseline
    const hovered = hoverNode?.id === node.id
    const active = hoverNode != null
    // Dim unless highlighted (hover) or search/filter-matched
    const isHighlighted = !active || highlightNodes.has(node.id)
    const staticDimmed = node._dimmed && !active
    const opacity = staticDimmed ? 0.18 : (isHighlighted ? 1.0 : 0.2)

    // Selected state (multi-select): draws a signature-color ring behind the shape
    const isSelected = (node._type === 'document' && selection.hasDoc(node._data?.doc_id))
      || (node._type === 'collection' && selection.hasCollection(node.id.replace('col:', '')))

    const fg1 = cssVar('--fg-1', '#d4d0ca')
    const fgDim = cssVar('--fg-dim', '#9a9690')
    const fgFaint = cssVar('--fg-faint', '#5a564f')

    ctx.globalAlpha = opacity

    if (node._type === 'collection') {
      // ==== FOLDER SHAPE ====
      const w = s * 2.4, h = s * 1.9
      const tabW = s * 0.9, tabH = s * 0.45
      const x = node.x, y = node.y

      // Selection ring (behind everything)
      if (isSelected) {
        ctx.globalAlpha = 1.0
        ctx.beginPath()
        ctx.roundRect?.(x - w/2 - 5, y - h/2 - tabH - 5, w + 10, h + tabH + 10, 5) ||
          ctx.rect(x - w/2 - 5, y - h/2 - tabH - 5, w + 10, h + tabH + 10)
        ctx.strokeStyle = cssVar('--signature', '#5b7ec9')
        ctx.lineWidth = 2.5
        ctx.stroke()
        ctx.globalAlpha = opacity
      }

      // Hover glow
      if (hovered) {
        ctx.beginPath()
        ctx.roundRect?.(x - w/2 - 3, y - h/2 - tabH - 3, w + 6, h + tabH + 6, 4) ||
          ctx.rect(x - w/2 - 3, y - h/2 - tabH - 3, w + 6, h + tabH + 6)
        ctx.fillStyle = FOLDER_COLOR + '33'
        ctx.fill()
      }

      // Folder tab
      ctx.beginPath()
      ctx.moveTo(x - w/2, y - h/2)
      ctx.lineTo(x - w/2 + tabW, y - h/2)
      ctx.lineTo(x - w/2 + tabW + tabH * 0.6, y - h/2 + tabH)
      ctx.lineTo(x + w/2, y - h/2 + tabH)
      ctx.lineTo(x + w/2, y + h/2)
      ctx.lineTo(x - w/2, y + h/2)
      ctx.closePath()
      ctx.fillStyle = FOLDER_COLOR
      ctx.fill()
      // Subtle top highlight
      ctx.strokeStyle = FOLDER_TAB_COLOR
      ctx.lineWidth = 0.8
      ctx.stroke()

      // Star marker for user-saved collections (top-left corner of folder)
      const collName = node.id.replace('col:', '')
      if (userSaved.has(collName)) {
        const sx = x - w/2 + tabH * 0.8
        const sy = y - h/2 - tabH * 0.1
        const sr = Math.max(2, s * 0.32)
        // 5-point star
        ctx.beginPath()
        for (let i = 0; i < 10; i++) {
          const r = i % 2 === 0 ? sr : sr * 0.45
          const a = (Math.PI / 5) * i - Math.PI / 2
          const px = sx + Math.cos(a) * r
          const py = sy + Math.sin(a) * r
          if (i === 0) ctx.moveTo(px, py)
          else ctx.lineTo(px, py)
        }
        ctx.closePath()
        ctx.fillStyle = cssVar('--signature', '#5b7ec9')
        ctx.fill()
        ctx.strokeStyle = '#ffffffcc'
        ctx.lineWidth = 0.6
        ctx.stroke()
      }

    } else {
      // ==== DOCUMENT (paper w/ folded corner) SHAPE ====
      const w = s * 1.7, h = s * 2.1
      const fold = s * 0.55
      const x = node.x, y = node.y

      // Selection ring (behind everything)
      if (isSelected) {
        ctx.globalAlpha = 1.0
        ctx.beginPath()
        ctx.roundRect?.(x - w/2 - 5, y - h/2 - 5, w + 10, h + 10, 4) ||
          ctx.rect(x - w/2 - 5, y - h/2 - 5, w + 10, h + 10)
        ctx.strokeStyle = cssVar('--signature', '#5b7ec9')
        ctx.lineWidth = 2.5
        ctx.stroke()
        ctx.globalAlpha = opacity
      }

      // Hover glow
      if (hovered) {
        ctx.beginPath()
        ctx.roundRect?.(x - w/2 - 3, y - h/2 - 3, w + 6, h + 6, 3) ||
          ctx.rect(x - w/2 - 3, y - h/2 - 3, w + 6, h + 6)
        ctx.fillStyle = DOC_COLOR + '33'
        ctx.fill()
      }

      // Paper body (rectangle w/ top-right corner cut)
      ctx.beginPath()
      ctx.moveTo(x - w/2, y - h/2)
      ctx.lineTo(x + w/2 - fold, y - h/2)
      ctx.lineTo(x + w/2, y - h/2 + fold)
      ctx.lineTo(x + w/2, y + h/2)
      ctx.lineTo(x - w/2, y + h/2)
      ctx.closePath()
      ctx.fillStyle = DOC_COLOR
      ctx.fill()

      // Folded corner triangle (inner darker shade)
      ctx.beginPath()
      ctx.moveTo(x + w/2 - fold, y - h/2)
      ctx.lineTo(x + w/2 - fold, y - h/2 + fold)
      ctx.lineTo(x + w/2, y - h/2 + fold)
      ctx.closePath()
      ctx.fillStyle = DOC_COLOR_DIM
      ctx.fill()
    }

    // Label
    const fontSize = Math.max(4, s * 0.55)
    const isCollection = node._type === 'collection'
    ctx.font = `${isCollection ? '500' : '400'} ${fontSize}px 'IBM Plex Sans', sans-serif`
    ctx.fillStyle = !isHighlighted ? fgFaint : (isCollection ? fg1 : fgDim)
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    const label = node.label?.length > 28 ? node.label.slice(0, 25) + '…' : node.label
    const labelY = node.y + (isCollection ? s * 1.9 / 2 : s * 2.1 / 2) + 4
    ctx.fillText(label || '', node.x, labelY)

    ctx.globalAlpha = 1.0
  }, [hoverNode, highlightNodes, selection, userSaved])

  const handleNodeClick = useCallback((node, event) => {
    // Shift-click → toggle multi-select instead of navigating
    if (event?.shiftKey) {
      if (node._type === 'document' && node._data?.doc_id) {
        selection.toggleDoc(node._data.doc_id)
      } else if (node._type === 'collection') {
        selection.toggleCollection(node.id.replace('col:', ''))
      }
      return
    }
    if (node._type === 'document' && node._data?.doc_id) {
      navigate(`/chat?doc=${node._data.doc_id}&name=${encodeURIComponent(node._data.filename || '')}`)
    } else if (node._type === 'collection') {
      setSelectedDomain(prev => prev === node.id.replace('col:', '') ? null : node.id.replace('col:', ''))
      setShowPanel(true)
    }
  }, [navigate, selection])

  const handleNodeHover = useCallback((node) => {
    setHoverNode(node || null)
    if (!node) {
      setHighlightNodes(new Set())
      setHighlightLinks(new Set())
      return
    }
    // Collect neighbors via current graph links
    const neighbors = new Set([node.id])
    const linkSet = new Set()
    for (const l of graphData.links) {
      const srcId = typeof l.source === 'object' ? l.source.id : l.source
      const tgtId = typeof l.target === 'object' ? l.target.id : l.target
      if (srcId === node.id) { neighbors.add(tgtId); linkSet.add(l) }
      if (tgtId === node.id) { neighbors.add(srcId); linkSet.add(l) }
    }
    setHighlightNodes(neighbors)
    setHighlightLinks(linkSet)
  }, [graphData])

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
    queryClient.invalidateQueries({ queryKey: ['collections', USER_ID] })
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

  const handleGraphRightClick = useCallback((node, event) => {
    event.preventDefault()
    const items = []
    if (node._type === 'document' && node._data) {
      items.push(
        { label: t('dashboard.chatAboutThis'), icon: MessageSquare, action: () => navigate(`/chat?doc=${node._data.doc_id}&name=${encodeURIComponent(node._data.filename || '')}`) },
        { label: t('dashboard.openInPdf'), icon: FileText, action: () => navigate(`/pdf/${node._data.doc_id}`) },
        { label: t('dashboard.viewInGraph'), icon: Network, action: () => navigate(`/graph/${node._data.doc_id}`) },
        { label: t('mindmap.modeTree'), icon: Brain, action: () => navigate(`/mindmap/${node._data.doc_id}?mode=tree`) },
        { label: t('mindmap.modeGraph'), icon: Network, action: () => navigate(`/mindmap/${node._data.doc_id}?mode=graph`) },
        { separator: true },
        { label: t('common.download'), icon: Download, action: () => handleDownload(node._data.doc_id) },
        { label: t('common.delete'), icon: Trash2, action: () => handleDelete(node._data.doc_id), danger: true },
      )
    } else if (node._type === 'collection') {
      const col = node.id.replace('col:', '')
      items.push(
        { label: t('dashboard.chatAboutCollection'), icon: MessageSquare, action: () => navigate(`/chat?collection=${encodeURIComponent(col)}`) },
        { label: t('dashboard.filterByThis'), icon: Filter, action: () => setSelectedDomain(col) },
      )
    }
    items.push({ separator: true }, { label: t('common.cancel'), action: () => {} })
    setContextMenu({ x: event.clientX, y: event.clientY, items })
  }, [navigate, t])

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
      queryClient.invalidateQueries({ queryKey: ['collections', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['graph-documents', USER_ID] })
    } catch { /* toast shown */ }
    finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  // Auto-expand panel when searching
  useEffect(() => {
    if (search) setShowPanel(true)
  }, [search])

  const panelTitle = useMemo(() => {
    const total = documents.length
    if (search) return t('dashboard.panelSearching', { shown: displayedDocs.length, total: filtered.length })
    if (selectedDomain) return t('dashboard.panelDomain', { domain: formatName(selectedDomain), shown: displayedDocs.length })
    return t('dashboard.panelDefault', { shown: displayedDocs.length, total })
  }, [documents, displayedDocs, filtered, search, selectedDomain, t])

  return (
    <div className="flex h-full" style={{ backgroundColor: 'var(--bg)' }}>

      {/* === Left: Domain sidebar === */}
      <aside
        className="w-56 shrink-0 flex flex-col border-r"
        style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-1)' }}
      >
        <div
          className="px-4 pt-5 pb-2 text-[10px] uppercase tracking-[0.1em]"
          style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
        >
          {t('dashboard.domains')}
        </div>
        <div className="flex-1 overflow-auto py-1 px-2">
          <DomainItem
            label={t('common.all')}
            count={documents.length}
            active={!selectedDomain}
            onClick={() => setSelectedDomain(null)}
          />
          {collectionList.length === 0 ? (
            <div
              className="px-3 py-6 text-xs text-center"
              style={{ color: 'var(--fg-faint)', fontFamily: 'var(--mono)' }}
            >
              {t('dashboard.noCollections')}
            </div>
          ) : (
            collectionList.map(col => (
              <DomainItem
                key={col.name}
                label={formatName(col.name)}
                count={col.count}
                active={selectedDomain === col.name}
                onClick={() => setSelectedDomain(d => (d === col.name ? null : col.name))}
              />
            ))
          )}
        </div>

        {selectedDomain && (
          <div className="p-3 border-t" style={{ borderColor: 'var(--border)' }}>
            <button
              onClick={() => navigate(`/chat?collection=${encodeURIComponent(selectedDomain)}`)}
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

        {/* Graph area */}
        <div
          ref={containerRef}
          className="flex-1 relative min-h-0"
          style={{ backgroundColor: 'var(--bg)' }}
        >
          {isLoading ? (
            <div
              className="absolute inset-0 flex items-center justify-center"
              style={{
                color: 'var(--fg-dim)',
                fontFamily: 'var(--display)',
                fontStyle: 'italic',
                fontSize: 18,
              }}
            >
              {t('common.loading')}
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div
              className="absolute inset-0 flex flex-col items-center justify-center"
              style={{ color: 'var(--fg-dim)' }}
            >
              <FileText size={48} className="mb-4 opacity-60" />
              <p
                className="text-lg mb-1"
                style={{
                  fontFamily: 'var(--display)',
                  fontStyle: 'italic',
                  fontWeight: 400,
                  letterSpacing: '-0.015em',
                }}
              >
                {t('dashboard.uploadFirst')}
              </p>
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
            </div>
          ) : (
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData}
              width={dimensions.width}
              height={dimensions.height}
              backgroundColor="rgba(0,0,0,0)"
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={(node, color, ctx) => {
                const r = Math.sqrt(node.val || 3) * 2.2 + 3
                ctx.beginPath()
                ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
                ctx.fillStyle = color
                ctx.fill()
              }}
              onNodeClick={handleNodeClick}
              onNodeHover={handleNodeHover}
              onNodeRightClick={handleGraphRightClick}
              linkColor={l => {
                const dim = hoverNode && !highlightLinks.has(l)
                if (l._type === 'similar_to') {
                  return dim ? '#6366f122' : '#6366f188'
                }
                return dim ? cssVar('--fg-faint', '#5a564f') + '15' : cssVar('--fg-faint', '#5a564f') + '40'
              }}
              linkWidth={l => highlightLinks.has(l) ? 2 : (l._type === 'similar_to' ? 1.5 : 0.5)}
              linkLineDash={l => l._type === 'similar_to' ? [3, 3] : []}
              cooldownTicks={30}
              onEngineStop={() => graphRef.current?.zoomToFit(300, 40)}
              enableNodeDrag={true}
            />
          )}

          {/* Stats overlay — top right */}
          {graphData.nodes.length > 0 && (
            <div
              className="absolute top-4 right-5 text-[10px] uppercase flex gap-5"
              style={{
                color: 'var(--fg-faint)',
                fontFamily: 'var(--mono)',
                letterSpacing: '0.08em',
              }}
            >
              <Stat label="Documents" value={documents.length} />
              <Stat label="Collections" value={collectionList.length} />
            </div>
          )}
        </div>

        {/* Floating upload button */}
        <label
          className={cn(
            'absolute bottom-6 right-6 flex items-center gap-2 px-4 py-2.5 rounded-lg text-[13px] font-medium cursor-pointer transition-all z-30',
            uploading ? 'opacity-50 pointer-events-none' : 'hover:scale-105'
          )}
          style={{
            backgroundColor: 'var(--signature)',
            color: 'var(--bg)',
            boxShadow: '0 10px 30px var(--signature-soft), 0 0 0 1px var(--signature-glow)',
            fontFamily: 'var(--sans)',
          }}
        >
          {uploading ? <RefreshCw size={15} className="animate-spin" /> : <Upload size={15} />}
          {uploading ? t('dashboard.uploading') : t('dashboard.upload')}
          <input
            type="file"
            className="hidden"
            onChange={handleUpload}
            disabled={uploading}
            accept=".pdf,.docx,.txt,.md,.html,.xlsx,.pptx"
          />
        </label>

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

        {/* Collapsible documents panel */}
        <div
          className="border-t shrink-0"
          style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-1)' }}
        >
          <button
            onClick={() => setShowPanel(p => !p)}
            className="flex items-center justify-between w-full px-5 py-2 text-[11px] uppercase"
            style={{
              color: 'var(--fg-dim)',
              fontFamily: 'var(--mono)',
              letterSpacing: '0.08em',
            }}
          >
            <span>{panelTitle}</span>
            {showPanel ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
          </button>

          {showPanel && (
            <div
              className="max-h-56 overflow-auto border-t"
              style={{ borderColor: 'var(--border)' }}
            >
              {displayedDocs.length === 0 ? (
                <div
                  className="p-6 text-center"
                  style={{
                    color: 'var(--fg-faint)',
                    fontFamily: 'var(--display)',
                    fontStyle: 'italic',
                    fontSize: 14,
                  }}
                >
                  {t('dashboard.noMatch')}
                </div>
              ) : (
                displayedDocs.map(doc => (
                  <DocRow
                    key={doc.doc_id}
                    doc={doc}
                    onClick={() => navigate(`/chat?doc=${doc.doc_id}&name=${encodeURIComponent(doc.filename || '')}`)}
                    onViewPdf={(e) => { e.stopPropagation(); navigate(`/pdf/${doc.doc_id}`) }}
                    onViewMindmapTree={(e) => { e.stopPropagation(); navigate(`/mindmap/${doc.doc_id}?mode=tree`) }}
                    onViewMindmapGraph={(e) => { e.stopPropagation(); navigate(`/mindmap/${doc.doc_id}?mode=graph`) }}
                    onMoreClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === doc.doc_id ? null : doc.doc_id) }}
                    menuOpen={menuOpen === doc.doc_id}
                    onDownload={() => handleDownload(doc.doc_id)}
                    onDelete={() => handleDelete(doc.doc_id)}
                    tDownload={t('common.download')}
                    tDelete={t('common.delete')}
                    tViewPdf={t('dashboard.viewPdf')}
                    tViewMindmapTree={t('mindmap.modeTree')}
                    tViewMindmapGraph={t('mindmap.modeGraph')}
                  />
                ))
              )}
            </div>
          )}
        </div>
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

function DocRow({ doc, onClick, onViewPdf, onViewMindmapTree, onViewMindmapGraph, onMoreClick, menuOpen, onDownload, onDelete, tDownload, tDelete, tViewPdf, tViewMindmapTree, tViewMindmapGraph }) {
  return (
    <div
      onClick={onClick}
      className="flex items-center gap-3 px-5 py-2.5 cursor-pointer transition-colors group text-[12px] border-b"
      style={{ borderColor: 'var(--border)' }}
      onMouseEnter={e => e.currentTarget.style.backgroundColor = 'var(--bg-2)'}
      onMouseLeave={e => e.currentTarget.style.backgroundColor = 'transparent'}
    >
      <FileText size={12} className="shrink-0" style={{ color: 'var(--fg-faint)' }} />
      <span
        className="flex-1 truncate"
        style={{
          color: 'var(--fg-1)',
          fontFamily: 'var(--display)',
          fontSize: 14,
          letterSpacing: '-0.008em',
        }}
      >
        {doc.filename}
      </span>
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
      <button
        type="button"
        onClick={onViewMindmapTree}
        className="p-1 rounded transition-opacity opacity-0 group-hover:opacity-70 hover:opacity-100"
        style={{ color: 'var(--fg-dim)' }}
        title={tViewMindmapTree}
        aria-label={tViewMindmapTree}
      >
        <Brain size={13} />
      </button>
      <button
        type="button"
        onClick={onViewMindmapGraph}
        className="p-1 rounded transition-opacity opacity-0 group-hover:opacity-70 hover:opacity-100"
        style={{ color: 'var(--fg-dim)' }}
        title={tViewMindmapGraph}
        aria-label={tViewMindmapGraph}
      >
        <Network size={13} />
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
