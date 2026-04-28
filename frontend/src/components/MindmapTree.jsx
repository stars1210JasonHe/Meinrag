import { useMemo, useCallback, useRef, useEffect, useState } from 'react'
import { Tree } from 'react-d3-tree'
import './MindmapTree.css'

/**
 * Per-depth visual style. Index = node depth. Append rows to add layers.
 * Each row is fully self-contained — the renderer reads it without branching.
 *
 *   shape:        'pill' | 'rounded' | 'underline'  — how the node draws
 *   width/height: bounding box for the shape + label hit target
 *   maxChars:     label truncation (set high to disable)
 *   fill:         background colour for shape
 *   stroke:       border colour (resting); selected state overrides to --signature
 *   labelColor:   text fill
 *   font:         { size, weight }
 *   showBadge:    whether to draw the chunk-count circle (typically only on leaves)
 */
const DEPTH_STYLES = [
  // depth 0 — central concept (one node)
  // 17px × 25 chars fits the 220px pill comfortably. Weight dropped
  // 700 → 600 — still distinct from branches but no longer chunky.
  { shape: 'pill',      width: 220, height: 44, maxChars: 25,
    fill: 'var(--signature)', stroke: 'transparent',
    labelColor: '#fff', font: { size: 17, weight: 600 }, showBadge: false },
  // depth 1 — branches
  // Weight 600 → 500 → 400. Bold weight on the colored soft fills was
  // muddy on pink/violet; regular weight reads cleanly. The hue + size
  // (15px vs 13px leaves) carries the level distinction now.
  { shape: 'rounded',   width: 200, height: 36, maxChars: 24,
    fill: 'var(--bg-2)', stroke: 'var(--border-strong)',
    labelColor: 'var(--fg)', font: { size: 15, weight: 400 }, showBadge: false },
  // depth 2 — leaves (clickable, has chunks)
  { shape: 'underline', width: 240, height: 36, maxChars: 30,
    fill: 'transparent', stroke: 'var(--border)',
    labelColor: 'var(--fg-1)', font: { size: 13, weight: 400 }, showBadge: true },
  // depth 3+ — fallback (last row repeats for any deeper depth)
  // To add real layer 4 styling: append a row above this comment.
]

const FALLBACK_STYLE = DEPTH_STYLES[DEPTH_STYLES.length - 1]
function styleFor(depth) {
  return DEPTH_STYLES[depth] ?? FALLBACK_STYLE
}

/**
 * Branch palette — 5 hues from index.css. Theme-aware: light/dark each
 * has its own tuning. Each tuple is [solid var, soft var]. depth-1
 * (branch) nodes pick by ownIndex % HUE_VARS.length; deeper levels
 * inherit. Central (depth 0) has __hue = null and stays signature.
 */
const HUE_VARS = [
  ['--mm-hue-1', '--mm-hue-1-soft'],
  ['--mm-hue-2', '--mm-hue-2-soft'],
  ['--mm-hue-3', '--mm-hue-3-soft'],
  ['--mm-hue-4', '--mm-hue-4-soft'],
  ['--mm-hue-5', '--mm-hue-5-soft'],
]

/**
 * MindmapTree — horizontal dendrogram for the LLM-derived concept tree.
 *
 * Props:
 *   tree              -- backend shape; see adaptBackend() below
 *   selectedChunkIds  -- number[] — visually mark nodes whose chunks intersect
 *   onLeafClick       -- (node) => void — fires for nodes flagged __leaf
 */
