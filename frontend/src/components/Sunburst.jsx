import { useMemo, useState } from 'react'
import { hierarchy, partition } from 'd3-hierarchy'
import { arc as d3arc } from 'd3-shape'
import { scaleOrdinal } from 'd3-scale'
import { schemeTableau10 } from 'd3-scale-chromatic'
import { color as d3color } from 'd3-color'

/**
 * Hierarchical sunburst — pure SVG, theme-aware.
 *
 * Props:
 *   data:           { name, children: [{name, count, children: [...]}] }
 *   size:           pixel diameter (default 280)
 *   onSegmentClick: ({layer, name, count, path}) => void
 *   onSegmentHover: (segment | null) => void
 *
 * Layers (from inner ring outward):
 *   1. depth=1 — primary_category    (layer = 'category')
 *   2. depth=2 — domain               (layer = 'domain')
 *   3. depth=3 — sub-domain           (layer = 'subdomain')
 */
export default function Sunburst({
  data,
  size = 280,
  totalDocs,                  // distinct doc count for the center label
  primaryCategoryOrder,       // optional canonical order for color stability — pass
                              //   taxonomyData.primary_categories so colors don't
                              //   shuffle when data ordering changes
  onSegmentClick,
  onSegmentHover,
}) {
  const radius = size / 2
  const [hoverPath, setHoverPath] = useState(null)

  const empty = !data || !data.children || data.children.length === 0

  // ── color scale: stable ordinal per top-level (primary) name ─────────
  // Domain is keyed off the canonical taxonomy order (when supplied) so the
  // same primary always maps to the same color, regardless of which docs are
  // present this render. Falls back to data order if no canonical list given.
  const colorScale = useMemo(() => {
    const names = primaryCategoryOrder && primaryCategoryOrder.length > 0
      ? primaryCategoryOrder
      : (data?.children || []).map(d => d.name)
    return scaleOrdinal().domain(names).range(schemeTableau10)
  }, [data, primaryCategoryOrder])

  // ── layout via d3 partition ─────────────────────────────────────────
  const segments = useMemo(() => {
    if (empty) return []
    const root = hierarchy(data)
      .sum(d => (d.children && d.children.length > 0 ? 0 : (d.count || 1)))
      .sort((a, b) => b.value - a.value)
    partition().size([2 * Math.PI, radius])(root)

    const arcGen = d3arc()
      .startAngle(d => d.x0)
      .endAngle(d => d.x1)
      .innerRadius(d => d.y0)
      .outerRadius(d => d.y1 - 1) // 1px gap between rings

    const out = []
    root.descendants().forEach(node => {
      if (node.depth === 0) return // skip the synthetic root
      const ancestors = node.ancestors().reverse().slice(1).map(n => n.data.name)
      const primary = ancestors[0]
      const baseColor = colorScale(primary)
      const c = d3color(baseColor)
      // depth 1 uses base; deeper rings lighten progressively
      const lighten = node.depth === 2 ? 0.45 : node.depth === 3 ? 0.85 : 0
      const fill = lighten ? c.brighter(lighten).formatHex() : baseColor

      out.push({
        path: arcGen(node),
        depth: node.depth,
        name: node.data.name,
        count: node.value,
        ancestors,
        layer: node.depth === 1 ? 'category' : node.depth === 2 ? 'domain' : 'subdomain',
        fill,
        // For label positioning
        midAngle: (node.x0 + node.x1) / 2,
        midRadius: (node.y0 + node.y1) / 2,
        arcSpan: node.x1 - node.x0,
      })
    })
    return out
  }, [data, radius, colorScale, empty])

  // Center label uses *distinct doc count* when caller supplies it; otherwise
  // falls back to the leaf-weight sum (which can over-count when docs have many
  // subtags). totalDocs is preferred — it matches the corpus stats panel.
  const total = useMemo(() => {
    if (typeof totalDocs === 'number') return totalDocs
    if (empty) return 0
    return (data.children || []).reduce((s, c) => s + (c.count || 0), 0)
  }, [data, empty, totalDocs])

  const isHighlighted = (seg) => {
    if (!hoverPath) return true
    // A segment is highlighted if its ancestor list starts with the hovered path
    if (seg.ancestors.length < hoverPath.length) return false
    return hoverPath.every((p, i) => seg.ancestors[i] === p)
  }

  const handleEnter = (seg) => {
    setHoverPath(seg.ancestors)
    onSegmentHover?.(seg)
  }
  const handleLeave = () => {
    setHoverPath(null)
    onSegmentHover?.(null)
  }
  const handleClick = (seg) => {
    onSegmentClick?.({
      layer: seg.layer,
      name: seg.name,
      count: seg.count,
      path: seg.ancestors,
    })
  }

  if (empty) {
    return (
      <div
        className="flex items-center justify-center"
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          border: '1px dashed var(--border)',
          color: 'var(--fg-faint)',
          fontFamily: 'var(--mono)',
          fontSize: 11,
          textAlign: 'center',
          padding: '0 24px',
        }}
      >
        Upload a document to see your taxonomy
      </div>
    )
  }

  return (
    <svg width={size} height={size} viewBox={`-${radius} -${radius} ${size} ${size}`}>
      {/* Segments */}
      {segments.map((seg, i) => {
        const opacity = isHighlighted(seg) ? 1 : 0.25
        return (
          <path
            key={i}
            d={seg.path}
            fill={seg.fill}
            opacity={opacity}
            stroke="var(--bg)"
            strokeWidth={1}
            style={{ cursor: 'pointer', transition: 'opacity 120ms' }}
            onMouseEnter={() => handleEnter(seg)}
            onMouseLeave={handleLeave}
            onClick={() => handleClick(seg)}
          >
            <title>{`${seg.ancestors.join(' › ')} · ${seg.count}`}</title>
          </path>
        )
      })}

      {/* Center label — total or hovered name */}
      <text
        x={0}
        y={hoverPath ? -4 : 0}
        textAnchor="middle"
        style={{
          fill: 'var(--fg-1)',
          fontFamily: 'var(--display)',
          fontSize: 18,
          fontWeight: 500,
          pointerEvents: 'none',
        }}
      >
        {hoverPath ? hoverPath[hoverPath.length - 1] : total}
      </text>
      {hoverPath && (
        <text
          x={0}
          y={14}
          textAnchor="middle"
          style={{
            fill: 'var(--fg-faint)',
            fontFamily: 'var(--mono)',
            fontSize: 10,
            letterSpacing: '0.05em',
            pointerEvents: 'none',
          }}
        >
          {segments.find(s => s.ancestors.join('/') === hoverPath.join('/'))?.count} docs
        </text>
      )}
      {!hoverPath && (
        <text
          x={0}
          y={14}
          textAnchor="middle"
          style={{
            fill: 'var(--fg-faint)',
            fontFamily: 'var(--mono)',
            fontSize: 9,
            letterSpacing: '0.1em',
            textTransform: 'uppercase',
            pointerEvents: 'none',
          }}
        >
          documents
        </text>
      )}
    </svg>
  )
}
