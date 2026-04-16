import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import ForceGraph2D from 'react-force-graph-2d'
import {
  Search, Upload, MoreVertical, Trash2, Download, RefreshCw,
  FileText, X, MessageSquare, Filter, ChevronUp, ChevronDown, Menu, Network
} from 'lucide-react'
import { toast } from 'sonner'
import { fetchDocuments, fetchCollections, fetchGraphDocuments, deleteDocument } from '@/lib/api'
import { cn } from '@/lib/utils'
import ContextMenu from '@/components/ContextMenu'
import ConfirmDialog from '@/components/ConfirmDialog'

const USER_ID = 'admin'

const NODE_COLORS = {
  document: '#3b82f6',
  collection: '#a855f7',
}

export default function DashboardPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const graphRef = useRef(null)
  const containerRef = useRef(null)
  const [search, setSearch] = useState('')
  const [activeFilters, setActiveFilters] = useState([])
  const [showFilters, setShowFilters] = useState(false)
  const [showPanel, setShowPanel] = useState(false)
  const [menuOpen, setMenuOpen] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [hoverNode, setHoverNode] = useState(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 })
  const [selectedDomain, setSelectedDomain] = useState(null)
  const [showDomains, setShowDomains] = useState(true)
  const [contextMenu, setContextMenu] = useState(null)

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
    onSuccess: (_, docId) => {
      queryClient.invalidateQueries({ queryKey: ['documents', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['graph-documents', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['collections', USER_ID] })
      toast.success('Document deleted')
    },
    onError: (err) => {
      toast.error(`Delete failed: ${err.message || 'Unknown error'}`)
    },
  })

  const [confirmDelete, setConfirmDelete] = useState(null)

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

  // Sync selectedDomain → activeFilters
  useEffect(() => {
    if (selectedDomain) {
      setActiveFilters([selectedDomain])
    } else {
      setActiveFilters([])
    }
  }, [selectedDomain])

  const availableTags = useMemo(() => {
    if (!collectionsData) return []
    const tags = new Set()
    collectionsData.taxonomy_categories?.forEach(c => tags.add(c))
    collectionsData.existing_collections?.forEach(c => tags.add(c))
    return [...tags].sort()
  }, [collectionsData])

  const formatName = (name) => name.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')

  // Collections list with per-collection document counts
  const collectionList = useMemo(() => {
    const docs = Array.isArray(documents) ? documents : []
    const collections = collectionsData?.existing_collections || []
    return collections.map(col => ({
      name: col,
      count: docs.filter(d => d.collections?.includes(col)).length,
    })).sort((a, b) => b.count - a.count)
  }, [documents, collectionsData])

  // Filter documents
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
      docs = docs.filter(d =>
        activeFilters.some(f => d.collections?.includes(f))
      )
    }
    return docs
  }, [documents, search, activeFilters])

  // Displayed docs in the bottom panel:
  // - collection selected → only that collection's docs
  // - searching → matching results, max 50
  // - neither → most recent 20
  const displayedDocs = useMemo(() => {
    const allDocs = Array.isArray(documents) ? documents : []
    if (search) {
      return filtered.slice(0, 50)
    }
    if (selectedDomain) {
      return filtered
    }
    // Most recent 20 by upload date (or doc_id order as fallback)
    const sorted = [...allDocs].sort((a, b) => {
      const da = a.created_at || a.upload_date || ''
      const db = b.created_at || b.upload_date || ''
      return db.localeCompare(da)
    })
    return sorted.slice(0, 20)
  }, [documents, filtered, search, selectedDomain])

  // Build graph data: document nodes + collection virtual nodes + links
  const graphData = useMemo(() => {
    const docs = Array.isArray(documents) ? documents : []
    if (docs.length === 0) return { nodes: [], links: [] }

    const nodes = []
    const links = []
    const collectionSet = new Set()
    const searchLower = search.toLowerCase()
    const filteredIds = new Set(filtered.map(d => d.doc_id))

    for (const d of docs) {
      const matchesSearch = !search ||
        d.filename?.toLowerCase().includes(searchLower) ||
        d.collections?.some(c => c.toLowerCase().includes(searchLower))
      const matchesFilter = activeFilters.length === 0 || filteredIds.has(d.doc_id)

      nodes.push({
        id: `doc:${d.doc_id}`,
        label: d.filename?.replace(/\.[^.]+$/, '').slice(0, 30) || d.doc_id,
        color: NODE_COLORS.document,
        val: 4,
        _type: 'document',
        _data: d,
        _dimmed: (search && !matchesSearch) || (activeFilters.length > 0 && !matchesFilter),
      })

      for (const c of (d.collections || [])) {
        collectionSet.add(c)
        links.push({ source: `col:${c}`, target: `doc:${d.doc_id}`, _type: 'belongs_to' })
      }
    }

    for (const c of collectionSet) {
      const matchesSearch = !search || c.toLowerCase().includes(searchLower)
      const matchesFilter = activeFilters.length === 0 || activeFilters.includes(c)
      nodes.push({
        id: `col:${c}`,
        label: c,
        color: NODE_COLORS.collection,
        val: 6,
        _type: 'collection',
        _dimmed: (search && !matchesSearch) || (activeFilters.length > 0 && !matchesFilter),
      })
    }

    // Cross-doc similar_to edges from API
    if (graphEdges?.edges) {
      for (const e of graphEdges.edges) {
        links.push({
          source: `doc:${e.source_doc_id}`,
          target: `doc:${e.target_doc_id}`,
          _type: 'similar_to',
        })
      }
    }

    // Only keep links where both endpoints exist
    const nodeIds = new Set(nodes.map(n => n.id))
    const validLinks = links.filter(l => nodeIds.has(l.source) && nodeIds.has(l.target))

    return {
      nodes: nodes.map(n => ({ ...n })),
      links: validLinks.map(l => ({ ...l })),
    }
  }, [documents, filtered, search, activeFilters, graphEdges])

  // Custom node canvas paint
  const paintNode = useCallback((node, ctx) => {
    const r = Math.sqrt(node.val || 3) * 1.8
    const dimmed = node._dimmed && !hoverNode
    ctx.globalAlpha = dimmed ? 0.2 : 1.0

    // Glow on hover
    if (hoverNode?.id === node.id) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2)
      ctx.fillStyle = node.color + '33'
      ctx.fill()
    }

    ctx.beginPath()
    if (node._type === 'collection') {
      // Diamond shape for collection nodes
      ctx.moveTo(node.x, node.y - r)
      ctx.lineTo(node.x + r, node.y)
      ctx.lineTo(node.x, node.y + r)
      ctx.lineTo(node.x - r, node.y)
      ctx.closePath()
    } else {
      // Circle for document nodes
      ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
    }
    ctx.fillStyle = node.color
    ctx.fill()

    // Label below node
    const fontSize = Math.max(3, r * 0.6)
    ctx.font = `${fontSize}px sans-serif`
    ctx.fillStyle = dimmed ? '#475569' : '#e2e8f0'
    ctx.textAlign = 'center'
    const label = node.label?.length > 25 ? node.label.slice(0, 22) + '..' : node.label
    ctx.fillText(label || '', node.x, node.y + r + fontSize + 1)

    ctx.globalAlpha = 1.0
  }, [hoverNode])

  const handleNodeClick = useCallback((node) => {
    if (node._type === 'document' && node._data?.doc_id) {
      navigate(`/chat?doc=${node._data.doc_id}&name=${encodeURIComponent(node._data.filename || node._data.source_file || '')}`)
    } else if (node._type === 'collection') {
      setSelectedDomain(prev => prev === node.label ? null : node.label)
      setShowPanel(true)
    }
  }, [navigate])

  const handleNodeHover = useCallback((node) => {
    setHoverNode(node || null)
  }, [])

  const handleDelete = (docId) => {
    const doc = documents.find(d => d.doc_id === docId)
    setConfirmDelete({ docId, filename: doc?.filename || 'this document' })
    setMenuOpen(null)
  }

  const handleDownload = (docId) => {
    const API_BASE = import.meta.env.VITE_API_URL
    window.open(`${API_BASE}/documents/${docId}/download`, '_blank')
    setMenuOpen(null)
  }

  const toggleFilter = (tag) => {
    setActiveFilters(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    )
  }

  const handleDomainClick = (col) => {
    if (selectedDomain === col) {
      setSelectedDomain(null)
    } else {
      setSelectedDomain(col)
      setShowPanel(true)
    }
  }

  const handleGraphRightClick = useCallback((node, event) => {
    event.preventDefault()

    const items = []

    if (node._type === 'document' && node._data) {
      items.push(
        { label: 'Chat about this', icon: MessageSquare, action: () => navigate(`/chat?doc=${node._data.doc_id}&name=${encodeURIComponent(node._data.filename || '')}`) },
        { label: 'Open in PDF', icon: FileText, action: () => navigate(`/pdf/${node._data.doc_id}`) },
        { label: 'View in Graph', icon: Network, action: () => navigate(`/graph/${node._data.doc_id}`) },
        { separator: true },
        { label: 'Download', icon: Download, action: () => handleDownload(node._data.doc_id) },
        { label: 'Delete', icon: Trash2, action: () => handleDelete(node._data.doc_id), danger: true },
      )
    } else if (node._type === 'collection') {
      items.push(
        { label: 'Chat about collection', icon: MessageSquare, action: () => navigate(`/chat?collection=${encodeURIComponent(node.label)}`) },
        { label: 'Filter by this', icon: Filter, action: () => handleDomainClick(node.label) },
      )
    }

    items.push({ separator: true })
    items.push({ label: 'Cancel', action: () => {} })

    setContextMenu({ x: event.clientX, y: event.clientY, items })
  }, [navigate, handleDownload, handleDelete, handleDomainClick])

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
        throw new Error(err.detail || `Upload failed (${resp.status})`)
      }
      return resp.json()
    })()

    toast.promise(uploadPromise, {
      loading: `Uploading ${file.name}...`,
      success: (data) => `${file.name} uploaded (${data.chunk_count} chunks)`,
      error: (err) => `Upload failed: ${err.message}`,
    })

    try {
      await uploadPromise
      queryClient.invalidateQueries({ queryKey: ['documents', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['collections', USER_ID] })
      queryClient.invalidateQueries({ queryKey: ['graph-documents', USER_ID] })
    } catch {
      // toast.promise already shows the error
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const formatDate = (iso) => {
    if (!iso) return ''
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  // Auto-expand panel when searching
  useEffect(() => {
    if (search) setShowPanel(true)
  }, [search])

  // Panel title: show count info
  const panelTitle = useMemo(() => {
    const total = Array.isArray(documents) ? documents.length : 0
    if (search) {
      return `Documents (showing ${displayedDocs.length} of ${filtered.length} matches)`
    }
    if (selectedDomain) {
      return `Documents in "${selectedDomain}" (${displayedDocs.length})`
    }
    return `Documents (showing ${displayedDocs.length} of ${total})`
  }, [documents, displayedDocs, filtered, search, selectedDomain])

  return (
    <div className="flex flex-col h-full">
      {/* Search + Filter toggle bar */}
      <div className="flex items-center gap-2 p-3 border-b" style={{ borderColor: 'hsl(217 33% 17%)' }}>
        <button
          onClick={() => setShowDomains(d => !d)}
          className="p-2 rounded-lg opacity-40 hover:opacity-100"
          style={{ backgroundColor: 'hsl(217 33% 17%)', color: 'hsl(210 40% 98%)' }}
          title={showDomains ? 'Hide domains' : 'Show domains'}
        >
          <Menu size={14} />
        </button>
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 opacity-40" />
          <input
            type="text"
            placeholder="Search documents..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2 rounded-lg text-sm outline-none"
            style={{ backgroundColor: 'hsl(217 33% 17%)', color: 'hsl(210 40% 98%)', border: '1px solid hsl(217 33% 22%)' }}
          />
        </div>
        <button
          onClick={() => setShowFilters(f => !f)}
          className={cn('p-2 rounded-lg text-xs transition-opacity', showFilters ? 'opacity-100' : 'opacity-40 hover:opacity-100')}
          style={{ backgroundColor: showFilters ? 'hsl(250 80% 65%)' : 'hsl(217 33% 17%)', color: 'hsl(210 40% 98%)' }}
          title="Toggle filters"
        >
          <Filter size={14} />
        </button>
      </div>

      {/* Filter tags — hidden by default, shown when showFilters is true */}
      {showFilters && availableTags.length > 0 && (
        <div className="px-3 py-2 flex flex-wrap gap-1.5 border-b" style={{ borderColor: 'hsl(217 33% 17%)' }}>
          {availableTags.map(tag => (
            <button
              key={tag}
              onClick={() => toggleFilter(tag)}
              className={cn(
                'px-2 py-0.5 rounded-full text-xs transition-colors flex items-center gap-1',
                activeFilters.includes(tag) ? 'font-medium' : 'opacity-50 hover:opacity-100'
              )}
              style={{
                backgroundColor: activeFilters.includes(tag) ? 'hsl(250 80% 65%)' : 'hsl(217 33% 17%)',
                color: 'hsl(210 40% 98%)',
              }}
            >
              {tag}
              {activeFilters.includes(tag) && <X size={8} />}
            </button>
          ))}
          {activeFilters.length > 0 && (
            <>
              <button
                onClick={() => navigate(`/chat?collection=${encodeURIComponent(activeFilters[0])}`)}
                className="p-1 rounded opacity-60 hover:opacity-100 transition-opacity"
                style={{ color: 'hsl(250 80% 65%)' }}
                title="Chat about this collection"
              >
                <MessageSquare size={14} />
              </button>
              <button
                onClick={() => setActiveFilters([])}
                className="px-2 py-0.5 text-xs opacity-40 hover:opacity-100"
                style={{ color: 'hsl(210 40% 98%)' }}
              >
                Clear
              </button>
            </>
          )}
        </div>
      )}

      {/* Main content: left sidebar + graph */}
      <div className="flex flex-1 min-h-0">
        {/* Left domain/collection sidebar */}
        {showDomains && (
        <div
          className="w-48 shrink-0 flex flex-col border-r"
          style={{ backgroundColor: 'hsl(222 47% 8%)', borderColor: 'hsl(217 33% 17%)' }}
        >
          <div
            className="px-3 py-2 text-xs font-semibold uppercase tracking-wider border-b"
            style={{ color: 'hsl(215 20% 65%)', borderColor: 'hsl(217 33% 17%)' }}
          >
            Domains
          </div>
          <div className="flex-1 overflow-auto py-1">
            {/* All option */}
            <button
              onClick={() => { setSelectedDomain(null); setActiveFilters([]) }}
              className="w-full flex items-center justify-between px-3 py-1.5 text-xs text-left transition-colors hover:bg-white/5"
              style={{
                color: !selectedDomain ? 'hsl(250 80% 65%)' : 'hsl(210 40% 98%)',
                backgroundColor: !selectedDomain ? 'hsl(250 80% 65% / 0.12)' : 'transparent',
                fontWeight: !selectedDomain ? 600 : 400,
              }}
            >
              <span>All</span>
              <span className="ml-1 shrink-0 tabular-nums" style={{ color: 'hsl(215 20% 65%)' }}>
                {Array.isArray(documents) ? documents.length : 0}
              </span>
            </button>

            {collectionList.length === 0 ? (
              <div className="px-3 py-4 text-xs opacity-30" style={{ color: 'hsl(215 20% 65%)' }}>
                No collections
              </div>
            ) : (
              collectionList.map(col => (
                <button
                  key={col.name}
                  onClick={() => handleDomainClick(col.name)}
                  className="w-full flex items-center justify-between px-3 py-1.5 text-xs text-left transition-colors hover:bg-white/5"
                  style={{
                    color: selectedDomain === col.name ? 'hsl(250 80% 65%)' : 'hsl(210 40% 98%)',
                    backgroundColor: selectedDomain === col.name ? 'hsl(250 80% 65% / 0.12)' : 'transparent',
                    fontWeight: selectedDomain === col.name ? 600 : 400,
                  }}
                >
                  <span className="truncate">{formatName(col.name)}</span>
                  <span className="ml-1 shrink-0 tabular-nums" style={{ color: 'hsl(215 20% 65%)' }}>
                    {col.count}
                  </span>
                </button>
              ))
            )}
          </div>

          {/* Chat button — only shown when a domain is selected */}
          {selectedDomain && (
            <div className="p-3 border-t" style={{ borderColor: 'hsl(217 33% 17%)' }}>
              <button
                onClick={() => navigate(`/chat?collection=${encodeURIComponent(selectedDomain)}`)}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-opacity hover:opacity-90"
                style={{ backgroundColor: 'hsl(250 80% 65%)', color: 'hsl(210 40% 98%)' }}
              >
                <MessageSquare size={12} /> Chat
              </button>
            </div>
          )}
        </div>
        )}

        {/* Mini document graph — fills remaining space */}
        <div className="flex-1 relative min-h-0" ref={containerRef} style={{ backgroundColor: 'hsl(222 47% 4%)' }}>
          {isLoading ? (
            <div className="absolute inset-0 flex items-center justify-center opacity-40" style={{ color: 'hsl(210 40% 98%)' }}>
              Loading...
            </div>
          ) : graphData.nodes.length === 0 ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center opacity-40" style={{ color: 'hsl(210 40% 98%)' }}>
              <FileText size={48} className="mb-4" />
              <p className="text-lg">Upload your first document</p>
              <p className="text-sm mt-1">to start building your knowledge graph</p>
            </div>
          ) : (
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData}
              width={dimensions.width}
              height={dimensions.height}
              backgroundColor="hsl(222, 47%, 4%)"
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={(node, color, ctx) => {
                const r = Math.sqrt(node.val || 3) * 1.8 + 2
                ctx.beginPath()
                ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
                ctx.fillStyle = color
                ctx.fill()
              }}
              onNodeClick={handleNodeClick}
              onNodeHover={handleNodeHover}
              onNodeRightClick={handleGraphRightClick}
              linkColor={l => l._type === 'similar_to' ? '#f59e0b99' : '#6366f133'}
              linkWidth={l => l._type === 'similar_to' ? 2.5 : 0.5}
              linkLineDash={l => l._type === 'similar_to' ? [4, 4] : null}
              cooldownTicks={20}
              onEngineStop={() => graphRef.current?.zoomToFit(300, 40)}
              enableNodeDrag={true}
            />
          )}

        </div>
      </div>

      {/* Floating upload button — fixed to viewport bottom-right */}
      <label
        className={cn(
          'fixed bottom-6 right-6 flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm cursor-pointer shadow-lg transition-opacity z-30',
          uploading ? 'opacity-50 pointer-events-none' : 'hover:opacity-90'
        )}
        style={{ backgroundColor: 'hsl(250 80% 65%)', color: 'hsl(210 40% 98%)' }}
      >
        {uploading ? <RefreshCw size={16} className="animate-spin" /> : <Upload size={16} />}
        {uploading ? 'Uploading...' : 'Upload'}
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
        title="Delete document?"
        message={`Are you sure you want to delete "${confirmDelete?.filename}"? This cannot be undone.`}
        confirmLabel="Delete"
        danger
        onConfirm={() => {
          deleteMutation.mutate(confirmDelete.docId)
          setConfirmDelete(null)
        }}
        onCancel={() => setConfirmDelete(null)}
      />


      {/* Collapsible document panel */}
      <div className="border-t shrink-0" style={{ borderColor: 'hsl(217 33% 17%)', backgroundColor: 'hsl(222 47% 8%)' }}>
        <button
          onClick={() => setShowPanel(p => !p)}
          className="flex items-center justify-between w-full px-4 py-2 text-xs"
          style={{ color: 'hsl(215 20% 65%)' }}
        >
          <span>{panelTitle}</span>
          {showPanel ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
        </button>

        {showPanel && (
          <div className="max-h-48 overflow-auto border-t" style={{ borderColor: 'hsl(217 33% 12%)' }}>
            {displayedDocs.length === 0 ? (
              <div className="p-4 text-xs text-center opacity-30">No documents match</div>
            ) : (
              displayedDocs.map(doc => (
                <div
                  key={doc.doc_id}
                  className="flex items-center gap-3 px-4 py-2 hover:bg-white/5 cursor-pointer transition-colors group text-xs"
                  onClick={() => navigate(`/chat?doc=${doc.doc_id}&name=${encodeURIComponent(doc.filename)}`)}
                >
                  <FileText size={12} className="shrink-0 opacity-40" />
                  <span className="flex-1 truncate" style={{ color: 'hsl(210 40% 98%)' }}>{doc.filename}</span>
                  <span className="opacity-30 shrink-0">{doc.chunk_count}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); navigate(`/pdf/${doc.doc_id}`) }}
                    className="p-1 rounded opacity-20 group-hover:opacity-80 hover:opacity-100 transition-opacity"
                    title="View PDF"
                  >
                    <FileText size={14} />
                  </button>
                  <div className="relative">
                    <button
                      onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === doc.doc_id ? null : doc.doc_id) }}
                      className="p-1 rounded opacity-0 group-hover:opacity-60 hover:opacity-100 transition-opacity"
                    >
                      <MoreVertical size={10} />
                    </button>
                    {menuOpen === doc.doc_id && (
                      <div
                        className="absolute right-0 bottom-8 z-20 rounded-lg shadow-lg py-1 min-w-[120px]"
                        style={{ backgroundColor: 'hsl(222 47% 12%)', border: '1px solid hsl(217 33% 22%)' }}
                      >
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDownload(doc.doc_id) }}
                          className="flex items-center gap-2 px-3 py-1.5 text-xs w-full hover:bg-white/5"
                          style={{ color: 'hsl(210 40% 98%)' }}
                        >
                          <Download size={10} /> Download
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDelete(doc.doc_id) }}
                          className="flex items-center gap-2 px-3 py-1.5 text-xs w-full hover:bg-white/5"
                          style={{ color: 'hsl(0 84% 60%)' }}
                        >
                          <Trash2 size={10} /> Delete
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}
