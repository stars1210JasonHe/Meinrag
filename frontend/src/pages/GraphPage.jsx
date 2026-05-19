import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import ForceGraph2D from 'react-force-graph-2d'
import { FileText, Table2, Image, Calculator, ExternalLink, MessageSquare, X, Network, GitBranch, Boxes, Plus, Minus } from 'lucide-react'
import { fetchGraphDocuments, fetchGraphNodes, fetchDocuments, fetchTaxonomy, fetchDocumentChunks } from '@/lib/api'
import DocCombobox from '@/components/DocCombobox'
import { cn } from '@/lib/utils'
import ContextMenu from '@/components/ContextMenu'
import MindmapTree from '@/components/MindmapTree'
import MultiDocChunkBody from '@/components/MultiDocChunkBody'
import MultiDocMindmapTree from '@/components/MultiDocMindmapTree'
import SelectionActionBar from '@/components/SelectionActionBar'
import SaveCollectionDialog from '@/components/SaveCollectionDialog'
import { useSelection } from '@/hooks/useSelection'
import { useDocMindmap } from '@/hooks/useDocMindmap'
import { useMultiDocMindmap } from '@/hooks/useMultiDocMindmap'

const USER_ID = 'admin'

const NODE_COLORS = {
  text: cssVar('--signature',  '#6b8fd6'),
  table: cssVar('--warn',      '#f59e0b'),
  formula: cssVar('--collection', '#d4a64a'),
  image: cssVar('--ok',        '#10b981'),
  document: cssVar('--signature-dim', '#4a6cb4'),
}

const EDGE_TYPES = ['follows', 'co_located', 'describes', 'references', 'similar_to']
// Edge colors derived from tokens. similar_to uses fg-faint to read as
// "inferred" (the deck's §B.3 recommendation); explicit edges use signature.
const EDGE_COLORS = {
  follows: cssVar('--fg-dim',      '#9a9690'),  // sequential
  co_located: cssVar('--signature','#6b8fd6'),  // same page
  describes: cssVar('--ok',        '#10b981'),  // text explains visual
  references: cssVar('--warn',     '#f59e0b'),  // cross-reference
  similar_to: cssVar('--fg-faint', 'rgba(154,150,144,0.6)'),  // inferred — soft
}
const TYPE_ICONS = { text: FileText, table: Table2, image: Image, formula: Calculator }

// Reads a CSS custom property off the root so the force-graph canvas can track theme
function cssVar(name, fallback = '#08080a') {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  } catch {
    return fallback
  }
}

