import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import {
  ChevronLeft, ChevronRight, Search, X, ZoomIn, ZoomOut,
  Download, FileText, Table2, Image, Calculator
} from 'lucide-react'
import { fetchDocumentChunks, fetchDocuments } from '@/lib/api'
import { cn } from '@/lib/utils'
import DocxViewer from '@/components/DocxViewer'

pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

const API_BASE = import.meta.env.VITE_API_URL
const USER_ID = 'admin'
const TYPE_ICONS = { text: FileText, table: Table2, image: Image, formula: Calculator }
const TYPE_COLORS = { text: '#3b82f6', table: '#f59e0b', formula: '#a855f7', image: '#10b981' }

export default function PdfViewerPage() {
  const { docId } = useParams()
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [numPages, setNumPages] = useState(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [zoom, setZoom] = useState(1.0)
  const [containerWidth, setContainerWidth] = useState(800)
  const [activeChunk, setActiveChunk] = useState(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [pageSize, setPageSize] = useState(null)
  const containerRef = useRef(null)

  const pdfUrl = useMemo(() => `${API_BASE}/documents/${docId}/pdf`, [docId])

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

  // Fetch document metadata for file_type routing
  const { data: documentsData } = useQuery({
    queryKey: ['documents', USER_ID],
    queryFn: () => fetchDocuments(USER_ID),
    staleTime: 5 * 60_000,
  })
  const docList = documentsData?.documents || (Array.isArray(documentsData) ? documentsData : [])
  const currentDoc = docList.find(d => d.doc_id === docId)
  const fileType = (currentDoc?.file_type || '').toLowerCase().replace('.', '')

  const [searchParams] = useSearchParams()
  const urlChunkRaw = searchParams.get('chunk')
  const urlChunkId = urlChunkRaw != null ? Number(urlChunkRaw) : null

  // Fetch chunks for current page (visual chunks only + active text)
  const { data: chunksData } = useQuery({
    queryKey: ['chunks', docId, currentPage - 1],
    queryFn: () => fetchDocumentChunks(docId, currentPage - 1, USER_ID),
    enabled: !!docId,
  })

  const pageChunks = useMemo(() => {
    if (!chunksData?.chunks) return []
    const visual = chunksData.chunks.filter(c => ['table', 'image', 'formula'].includes(c.chunk_type))
    const text = chunksData.chunks.filter(c => c.chunk_type === 'text').slice(0, 3)
    return [...visual, ...text]
  }, [chunksData])

  const handleDocLoad = useCallback((pdf) => {
    setNumPages(pdf.numPages)
  }, [])

  // Bbox overlay for active chunk
  const renderBbox = () => {
    if (!activeChunk?.bbox || !pageSize) return null
    const [x0, y0, x1, y1] = activeChunk.bbox
    const pw = pageSize.originalWidth
    const ph = pageSize.originalHeight
    const color = TYPE_COLORS[activeChunk.chunk_type] || TYPE_COLORS.text

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
        }} />
      </div>
    )
  }

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement?.tagName === 'INPUT') return
      if (e.key === 'ArrowLeft') setCurrentPage(p => Math.max(1, p - 1))
      if (e.key === 'ArrowRight' && numPages) setCurrentPage(p => Math.min(numPages, p + 1))
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') { e.preventDefault(); setSearchOpen(true) }
      if (e.key === 'Escape') { setSearchOpen(false); setActiveChunk(null) }
      if (e.key === '+' || e.key === '=') setZoom(z => Math.min(3, z + 0.1))
      if (e.key === '-') setZoom(z => Math.max(0.3, z - 0.1))
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [numPages])

  if (!docId) {
    return (
      <div className="flex items-center justify-center h-full opacity-40">
        <div className="text-center">
          <FileText size={48} className="mx-auto mb-4" />
          <p>{t('pdfViewer.selectFromDashboard')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b"
           style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--bg)' }}>
        <button onClick={() => navigate('/')} className="text-xs opacity-40 hover:opacity-100 mr-2">
          <ChevronLeft size={16} />
        </button>

        <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage <= 1}
                className="p-1 opacity-60 hover:opacity-100 disabled:opacity-20">
          <ChevronLeft size={16} />
        </button>
        <span className="text-xs tabular-nums" style={{ color: 'var(--fg)' }}>
          {currentPage} / {numPages || '?'}
        </span>
        <button onClick={() => numPages && setCurrentPage(p => Math.min(numPages, p + 1))} disabled={currentPage >= numPages}
                className="p-1 opacity-60 hover:opacity-100 disabled:opacity-20">
          <ChevronRight size={16} />
        </button>

        <span className="opacity-20 mx-1">|</span>

        <button onClick={() => setZoom(z => Math.max(0.3, z - 0.1))} className="p-1 opacity-60 hover:opacity-100">
          <ZoomOut size={14} />
        </button>
        <span className="text-xs tabular-nums w-10 text-center" style={{ color: 'var(--fg)' }}>
          {Math.round(zoom * 100)}%
        </span>
        <button onClick={() => setZoom(z => Math.min(3, z + 0.1))} className="p-1 opacity-60 hover:opacity-100">
          <ZoomIn size={14} />
        </button>

        <span className="opacity-20 mx-1">|</span>

        <button onClick={() => setSearchOpen(!searchOpen)} className="p-1 opacity-60 hover:opacity-100">
          <Search size={14} />
        </button>

        <div className="flex-1" />

        <button onClick={() => window.open(`${API_BASE}/documents/${docId}/download`, '_blank')}
                className="p-1 opacity-60 hover:opacity-100">
          <Download size={14} />
        </button>
      </div>

      {/* Search bar */}
      {searchOpen && (
        <div className="flex items-center gap-2 px-3 py-1.5 border-b"
             style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--bg-1)' }}>
          <Search size={12} className="opacity-40" />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder={t('pdfViewer.searchPlaceholder')}
            autoFocus
            className="flex-1 text-xs bg-transparent outline-none"
            style={{ color: 'var(--fg)' }}
          />
          <button onClick={() => { setSearchOpen(false); setSearchQuery('') }} className="opacity-40 hover:opacity-100">
            <X size={12} />
          </button>
        </div>
      )}

      {/* Content area */}
      {fileType === 'pdf' && (
        <div className="flex flex-1 overflow-hidden">
          {/* PDF */}
          <div className="flex-1 overflow-auto" ref={containerRef}>
            <div className="flex justify-center py-4">
              <Document
                file={pdfUrl}
                onLoadSuccess={handleDocLoad}
                loading={<div className="p-8 opacity-40">{t('pdfViewer.loadingPdf')}</div>}
                error={<div className="p-8 opacity-40">{t('pdfViewer.failedToLoadPdf')}</div>}
              >
                <Page
                  pageNumber={currentPage}
                  width={containerWidth * zoom * 0.9}
                  renderTextLayer={true}
                  renderAnnotationLayer={false}
                  onLoadSuccess={(info) => setPageSize(info)}
                  loading=""
                >
                  {renderBbox()}
                </Page>
              </Document>
            </div>
          </div>

          {/* Page chunks sidebar */}
          <div className="w-64 border-l overflow-auto shrink-0"
               style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--bg)' }}>
            <div className="px-3 py-2 border-b text-xs font-medium uppercase tracking-wider opacity-40"
                 style={{ borderColor: 'var(--border-strong)' }}>
              {t('pdfViewer.pageChunks', { count: pageChunks.length })}
            </div>
            {pageChunks.length === 0 ? (
              <div className="p-4 text-xs opacity-30 text-center">{t('pdfViewer.noChunks')}</div>
            ) : (
              <div className="py-1">
                {pageChunks.map((chunk, i) => {
                  const Icon = TYPE_ICONS[chunk.chunk_type] || FileText
                  const color = TYPE_COLORS[chunk.chunk_type] || TYPE_COLORS.text
                  const isActive = activeChunk?.chunk_index === chunk.chunk_index
                  const label = chunk.label || (chunk.content?.slice(0, 40) + '...')

                  return (
                    <button
                      key={chunk.chunk_index ?? i}
                      onClick={() => setActiveChunk(isActive ? null : chunk)}
                      className={cn(
                        'flex items-start gap-2 w-full px-3 py-2 text-left text-xs transition-colors',
                        isActive ? 'bg-white/10' : 'hover:bg-white/5'
                      )}
                    >
                      <Icon size={12} className="mt-0.5 shrink-0" style={{ color }} />
                      <div className="min-w-0">
                        <div className="truncate font-medium" style={{ color: 'var(--fg)' }}>
                          {label}
                        </div>
                        <span className="opacity-40">{chunk.chunk_type}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {fileType === 'docx' && (
        <DocxViewer docId={docId} activeChunkIndex={urlChunkId} />
      )}

      {fileType && fileType !== 'pdf' && fileType !== 'docx' && (
        <div className="flex items-center justify-center h-full opacity-40">
          <div className="text-center text-sm">
            <p>{t('pdfViewer.unsupportedFileType', { defaultValue: 'This file type is not supported for in-browser viewing.' })}</p>
            <p className="text-xs mt-2 opacity-60">{fileType}</p>
          </div>
        </div>
      )}
    </div>
  )
}
