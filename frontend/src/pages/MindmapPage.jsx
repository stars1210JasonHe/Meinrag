import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft } from 'lucide-react'
import { useMindmap } from '@/hooks/useMindmap'
import MindmapGraph from '@/components/MindmapGraph'
import MindmapLegend from '@/components/MindmapLegend'
import MindmapNodePanel from '@/components/MindmapNodePanel'

const DEFAULT_EDGE_TYPES = new Set(['follows', 'describes', 'references'])

export default function MindmapPage() {
  const { docId } = useParams()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { data, isLoading, error } = useMindmap(docId)

  const [selectedNode, setSelectedNode] = useState(null)
  const [enabledEdgeTypes, setEnabledEdgeTypes] = useState(
    new Set(DEFAULT_EDGE_TYPES),
  )

  if (isLoading) {
    return (
      <div className="p-8" style={{ color: 'var(--fg-dim, #9a9690)' }}>
        {t('mindmap.loading')}
      </div>
    )
  }
  if (error) {
    return (
      <div className="p-8" style={{ color: '#ef4444' }}>
        {t('mindmap.error')}
      </div>
    )
  }
  if (!data) return null

  const visibleEdges = (data.edges || []).filter(e => enabledEdgeTypes.has(e.relation))

  const toggleEdgeType = (type) => {
    setEnabledEdgeTypes(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const openInPdf = () => {
    if (!selectedNode) return
    const params = new URLSearchParams()
    if (selectedNode.page != null) params.set('page', selectedNode.page)
    params.set('chunk', selectedNode.chunk_index)
    navigate(`/pdf/${docId}?${params.toString()}`)
  }

  return (
    <div className="flex h-full" style={{ backgroundColor: 'var(--bg, #08080a)' }}>
      <div className="flex-1 flex flex-col min-w-0">
        <header
          className="p-4 border-b flex items-center gap-4 shrink-0"
          style={{
            borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
            backgroundColor: 'var(--bg-1, #0c0c0f)',
          }}
        >
          <button
            onClick={() => navigate(-1)}
            aria-label={t('mindmap.back')}
            className="opacity-60 hover:opacity-100"
            style={{ color: 'var(--fg, #f4f2ee)' }}
          >
            <ArrowLeft size={18} />
          </button>
          <div className="min-w-0">
            <h1
              className="text-base font-semibold truncate"
              style={{ color: 'var(--fg, #f4f2ee)' }}
            >
              {data.filename}
            </h1>
            {data.doc_summary && (
              <p
                className="text-xs truncate"
                style={{ color: 'var(--fg-dim, #9a9690)' }}
              >
                {data.doc_summary}
              </p>
            )}
          </div>
        </header>

        <main className="flex-1 relative" style={{ backgroundColor: 'var(--bg, #08080a)' }}>
          {(!data.nodes || data.nodes.length === 0) ? (
            <div
              className="p-8 text-center"
              style={{ color: 'var(--fg-dim, #9a9690)' }}
            >
              {t('mindmap.empty')}
            </div>
          ) : (
            <MindmapGraph
              nodes={data.nodes}
              edges={visibleEdges}
              onNodeClick={setSelectedNode}
              selectedId={selectedNode?.id}
            />
          )}
        </main>
      </div>

      <aside
        className="w-80 border-l overflow-y-auto shrink-0"
        style={{
          borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
          backgroundColor: 'var(--bg-1, #0c0c0f)',
        }}
      >
        <MindmapLegend
          stats={data.stats}
          enabledEdgeTypes={enabledEdgeTypes}
          onToggleEdgeType={toggleEdgeType}
        />
        {selectedNode && (
          <MindmapNodePanel
            node={selectedNode}
            onOpenInPdf={openInPdf}
            onClose={() => setSelectedNode(null)}
          />
        )}
      </aside>
    </div>
  )
}
