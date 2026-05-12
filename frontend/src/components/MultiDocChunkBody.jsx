import { useMemo, useRef, useEffect, useState, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { X, MessageSquare, ExternalLink, Eye, Filter as FilterIcon } from 'lucide-react'

import { useMultiDocGraph } from '@/hooks/useMultiDocGraph'
import { buildDocColorMap } from '@/lib/docPalette'
import { drawChunkShape, drawChunkHitArea } from '@/lib/chunkShape'
import { cssVar } from '@/lib/cssVar'
import MultiDocLegend from './MultiDocLegend'
import MultiDocNodePanel from './MultiDocNodePanel'
import ContextMenu from './ContextMenu'

/**
 * The multi-doc chunk graph body. Self-contained: fetches its own data,
 * renders its own ForceGraph2D instance, owns its hover/focus/highlight
 * state.
 *
 * Visual encoding is multi-doc-specific (colour=doc, shape=chunk-type),
 * but the *interaction* model mirrors the single-doc chunk graph in
 * GraphPage.jsx: hover + click highlight neighbours, dim everything else,
 * NodePanel detail card at the bottom, right-click context menu, F/Esc
 * keyboard shortcuts. The aim is "learn one model, works in both views".
 *
 * Props:
 *   docIds              — string[] of selected document IDs
 *   documents           — full doc registry list (used to look up filenames)
 *   includeIntraDoc     — toggle whether doc-internal edges render
 *   filter              — keyword highlight (controlled by parent / URL)
 *   onFilterChange      — (next: string) => void
 *   width, height       — canvas size (parent measures the container)
 */
export default function MultiDocChunkBody({
  docIds,
  documents,
  includeIntraDoc = false,
  edgeTypes = 'similar_to',
  filter = '',
  onFilterChange,
  width,
  height,
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const graphRef = useRef(null)
  const containerRef = useRef(null)

  // Local typing state — debounced into the URL via onFilterChange so the
  // address bar doesn't update on every keystroke. 250 ms felt right in
  // the G4 dashboard search.
  const [filterDraft, setFilterDraft] = useState(filter)
  useEffect(() => {
    if (filterDraft === filter) return
    const id = setTimeout(() => { onFilterChange?.(filterDraft) }, 250)
    return () => clearTimeout(id)
  }, [filterDraft, filter, onFilterChange])
  useEffect(() => { setFilterDraft(filter) }, [filter])

  const { graphData, isLoading, paletteByDocId, palettesLoading } = useMultiDocGraph(
    docIds,
    { includeIntraDoc, edgeTypes, enabled: docIds.length > 0 },
  )

  // Theme tick so we re-resolve CSS vars on theme switch.
  const [themeTick, setThemeTick] = useState(0)
  useEffect(() => {
    const obs = new MutationObserver(() => setThemeTick(t => t + 1))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])

  const canvasBg = useMemo(() => cssVar('--bg', '#08080a'), [themeTick])

  // Doc colour map: prefer LLM-suggested palette, fall back to --mm-hue hash.
  const docColorMap = useMemo(() => {
    const entries = docIds.map(id => ({
      doc_id: id,
      tree: paletteByDocId[id]?.tree,
    }))
    return buildDocColorMap(entries)
  }, [docIds, paletteByDocId, themeTick])

  const docMeta = useMemo(() => {
    const byId = new Map((documents || []).map(d => [d.doc_id, d]))
    return docIds.map(id => byId.get(id)).filter(Boolean)
  }, [docIds, documents])

  const docNameById = useMemo(() => {
    const map = {}
    for (const d of (documents || [])) map[d.doc_id] = d.filename
    return map
  }, [documents])

  // Per-doc chunk counts for the legend.
  const chunkCountByDoc = useMemo(() => {
    const counts = {}
    for (const n of (graphData?.nodes || [])) {
      counts[n.doc_id] = (counts[n.doc_id] || 0) + 1
    }
    return counts
  }, [graphData])

  const legendDocs = useMemo(
    () => docMeta.map(d => ({
      doc_id: d.doc_id,
      filename: d.filename,
      color: docColorMap[d.doc_id] || '#888',
      chunkCount: chunkCountByDoc[d.doc_id] || 0,
    })),
    [docMeta, docColorMap, chunkCountByDoc],
  )

  // ── Interaction state ──────────────────────────────────────
  // Mirrors the single-doc model in GraphPage.jsx: hover sets a transient
  // highlight; click pins it; both maintain neighbour Sets the renderer
  // reads for dim/undim decisions.
  const [hoverNode, setHoverNode] = useState(null)
  const [pinnedNode, setPinnedNode] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [highlightNodes, setHighlightNodes] = useState(new Set())
  const [highlightLinks, setHighlightLinks] = useState(new Set())
  const [contextMenu, setContextMenu] = useState(null)
  const [focusedDocId, setFocusedDocId] = useState(null)
  const clickTimerRef = useRef(null)

  const activeNode = pinnedNode || hoverNode

  // Click a legend row to focus that doc (others dim on the canvas).
  const handleFocusToggle = useCallback(
    (docId) => setFocusedDocId(prev => (prev === docId ? null : docId)),
    [],
  )

  // ── Data transform ─────────────────────────────────────────
  const graphFormatted = useMemo(() => {
    if (!graphData) return { nodes: [], links: [] }
    const nodes = (graphData.nodes || []).map(n => ({
      ...n,
      id: `${n.doc_id}:${n.chunk_index}`,
    }))
    const links = (graphData.edges || []).map(e => ({
      source: `${e.source_doc_id}:${e.source_chunk_index}`,
      target: `${e.target_doc_id}:${e.target_chunk_index}`,
      relation: e.relation,
      score: e.score,
      crossDoc: e.source_doc_id !== e.target_doc_id,
    }))
    return { nodes, links }
  }, [graphData])

  // Adjacency: id → Set<id>. Memoised once per data change.
  const adjacency = useMemo(() => {
    const map = new Map()
    for (const n of graphFormatted.nodes) map.set(n.id, new Set([n.id]))
    for (const l of graphFormatted.links) {
      const s = typeof l.source === 'object' ? l.source.id : l.source
      const t = typeof l.target === 'object' ? l.target.id : l.target
      map.get(s)?.add(t)
      map.get(t)?.add(s)
    }
    return map
  }, [graphFormatted])

  const computeNeighbors = useCallback((node) => {
    const neighbors = adjacency.get(node.id) || new Set([node.id])
    const links = new Set()
    for (const l of graphFormatted.links) {
      const s = typeof l.source === 'object' ? l.source.id : l.source
      const t = typeof l.target === 'object' ? l.target.id : l.target
      if (s === node.id || t === node.id) links.add(l)
    }
    return { neighbors, links }
  }, [adjacency, graphFormatted.links])

  // ── Filter match set ───────────────────────────────────────
  const matchingIds = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return null
    const set = new Set()
    for (const n of graphFormatted.nodes) {
      const hay = [
        n.summary_preview || '',
        n.content_preview || '',
        n.label || '',
      ].join(' ').toLowerCase()
      if (hay.includes(q)) set.add(n.id)
    }
    return set
  }, [filter, graphFormatted.nodes])

  const matchCount = matchingIds?.size ?? null

  // ── Handlers ───────────────────────────────────────────────

  const openChunkInChat = useCallback((node) => {
    const docIdsParam = docIds.join(',')
    const params = new URLSearchParams({
      doc_ids: docIdsParam,
      doc: node.doc_id,
      chunk: String(node.chunk_index),
    })
    const label = node.label || node.summary_preview?.slice(0, 40) || ''
    const ct = node.chunk_type
    const suggestion = ct === 'image' ? `What does ${label || 'this figure'} show?`
      : ct === 'table' ? `Explain the data in ${label || 'this table'}`
      : ct === 'formula' ? `Explain ${label || 'this equation'}`
      : label ? `Tell me about: ${label}` : ''
    if (suggestion) params.set('suggest', suggestion)
    navigate(`/chat?${params.toString()}`)
  }, [docIds, navigate])

  const handleNodeClick = useCallback((node) => {
    // If already pinned → double-click navigates to chat, single-click unpins
    if (pinnedNode?.id === node.id) {
      if (clickTimerRef.current) {
        clearTimeout(clickTimerRef.current)
        clickTimerRef.current = null
        openChunkInChat(node._data || node)
      } else {
        clickTimerRef.current = setTimeout(() => {
          clickTimerRef.current = null
          setPinnedNode(null)
          setSelectedNode(null)
          setHighlightNodes(new Set())
          setHighlightLinks(new Set())
        }, 400)
      }
      return
    }
    // New node: pin + show NodePanel
    clearTimeout(clickTimerRef.current)
    clickTimerRef.current = setTimeout(() => { clickTimerRef.current = null }, 400)
    setPinnedNode(node)
    setSelectedNode(node._data || node)
    const { neighbors, links } = computeNeighbors(node)
    setHighlightNodes(neighbors)
    setHighlightLinks(links)
  }, [pinnedNode, openChunkInChat, computeNeighbors])

  const handleBackgroundClick = useCallback(() => {
    setPinnedNode(null)
    setSelectedNode(null)
    setHoverNode(null)
    setHighlightNodes(new Set())
    setHighlightLinks(new Set())
    setContextMenu(null)
  }, [])

  const handleNodeHover = useCallback((node) => {
    setHoverNode(node || null)
    if (pinnedNode) return  // pin wins
    if (node) {
      const { neighbors, links } = computeNeighbors(node)
      setHighlightNodes(neighbors)
      setHighlightLinks(links)
    } else {
      setHighlightNodes(new Set())
      setHighlightLinks(new Set())
    }
  }, [pinnedNode, computeNeighbors])

  const handleNodeRightClick = useCallback((node, event) => {
    event.preventDefault()
    const data = node._data || node
    const items = [
      {
        label: t('graph.openChunk', { defaultValue: 'Open chunk' }),
        icon: MessageSquare,
        action: () => openChunkInChat(data),
      },
      {
        label: t('dashboard.openInPdf', { defaultValue: 'Open in PDF' }),
        icon: ExternalLink,
        action: () => navigate(`/pdf/${data.doc_id}`),
      },
      {
        label: t('multiDoc.focusOnThisDoc', { defaultValue: 'Focus on this doc' }),
        icon: Eye,
        action: () => setFocusedDocId(data.doc_id),
      },
      {
        label: t('multiDoc.filterToSimilar', { defaultValue: 'Filter to similar chunks' }),
        icon: FilterIcon,
        action: () => {
          // Pull the first salient word from the label or summary to seed
          // the keyword filter. Lowercase + strip punctuation. Crude but
          // surprisingly useful — usually catches the first noun.
          const seed = (data.label || data.summary_preview || '')
            .toLowerCase()
            .replace(/[^\p{L}\p{N}\s]/gu, ' ')
            .split(/\s+/)
            .filter(w => w.length >= 4)[0] || ''
          if (seed) setFilterDraft(seed)
        },
      },
      { separator: true },
      { label: t('common.cancel', { defaultValue: 'Cancel' }), action: () => {} },
    ]
    setContextMenu({ x: event.clientX, y: event.clientY, items })
  }, [t, openChunkInChat, navigate])

  // F = fit, Escape = clear selection. Ignored when typing in the filter input.
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement?.tagName === 'INPUT') return
      if (e.key === 'f' || e.key === 'F') {
        graphRef.current?.zoomToFit(300, 30)
      } else if (e.key === 'Escape') {
        handleBackgroundClick()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleBackgroundClick])

  // ── Rendering helpers ──────────────────────────────────────

  // Node size: 4 + min(content_length / 200, 8). Mirrors single-doc's
  // "longer chunks render bigger" — gives a sense of importance at
  // a glance.
  const nodeRadius = useCallback((node) => {
    const len = node.content_length ?? 0
    return 4 + Math.min(len / 200, 8)
  }, [])

  // ── Hover tooltip (HTML) ───────────────────────────────────
  const nodeLabel = useCallback((node) => {
    const filename = docNameById[node.doc_id] || node.doc_id
    const ctype = node.chunk_type || 'text'
    const preview = (node.summary_preview || node.content_preview || '')
      .slice(0, 140)
      .replace(/</g, '&lt;')
    const safeFilename = String(filename).replace(/</g, '&lt;')
    return `
      <div style="
        max-width: 320px; padding: 8px 10px;
        background: var(--bg-1, #0c0c0f); color: var(--fg, #f4f2ee);
        border: 1px solid var(--border-strong, rgba(255,255,255,0.18));
        border-radius: 6px; font-size: 12px; line-height: 1.35;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
      ">
        <div style="font-weight: 600; margin-bottom: 4px;">${safeFilename}</div>
        <div style="opacity: 0.65; margin-bottom: 6px;">chunk #${node.chunk_index} · ${ctype}</div>
        <div style="opacity: 0.85;">${preview || '<em>(no preview)</em>'}</div>
        <div style="margin-top: 6px; opacity: 0.55; font-size: 11px;">click to inspect · double-click → chat</div>
      </div>
    `
  }, [docNameById])

  if (docIds.length === 0) return null

  // Canvas shrinks when NodePanel is open (matches single-doc behaviour).
  const canvasHeight = selectedNode ? Math.max(height - 140, 100) : height

  return (
    <div ref={containerRef} className="relative w-full h-full">
      {/* Filter input — top-left */}
      <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5 rounded-md border px-2 py-1.5"
           style={{
             background: 'var(--bg-1, #0c0c0f)',
             borderColor: 'var(--border, rgba(255,255,255,0.08))',
             minWidth: 220,
           }}>
        <input
          type="text"
          value={filterDraft}
          onChange={e => setFilterDraft(e.target.value)}
          placeholder={t('multiDoc.filterPlaceholder', {
            defaultValue: 'Filter chunks (e.g., "attention")',
          })}
          className="flex-1 bg-transparent text-xs focus:outline-none"
          style={{ color: 'var(--fg, #f4f2ee)' }}
        />
        {filterDraft && (
          <button
            type="button"
            onClick={() => setFilterDraft('')}
            className="opacity-60 hover:opacity-100"
            title={t('multiDoc.filterClear', { defaultValue: 'Clear' })}
            style={{ color: 'var(--fg-dim, #9a9690)' }}
          >
            <X size={12} />
          </button>
        )}
        {matchCount != null && (
          <span className="text-xs whitespace-nowrap"
                style={{ color: 'var(--fg-dim, #9a9690)' }}>
            {t('multiDoc.matchCount', {
              count: matchCount,
              defaultValue: `${matchCount} match${matchCount === 1 ? '' : 'es'}`,
            })}
          </span>
        )}
      </div>

      {isLoading && (
        <div
          className="absolute inset-0 flex items-center justify-center z-20"
          style={{ background: 'rgba(0,0,0,0.05)', color: 'var(--fg-dim)' }}
        >
          {t('multiDoc.loading', {
            count: docIds.length,
            defaultValue: `Loading ${docIds.length} documents…`,
          })}
        </div>
      )}

      {!isLoading && graphData && graphData.nodes.length === 0 && (
        <div
          className="absolute inset-x-0 top-4 mx-auto z-10 max-w-md rounded-md border px-4 py-3 text-sm text-center"
          style={{
            background: 'var(--bg-1)',
            borderColor: 'var(--border)',
            color: 'var(--fg-dim)',
          }}
        >
          {t('multiDoc.empty', {
            defaultValue: 'No chunks found across the selected documents. They may still be processing.',
          })}
        </div>
      )}

      {!isLoading
        && graphData
        && graphData.nodes.length > 0
        && graphData.edges.length === 0
        && !includeIntraDoc && (
        <div
          className="absolute inset-x-0 top-4 mx-auto z-10 max-w-lg rounded-md border px-4 py-3 text-sm text-center"
          style={{
            background: 'var(--bg-1)',
            borderColor: 'var(--border)',
            color: 'var(--fg-dim)',
          }}
        >
          {t('multiDoc.noCrossDocEdges', {
            defaultValue: 'No cross-doc similarities found between these documents. Try toggling "Show intra-doc edges" to see each doc\'s internal structure.',
          })}
        </div>
      )}

      <ForceGraph2D
        ref={graphRef}
        graphData={graphFormatted}
        width={width}
        height={canvasHeight}
        backgroundColor={canvasBg}
        nodeRelSize={5}
        nodeLabel={nodeLabel}
        nodeVal={(node) => {
          // ForceGraph2D uses this for collision sizing. Keep in sync with
          // the per-node radius we draw in nodeCanvasObject.
          const r = nodeRadius(node)
          return (r * r) / 25
        }}
        nodeCanvasObject={(node, ctx, globalScale) => {
          const radius = nodeRadius(node)
          const docColor = docColorMap[node.doc_id] || '#888'

          // Three dimming layers compose multiplicatively:
          //   - active-highlight (hover or pin)
          //   - legend-focus (a doc was selected in the legend)
          //   - keyword-filter (filter input non-empty)
          const inHighlight = !activeNode || highlightNodes.has(node.id)
          const focusDimmed = focusedDocId && node.doc_id !== focusedDocId
          const keywordDimmed = matchingIds && !matchingIds.has(node.id)
          const alpha =
            (inHighlight ? 1 : 0.18) *
            (focusDimmed ? 0.3 : 1) *
            (keywordDimmed ? 0.3 : 1)

          const fill = alpha < 1 ? hexWithAlpha(docColor, alpha) : docColor
          const strokeResolved = cssVar('--bg', '#08080a')

          // Pinned node gets a signature-coloured ring so the user can
          // always find it after clicking.
          const isPinned = pinnedNode?.id === node.id
          const strokeWidth = isPinned ? 2.5 : 1
          const strokeColor = isPinned
            ? cssVar('--signature', '#5b7ec9')
            : strokeResolved

          drawChunkShape(ctx, node, radius, fill, strokeColor, strokeWidth)
        }}
        nodePointerAreaPaint={(node, color, ctx) => {
          drawChunkHitArea(ctx, node, nodeRadius(node) + 2, color)
        }}
        linkColor={l => {
          // Active-highlight wins: dim everything not in the highlight set.
          if (activeNode && !highlightLinks.has(l)) {
            return 'rgba(154,150,144,0.08)'
          }
          // Keyword filter: dim edges where neither endpoint is matching.
          if (matchingIds) {
            const s = typeof l.source === 'object' ? l.source.id : l.source
            const t = typeof l.target === 'object' ? l.target.id : l.target
            if (!matchingIds.has(s) && !matchingIds.has(t)) {
              return 'rgba(154,150,144,0.1)'
            }
          }
          if (l.crossDoc) {
            const fade = focusedDocId
              && l.source.doc_id !== focusedDocId
              && l.target.doc_id !== focusedDocId
            return fade
              ? 'rgba(154,150,144,0.2)'
              : cssVar('--signature', '#5b7ec9')
          }
          return 'rgba(154,150,144,0.4)'
        }}
        linkWidth={l => {
          if (activeNode && highlightLinks.has(l)) return 3
          return l.crossDoc ? 1.5 : 0.5
        }}
        linkLineDash={l => (l.crossDoc ? null : [3, 3])}
        onNodeClick={handleNodeClick}
        onNodeHover={handleNodeHover}
        onNodeRightClick={handleNodeRightClick}
        onBackgroundClick={handleBackgroundClick}
        cooldownTicks={60}
        onEngineStop={() => graphRef.current?.zoomToFit(300, 30)}
        enableNodeDrag={true}
      />

      <MultiDocLegend
        docs={legendDocs}
        focusedDocId={focusedDocId}
        onFocusToggle={handleFocusToggle}
      />

      {palettesLoading && (
        <div
          className="absolute bottom-3 left-3 z-10 rounded-md px-2 py-1 text-xs"
          style={{
            background: 'var(--bg-1)',
            color: 'var(--fg-dim)',
            border: '1px solid var(--border)',
          }}
        >
          {t('multiDoc.paletteLoading', {
            defaultValue: 'Loading doc palettes…',
          })}
        </div>
      )}

      {/* NodePanel — fixed at the bottom inside the relative container.
          The canvas height is shrunk by 140px above to make room. */}
      {selectedNode && (
        <div className="absolute inset-x-0 bottom-0 z-10">
          <MultiDocNodePanel
            node={selectedNode}
            filename={docNameById[selectedNode.doc_id] || selectedNode.doc_id}
            docColor={docColorMap[selectedNode.doc_id] || '#888'}
            onOpenChunk={() => openChunkInChat(selectedNode)}
            onClose={() => {
              setSelectedNode(null)
              setPinnedNode(null)
              setHighlightNodes(new Set())
              setHighlightLinks(new Set())
            }}
          />
        </div>
      )}

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={contextMenu.items}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  )
}

// Hex (#rrggbb) → rgba(r,g,b,a). Used for the dimmed-state fill so focused
// nodes visually pop above the others.
function hexWithAlpha(hex, alpha) {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex || '')
  if (!m) return hex
  const r = parseInt(m[1].slice(0, 2), 16)
  const g = parseInt(m[1].slice(2, 4), 16)
  const b = parseInt(m[1].slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}
