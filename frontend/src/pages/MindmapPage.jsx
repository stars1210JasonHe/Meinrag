import { useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Brain, Network } from 'lucide-react'
import { useMindmap } from '@/hooks/useMindmap'
import { useDocGraph } from '@/hooks/useDocGraph'
import MindmapTree from '@/components/MindmapTree'
import MindmapGraph from '@/components/MindmapGraph'
import MindmapLegend from '@/components/MindmapLegend'
import MindmapNodePanel from '@/components/MindmapNodePanel'

const DEFAULT_EDGE_TYPES = new Set(['follows', 'describes', 'references'])

function ModeToggle({ mode, setMode, t }) {
  const btnCls = (active) =>
    `px-3 py-1.5 text-sm flex items-center gap-2 transition ${
      active
        ? 'bg-[var(--border-strong)] text-[var(--fg)]'
        : 'opacity-70 hover:opacity-100'
    }`
  return (
    <div className="inline-flex rounded overflow-hidden border border-[var(--border-strong)]">
      <button
        type="button"
        className={btnCls(mode === 'tree')}
        onClick={() => setMode('tree')}
      >
        <Brain className="h-4 w-4" />
        {t('mindmap.modeTree')}
      </button>
      <button
        type="button"
        className={btnCls(mode === 'graph')}
        onClick={() => setMode('graph')}
      >
        <Network className="h-4 w-4" />
        {t('mindmap.modeGraph')}
      </button>
    </div>
  )
}

export default function MindmapPage() {
  const { docId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const mode = searchParams.get('mode') === 'graph' ? 'graph' : 'tree'
  const setMode = (m) => {
    setSearchParams(p => {
      const np = new URLSearchParams(p)
      np.set('mode', m)
      return np
    })
  }

  const navigate = useNavigate()
  const { t } = useTranslation()

  const treeQuery = useMindmap(mode === 'tree' ? docId : null)
  const graphQuery = useDocGraph(mode === 'graph' ? docId : null)

  const active = mode === 'tree' ? treeQuery : graphQuery
  const { data, isLoading, error } = active

  const [selectedNode, setSelectedNode] = useState(null)
  const [selectedLeaf, setSelectedLeaf] = useState(null)
  const [enabledEdgeTypes, setEnabledEdgeTypes] = useState(
    new Set(DEFAULT_EDGE_TYPES),
  )

  const toggleEdgeType = (type) => {
    setEnabledEdgeTypes(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const openInPdf = () => {
    const target = selectedNode
    if (!target) return
    const params = new URLSearchParams()
    if (target.page != null) params.set('page', target.page)
    params.set('chunk', target.chunk_index)
    navigate(`/pdf/${docId}?${params.toString()}`)
  }

  const openChunkInPdf = (chunkIndex) => {
    const params = new URLSearchParams()
    params.set('chunk', chunkIndex)
    navigate(`/pdf/${docId}?${params.toString()}`)
  }

  const onTreeLeafClick = (leaf) => {
    setSelectedLeaf(leaf)
    setSelectedNode(null)
  }

  const onGraphNodeClick = (node) => {
    setSelectedNode(node)
    setSelectedLeaf(null)
  }

  let content
  if (isLoading) {
    content = <div className="p-8 opacity-70">{t('mindmap.loading')}</div>
  } else if (error) {
    content = <div className="p-8 text-red-400">{t('mindmap.error')}</div>
  } else if (!data) {
    content = null
  } else if (mode === 'tree') {
    if (!data.tree || !data.tree.branches || data.tree.branches.length === 0) {
      content = <div className="p-8 opacity-70 text-center">{t('mindmap.emptyTree')}</div>
    } else {
      content = (
        <div className="h-full">
          <MindmapTree tree={data.tree} onLeafClick={onTreeLeafClick} />
        </div>
      )
    }
  } else {
    if (!data.nodes || data.nodes.length === 0) {
      content = <div className="p-8 opacity-70 text-center">{t('mindmap.empty')}</div>
    } else {
      const visibleEdges = (data.edges || []).filter(
        e => enabledEdgeTypes.has(e.relation),
      )
      content = (
        <MindmapGraph
          nodes={data.nodes}
          edges={visibleEdges}
          onNodeClick={onGraphNodeClick}
          selectedId={selectedNode?.id}
        />
      )
    }
  }

  const filename = data?.filename || ''
  const docSummary = mode === 'tree' ? data?.tree?.central : data?.doc_summary

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col min-w-0">
        <header className="p-4 border-b border-[var(--border-strong)] flex items-center gap-4">
          <button
            type="button"
            onClick={() => navigate(-1)}
            aria-label={t('mindmap.back')}
            className="p-2 rounded hover:bg-[var(--border-strong)] transition"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-semibold truncate">{filename}</h1>
            {docSummary && (
              <p className="text-sm opacity-70 line-clamp-1">{docSummary}</p>
            )}
          </div>
          <ModeToggle mode={mode} setMode={setMode} t={t} />
        </header>

        <main className="flex-1 relative">{content}</main>
      </div>

      <aside className="w-80 border-l border-[var(--border-strong)] overflow-y-auto">
        {mode === 'graph' && data?.stats && (
          <MindmapLegend
            stats={data.stats}
            enabledEdgeTypes={enabledEdgeTypes}
            onToggleEdgeType={toggleEdgeType}
          />
        )}
        {mode === 'graph' && selectedNode && (
          <MindmapNodePanel
            node={selectedNode}
            onOpenInPdf={openInPdf}
            onClose={() => setSelectedNode(null)}
          />
        )}
        {mode === 'tree' && selectedLeaf && (
          <MindmapNodePanel
            leaf={selectedLeaf}
            onOpenChunk={openChunkInPdf}
            onClose={() => setSelectedLeaf(null)}
          />
        )}
      </aside>
    </div>
  )
}
