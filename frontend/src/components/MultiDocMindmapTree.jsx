import { useMemo, useCallback, useRef, useEffect, useState } from 'react'
import { Tree } from 'react-d3-tree'
import './MindmapTree.css'

/**
 * Multi-doc mindmap — synthesises one tree across N documents, each
 * leaf rendered with coverage colour blocks showing which docs feed
 * that concept.
 *
 * Shares the DEPTH_STYLES + foreignObject label rendering of the single-
 * doc MindmapTree (kept in sync via the shared CSS file). What's
 * different here: leaves below their label show a horizontal strip of
 * doc-colour blocks (one per doc in chunks_by_doc) and a count badge
 * with the total chunks. The branch hue is the union-blend of its
 * descendants' palettes, capped at the central signature colour at
 * depth 0.
 *
 * Props:
 *   tree          backend MultiMindmapTree (central + branches + palette)
 *   onLeafClick   (leafNode) => void
 */
const DEPTH_STYLES = [
  // depth 0 — central
  { shape: 'pill',      width: 240, height: 44, maxChars: 28,
    fill: 'var(--signature)', stroke: 'transparent',
    labelColor: '#fff', font: { size: 17, weight: 600 } },
  // depth 1 — branches
  { shape: 'rounded',   width: 210, height: 36, maxChars: 26,
    fill: 'var(--bg-2)', stroke: 'var(--border-strong)',
    labelColor: 'var(--fg)', font: { size: 15, weight: 400 } },
  // depth 2 — inner-or-leaf
  { shape: 'underline', width: 260, height: 50, maxChars: 32,
    fill: 'transparent', stroke: 'var(--border)',
    labelColor: 'var(--fg)', font: { size: 13, weight: 400 } },
  // depth 3+ — grandchildren (conditional)
  { shape: 'underline', width: 240, height: 46, maxChars: 28,
    fill: 'transparent', stroke: 'var(--border)',
    labelColor: 'var(--fg-1)', font: { size: 12, weight: 400 } },
]

function styleFor(depth) {
  return DEPTH_STYLES[depth] ?? DEPTH_STYLES[DEPTH_STYLES.length - 1]
}

