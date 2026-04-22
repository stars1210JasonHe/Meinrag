import { useMemo, useRef, useEffect } from 'react'
import ForceGraph2D from 'react-force-graph-2d'

// Reuse EXACT constants from GraphPage for visual consistency across pages
const NODE_COLORS = {
  text: '#3b82f6',
  table: '#f59e0b',
  formula: '#a855f7',
  image: '#10b981',
}

const EDGE_COLORS = {
  follows: '#64748b',
  co_located: '#6366f1',
  describes: '#10b981',
  references: '#f59e0b',
  similar_to: '#ec4899',
}

export default function MindmapGraph({
  nodes,
  edges,
  onNodeClick,
  selectedId,
}) {
  const fgRef = useRef()

  // Transform to react-force-graph shape. Node size scales as sqrt(content_length)
  // so 10-char chunks don't vanish and 10k-char chunks don't dominate.
  const graphData = useMemo(() => ({
    nodes: nodes.map(n => ({
      ...n,
      val: Math.max(1, Math.sqrt(n.content_length || 10) / 4),
    })),
    links: edges.map(e => ({
      source: e.source,
      target: e.target,
      relation: e.relation,
      score: e.score,
    })),
  }), [nodes, edges])

  // Auto-zoom to selected node
  useEffect(() => {
    if (selectedId && fgRef.current) {
      const node = graphData.nodes.find(n => n.id === selectedId)
      if (node && node.x != null && node.y != null) {
        fgRef.current.centerAt(node.x, node.y, 500)
        fgRef.current.zoom(2.5, 500)
      }
    }
  }, [selectedId, graphData.nodes])

  return (
    <ForceGraph2D
      ref={fgRef}
      graphData={graphData}
      nodeLabel={n => n.full_summary || n.label}
      nodeColor={n => NODE_COLORS[n.chunk_type] || NODE_COLORS.text}
      nodeVal={n => n.val}
      linkColor={l => EDGE_COLORS[l.relation] || '#999999'}
      linkWidth={l => (l.relation === 'follows' ? 0.5 : 1.5)}
      linkDirectionalArrowLength={l => (l.relation === 'references' ? 4 : 0)}
      linkDirectionalArrowRelPos={0.9}
      onNodeClick={onNodeClick}
      cooldownTicks={120}
      onEngineStop={() => fgRef.current?.zoomToFit(400, 40)}
    />
  )
}
