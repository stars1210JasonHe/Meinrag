import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import ForceGraph2D from 'react-force-graph-2d'
import { FileText, Table2, Image, Calculator, ExternalLink, MessageSquare, X } from 'lucide-react'
import { fetchGraphDocuments, fetchGraphNodes, fetchDocuments, fetchCollections } from '@/lib/api'
import { cn } from '@/lib/utils'

const USER_ID = 'admin'

const NODE_COLORS = {
  text: '#3b82f6',
  table: '#f59e0b',
  formula: '#a855f7',
  image: '#10b981',
  document: '#6366f1',
}

const EDGE_TYPES = ['follows', 'co_located', 'describes', 'references', 'similar_to']
const EDGE_COLORS = {
  follows: '#64748b',     // gray — sequential order
  co_located: '#6366f1',  // indigo — same page
  describes: '#10b981',   // green — text explains visual
  references: '#f59e0b',  // amber — cross-reference
  similar_to: '#ec4899',  // pink — semantic similarity
}
const TYPE_ICONS = { text: FileText, table: Table2, image: Image, formula: Calculator }

export default function GraphPage() {
  const { docId } = useParams()
  const navigate = useNavigate()
  const graphRef = useRef(null)
  const containerRef = useRef(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [hoverNode, setHoverNode] = useState(null)
  const [highlightNodes, setHighlightNodes] = useState(new Set())
  const [highlightLinks, setHighlightLinks] = useState(new Set())
  const [nodeFilter, setNodeFilter] = useState({ text: true, table: true, formula: true, image: true })
  const [edgeFilter, setEdgeFilter] = useState({
    follows: true,
    describes: true,
    references: true,
    similar_to: false,
    co_located: false,
  })
  const [scope, setScope] = useState(docId || '')
  const [scopeType, setScopeType] = useState(docId ? 'doc' : 'all') // 'all' | 'collection' | 'doc'
  const [scopeLabel, setScopeLabel] = useState('')
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })

  const { data: documents = [] } = useQuery({
    queryKey: ['documents', USER_ID],
    queryFn: () => fetchDocuments(USER_ID),
  })

  const { data: collectionsData } = useQuery({
    queryKey: ['collections', USER_ID],
    queryFn: () => fetchCollections(USER_ID),
  })

  const activeEdgeTypes = EDGE_TYPES.filter(t => edgeFilter[t]).join(',')

  const { data: graphData, isLoading } = useQuery({
    queryKey: ['graph', scope, activeEdgeTypes],
    queryFn: () =>
      scope
        ? fetchGraphNodes(scope, activeEdgeTypes || 'follows', USER_ID)
        : fetchGraphDocuments(USER_ID),
  })

  // Measure container size
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => setDimensions({ width: el.clientWidth, height: el.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const docList = documents?.documents || (Array.isArray(documents) ? documents : [])
  const collections = collectionsData?.existing_collections || []

  // Group documents by collection for the dropdown
  const docsByCollection = useMemo(() => {
    const groups = {}
    for (const d of (Array.isArray(docList) ? docList : [])) {
      for (const c of (d.collections || [])) {
        if (!groups[c]) groups[c] = []
        if (!groups[c].find(x => x.doc_id === d.doc_id)) groups[c].push(d)
      }
    }
    return groups
  }, [docList])

  // For collection scope, filter document-level graph to matching docs
  const filteredGraphData = useMemo(() => {
    if (scopeType !== 'collection' || !graphData) return graphData
    const colDocs = docsByCollection[scopeLabel] || []
    const colDocIds = new Set(colDocs.map(d => d.doc_id))
    return {
      nodes: (graphData.nodes || []).filter(n => colDocIds.has(n.doc_id)),
      edges: (graphData.edges || []).filter(e =>
        colDocIds.has(e.source_doc_id) && colDocIds.has(e.target_doc_id)
      ),
    }
  }, [graphData, scopeType, scopeLabel, docsByCollection])

  // Transform backend data to react-force-graph format
  const graphFormatted = useMemo(() => {
    const data = scopeType === 'collection' ? filteredGraphData : graphData
    if (!data) return { nodes: [], links: [] }

    const nodes = (data.nodes || [])
      .filter(n => n.node_type === 'document' || nodeFilter[n.chunk_type] !== false)
      .map(n => ({
        id: n.node_type === 'document' ? `doc:${n.doc_id}` : `${n.doc_id}:${n.chunk_index}`,
        label: n.label || n.content_preview?.slice(0, 25) || n.source_file?.slice(0, 25) || '?',
        color: NODE_COLORS[n.chunk_type] || NODE_COLORS.document,
        _data: n,
      }))

    const nodeIds = new Set(nodes.map(n => n.id))

    const links = (data.edges || [])
      .map(e => ({
        source: e.source_chunk_index != null ? `${e.source_doc_id}:${e.source_chunk_index}` : `doc:${e.source_doc_id}`,
        target: e.target_chunk_index != null ? `${e.target_doc_id}:${e.target_chunk_index}` : `doc:${e.target_doc_id}`,
        relation: e.relation,
        color: '#334155',
      }))
      .filter(l => nodeIds.has(l.source) && nodeIds.has(l.target))

    // Compute connection count for node sizing
    const connCount = {}
    for (const l of links) {
      connCount[l.source] = (connCount[l.source] || 0) + 1
      connCount[l.target] = (connCount[l.target] || 0) + 1
    }
    const maxConn = Math.max(1, ...Object.values(connCount))

    // Deep copy + add computed size
    return {
      nodes: nodes.map(n => ({
        ...n,
        val: n._data?.node_type === 'document' ? 8 : 1 + (connCount[n.id] || 0) / maxConn * 5,
      })),
      links: links.map(l => ({ ...l })),
    }
  }, [graphData, filteredGraphData, scopeType, nodeFilter])

  const handleNodeClick = useCallback((node) => {
    if (node._data?.node_type === 'document') {
      setScope(node._data.doc_id)
      setSelectedNode(null)
      setHoverNode(null)
      setHighlightNodes(new Set())
      setHighlightLinks(new Set())
    } else {
      setSelectedNode(node._data)
      // Persist highlight on click (same as hover)
      const neighbors = new Set([node.id])
      const links = new Set()
      for (const l of graphFormatted.links) {
        const srcId = typeof l.source === 'object' ? l.source.id : l.source
        const tgtId = typeof l.target === 'object' ? l.target.id : l.target
        if (srcId === node.id) { neighbors.add(tgtId); links.add(l) }
        if (tgtId === node.id) { neighbors.add(srcId); links.add(l) }
      }
      setHoverNode(node)
      setHighlightNodes(neighbors)
      setHighlightLinks(links)
    }
  }, [graphFormatted.links])

  const handleNodeDoubleClick = useCallback((node) => {
    if (node._data?.doc_id) {
      navigate(`/chat?doc=${node._data.doc_id}&name=${encodeURIComponent(node._data.source_file || '')}`)
    }
  }, [navigate])

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null)
    setHoverNode(null)
    setHighlightNodes(new Set())
    setHighlightLinks(new Set())
  }, [])

  const handleNodeHover = useCallback((node) => {
    setHoverNode(node || null)
    if (node) {
      const neighbors = new Set([node.id])
      const links = new Set()
      for (const l of graphFormatted.links) {
        const srcId = typeof l.source === 'object' ? l.source.id : l.source
        const tgtId = typeof l.target === 'object' ? l.target.id : l.target
        if (srcId === node.id) { neighbors.add(tgtId); links.add(l) }
        if (tgtId === node.id) { neighbors.add(srcId); links.add(l) }
      }
      setHighlightNodes(neighbors)
      setHighlightLinks(links)
    } else {
      setHighlightNodes(new Set())
      setHighlightLinks(new Set())
    }
  }, [graphFormatted.links])

  // Custom node rendering with hover glow
  const paintNode = useCallback((node, ctx) => {
    const r = Math.sqrt(node.val || 4) * 2
    const isHighlighted = !hoverNode || highlightNodes.has(node.id)
    const opacity = isHighlighted ? 1.0 : 0.15

    ctx.globalAlpha = opacity

    // Glow for hovered node
    if (hoverNode?.id === node.id) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, r + 3, 0, Math.PI * 2)
      ctx.fillStyle = node.color + '44'
      ctx.fill()
    }

    // Node shape
    ctx.beginPath()
    if (node._data?.node_type === 'document') {
      const s = r * 1.2
      ctx.roundRect?.(node.x - s, node.y - s, s * 2, s * 2, 2) ||
        ctx.rect(node.x - s, node.y - s, s * 2, s * 2)
    } else {
      ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
    }
    ctx.fillStyle = node.color || '#6366f1'
    ctx.fill()

    // Border ring for selected
    if (selectedNode && node._data?.chunk_index === selectedNode.chunk_index && node._data?.doc_id === selectedNode.doc_id) {
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 1
      ctx.stroke()
    }

    // Label (only show on hover or for documents)
    if (hoverNode?.id === node.id || node._data?.node_type === 'document' || !hoverNode) {
      ctx.font = `${Math.max(3, r * 0.8)}px sans-serif`
      ctx.fillStyle = isHighlighted ? '#e2e8f0' : '#64748b'
      ctx.textAlign = 'center'
      const label = node.label?.length > 20 ? node.label.slice(0, 18) + '..' : node.label
      ctx.fillText(label || '', node.x, node.y + r + 4)
    }

    ctx.globalAlpha = 1.0
  }, [hoverNode, highlightNodes, selectedNode])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement?.tagName === 'INPUT') return
      if (e.key === 'f' || e.key === 'F') {
        graphRef.current?.zoomToFit(300)
      }
      if (e.key === 'Escape') {
        setSelectedNode(null)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // (docList and collections moved up before filteredGraphData)

  const handleScopeChange = (value) => {
    setSelectedNode(null)
    if (!value) {
      setScope(''); setScopeType('all'); setScopeLabel('')
    } else if (value.startsWith('col:')) {
      const col = value.slice(4)
      setScopeType('collection'); setScopeLabel(col); setScope('')
    } else {
      const doc = docList.find(d => d.doc_id === value)
      setScopeType('doc'); setScopeLabel(doc?.filename || value); setScope(value)
    }
  }

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: 'hsl(222 47% 4%)' }}>
      {/* Breadcrumb */}
      {(scopeType !== 'all') && (
        <div className="flex items-center gap-1 px-4 py-1.5 text-xs border-b"
             style={{ borderColor: 'hsl(217 33% 12%)', color: 'hsl(215 20% 65%)' }}>
          <button onClick={() => handleScopeChange('')} className="hover:underline opacity-60 hover:opacity-100">
            All Documents
          </button>
          <span className="opacity-30">→</span>
          {scopeType === 'collection' && (
            <span style={{ color: 'hsl(210 40% 98%)' }}>{scopeLabel}</span>
          )}
          {scopeType === 'doc' && (
            <span style={{ color: 'hsl(210 40% 98%)' }}>{scopeLabel}</span>
          )}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b flex-wrap"
           style={{ borderColor: 'hsl(217 33% 17%)', backgroundColor: 'hsl(222 47% 8%)' }}>
        {Object.entries(NODE_COLORS).filter(([k]) => k !== 'document').map(([type, color]) => (
          <button
            key={type}
            onClick={() => setNodeFilter(f => ({ ...f, [type]: !f[type] }))}
            className={cn('flex items-center gap-1 text-xs transition-opacity',
              nodeFilter[type] ? 'opacity-100' : 'opacity-30'
            )}
            style={{ color: 'hsl(210 40% 98%)' }}
          >
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            {type}
          </button>
        ))}

        <span className="opacity-20" style={{ color: 'hsl(210 40% 98%)' }}>|</span>

        {EDGE_TYPES.map(type => (
          <button
            key={type}
            onClick={() => setEdgeFilter(f => ({ ...f, [type]: !f[type] }))}
            className={cn('flex items-center gap-1 text-xs px-1.5 py-0.5 rounded transition-opacity',
              edgeFilter[type] ? 'opacity-100' : 'opacity-30'
            )}
            style={{
              backgroundColor: edgeFilter[type] ? 'hsl(217 33% 17%)' : 'transparent',
              color: 'hsl(210 40% 98%)',
            }}
          >
            <span className="w-3 h-0.5 inline-block rounded" style={{ backgroundColor: EDGE_COLORS[type] }} />
            {type}
          </button>
        ))}

        <span className="opacity-20" style={{ color: 'hsl(210 40% 98%)' }}>|</span>

        <select
          value={scopeType === 'collection' ? `col:${scopeLabel}` : scope}
          onChange={e => handleScopeChange(e.target.value)}
          className="text-xs rounded px-2 py-1 outline-none"
          style={{ backgroundColor: 'hsl(217 33% 17%)', color: 'hsl(210 40% 98%)', border: 'none' }}
        >
          <option value="">All Documents</option>
          {collections.length > 0 && (
            <optgroup label="Collections">
              {collections.map(c => (
                <option key={`col:${c}`} value={`col:${c}`}>{c}</option>
              ))}
            </optgroup>
          )}
          <optgroup label="Documents">
            {(Array.isArray(docList) ? docList : []).map(d => (
              <option key={d.doc_id} value={d.doc_id}>{d.filename}</option>
            ))}
          </optgroup>
        </select>

        {scopeType !== 'all' && (
          <button onClick={() => handleScopeChange('')}
                  className="text-xs opacity-40 hover:opacity-100" style={{ color: 'hsl(210 40% 98%)' }}>
            <X size={12} />
          </button>
        )}
      </div>

      {/* Graph canvas */}
      <div className="flex-1 relative" ref={containerRef}>
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center z-10 opacity-40"
               style={{ color: 'hsl(210 40% 98%)' }}>
            Loading graph...
          </div>
        )}
        {graphFormatted.nodes.length > 0 && (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphFormatted}
            width={dimensions.width}
            height={dimensions.height - (selectedNode ? 140 : 0)}
            backgroundColor="hsl(222, 47%, 4%)"
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(node, color, ctx) => {
              const r = (node.size || 4) + 2
              ctx.beginPath()
              ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
              ctx.fillStyle = color
              ctx.fill()
            }}
            onNodeClick={handleNodeClick}
            onNodeDblClick={handleNodeDoubleClick}
            onNodeHover={handleNodeHover}
            onBackgroundClick={handleBackgroundClick}
            linkColor={l => {
              if (hoverNode && !highlightLinks.has(l)) return '#1e293b'
              return EDGE_COLORS[l.relation] || '#64748b'
            }}
            linkWidth={l => {
              if (hoverNode && highlightLinks.has(l)) return 3
              return l.relation === 'follows' ? 0.5 : 1.5
            }}
            linkLineDash={l => l.relation === 'similar_to' ? [4, 4] : null}
            linkDirectionalArrowLength={l => l.relation === 'follows' ? 3 : 0}
            linkDirectionalArrowRelPos={1}
            cooldownTicks={30}
            onEngineStop={() => graphRef.current?.zoomToFit(300, 20)}
            enableNodeDrag={true}
          />
        )}
        {!isLoading && graphFormatted.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center opacity-40"
               style={{ color: 'hsl(210 40% 98%)' }}>
            No graph data. Select a document or upload one.
          </div>
        )}
      </div>

      {/* Node preview panel */}
      {selectedNode && (
        <div className="border-t px-4 py-3" style={{ borderColor: 'hsl(217 33% 17%)', backgroundColor: 'hsl(222 47% 8%)' }}>
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2">
              {(() => {
                const Icon = TYPE_ICONS[selectedNode.chunk_type] || FileText
                return <Icon size={16} style={{ color: NODE_COLORS[selectedNode.chunk_type] }} />
              })()}
              <span className="text-sm font-medium" style={{ color: 'hsl(210 40% 98%)' }}>
                {selectedNode.label || selectedNode.chunk_type} · {selectedNode.source_file}
              </span>
            </div>
            <button onClick={() => setSelectedNode(null)} className="opacity-40 hover:opacity-100"
                    style={{ color: 'hsl(210 40% 98%)' }}>
              <X size={14} />
            </button>
          </div>
          <p className="text-xs mb-3 leading-relaxed" style={{ color: 'hsl(215 20% 65%)' }}>
            {selectedNode.content_preview}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate(`/pdf/${selectedNode.doc_id}`)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs"
              style={{ backgroundColor: 'hsl(217 33% 17%)', color: 'hsl(210 40% 98%)' }}
            >
              <ExternalLink size={12} /> Open in PDF
            </button>
            <button
              onClick={() => navigate(`/chat?doc=${selectedNode.doc_id}`)}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs"
              style={{ backgroundColor: 'hsl(217 33% 17%)', color: 'hsl(210 40% 98%)' }}
            >
              <MessageSquare size={12} /> Ask about this
            </button>
            {selectedNode.page != null && (
              <span className="text-xs opacity-40" style={{ color: 'hsl(210 40% 98%)' }}>
                Page {selectedNode.page + 1}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