export default function MindmapTree({ tree, selectedChunkIds = [], onLeafClick }) {
  const containerRef = useRef(null)
  const [translate, setTranslate] = useState({ x: 120, y: 240 })

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
      const style = styleFor(nodeDatum.__depth)
      const chunks = nodeDatum.__chunk_indices ?? []
      const chunkCount = chunks.length
      const isSelected = nodeDatum.__leaf && chunks.some(i => selectedSet.has(i))
      const handle = nodeDatum.__leaf ? () => onLeafClick?.(nodeDatum) : toggleNode

      return (
        <g
          role="treeitem"
          aria-level={nodeDatum.__depth + 1}
          tabIndex={0}
          onClick={handle}
          onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handle() } }}
          style={{ cursor: 'pointer' }}
        >
          {renderShape(style, isSelected, nodeDatum.__hue)}
          <text
            x={0} y={0}
            textAnchor="middle" dominantBaseline="central"
            style={{
              fill: style.labelColor,
              fontSize: `${style.font.size}px`,
              fontWeight: style.font.weight,
              pointerEvents: 'none',
              userSelect: 'none',
            }}
          >
            {clampLabel(nodeDatum.name, style.maxChars)}
          </text>
          <title>{nodeDatum.name}</title>
          {style.showBadge && chunkCount > 0 && (
            <g transform={`translate(${style.width / 2 - 10}, ${-style.height / 2 + 10})`}>
              <circle r={9} style={{ fill: 'var(--signature)', opacity: 0.9 }} />
              <text
                style={{
                  fill: '#fff',
                  fontSize: '10px',
                  fontWeight: 600,
                  pointerEvents: 'none',
                }}
                textAnchor="middle"
                dominantBaseline="central"
              >
                {chunkCount}
              </text>
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
        nodeSize={{ x: 280, y: 56 }}
        translate={translate}
        renderCustomNodeElement={renderNode}
      />
    </div>
  )
}

/* ─── shape renderers ──────────────────────────────────────── */

function renderShape(style, isSelected, hue) {
  // When the node has a branch hue (depth >= 1), override the stroke and
  // the soft fill from the per-theme palette in index.css. Selected leaves
  // still take the signature stroke so they pop above their hue.
  const hueVars = hue != null ? HUE_VARS[hue] : null
  const stroke = isSelected
    ? 'var(--signature)'
    : hueVars
      ? `var(${hueVars[0]})`
      : style.stroke
  const fill = hueVars && style.shape !== 'underline'
    ? `var(${hueVars[1]})`
    : style.fill
  const strokeWidth = isSelected ? 2 : 1
  const common = {
    style: {
      fill,
      stroke, strokeWidth,
      transition: 'stroke 0.12s, fill 0.12s',
    },
  }
  switch (style.shape) {
    case 'pill':
      return (
        <rect
          x={-style.width / 2} y={-style.height / 2}
          width={style.width} height={style.height}
          rx={style.height / 2} ry={style.height / 2}
          {...common}
        />
      )
    case 'rounded':
      return (
        <rect
          x={-style.width / 2} y={-style.height / 2}
          width={style.width} height={style.height}
          rx={6} ry={6}
          {...common}
        />
      )
    case 'underline':
      // Invisible hit target + a baseline rule under the label.
      return (
        <>
          <rect
            x={-style.width / 2} y={-style.height / 2}
            width={style.width} height={style.height}
            rx={4} ry={4}
            style={{ fill: 'transparent', stroke: 'transparent' }}
          />
          <line
            x1={-style.width / 2 + 8} x2={style.width / 2 - 8}
            y1={style.height / 2 - 2}  y2={style.height / 2 - 2}
            style={{ stroke, strokeWidth }}
          />
        </>
      )
    default:
      return null
  }
}

/* ─── data adapter ─────────────────────────────────────────── */

/**
 * Walks the backend tree once, stamping each node with __depth, __leaf,
 * __hasChunks, __chunk_indices. Renderer reads only these flags — depth
 * is no longer overloaded with semantic meaning.
 *
 * To add layer 4: change the recursion below to keep going past
 * b.children[].children[]. The flags carry the meaning forward.
 */
function adaptBackend(tree) {
  const visit = (node, depth, hue) => {
    const children = node.children || node.branches
    const isLeaf = !children || children.length === 0
    const chunks = node.chunk_indices || []
    return {
      name: node.name ?? node.central,
      __depth: depth,
      __leaf: isLeaf,
      __hasChunks: chunks.length > 0,
      __chunk_indices: chunks,
      __hue: hue, // null at central; depth-1 nodes get an index; deeper inherit.
      children: isLeaf
        ? undefined
        : children.map((c, i) =>
            visit(
              c,
              depth + 1,
              // depth=0 children (i.e. branches) each pick their own hue;
              // deeper nodes inherit the branch ancestor's hue unchanged.
              depth === 0 ? i % HUE_VARS.length : hue,
            ),
          ),
    }
  }
  return visit({ name: tree.central, children: tree.branches || [] }, 0, null)
}

function clampLabel(text, maxChars) {
  if (!text) return ''
  if (text.length <= maxChars) return text
  return text.slice(0, maxChars - 1) + '…'
}
