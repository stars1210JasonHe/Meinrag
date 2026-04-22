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
    const radius =
      kind === 'central' ? 12 :
      kind === 'branch' ? 8 :
      5
    return (
      <g onClick={toggleNode}>
        <circle r={radius} fill={fill} stroke="#fff" strokeWidth={1.5} />
        <text
          fill="currentColor"
          strokeWidth="0"
          x={radius + 6}
          y={4}
          fontSize={kind === 'central' ? 14 : 12}
          fontWeight={kind === 'central' ? 600 : 400}
          style={{ fontFamily: 'inherit' }}
        >
          {nodeDatum.name}
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
      separation={{ siblings: 1, nonSiblings: 1.3 }}
      renderCustomNodeElement={renderNode}
      onNodeClick={handleNodeClick}
      collapsible={false}
      zoom={0.9}
      scaleExtent={{ min: 0.3, max: 2 }}
    />
  )
}
