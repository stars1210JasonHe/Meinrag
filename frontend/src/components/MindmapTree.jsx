import { useMemo } from 'react'
import Tree from 'react-d3-tree'

/**
 * Radial tree visualization for the hierarchical mind map.
 *
 * Props:
 *  - tree: { central, branches: [{ name, children: [{ name, chunk_indices }] }] }
 *  - onLeafClick: (leaf, branchName) => void, triggered when a leaf concept is clicked
 */
export default function MindmapTree({ tree, onLeafClick }) {
  // Transform to react-d3-tree shape: one root, recursive children
  const d3Data = useMemo(() => {
    if (!tree) return null
    return {
      name: tree.central || '...',
      _kind: 'central',
      children: (tree.branches || []).map(b => ({
        name: b.name,
        _kind: 'branch',
        children: (b.children || []).map(leaf => ({
          name: leaf.name,
          _kind: 'leaf',
          _chunk_indices: leaf.chunk_indices,
          _branch_name: b.name,
          attributes: { chunks: leaf.chunk_indices?.length || 0 },
        })),
      })),
    }
  }, [tree])

  if (!d3Data) return null

  const handleNodeClick = (node) => {
    const data = node.data
    if (data._kind === 'leaf' && onLeafClick) {
      onLeafClick({
        name: data.name,
        chunk_indices: data._chunk_indices,
        branch_name: data._branch_name,
      })
    }
  }

  const renderNode = ({ nodeDatum, toggleNode }) => {
    const kind = nodeDatum._kind
    const fill =
      kind === 'central' ? '#3b82f6' :
      kind === 'branch' ? '#6366f1' :
      '#10b981'
    // Rectangle sizing per kind — central largest, leaf smallest
    const width =
      kind === 'central' ? 200 :
      kind === 'branch' ? 160 :
      140
    const height =
      kind === 'central' ? 44 :
      kind === 'branch' ? 34 :
      28
    const fontSize =
      kind === 'central' ? 14 :
      kind === 'branch' ? 12 :
      11
    const fontWeight = kind === 'leaf' ? 400 : 600
    // Truncate label to fit — char counts tuned to average px widths
    const maxChars =
      kind === 'central' ? 26 :
      kind === 'branch' ? 22 :
      20
    const label = nodeDatum.name && nodeDatum.name.length > maxChars
      ? nodeDatum.name.slice(0, maxChars - 1) + '…'
      : (nodeDatum.name || '')
    return (
      <g onClick={toggleNode} style={{ cursor: 'pointer' }}>
        <rect
          x={-width / 2}
          y={-height / 2}
          width={width}
          height={height}
          rx={6}
          ry={6}
          fill={fill}
          stroke="rgba(255,255,255,0.25)"
          strokeWidth={1}
        />
        <text
          fill="#ffffff"
          strokeWidth="0"
          textAnchor="middle"
          dominantBaseline="central"
          fontSize={fontSize}
          fontWeight={fontWeight}
          style={{ fontFamily: 'inherit', pointerEvents: 'none' }}
        >
          {label}
        </text>
      </g>
    )
  }

  return (
    <Tree
      data={d3Data}
      orientation="horizontal"
      translate={{ x: 200, y: 400 }}
      pathFunc="diagonal"
      separation={{ siblings: 0.9, nonSiblings: 1.4 }}
      renderCustomNodeElement={renderNode}
      onNodeClick={handleNodeClick}
      collapsible={false}
      zoom={0.9}
      scaleExtent={{ min: 0.3, max: 2 }}
      nodeSize={{ x: 260, y: 60 }}
    />
  )
}
