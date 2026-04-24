import { useMemo, useCallback, useRef, useEffect, useState } from 'react'
import { Tree } from 'react-d3-tree'
import './MindmapTree.css'

/**
 * MindmapTree — horizontal dendrogram renderer for the LLM-derived
 * concept tree (see GET /documents/:id/mindmap).
 *
 * Props:
 *   tree              -- { central, branches: [{ name, children: [{ name, chunk_indices }] }] }
 *   selectedChunkIds  -- number[] — chunks to visually mark on matching leaves
 *   onLeafClick       -- (leaf) => void — parent handles NodePanel update
 */
export default function MindmapTree({ tree, selectedChunkIds = [], onLeafClick }) {
  const containerRef = useRef(null)
  const [translate, setTranslate] = useState({ x: 120, y: 240 })

  // Fit-to-screen on mount (research §6: explicit fit + wheel/button zoom)
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setTranslate({ x: 100, y: rect.height / 2 })
  }, [])

  const data = useMemo(() => adaptBackend(tree), [tree])
  const selectedSet = useMemo(() => new Set(selectedChunkIds), [selectedChunkIds])

  const renderNode = useCallback(
    ({ nodeDatum, toggleNode }) => {
      const isCentral = nodeDatum.__depth === 0
      const isBranch = nodeDatum.__depth === 1
      const isLeaf = nodeDatum.__depth === 2
      const chunkIndices = nodeDatum.__chunk_indices
      const chunkCount = chunkIndices?.length ?? 0

      const isSelected =
        isLeaf && chunkIndices?.some(i => selectedSet.has(i))

      const handle = isLeaf ? () => onLeafClick?.(nodeDatum) : toggleNode

      const width = isCentral ? 220 : isBranch ? 200 : 220
      const height = isCentral ? 44 : isBranch ? 36 : 40

      return (
        <g
          role="treeitem"
          aria-level={nodeDatum.__depth + 1}
          tabIndex={0}
          onClick={handle}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handle() } }}
        >
          <rect
            x={-width / 2} y={-height / 2} width={width} height={height}
            className={`mm-leaf-rect${isSelected ? ' selected' : ''}`}
          />
          <text
            x={0} y={0}
            textAnchor="middle" dominantBaseline="central"
            className={`mm-leaf-label${isCentral ? ' central' : isBranch ? ' branch' : ''}`}
          >
            {clampLabel(nodeDatum.name, isCentral ? 36 : isBranch ? 30 : 28)}
          </text>
          <title>{nodeDatum.name}</title>
          {isLeaf && chunkCount > 0 && (
            <g transform={`translate(${width / 2 - 10}, ${-height / 2 + 10})`}>
              <circle r={10} className="mm-badge" />
              <text className="mm-badge-text">{chunkCount}</text>
            </g>
          )}
        </g>
      )
    },
    [onLeafClick, selectedSet],
  )

  if (!tree || !Array.isArray(tree.branches) || tree.branches.length === 0) {
    return null
  }

  return (
    <div ref={containerRef} className="mm-container" role="tree" aria-label="Document mind map">
      <Tree
        data={data}
        orientation="horizontal"
        pathFunc="diagonal"
        initialDepth={1}
        collapsible
        zoomable
        zoom={0.9}
        scaleExtent={{ min: 0.3, max: 2 }}
        separation={{ siblings: 1.2, nonSiblings: 1.6 }}
        nodeSize={{ x: 260, y: 50 }}
        translate={translate}
        renderCustomNodeElement={renderNode}
      />
    </div>
  )
}

function adaptBackend(tree) {
  const root = {
    name: tree.central,
    __depth: 0,
    children: (tree.branches || []).map(b => ({
      name: b.name,
      __depth: 1,
      children: (b.children || []).map(c => ({
        name: c.name,
        __depth: 2,
        __chunk_indices: c.chunk_indices || [],
      })),
    })),
  }
  return root
}

function clampLabel(text, maxChars) {
  if (!text) return ''
  if (text.length <= maxChars) return text
  return text.slice(0, maxChars - 1) + '…'
}