export default function MultiDocMindmapTree({ tree, onLeafClick }) {
  const containerRef = useRef(null)
  const [translate, setTranslate] = useState({ x: 120, y: 240 })

  // Theme-aware --fg colour for the foreignObject label trick (matches
  // single-doc behaviour — see MindmapTree.jsx).
  const [themedFg, setThemedFg] = useState('#f4f2ee')
  useEffect(() => {
    const read = () => {
      const v = getComputedStyle(document.documentElement)
        .getPropertyValue('--fg').trim()
      if (v) setThemedFg(v)
    }
    read()
    const obs = new MutationObserver(read)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setTranslate({ x: 100, y: rect.height / 2 })
  }, [])

  const palette = tree?.palette || {}
  const data = useMemo(() => adaptBackend(tree), [tree])

  const renderNode = useCallback(
    ({ nodeDatum, toggleNode }) => {
      const style = styleFor(nodeDatum.__depth)
      const chunksByDoc = nodeDatum.__chunks_by_doc || {}
      const coverage = Object.keys(chunksByDoc)
      const totalChunks = coverage.reduce(
        (acc, d) => acc + (chunksByDoc[d]?.length || 0), 0,
      )
      const handle = nodeDatum.__leaf
        ? () => onLeafClick?.(nodeDatum)
        : toggleNode

      // Leaves with colour blocks need extra vertical room. We extend
      // the foreignObject height by 12 px so the strip + label both fit.
      const isLeafWithCoverage = nodeDatum.__leaf && coverage.length > 0
      const boxHeight = isLeafWithCoverage ? style.height : style.height - 14

      return (
        <g
          role="treeitem"
          aria-level={nodeDatum.__depth + 1}
          tabIndex={0}
          onClick={handle}
          onKeyDown={e => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault(); handle()
            }
          }}
          style={{ cursor: 'pointer' }}
        >
          {renderShape(style, false, null)}

          <foreignObject
            x={-style.width / 2}
            y={-style.height / 2}
            width={style.width}
            height={boxHeight}
            style={{ pointerEvents: 'none' }}
          >
            <div
              xmlns="http://www.w3.org/1999/xhtml"
              className={`mm-node-label-html mm-node-label-d${nodeDatum.__depth}`}
              style={{
                width: '100%',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '3px',
                fontSize: `${style.font.size}px`,
                fontWeight: style.font.weight,
                color: style.labelColor === 'var(--fg)' ? themedFg : style.labelColor,
                userSelect: 'none',
                lineHeight: 1.2,
                padding: '4px 8px',
                boxSizing: 'border-box',
                textAlign: 'center',
              }}
            >
              <div style={{ width: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {clampLabel(nodeDatum.name, style.maxChars)}
              </div>

              {isLeafWithCoverage && (
                <div style={{
                  display: 'flex',
                  gap: 3,
                  alignItems: 'center',
                  justifyContent: 'center',
                }}>
                  {coverage.slice(0, 6).map(docId => (
                    <span
                      key={docId}
                      style={{
                        display: 'inline-block',
                        width: 10,
                        height: 10,
                        borderRadius: 2,
                        background: palette[docId] || '#888',
                      }}
                    />
                  ))}
                  {coverage.length > 6 && (
                    <span style={{ fontSize: 10, opacity: 0.55, marginLeft: 2 }}>
                      +{coverage.length - 6}
                    </span>
                  )}
                  {totalChunks > 0 && (
                    <span style={{ fontSize: 10, opacity: 0.55, marginLeft: 4 }}>
                      · {totalChunks}
                    </span>
                  )}
                </div>
              )}
            </div>
          </foreignObject>
          <title>{buildTooltipText(nodeDatum.name, coverage, palette, tree?.__nameByDocId)}</title>
        </g>
      )
    },
    [onLeafClick, palette, themedFg, tree],
  )

  if (!tree || !Array.isArray(tree.branches) || tree.branches.length === 0) {
    return null
  }

  return (
    <div ref={containerRef} className="mm-container" role="tree" aria-label="Multi-doc mind map">
      <Tree
        data={data}
        orientation="horizontal"
        pathFunc="diagonal"
        initialDepth={1}
        collapsible
        zoomable
        zoom={0.9}
        scaleExtent={{ min: 0.3, max: 2 }}
        separation={{ siblings: 1.3, nonSiblings: 1.7 }}
        nodeSize={{ x: 300, y: 64 }}
        translate={translate}
        renderCustomNodeElement={renderNode}
      />
    </div>
  )
}

/* ─── shape renderers (copy of MindmapTree.jsx) ──────────────── */
function renderShape(style, isSelected, hue) {
  const stroke = isSelected ? 'var(--signature)' : style.stroke
  const strokeWidth = isSelected ? 2 : 1
  const common = {
    style: {
      fill: style.fill,
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
function adaptBackend(tree) {
  const visit = (node, depth) => {
    const children = node.children || node.branches
    const chunksByDoc = node.chunks_by_doc || null
    const isLeaf = !children || children.length === 0
    return {
      name: node.name ?? node.central,
      __depth: depth,
      __leaf: isLeaf,
      __chunks_by_doc: chunksByDoc,
      children: isLeaf
        ? undefined
        : children.map(c => visit(c, depth + 1)),
    }
  }
  return visit({ name: tree.central, children: tree.branches || [] }, 0)
}

function clampLabel(text, maxChars) {
  if (!text) return ''
  if (text.length <= maxChars) return text
  return text.slice(0, maxChars - 1) + '…'
}

function buildTooltipText(name, coverage, palette, nameByDocId) {
  if (!coverage || coverage.length === 0) return name
  const docNames = coverage
    .map(id => (nameByDocId?.[id] ?? id))
    .join(', ')
  return `${name}\nCovered by: ${docNames}`
}
