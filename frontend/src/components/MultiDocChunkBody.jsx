import { useMemo, useRef, useEffect, useState, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

import { useMultiDocGraph } from '@/hooks/useMultiDocGraph'
import { buildDocColorMap } from '@/lib/docPalette'
import { drawChunkShape, drawChunkHitArea } from '@/lib/chunkShape'
import { cssVar } from '@/lib/cssVar'
import MultiDocLegend from './MultiDocLegend'

/**
 * The multi-doc chunk graph body. Self-contained: fetches its own data,
 * renders its own ForceGraph2D instance, owns its hover/focus state.
 *
 * Why a separate body component? The single-doc + doc-level views share a
 * mature rendering pipeline in GraphPage (with EDGE_TYPES filter, mindmap
 * mode, click-locked highlight, etc). Multi-doc chunk view has different
 * encoding (shape-by-type instead of colour-by-type) and a different
 * primary task (cross-doc overlap discovery), so isolating it keeps
 * GraphPage from sprawling into a 1000-line god component.
 *
 * Props:
 *   docIds              — string[] of selected document IDs
 *   documents           — full doc registry list (used to look up filenames)
 *   includeIntraDoc     — toggle whether doc-internal edges render
 *   width, height       — canvas size (parent measures the container)
 */
export default function MultiDocChunkBody({
  docIds,
  documents,
  includeIntraDoc = false,
  filter = '',
  onFilterChange,
  width,
  height,
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const graphRef = useRef(null)

  // Local typing state — debounced into the URL via onFilterChange so the
  // address bar doesn't update on every keystroke (which would also retrigger
  // any parent rerenders). 250 ms felt right in the G4 dashboard search.
  const [filterDraft, setFilterDraft] = useState(filter)
  useEffect(() => {
    if (filterDraft === filter) return  // already in sync (URL pushed the change)
    const id = setTimeout(() => {
      onFilterChange?.(filterDraft)
    }, 250)
    return () => clearTimeout(id)
  }, [filterDraft, filter, onFilterChange])
  // Sync the draft when the parent (URL / back button) changes the filter.
  useEffect(() => { setFilterDraft(filter) }, [filter])

  const { graphData, isLoading, paletteByDocId, palettesLoading } = useMultiDocGraph(
    docIds,
    { includeIntraDoc, enabled: docIds.length > 0 },
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

  // Click a legend row to focus that doc (others dim on the canvas).
  const [focusedDocId, setFocusedDocId] = useState(null)
  const handleFocusToggle = useCallback(
    (docId) => setFocusedDocId(prev => (prev === docId ? null : docId)),
    [],
  )

  // Transform backend data → ForceGraph2D shape.
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

  // Filter match set — keys are node ids that match the filter substring.
  // Matching falls back through summary → content preview → label so the
  // user finds chunks by either the LLM-derived summary or the raw text.
  // Empty filter → null (no dimming).
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

  const handleNodeClick = useCallback(
    (node) => {
      // Reuse the existing Open chunk flow but scope to ALL selected docs.
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
    },
    [docIds, navigate],
  )

  // Node sizing: smaller in dense multi-doc views so the canvas isn't a blob.
  const baseRadius = 5

  if (docIds.length === 0) return null

  return (
    <div className="relative w-full h-full">
      {/* Filter input — solves the central use case "are all 3 papers
          talking about X?". Highlights matching chunks; dims the rest.
          Coloured by doc, so the user reads three colours = three papers
          all mention X. Two colours = one paper missed it. */}
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

      {/* Chunks but no edges — the 'these docs are unrelated' moment.
          Only fires when intra-doc is OFF, because turning it on usually
          surfaces structural edges that the cross-doc filter hides. */}
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
        height={height}
        backgroundColor={canvasBg}
        nodeRelSize={baseRadius}
        nodeCanvasObject={(node, ctx, globalScale) => {
          const radius = baseRadius
          const docColor = docColorMap[node.doc_id] || '#888'
          // Three layers of dimming, applied with multiplication so they
          // compose cleanly: focus filter, then keyword filter.
          const focusDimmed = focusedDocId && node.doc_id !== focusedDocId
          const keywordDimmed = matchingIds && !matchingIds.has(node.id)
          const alpha = (focusDimmed ? 0.25 : 1) * (keywordDimmed ? 0.3 : 1)
          const fill = alpha < 1 ? hexWithAlpha(docColor, alpha) : docColor
          // Canvas2D doesn't resolve CSS vars — read once.
          const strokeResolved = cssVar('--bg', '#08080a')
          drawChunkShape(ctx, node, radius, fill, strokeResolved, 1)
        }}
        nodePointerAreaPaint={(node, color, ctx) => {
          drawChunkHitArea(ctx, node, baseRadius + 2, color)
        }}
        linkColor={l => {
          if (l.crossDoc) {
            return focusedDocId &&
              l.source.doc_id !== focusedDocId &&
              l.target.doc_id !== focusedDocId
              ? 'rgba(154,150,144,0.2)'
              : cssVar('--signature', '#5b7ec9')
          }
          return 'rgba(154,150,144,0.4)'
        }}
        linkWidth={l => (l.crossDoc ? 1.5 : 0.5)}
        linkLineDash={l => (l.crossDoc ? null : [3, 3])}
        onNodeClick={handleNodeClick}
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
    </div>
  )
}

// Hex (#rrggbb) → rgba(r,g,b,a). Used for the dimmed-state fill so focused
// docs visually pop above the others.
function hexWithAlpha(hex, alpha) {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex || '')
  if (!m) return hex
  const r = parseInt(m[1].slice(0, 2), 16)
  const g = parseInt(m[1].slice(2, 4), 16)
  const b = parseInt(m[1].slice(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}
