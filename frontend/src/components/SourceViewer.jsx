import { useState, useRef, useEffect, useCallback } from 'react'
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Loader2, FileText } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { Document, Page, pdfjs } from 'react-pdf'
import { TYPE_ICONS } from './SourceItem'

const API_BASE = import.meta.env.VITE_API_URL

const TYPE_BBOX_COLORS = {
  text: '#3b82f6',
  table: '#f59e0b',
  formula: '#a855f7',
  image: '#10b981',
}

export { TYPE_BBOX_COLORS }

export default function SourceViewer({ source, sourceIndex, sources, onBack, onSelectSource }) {
  const { t } = useTranslation()
  const containerRef = useRef(null)
  const [numPages, setNumPages] = useState(null)
  const [currentPage, setCurrentPage] = useState((source.page ?? 0) + 1)
  const [zoom, setZoom] = useState(1.0)
  const [pageSize, setPageSize] = useState(null)
  const [containerWidth, setContainerWidth] = useState(500)

  const isPdf = source.source_file?.toLowerCase().endsWith('.pdf')
  const isImage = source.chunk_type === 'image' && source.image_path
  const pdfUrl = isPdf ? `${API_BASE}/documents/${source.doc_id}/pdf` : null

  // Measure container width
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => setContainerWidth(el.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Jump to source page when source changes
  useEffect(() => {
    setCurrentPage((source.page ?? 0) + 1)
  }, [source])

  // Scroll wheel zoom
  const handleWheel = useCallback((e) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault()
      setZoom(z => Math.min(3, Math.max(0.3, z + (e.deltaY > 0 ? -0.1 : 0.1))))
    }
  }, [])

  // Bbox overlay
  const renderBbox = () => {
    if (!source.bbox || source.bbox.length !== 4 || !pageSize) return null
    if (currentPage !== (source.page ?? 0) + 1) return null
    const [x0, y0, x1, y1] = source.bbox
    const pw = pageSize.originalWidth
    const ph = pageSize.originalHeight
    const color = TYPE_BBOX_COLORS[source.chunk_type] || '#3b82f6'
    return (
      <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
        <div style={{
          position: 'absolute',
          left: `${(x0 / pw) * 100}%`,
          top: `${(y0 / ph) * 100}%`,
          width: `${((x1 - x0) / pw) * 100}%`,
          height: `${((y1 - y0) / ph) * 100}%`,
          border: `3px solid ${color}`,
          backgroundColor: `${color}22`,
          borderRadius: '2px',
        }}>
          <span style={{
            position: 'absolute', top: -18, left: -1,
            backgroundColor: color, color: '#fff',
            fontSize: '10px', padding: '1px 5px', borderRadius: '2px',
          }}>
            [{sourceIndex + 1}]
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header: back + source mini-list + nav */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b shrink-0"
           style={{ borderColor: 'var(--border-strong)' }}>
        <button onClick={onBack}
                className="flex items-center gap-0.5 text-xs opacity-60 hover:opacity-100 shrink-0"
                style={{ color: 'var(--fg)' }}>
          <ChevronLeft size={14} /> {t('sourceViewer.sources')}
        </button>

        <div className="flex-1" />

        {/* Source mini-list */}
        <div className="flex items-center gap-0.5">
          {sources.map((s, i) => {
            const Icon = TYPE_ICONS[s.chunk_type] || FileText
            const isActive = i === sourceIndex
            return (
              <button key={i} onClick={() => onSelectSource(i)}
                      className={cn('p-1 rounded transition-opacity', isActive ? 'opacity-100' : 'opacity-30 hover:opacity-60')}
                      style={{ color: isActive ? TYPE_BBOX_COLORS[s.chunk_type] || '#3b82f6' : 'var(--fg)' }}
                      title={`[${i+1}] ${s.chunk_type}`}>
                <Icon size={12} />
              </button>
            )
          })}
        </div>

        <div className="flex-1" />

        {/* Page nav (PDF only) */}
        {isPdf && numPages && (
          <div className="flex items-center gap-0.5 shrink-0">
            <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage <= 1}
                    className="p-0.5 opacity-40 hover:opacity-100 disabled:opacity-10">
              <ChevronLeft size={12} />
            </button>
            <span className="text-[10px] tabular-nums" style={{ color: 'var(--fg)' }}>
              {currentPage}/{numPages}
            </span>
            <button onClick={() => setCurrentPage(p => Math.min(numPages, p + 1))} disabled={currentPage >= numPages}
                    className="p-0.5 opacity-40 hover:opacity-100 disabled:opacity-10">
              <ChevronRight size={12} />
            </button>
          </div>
        )}

        {/* Zoom */}
        <div className="flex items-center gap-0.5 shrink-0 ml-1">
          <button onClick={() => setZoom(z => Math.max(0.3, z - 0.2))} className="p-0.5 opacity-40 hover:opacity-100">
            <ZoomOut size={12} />
          </button>
          <span className="text-[10px] tabular-nums w-7 text-center" style={{ color: 'var(--fg)' }}>
            {Math.round(zoom * 100)}%
          </span>
          <button onClick={() => setZoom(z => Math.min(3, z + 0.2))} className="p-0.5 opacity-40 hover:opacity-100">
            <ZoomIn size={12} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto" ref={containerRef} onWheel={handleWheel}>
        {isImage ? (
          <div className="flex items-center justify-center p-4 h-full">
            <img src={`${API_BASE}/documents/images/${source.image_path}`}
                 alt={source.content?.slice(0, 50) || t('sourceViewer.image')}
                 className="max-w-full max-h-full object-contain rounded" />
          </div>
        ) : isPdf && pdfUrl ? (
          <div className="flex justify-center py-2">
            <Document file={pdfUrl}
                      onLoadSuccess={(pdf) => setNumPages(pdf.numPages)}
                      loading={<div className="p-8 flex items-center justify-center opacity-40"><Loader2 size={20} className="animate-spin" /></div>}
                      error={<div className="p-8 text-center opacity-40 text-xs">{t('sourceViewer.failedToLoadPdf')}</div>}>
              <Page pageNumber={currentPage}
                    width={containerWidth * zoom * 0.95}
                    renderTextLayer={true}
                    renderAnnotationLayer={false}
                    onLoadSuccess={(info) => setPageSize(info)}
                    loading="">
                {renderBbox()}
              </Page>
            </Document>
          </div>
        ) : (
          <div className="p-4 text-sm leading-relaxed" style={{ color: 'var(--fg)' }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {source.content || t('sourceViewer.noContent')}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  )
}