// Convert a hex color (#rrggbb / #rgb) or rgba()/rgb() string to rgba(...) with the given alpha.
// Used to modulate similar_to edge opacity by mean_score so stronger relationships read denser.
function applyAlpha(color, alpha) {
  const a = Math.max(0, Math.min(1, alpha))
  if (!color) return `rgba(154,150,144,${a})`
  const hex = color.match(/^#([0-9a-f]{3,8})$/i)
  if (hex) {
    let h = hex[1]
    if (h.length === 3) h = h.split('').map(c => c + c).join('')
    if (h.length === 8) h = h.slice(0, 6)
    const r = parseInt(h.slice(0, 2), 16)
    const g = parseInt(h.slice(2, 4), 16)
    const b = parseInt(h.slice(4, 6), 16)
    return `rgba(${r},${g},${b},${a})`
  }
  const rgb = color.match(/rgba?\(\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)/i)
  if (rgb) return `rgba(${rgb[1]},${rgb[2]},${rgb[3]},${a})`
  return color
}

// Map mean_score in [min_score, 1.0] to a visible opacity range. The floor
// is set high enough that even weak relationships stay legible in light mode
// where the base colour (--fg-faint) is already a soft beige.
function meanScoreToAlpha(meanScore) {
  if (meanScore == null) return 0.7
  const lo = 0.7
  const t = Math.max(0, Math.min(1, (meanScore - lo) / (1.0 - lo)))
  return 0.55 + t * 0.45  // 0.55 at lo, 1.0 at 1.0
}

// supporting_pairs: 1 → thinnest, 6+ → thickest. Below 1 (chunk-level edges
// without aggregation) falls back to the relation default so per-chunk views
// keep their look.
function supportingPairsToWidth(pairs) {
  if (pairs == null) return null
  return 1 + Math.min(pairs, 6) * 0.5
}

// Doc-level similar_to edges are rendered as three discrete tiers — eye is
// far more sensitive to colour + dash transitions than to opacity gradients,
// so tiered styling reads way clearer than the old "all faint dashed" look.
// Pre-2026-05-11 every cross-doc edge looked identical in both themes.
//
//   strong  (mean_score >= 0.9)  → signature blue, solid, thick
//   medium  (0.8-0.9)            → muted blue,     solid, medium
//   weak    (0.7-0.8 / unknown)  → faint gray,     dashed, thin
function edgeStrengthTier(meanScore) {
  if (meanScore == null) return 'weak'
  if (meanScore >= 0.9) return 'strong'
  if (meanScore >= 0.8) return 'medium'
  return 'weak'
}

function similarToTieredColor(tier) {
  if (tier === 'strong') return cssVar('--signature', '#5b7ec9')
  if (tier === 'medium') return cssVar('--signature-dim', '#4a6cb4')
  return cssVar('--fg-faint', 'rgba(154,150,144,0.6)')
}

function similarToTieredWidth(tier, supportingPairs) {
  // supporting_pairs still adds a small width bump within each tier so a
  // 10-pair "strong" edge reads heavier than a 2-pair one.
  const pairsBump = supportingPairs != null
    ? Math.min(supportingPairs, 6) * 0.25
    : 0
  if (tier === 'strong') return 3 + pairsBump
  if (tier === 'medium') return 2 + pairsBump
  return 1 + pairsBump
}

// Build the chat URL for "Open chunk" — single-button replacement for the old
// (Open in PDF / Ask about this) pair. The `suggest` param is rendered as a
// ghost-text the user can dismiss; `chunk` triggers PDF jump + bbox highlight.
function buildOpenChunkHref(nodeData) {
  const docId = nodeData.doc_id
  const name = nodeData.source_file || ''
  const chunkIdx = nodeData.chunk_index
  const label = nodeData.label || nodeData.content_preview?.slice(0, 40) || ''
  const ct = nodeData.chunk_type
  const suggestion = ct === 'image' ? `What does ${label || 'this figure'} show?`
    : ct === 'table' ? `Explain the data in ${label || 'this table'}`
    : ct === 'formula' ? `Explain ${label || 'this equation'}`
    : label ? `Tell me about: ${label}` : ''
  const params = [`doc=${encodeURIComponent(docId)}`, `name=${encodeURIComponent(name)}`]
  if (chunkIdx != null) params.push(`chunk=${chunkIdx}`)
  if (suggestion) params.push(`suggest=${encodeURIComponent(suggestion)}`)
  return `/chat?${params.join('&')}`
}

export default function GraphPage() {
  const { docId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const multiDocsParam = searchParams.get('docs')
  const multiDocIds = useMemo(
    () => (multiDocsParam ? multiDocsParam.split(',').filter(Boolean) : null),
    [multiDocsParam]
  )
  const mode = searchParams.get('mode') === 'mindmap' ? 'mindmap' : 'graph'
  const urlChunk = searchParams.get('chunk')
  const urlChunkId = urlChunk != null ? Number(urlChunk) : null

  // 'view' is only meaningful in multi-doc mode. 'chunk' renders the new
  // chunk-level view (MultiDocChunkBody); 'doc' (default) keeps the legacy
  // doc-level filtered view that was already shipping pre-2026-05-11.
  const view = (multiDocIds && searchParams.get('view') === 'chunk') ? 'chunk' : 'doc'
  // 'intra' toggles whether the chunk view shows doc-internal edges in
  // addition to cross-doc similar_to. Persisted in the URL so deep links
  // and back-button preserve the toggle state.
  const includeIntraDoc = searchParams.get('intra') === '1'
  // 'filter' is the keyword the user typed to narrow visible chunks. Kept
  // in the URL so demos / shared links restore exactly what the sender saw.
  const urlFilter = searchParams.get('filter') || ''

  const setMode = useCallback((next) => {
    setSearchParams(prev => {
      const params = new URLSearchParams(prev)
      if (next === 'graph') params.delete('mode')
      else params.set('mode', next)
      return params
    })
  }, [setSearchParams])

  const setView = useCallback((next) => {
    setSearchParams(prev => {
      const params = new URLSearchParams(prev)
      if (next === 'doc') params.delete('view')
      else params.set('view', next)
      return params
    })
  }, [setSearchParams])

  const setIncludeIntraDoc = useCallback((next) => {
    setSearchParams(prev => {
      const params = new URLSearchParams(prev)
      if (next) params.set('intra', '1')
      else params.delete('intra')
      return params
    })
  }, [setSearchParams])

  const setUrlFilter = useCallback((next) => {
    setSearchParams(prev => {
      const params = new URLSearchParams(prev)
      if (next) params.set('filter', next)
      else params.delete('filter')
      return params
    }, { replace: true })  // typing shouldn't pollute browser history
  }, [setSearchParams])

  const navigate = useNavigate()
  // Edge UX detail: arriving with a single-element ?docs=A pre-selection
  // is functionally the same as /graph/A — bounce to the single-doc URL
  // so all the single-doc-specific behaviour (mindmap toggle, edge filter)
  // is enabled.
  useEffect(() => {
    if (multiDocIds && multiDocIds.length === 1) {
      navigate(`/graph/${multiDocIds[0]}`, { replace: true })
    }
  }, [multiDocIds, navigate])
  const { t } = useTranslation()
  const graphRef = useRef(null)
  const containerRef = useRef(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [hoverNode, setHoverNode] = useState(null)
  const [pinnedNode, setPinnedNode] = useState(null)  // click-locked highlight
  const [highlightNodes, setHighlightNodes] = useState(new Set())
  const [highlightLinks, setHighlightLinks] = useState(new Set())
  const clickTimerRef = useRef(null)
  const [nodeFilter, setNodeFilter] = useState({ text: true, table: true, formula: true, image: true })
  const [edgeFilter, setEdgeFilter] = useState({
    follows: true,
    describes: true,
    references: true,
    similar_to: false,
    co_located: false,
  })
  const [scope, setScope] = useState(docId || '')
  const [scopeType, setScopeType] = useState(
    multiDocIds ? 'docs' : (docId ? 'doc' : 'all')
  ) // 'all' | 'collection' | 'doc' | 'docs'
  const [scopeLabel, setScopeLabel] = useState('')

  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })
  // Track theme so the force-graph canvas background re-renders on toggle
  const [themeTick, setThemeTick] = useState(0)
  useEffect(() => {
    const obs = new MutationObserver(() => setThemeTick(t => t + 1))
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => obs.disconnect()
  }, [])
  const canvasBg = useMemo(() => cssVar('--bg', '#08080a'), [themeTick])
  const [contextMenu, setContextMenu] = useState(null) // {x, y, items}

  const { data: documents = [] } = useQuery({
    queryKey: ['documents', USER_ID],
    queryFn: () => fetchDocuments(USER_ID),
  })

  // Sync scope state when the URL :docId changes — e.g. when the user
  // clicks a document node in the all-docs view and we navigate(/graph/<id>).
  // Without this, scope stayed at its initial value and the graph query
  // never re-fetched. `documents` is in the deps so the breadcrumb filename
  // fills in once documents finish loading. Must run after the useQuery
  // above so `documents` isn't in TDZ when read here.
  useEffect(() => {
    if (docId) {
      setScope(docId)
      setScopeType('doc')
      const doc = (Array.isArray(documents?.documents) ? documents.documents
        : Array.isArray(documents) ? documents : []).find(d => d.doc_id === docId)
      setScopeLabel(doc?.filename || docId)
    } else if (multiDocIds) {
      setScopeType('docs')
      setScope('')
    } else {
      setScope('')
      setScopeType('all')
      setScopeLabel('')
    }
  }, [docId, multiDocsParam, documents])

  const { data: taxonomyData } = useQuery({
    queryKey: ['taxonomy', USER_ID],
    queryFn: () => fetchTaxonomy(USER_ID),
  })

  const activeEdgeTypes = EDGE_TYPES.filter(t => edgeFilter[t]).join(',')

  const { data: graphData, isLoading } = useQuery({
    queryKey: ['graph', scope, activeEdgeTypes],
    queryFn: () =>
      scope
        ? fetchGraphNodes(scope, activeEdgeTypes || 'follows', USER_ID)
        : fetchGraphDocuments(USER_ID),
  })

  // Mindmap tree — only fetched when mode is 'mindmap'
  const {
    data: mindmapData,
    isLoading: mindmapLoading,
    error: mindmapError,
  } = useDocMindmap(docId, { enabled: mode === 'mindmap' && Boolean(docId) })

  // Multi-doc mindmap — only fetched when in mindmap mode AND 2+ docs.
  // First call per doc-set is slow (LLM); cache makes subsequent instant.
  const isMultiDocMindmap = mode === 'mindmap' && !docId
    && Array.isArray(multiDocIds) && multiDocIds.length >= 2
  const {
    data: multiMindmapData,
    isLoading: multiMindmapLoading,
    error: multiMindmapError,
  } = useMultiDocMindmap(multiDocIds, { enabled: isMultiDocMindmap })

  // All chunks for this doc — needed so a leaf-click can resolve chunk_index
  // to the full chunk shape the existing NodePanel expects.
  const { data: allChunksData } = useQuery({
    queryKey: ['doc-chunks-all', docId],
    queryFn: () => fetchDocumentChunks(docId, null, USER_ID),
    enabled: mode === 'mindmap' && Boolean(docId),
    staleTime: 5 * 60_000,
  })

  const chunkByIndex = useMemo(() => {
    const map = new Map()
    for (const c of (allChunksData?.chunks || [])) {
      if (c.chunk_index != null) map.set(c.chunk_index, c)
    }
    return map
  }, [allChunksData])

  // Measure container size
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => setDimensions({ width: el.clientWidth, height: el.clientHeight })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const docList = documents?.documents || (Array.isArray(documents) ? documents : [])
  const collections = taxonomyData?.user_collections || []

  // Group documents by collection for the dropdown
  const docsByCollection = useMemo(() => {
    const groups = {}
    for (const d of (Array.isArray(docList) ? docList : [])) {
      for (const c of (d.collections || [])) {
        if (!groups[c]) groups[c] = []
        if (!groups[c].find(x => x.doc_id === d.doc_id)) groups[c].push(d)
      }
    }
    return groups
  }, [docList])

  // Multi-select state — same global hook the Dashboard uses, so picks
  // here carry over to /chat or back to /dashboard via localStorage.
  const selection = useSelection()
  const queryClient = useQueryClient()
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)

  const selectedDocIds = useMemo(
    () => selection.expandedDocIds(docsByCollection),
    [selection, docsByCollection],
  )

  const handleSelectionAsk = useCallback(() => {
    if (selectedDocIds.length === 0) return
    navigate(`/chat?doc_ids=${selectedDocIds.join(',')}`)
  }, [selectedDocIds, navigate])

  const handleSelectionVisualize = useCallback(() => {
    if (selectedDocIds.length === 0) return
    navigate(`/graph?docs=${selectedDocIds.join(',')}`)
  }, [selectedDocIds, navigate])

  const handleSelectionSave = useCallback(() => {
    if (selectedDocIds.length < 2) return
    setSaveDialogOpen(true)
  }, [selectedDocIds])

  const handleSavedSuccess = useCallback((name) => {
    setSaveDialogOpen(false)
    selection.clear()
    toast.success(t('selection.saveSuccess', {
      name, defaultValue: `Saved collection "${name}"`,
    }))
    queryClient.invalidateQueries({ queryKey: ['taxonomy', USER_ID] })
    queryClient.invalidateQueries({ queryKey: ['documents', USER_ID] })
  }, [selection, queryClient, t])

  // For collection / multi-doc scope, filter document-level graph to matching docs
  const filteredGraphData = useMemo(() => {
    if (!graphData) return graphData
    let allowedIds = null
    if (scopeType === 'collection') {
      const colDocs = docsByCollection[scopeLabel] || []
      allowedIds = new Set(colDocs.map(d => d.doc_id))
    } else if (scopeType === 'docs' && multiDocIds) {
      allowedIds = new Set(multiDocIds)
    }
    if (!allowedIds) return graphData
    return {
      nodes: (graphData.nodes || []).filter(n => allowedIds.has(n.doc_id)),
      edges: (graphData.edges || []).filter(e =>
        allowedIds.has(e.source_doc_id) && allowedIds.has(e.target_doc_id)
      ),
    }
  }, [graphData, scopeType, scopeLabel, docsByCollection, multiDocIds])

  // Transform backend data to react-force-graph format
  const graphFormatted = useMemo(() => {
    const data = (scopeType === 'collection' || scopeType === 'docs') ? filteredGraphData : graphData
    if (!data) return { nodes: [], links: [] }

    const nodes = (data.nodes || [])
      .filter(n => n.node_type === 'document' || nodeFilter[n.chunk_type] !== false)
      .map(n => ({
        id: n.node_type === 'document' ? `doc:${n.doc_id}` : `${n.doc_id}:${n.chunk_index}`,
        label: n.label || n.summary_preview?.slice(0, 40) || n.content_preview?.slice(0, 25) || n.source_file?.slice(0, 25) || '?',
        color: NODE_COLORS[n.chunk_type] || NODE_COLORS.document,
        _data: n,
      }))

    const nodeIds = new Set(nodes.map(n => n.id))

    const links = (data.edges || [])
      .map(e => ({
        source: e.source_chunk_index != null ? `${e.source_doc_id}:${e.source_chunk_index}` : `doc:${e.source_doc_id}`,
        target: e.target_chunk_index != null ? `${e.target_doc_id}:${e.target_chunk_index}` : `doc:${e.target_doc_id}`,
        relation: e.relation,
        color: '#334155',
        // Doc-level aggregation: only present on /graph/documents responses.
        supporting_pairs: e.supporting_pairs ?? null,
        mean_score: e.mean_score ?? null,
      }))
      .filter(l => nodeIds.has(l.source) && nodeIds.has(l.target))

    // Compute connection count for node sizing
    const connCount = {}
    for (const l of links) {
      connCount[l.source] = (connCount[l.source] || 0) + 1
      connCount[l.target] = (connCount[l.target] || 0) + 1
    }
    const maxConn = Math.max(1, ...Object.values(connCount))

    // Deep copy + add computed size
    return {
      nodes: nodes.map(n => ({
        ...n,
        val: n._data?.node_type === 'document' ? 8 : 1 + (connCount[n.id] || 0) / maxConn * 5,
      })),
      links: links.map(l => ({ ...l })),
    }
  }, [graphData, filteredGraphData, scopeType, nodeFilter])

  const computeNeighbors = useCallback((node) => {
    const neighbors = new Set([node.id])
    const links = new Set()
    for (const l of graphFormatted.links) {
      const srcId = typeof l.source === 'object' ? l.source.id : l.source
      const tgtId = typeof l.target === 'object' ? l.target.id : l.target
      if (srcId === node.id) { neighbors.add(tgtId); links.add(l) }
      if (tgtId === node.id) { neighbors.add(srcId); links.add(l) }
    }
    return { neighbors, links }
  }, [graphFormatted.links])

  const handleNodeClick = useCallback((node, event) => {
    // Document node: with shift/ctrl/meta held, toggle the doc in the
    // global selection instead of drilling in. Plain click stays as the
    // primary drill-in action so muscle memory isn't broken.
    if (node._data?.node_type === 'document') {
      const isModifierClick = !!(event && (event.shiftKey || event.ctrlKey || event.metaKey))
      if (isModifierClick) {
        selection.toggleDoc(node._data.doc_id)
        return
      }
      clearTimeout(clickTimerRef.current)
      setSelectedNode(null)
      setPinnedNode(null)
      setHighlightNodes(new Set())
      setHighlightLinks(new Set())
      navigate(`/graph/${node._data.doc_id}`)
      return
    }

    // Chunk node: if already pinned on this node, check for double-click
    if (pinnedNode?.id === node.id) {
      // Second click on pinned node — is it double-click or unpin?
      if (clickTimerRef.current) {
        // Double-click: navigate to chat
        clearTimeout(clickTimerRef.current)
        clickTimerRef.current = null
        if (node._data?.doc_id) {
          navigate(buildOpenChunkHref(node._data))
        }
      } else {
        // Single click on pinned node: unpin after delay (to allow double-click)
        clickTimerRef.current = setTimeout(() => {
          clickTimerRef.current = null
          setPinnedNode(null)
          setSelectedNode(null)
          setHighlightNodes(new Set())
          setHighlightLinks(new Set())
        }, 400)
      }
    } else {
      // Click new node: pin it immediately
      clearTimeout(clickTimerRef.current)
      clickTimerRef.current = setTimeout(() => { clickTimerRef.current = null }, 400)
      setSelectedNode(node._data)
      setPinnedNode(node)
      const { neighbors, links } = computeNeighbors(node)
      setHighlightNodes(neighbors)
      setHighlightLinks(links)
    }
  }, [graphFormatted.links, pinnedNode, navigate, computeNeighbors, selection.docs])

  const handleBackgroundClick = useCallback(() => {
    setSelectedNode(null)
    setHoverNode(null)
    setPinnedNode(null)
    setHighlightNodes(new Set())
    setHighlightLinks(new Set())
    setContextMenu(null)
  }, [])

  const handleNodeRightClick = useCallback((node, event) => {
    event.preventDefault()

    const items = []

    if (node._data?.node_type === 'document') {
      const docId = node._data.doc_id
      const isSelected = selection.hasDoc(docId)
      items.push(
        isSelected
          ? { label: t('graph.removeFromSelection', { defaultValue: 'Remove from selection' }),
              icon: Minus, action: () => selection.toggleDoc(docId) }
          : { label: t('graph.addToSelection', { defaultValue: 'Add to selection' }),
              icon: Plus, action: () => selection.toggleDoc(docId) },
        { label: t('graph.exploreChunks'), icon: Network, action: () => navigate(`/graph/${docId}`) },
        { label: t('graph.viewAsMindmap', { defaultValue: 'View as Mind Map' }), icon: GitBranch, action: () => navigate(`/graph/${docId}?mode=mindmap`) },
        { label: t('dashboard.chatAboutThis'), icon: MessageSquare, action: () => navigate(`/chat?doc=${docId}&name=${encodeURIComponent(node._data.source_file || '')}`) },
        { label: t('dashboard.openInPdf'), icon: ExternalLink, action: () => navigate(`/pdf/${docId}`) },
      )
    } else {
      items.push(
        { label: t('dashboard.chatAboutThis'), icon: MessageSquare, action: () => navigate(`/chat?doc=${node._data.doc_id}&name=${encodeURIComponent(node._data.source_file || '')}`) },
        { label: t('dashboard.openInPdf'), icon: ExternalLink, action: () => navigate(`/pdf/${node._data.doc_id}`) },
        { label: t('graph.viewNeighbors'), icon: Network, action: () => { handleNodeClick(node) } },
      )
    }

    items.push({ separator: true })
    items.push({ label: t('common.cancel'), action: () => {} })

    setContextMenu({ x: event.clientX, y: event.clientY, items })
  }, [navigate, handleNodeClick, selection.docs, t])

  const handleNodeHover = useCallback((node) => {
    setHoverNode(node || null)
    // Don't override highlights if a node is pinned
    if (pinnedNode) return
    if (node) {
      const { neighbors, links } = computeNeighbors(node)
      setHighlightNodes(neighbors)
      setHighlightLinks(links)
    } else {
      setHighlightNodes(new Set())
      setHighlightLinks(new Set())
    }
  }, [pinnedNode, computeNeighbors])

  // Custom node rendering with hover/pin glow
  const activeNode = pinnedNode || hoverNode
  const paintNode = useCallback((node, ctx) => {
    const r = Math.sqrt(node.val || 4) * 2
    const isHighlighted = !activeNode || highlightNodes.has(node.id)
    const opacity = isHighlighted ? 1.0 : 0.15

    ctx.globalAlpha = opacity

    // Glow for active (hovered or pinned) node
    if (activeNode?.id === node.id) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, r + 3, 0, Math.PI * 2)
      ctx.fillStyle = node.color + '44'
      ctx.fill()
    }

    // Node shape
    if (node._data?.node_type === 'document') {
      // Paper with folded top-right corner
      const w = r * 2, h = r * 2.4
      const fold = r * 0.6
      const x = node.x, y = node.y
      ctx.beginPath()
      ctx.moveTo(x - w/2, y - h/2)
      ctx.lineTo(x + w/2 - fold, y - h/2)
      ctx.lineTo(x + w/2, y - h/2 + fold)
      ctx.lineTo(x + w/2, y + h/2)
      ctx.lineTo(x - w/2, y + h/2)
      ctx.closePath()
      ctx.fillStyle = node.color || '#6366f1'
      ctx.fill()
      // Folded corner triangle — darker inner shade
      ctx.beginPath()
      ctx.moveTo(x + w/2 - fold, y - h/2)
      ctx.lineTo(x + w/2 - fold, y - h/2 + fold)
      ctx.lineTo(x + w/2, y - h/2 + fold)
      ctx.closePath()
      ctx.fillStyle = '#4f52c5'
      ctx.fill()
      // Multi-select ring — signature-blue stroke around the paper if
      // this doc is in the global selection.
      if (selection.hasDoc(node._data.doc_id)) {
        ctx.beginPath()
        ctx.moveTo(x - w/2, y - h/2)
        ctx.lineTo(x + w/2 - fold, y - h/2)
        ctx.lineTo(x + w/2, y - h/2 + fold)
        ctx.lineTo(x + w/2, y + h/2)
        ctx.lineTo(x - w/2, y + h/2)
        ctx.closePath()
        ctx.strokeStyle = cssVar('--signature', '#5b7ec9')
        ctx.lineWidth = 2
        ctx.stroke()
      }
    } else {
      ctx.beginPath()
      ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
      ctx.fillStyle = node.color || '#6366f1'
      ctx.fill()
    }

    // Border ring for selected
    if (selectedNode && node._data?.chunk_index === selectedNode.chunk_index && node._data?.doc_id === selectedNode.doc_id) {
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 1
      ctx.stroke()
    }

    // Label: show for active node, its neighbors, documents, or when nothing is active
    if (activeNode?.id === node.id || (activeNode && highlightNodes.has(node.id)) || node._data?.node_type === 'document' || !activeNode) {
      ctx.font = `${Math.max(3, r * 0.8)}px sans-serif`
      // Theme-aware label color: fg-1 / fg-dim from CSS vars, with dark fallbacks.
      ctx.fillStyle = isHighlighted
        ? cssVar('--fg-1', '#e2e8f0')
        : cssVar('--fg-dim', '#64748b')
      ctx.textAlign = 'center'
      const label = node.label?.length > 20 ? node.label.slice(0, 18) + '..' : node.label
      ctx.fillText(label || '', node.x, node.y + r + 4)
    }

    ctx.globalAlpha = 1.0
  }, [activeNode, highlightNodes, selectedNode, selection.docs])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement?.tagName === 'INPUT') return
      if (e.key === 'f' || e.key === 'F') {
        graphRef.current?.zoomToFit(300)
      }
      if (e.key === 'Escape') {
        setSelectedNode(null)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // (docList and collections moved up before filteredGraphData)

  const handleScopeChange = (value) => {
    setSelectedNode(null)
    if (!value) {
      setScope(''); setScopeType('all'); setScopeLabel('')
      // If we arrived here via a URL like /graph/<docId>, state alone
      // isn't enough — the URL needs to clear too, otherwise refreshing
      // or sharing the link snaps back to the per-doc view.
      if (docId || multiDocsParam) {
        navigate('/graph')
      }
    } else if (value.startsWith('col:')) {
      const col = value.slice(4)
      setScopeType('collection'); setScopeLabel(col); setScope('')
      if (docId || multiDocsParam) navigate('/graph')
    } else {
      const doc = docList.find(d => d.doc_id === value)
      setScopeType('doc'); setScopeLabel(doc?.filename || value); setScope(value)
      if (value !== docId) navigate(`/graph/${value}`)
    }
  }

  return (
    <div className="flex flex-col h-full" style={{ backgroundColor: 'var(--bg, #08080a)' }}>
      {/* Breadcrumb */}
      {(scopeType !== 'all') && (
        <div className="flex items-center gap-1 px-4 py-1.5 text-xs border-b"
             style={{ borderColor: 'var(--border, rgba(255,255,255,0.08))', color: 'var(--fg-dim, #9a9690)' }}>
          <button onClick={() => handleScopeChange('')} className="hover:underline opacity-60 hover:opacity-100">
            {t('graph.allDocuments')}
          </button>
          <span className="opacity-30">→</span>
          {scopeType === 'collection' && (
            <span style={{ color: 'var(--fg, #f4f2ee)' }}>{scopeLabel}</span>
          )}
          {scopeType === 'doc' && (
            <span style={{ color: 'var(--fg, #f4f2ee)' }}>{scopeLabel}</span>
          )}
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center gap-3 px-4 py-2 border-b flex-wrap"
           style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))', backgroundColor: 'var(--bg-1, #0c0c0f)' }}>
        {/* Mode toggle */}
        <div
          role="tablist"
          aria-label={t('graph.modeToggleAria')}
          className="flex items-center border rounded-md overflow-hidden text-xs"
          style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
        >
          <button
            role="tab"
            aria-selected={mode === 'graph'}
            onClick={() => setMode('graph')}
            className={cn(
              'flex items-center gap-1 px-2.5 py-1 transition-colors',
              mode === 'graph' ? 'bg-white/10' : 'opacity-60 hover:opacity-100',
            )}
            style={{ color: 'var(--fg, #f4f2ee)' }}
          >
            <Network size={12} />
            {t('graph.modeGraph')}
          </button>
          <button
            role="tab"
            aria-selected={mode === 'mindmap'}
            onClick={() => setMode('mindmap')}
            className={cn(
              'flex items-center gap-1 px-2.5 py-1 transition-colors',
              mode === 'mindmap' ? 'bg-white/10' : 'opacity-60 hover:opacity-100',
            )}
            style={{ color: 'var(--fg, #f4f2ee)' }}
            disabled={!docId && !(multiDocIds && multiDocIds.length >= 2)}
            title={!docId && !(multiDocIds && multiDocIds.length >= 2)
              ? t('graph.modeMindmapNeedsDoc')
              : ''}
          >
            <GitBranch size={12} />
            {t('graph.modeMindmap')}
          </button>
        </div>

        {/* Multi-doc view toggle: only when 2+ docs are selected. Switches
            between the legacy doc-level filtered view and the new chunk-
            level cross-doc view. */}
        {multiDocIds && multiDocIds.length >= 2 && (
          <div
            role="tablist"
            aria-label={t('graph.viewToggleAria', { defaultValue: 'Multi-doc view' })}
            className="flex items-center border rounded-md overflow-hidden text-xs"
            style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
          >
            <button
              role="tab"
              aria-selected={view === 'doc'}
              onClick={() => setView('doc')}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 transition-colors',
                view === 'doc' ? 'bg-white/10' : 'opacity-60 hover:opacity-100',
              )}
              style={{ color: 'var(--fg, #f4f2ee)' }}
            >
              <Network size={12} />
              {t('graph.viewDoc', { defaultValue: 'Doc' })}
            </button>
            <button
              role="tab"
              aria-selected={view === 'chunk'}
              onClick={() => setView('chunk')}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 transition-colors',
                view === 'chunk' ? 'bg-white/10' : 'opacity-60 hover:opacity-100',
              )}
              style={{ color: 'var(--fg, #f4f2ee)' }}
            >
              <Boxes size={12} />
              {t('graph.viewChunk', { defaultValue: 'Chunk' })}
            </button>
          </div>
        )}

        {/* Intra-doc edge toggle — only meaningful in chunk view, where it
            additionally renders the 4 doc-internal edge types alongside the
            default cross-doc similar_to edges. */}
        {view === 'chunk' && multiDocIds && multiDocIds.length >= 2 && (
          <label
            className="flex items-center gap-1.5 text-xs cursor-pointer select-none px-2 py-1 rounded-md border"
            style={{
              borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
              color: 'var(--fg, #f4f2ee)',
            }}
            title={t('graph.intraDocToggleHelp', {
              defaultValue: 'Also show edges within each document (follows, references, …)',
            })}
          >
            <input
              type="checkbox"
              checked={includeIntraDoc}
              onChange={(e) => setIncludeIntraDoc(e.target.checked)}
              className="cursor-pointer"
            />
            {t('graph.intraDocToggleLabel', { defaultValue: 'Show intra-doc edges' })}
          </label>
        )}

        <span className="opacity-30 text-xs">|</span>

        {Object.entries(NODE_COLORS).filter(([k]) => k !== 'document').map(([type, color]) => (
          <button
            key={type}
            onClick={() => setNodeFilter(f => ({ ...f, [type]: !f[type] }))}
            className={cn('flex items-center gap-1 text-xs transition-opacity',
              nodeFilter[type] ? 'opacity-100' : 'opacity-30'
            )}
            style={{ color: 'var(--fg, #f4f2ee)' }}
          >
            <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            {t(`nodeType.${type}`)}
          </button>
        ))}

        <span className="opacity-20" style={{ color: 'var(--fg, #f4f2ee)' }}>|</span>

        {EDGE_TYPES.map(type => {
          // In multi-doc chunk view, the 4 intra-doc edge types only have
          // data when the user has explicitly opted into intra-doc edges
          // (the parent toggle). Visually disable the chips otherwise so
          // it's obvious why clicking them does nothing.
          const multiDocChunkView = view === 'chunk' && multiDocIds && multiDocIds.length >= 2
          const isIntraOnlyType = type !== 'similar_to'
          const disabled = multiDocChunkView && isIntraOnlyType && !includeIntraDoc
          return (
            <button
              key={type}
              onClick={() => {
                if (disabled) return
                setEdgeFilter(f => ({ ...f, [type]: !f[type] }))
              }}
              disabled={disabled}
              title={disabled
                ? t('graph.intraEdgeDisabledHint', {
                    defaultValue: 'Enable "Show intra-doc edges" first',
                  })
                : undefined}
              className={cn(
                'flex items-center gap-1 text-xs px-1.5 py-0.5 rounded transition-opacity',
                disabled
                  ? 'opacity-25 cursor-not-allowed'
                  : edgeFilter[type] ? 'opacity-100' : 'opacity-30',
              )}
              style={{
                backgroundColor: edgeFilter[type] && !disabled
                  ? 'var(--border-strong, rgba(255,255,255,0.14))'
                  : 'transparent',
                color: 'var(--fg, #f4f2ee)',
              }}
            >
              <span className="w-3 h-0.5 inline-block rounded" style={{ backgroundColor: EDGE_COLORS[type] }} />
              {t(`edgeType.${type}`)}
            </button>
          )
        })}

        <span className="opacity-20" style={{ color: 'var(--fg, #f4f2ee)' }}>|</span>

        <DocCombobox
          value={scopeType === 'collection' ? `col:${scopeLabel}` : scope}
          onChange={handleScopeChange}
          collections={collections}
          userId={USER_ID}
          currentLabel={
            scope && scopeType !== 'collection'
              ? (Array.isArray(docList) ? docList : []).find(d => d.doc_id === scope)?.filename
              : null
          }
          labels={{
            allLabel: t('graph.allDocuments'),
            collections: t('graph.collections'),
            documents: t('graph.documents'),
            placeholder: t('graph.searchDocsPlaceholder', { defaultValue: 'Search documents…' }),
            recent: t('graph.recentDocs', { defaultValue: 'Recent' }),
            noResults: t('graph.noResults', { defaultValue: 'No matches' }),
          }}
        />

        {scopeType !== 'all' && (
          <button onClick={() => handleScopeChange('')}
                  className="text-xs opacity-40 hover:opacity-100" style={{ color: 'var(--fg, #f4f2ee)' }}>
            <X size={12} />
          </button>
        )}
      </div>

      {/* Graph canvas */}
      <div className="flex-1 relative" ref={containerRef}>
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center z-10 opacity-40"
               style={{ color: 'var(--fg, #f4f2ee)' }}>
            {t('graph.loadingGraph')}
          </div>
        )}
        {/* Multi-doc chunk view — drives off the URL ?view=chunk param,
            uses its own data fetch + renderer. Skipping the parent
            ForceGraph2D entirely is intentional: the legacy doc-level
            view has very different visual semantics (colour-by-edge-type,
            EDGE_TYPES filter) and bolting both onto one canvas got
            unreadable in the design discussion. */}
        {mode === 'graph' && view === 'chunk' && multiDocIds && multiDocIds.length >= 2 && (
          <MultiDocChunkBody
            docIds={multiDocIds}
            documents={docList}
            includeIntraDoc={includeIntraDoc}
            edgeTypes={(() => {
              // In multi-doc chunk view, the active edge types are:
              //   - always similar_to if its chip is on
              //   - the 4 intra-doc types only if intra-doc is enabled
              // This matches what the chip-disable rule lets the user
              // toggle, and saves a wasted backend round-trip.
              const types = EDGE_TYPES.filter(t => {
                if (!edgeFilter[t]) return false
                if (t === 'similar_to') return true
                return includeIntraDoc
              })
              return types.length ? types.join(',') : 'similar_to'
            })()}
            filter={urlFilter}
            onFilterChange={setUrlFilter}
            width={dimensions.width}
            height={dimensions.height}
          />
        )}
        {mode === 'graph' && view === 'doc' && graphFormatted.nodes.length > 0 && (
          <ForceGraph2D
            ref={graphRef}
            graphData={graphFormatted}
            width={dimensions.width}
            height={dimensions.height - (selectedNode ? 140 : 0)}
            backgroundColor={canvasBg}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(node, color, ctx) => {
              const r = (node.size || 4) + 2
              ctx.beginPath()
              ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
              ctx.fillStyle = color
              ctx.fill()
            }}
            onNodeClick={handleNodeClick}
            onNodeHover={handleNodeHover}
            onBackgroundClick={handleBackgroundClick}
            onNodeRightClick={handleNodeRightClick}
            linkColor={l => {
              if (activeNode && !highlightLinks.has(l)) return '#1e293b'
              // Doc-level similar_to edges get tiered colour: signature for
              // strong (mean_score >= 0.9), signature-dim for medium, faint
              // for weak. Makes "which pairs are most similar" jump out
              // instead of all reading as the same dashed line.
              if (l.relation === 'similar_to' && l.mean_score != null) {
                return similarToTieredColor(edgeStrengthTier(l.mean_score))
              }
              return EDGE_COLORS[l.relation] || '#64748b'
            }}
            linkWidth={l => {
              if (activeNode && highlightLinks.has(l)) return 3
              // Doc-level similar_to: tiered width (strong > medium > weak)
              // with a small per-pair bump within tier.
              if (l.relation === 'similar_to' && l.mean_score != null) {
                return similarToTieredWidth(
                  edgeStrengthTier(l.mean_score),
                  l.supporting_pairs,
                )
              }
              // Chunk-level: fall back to the existing supporting_pairs
              // scaler for backward compat.
              const w = supportingPairsToWidth(l.supporting_pairs)
              if (w != null) return w
              return l.relation === 'follows' ? 0.5 : 1.5
            }}
            linkLineDash={l => {
              // Dash ONLY weak similar_to edges so they read as "tentative"
              // while strong + medium are confidently solid. Other relations
              // are always solid.
              if (l.relation !== 'similar_to') return null
              return edgeStrengthTier(l.mean_score) === 'weak' ? [4, 4] : null
            }}
            linkDirectionalArrowLength={l => l.relation === 'follows' ? 3 : 0}
            linkDirectionalArrowRelPos={1}
            cooldownTicks={30}
            onEngineStop={() => graphRef.current?.zoomToFit(300, 20)}
            enableNodeDrag={true}
          />
        )}
        {mode === 'mindmap' && docId && (
          <MindmapModeBody
            tree={mindmapData?.tree}
            loading={mindmapLoading}
            error={mindmapError}
            urlChunkId={urlChunkId}
            onLeafClick={(leafNode) => {
              const firstChunk = leafNode.__chunk_indices?.[0]
              if (firstChunk == null) return
              const chunk = chunkByIndex.get(firstChunk)
              if (!chunk) return
              setSelectedNode({
                id: `${docId}:${firstChunk}`,
                chunk_index: firstChunk,
                chunk_type: chunk.chunk_type,
                doc_id: docId,
                label: chunk.label || leafNode.name,
                source_file: chunk.source_file,
                content_preview: chunk.content_preview ?? chunk.content?.slice(0, 400),
                summary_preview: chunk.summary_preview,
                page: chunk.page,
              })
              setSearchParams(prev => {
                const p = new URLSearchParams(prev)
                p.set('chunk', String(firstChunk))
                return p
              })
            }}
            onFallbackToGraph={() => setMode('graph')}
          />
        )}
        {mode === 'graph' && !isLoading && graphFormatted.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center opacity-40"
               style={{ color: 'var(--fg, #f4f2ee)' }}>
            {t('graph.noGraphData')}
          </div>
        )}
        {/* Multi-doc mindmap — synthesised tree across the selected
            docs. Inherits the same renderer skeleton as single-doc but
            paints coverage colour blocks on each leaf. */}
        {isMultiDocMindmap && (() => {
          const tree = multiMindmapData?.tree
          if (multiMindmapLoading) {
            return (
              <div className="mm-skeleton">
                <div className="text-sm">
                  {t('multiDoc.mindmapLoading', {
                    count: multiDocIds.length,
                    defaultValue: `Synthesizing tree across ${multiDocIds.length} documents… (first time, 15–30 s)`,
                  })}
                </div>
                <div className="mm-skeleton-lines" />
                <div className="mm-skeleton-lines" />
                <div className="mm-skeleton-lines" />
              </div>
            )
          }
          if (multiMindmapError) {
            return (
              <div className="mm-skeleton" role="alert">
                <div className="text-sm">{t('graph.mindmapErrorTitle')}</div>
                <div className="text-xs opacity-70">{t('graph.mindmapErrorBody')}</div>
                <button onClick={() => setMode('graph')}
                        className="text-xs underline hover:opacity-80"
                        style={{ color: 'var(--signature, #5b7ec9)' }}>
                  {t('graph.mindmapErrorFallback')}
                </button>
              </div>
            )
          }
          if (!tree || (tree.branches?.length || 0) === 0) {
            return (
              <div className="mm-skeleton">
                <div className="text-sm">{t('multiDoc.mindmapEmpty', {
                  defaultValue: 'Couldn\'t synthesise a tree for this set. The documents may not share enough common ground.',
                })}</div>
              </div>
            )
          }
          // Inject filename lookup so leaf tooltips can show "Covered by:
          // filename_A, filename_B" instead of opaque doc_ids.
          const nameByDocId = Object.fromEntries(
            (docList || []).map(d => [d.doc_id, d.filename]),
          )
          const treeWithNames = { ...tree, __nameByDocId: nameByDocId }
          return (
            <MultiDocMindmapTree
              tree={treeWithNames}
              onLeafClick={(leafNode) => {
                const chunksByDoc = leafNode.__chunks_by_doc || {}
                const coverage = Object.keys(chunksByDoc)
                if (coverage.length === 0) return
                // Scope chat to all docs covering this leaf.
                const params = new URLSearchParams({
                  doc_ids: coverage.join(','),
                  suggest: `Tell me about: ${leafNode.name}`,
                })
                navigate(`/chat?${params.toString()}`)
              }}
            />
          )
        })()}

        {/* Legacy: mindmap mode but no doc + no multi-doc context */}
        {mode === 'mindmap' && !docId && !isMultiDocMindmap && (
          <div className="absolute inset-0 flex items-center justify-center opacity-40"
               style={{ color: 'var(--fg, #f4f2ee)' }}>
            {t('graph.modeMindmapNeedsDoc')}
          </div>
        )}
      </div>

      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={contextMenu.items}
          onClose={() => setContextMenu(null)}
        />
      )}

      {/* Node preview panel */}
      {selectedNode && (
        <div className="border-t px-4 py-3" style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))', backgroundColor: 'var(--bg-1, #0c0c0f)' }}>
          <div className="flex items-start justify-between mb-2">
            <div className="flex items-center gap-2">
              {(() => {
                const Icon = TYPE_ICONS[selectedNode.chunk_type] || FileText
                return <Icon size={16} style={{ color: NODE_COLORS[selectedNode.chunk_type] }} />
              })()}
              <span className="text-sm font-medium" style={{ color: 'var(--fg, #f4f2ee)' }}>
                {selectedNode.label || selectedNode.chunk_type} · {selectedNode.source_file}
              </span>
            </div>
            <button onClick={() => setSelectedNode(null)} className="opacity-40 hover:opacity-100"
                    style={{ color: 'var(--fg, #f4f2ee)' }}>
              <X size={14} />
            </button>
          </div>
          {selectedNode.summary_preview && (
            <p className="text-xs mb-2 leading-relaxed italic" style={{ color: 'var(--fg-1, #d4d0ca)' }}>
              {selectedNode.summary_preview}
            </p>
          )}
          <p className="text-xs mb-3 leading-relaxed" style={{ color: 'var(--fg-dim, #9a9690)' }}>
            {selectedNode.content_preview}
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate(buildOpenChunkHref(selectedNode))}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs"
              style={{ backgroundColor: 'var(--border-strong, rgba(255,255,255,0.14))', color: 'var(--fg, #f4f2ee)' }}
            >
              <ExternalLink size={12} /> {t('graph.openChunk')}
            </button>
            {selectedNode.page != null && (
              <span className="text-xs opacity-40" style={{ color: 'var(--fg, #f4f2ee)' }}>
                {t('graph.page', { num: selectedNode.page + 1 })}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Multi-select action bar — same global selection state Dashboard uses */}
      <SelectionActionBar
        documents={docList}
        onAsk={handleSelectionAsk}
        onVisualize={handleSelectionVisualize}
        onSave={handleSelectionSave}
      />
      <SaveCollectionDialog
        open={saveDialogOpen}
        count={selectedDocIds.length}
        docIds={selectedDocIds}
        onClose={() => setSaveDialogOpen(false)}
        onSaved={handleSavedSuccess}
      />
    </div>
  )
}

