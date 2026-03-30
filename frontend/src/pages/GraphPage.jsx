import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Network } from 'vis-network'
import { DataSet } from 'vis-data'
import { FileText, Table2, Image, Calculator, ExternalLink, MessageSquare, X } from 'lucide-react'
import { fetchGraphDocuments, fetchGraphNodes, fetchDocuments } from '@/lib/api'
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

const TYPE_ICONS = { text: FileText, table: Table2, image: Image, formula: Calculator }

export default function GraphPage() {
  const { docId } = useParams()
  const navigate = useNavigate()
  const containerRef = useRef(null)
  const networkRef = useRef(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [nodeFilter, setNodeFilter] = useState({ text: true, table: true, formula: true, image: true })
  const [edgeFilter, setEdgeFilter] = useState(
    Object.fromEntries(EDGE_TYPES.map(t => [t, true]))
  )
  const [scope, setScope] = useState(docId || '')

  const { data: documents = [] } = useQuery({
    queryKey: ['documents', USER_ID],
    queryFn: () => fetchDocuments(USER_ID),
  })

  const { data: graphData, isLoading } = useQuery({
    queryKey: ['graph', scope],
    queryFn: () =>
      scope
        ? fetchGraphNodes(scope, EDGE_TYPES.filter(t => edgeFilter[t]).join(','), USER_ID)
        : fetchGraphDocuments(USER_ID),
    enabled: true,
  })

  // Build and render vis-network
  useEffect(() => {
    if (!containerRef.current || !graphData) return

    const filteredNodes = (graphData.nodes || []).filter(n => {
      if (n.node_type === 'document') return true
      return nodeFilter[n.chunk_type] !== false
    })

    const nodeIds = new Set(filteredNodes.map(n =>
      n.node_type === 'document' ? `doc:${n.doc_id}` : `${n.doc_id}:${n.chunk_index}`
    ))

    const filteredEdges = (graphData.edges || []).filter(e => {
      if (!edgeFilter[e.relation]) return false
      const srcId = e.source_chunk_index != null
        ? `${e.source_doc_id}:${e.source_chunk_index}`
        : `doc:${e.source_doc_id}`
      const tgtId = e.target_chunk_index != null
        ? `${e.target_doc_id}:${e.target_chunk_index}`
        : `doc:${e.target_doc_id}`
      return nodeIds.has(srcId) && nodeIds.has(tgtId)
    })

    const nodes = new DataSet(filteredNodes.map(n => {
      const id = n.node_type === 'document' ? `doc:${n.doc_id}` : `${n.doc_id}:${n.chunk_index}`
      const rawLabel = n.label || n.content_preview?.slice(0, 20) || n.source_file?.slice(0, 20) || id
      return {
        id,
        label: rawLabel.length > 25 ? rawLabel.slice(0, 22) + '...' : rawLabel,
        color: NODE_COLORS[n.chunk_type] || NODE_COLORS.document,
        shape: n.node_type === 'document' ? 'box' : 'dot',
        size: n.node_type === 'document' ? 20 : 12,
        font: { color: '#e2e8f0', size: 10 },
        title: n.content_preview || n.label || '',
        _data: n,
      }
    }))

    const edges = new DataSet(filteredEdges.map((e, i) => {
      const from = e.source_chunk_index != null
        ? `${e.source_doc_id}:${e.source_chunk_index}`
        : `doc:${e.source_doc_id}`
      const to = e.target_chunk_index != null
        ? `${e.target_doc_id}:${e.target_chunk_index}`
        : `doc:${e.target_doc_id}`
      return {
        id: `e${i}`,
        from,
        to,
        label: e.relation,
        font: { color: '#64748b', size: 8, strokeWidth: 0 },
        color: { color: '#334155', highlight: '#64748b' },
        arrows: e.relation === 'follows' ? 'to' : '',
        dashes: e.relation === 'similar_to',
        hidden: false,
      }
    }))

    const options = {
      physics: {
        forceAtlas2Based: {
          gravitationalConstant: -80,
          centralGravity: 0.01,
          springLength: 120,
          springConstant: 0.08,
        },
        solver: 'forceAtlas2Based',
        stabilization: { iterations: 100 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
        zoomView: true,
        dragView: true,
      },
      edges: {
        smooth: { type: 'continuous' },
        width: 1,
        hoverWidth: 2,
        font: { align: 'middle' },
      },
      nodes: {
        borderWidth: 0,
      },
    }

    if (networkRef.current) {
      networkRef.current.destroy()
    }

    const network = new Network(containerRef.current, { nodes, edges }, options)
    networkRef.current = network

    network.on('click', (params) => {
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0]
        const node = nodes.get(nodeId)
        if (node?._data) {
          if (node._data.node_type === 'document') {
            setScope(node._data.doc_id)
            setSelectedNode(null)
          } else {
            setSelectedNode(node._data)
          }
        }
      } else {
        setSelectedNode(null)
      }
    })

    network.once('stabilizationIterationsDone', () => {
      network.fit({ animation: { duration: 500 } })
    })

    return () => {
      network.destroy()
      networkRef.current = null
    }
  }, [graphData, nodeFilter, edgeFilter])

  // Keyboard shortcuts: F to fit, Escape to close preview
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement?.tagName === 'INPUT') return
      if (e.key === 'f' || e.key === 'F') {
        networkRef.current?.fit({ animation: { duration: 300 } })
      }
      if (e.key === 'Escape') {
        setSelectedNode(null)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const docList = Array.isArray(documents) ? documents : []

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: 'hsl(222 47% 4%)' }}>
      {/* Toolbar */}
      <div
        className="flex items-center gap-3 px-4 py-2 border-b flex-wrap"
        style={{ borderColor: 'hsl(217 33% 17%)', backgroundColor: 'hsl(222 47% 8%)' }}
      >
        {/* Node type toggles */}
        {Object.entries(NODE_COLORS)
          .filter(([k]) => k !== 'document')
          .map(([type, color]) => (
            <button
              key={type}
              onClick={() => setNodeFilter(f => ({ ...f, [type]: !f[type] }))}
              className={cn('flex items-center gap-1 text-xs transition-opacity',
                nodeFilter[type] ? 'opacity-100' : 'opacity-30'
              )}
            >
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
              {type}
            </button>
          ))}

        <span className="opacity-20">|</span>

        {/* Edge type toggles */}
        {EDGE_TYPES.map(type => (
          <button
            key={type}
            onClick={() => setEdgeFilter(f => ({ ...f, [type]: !f[type] }))}
            className={cn('text-xs px-1.5 py-0.5 rounded transition-opacity',
              edgeFilter[type] ? 'opacity-100' : 'opacity-30'
            )}
            style={{
              backgroundColor: edgeFilter[type] ? 'hsl(217 33% 17%)' : 'transparent',
              color: 'hsl(210 40% 98%)',
            }}
          >
            {type}
          </button>
        ))}

        <span className="opacity-20">|</span>

        {/* Scope selector */}
        <select
          value={scope}
          onChange={e => { setScope(e.target.value); setSelectedNode(null) }}
          className="text-xs rounded px-2 py-1 outline-none"
          style={{ backgroundColor: 'hsl(217 33% 17%)', color: 'hsl(210 40% 98%)', border: 'none' }}
        >
          <option value="">All Documents</option>
          {docList.map(d => (
            <option key={d.doc_id} value={d.doc_id}>{d.filename}</option>
          ))}
        </select>
      </div>

      {/* Graph canvas */}
      <div className="flex-1 relative">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center z-10"
               style={{ color: 'hsl(215 20% 65%)' }}>
            Loading graph...
          </div>
        )}
        <div ref={containerRef} className="w-full h-full" />
      </div>

      {/* Node preview panel */}
      {selectedNode && (
        <div
          className="border-t px-4 py-3"
          style={{ borderColor: 'hsl(217 33% 17%)', backgroundColor: 'hsl(222 47% 8%)' }}
        >
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2">
              {(() => {
                const Icon = TYPE_ICONS[selectedNode.chunk_type] || FileText
                return <Icon size={16} style={{ color: NODE_COLORS[selectedNode.chunk_type] }} />
              })()}
              <span className="text-sm font-medium" style={{ color: 'hsl(210 40% 98%)' }}>
                {selectedNode.label || selectedNode.chunk_type}
                {selectedNode.source_file ? ` · ${selectedNode.source_file}` : ''}
              </span>
            </div>
            <button onClick={() => setSelectedNode(null)} className="opacity-40 hover:opacity-100">
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
              <ExternalLink size={12} />
              Open in PDF
            </button>
            <button
              onClick={() => navigate('/chat')}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs"
              style={{ backgroundColor: 'hsl(217 33% 17%)', color: 'hsl(210 40% 98%)' }}
            >
              <MessageSquare size={12} />
              Ask about this
            </button>
            {selectedNode.page != null && (
              <span className="text-xs opacity-40">Page {selectedNode.page + 1}</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