function MindmapModeBody({ tree, loading, error, urlChunkId, onLeafClick, onFallbackToGraph }) {
  const { t } = useTranslation()

  if (loading) {
    return (
      <div className="mm-skeleton">
        <div className="text-sm">{t('graph.mindmapLoading')}</div>
        <div className="mm-skeleton-lines" />
        <div className="mm-skeleton-lines" />
        <div className="mm-skeleton-lines" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="mm-skeleton" role="alert">
        <div className="text-sm">{t('graph.mindmapErrorTitle')}</div>
        <div className="text-xs opacity-70">{t('graph.mindmapErrorBody')}</div>
        <button
          onClick={onFallbackToGraph}
          className="text-xs underline hover:opacity-80"
          style={{ color: 'var(--signature, #5b7ec9)' }}
        >
          {t('graph.mindmapErrorFallback')}
        </button>
      </div>
    )
  }

  if (!tree || !Array.isArray(tree.branches) || tree.branches.length === 0) {
    return (
      <div className="mm-skeleton">
        <div className="text-sm">{t('graph.mindmapEmpty')}</div>
      </div>
    )
  }

  return (
    <MindmapTree
      tree={tree}
      selectedChunkIds={urlChunkId != null ? [urlChunkId] : []}
      onLeafClick={onLeafClick}
    />
  )
}
