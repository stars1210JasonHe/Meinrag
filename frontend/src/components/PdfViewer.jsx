import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import { API_BASE } from '../api/client'

// Worker — must match react-pdf's bundled pdfjs-dist version (not top-level)
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// Build text highlight fragments from chunk text
function buildFragments(text) {
  const normalized = text.replace(/\s+/g, ' ').trim().toLowerCase()
  if (normalized.length < 10) return []
  const fragments = []
  for (let i = 0; i < normalized.length; i += 40) {
    const frag = normalized.slice(i, i + 60).trim()
    if (frag.length >= 15) fragments.push(frag)
  }
  return fragments
}

// Target height for PDF page rendering
const PAGE_HEIGHT = Math.round(window.innerHeight * 0.82)

/**
 * In-browser PDF viewer using react-pdf.
 * Text selection, page navigation, bbox + text highlighting.
 */
export default function PdfViewer({ docId, page, bbox, chunkText, zoom, pan, dragging, onClick, onError }) {
  const [numPages, setNumPages] = useState(null)
  const [currentPage, setCurrentPage] = useState((page || 0) + 1) // react-pdf is 1-indexed
  const [pageSize, setPageSize] = useState(null)
  const pageInputTimer = useRef(null)

  const pdfUrl = useMemo(() => `${API_BASE}/documents/${docId}/pdf`, [docId])
  const initialPage = (page || 0) + 1
  const isSourcePage = currentPage === initialPage
  const isZoomed = zoom > 1

  // Reset page when docId changes
  useEffect(() => {
    setCurrentPage((page || 0) + 1)
  }, [docId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Custom text renderer for yellow highlights (only on source page, only when no bbox)
  const textRenderer = useMemo(() => {
    if (!isSourcePage || !chunkText || (bbox && bbox.length === 4)) return undefined
    const fragments = buildFragments(chunkText)
    if (fragments.length === 0) return undefined

    return ({ str }) => {
      const norm = str.replace(/\s+/g, ' ').trim().toLowerCase()
      if (norm.length < 4) return escapeHtml(str)
      const matched = fragments.some(f => f.includes(norm))
      return matched ? `<mark>${escapeHtml(str)}</mark>` : escapeHtml(str)
    }
  }, [isSourcePage, chunkText, bbox])

  // Bbox overlay as percentage-positioned div
  const renderBboxOverlay = () => {
    if (!isSourcePage || !bbox || bbox.length !== 4 || !pageSize) return null
    const [x0, y0, x1, y1] = bbox
    const pw = pageSize.originalWidth
    const ph = pageSize.originalHeight
    return (
      <div className="pdf-highlight-overlay">
        <div className="pdf-highlight-bbox" style={{
          left: `${(x0 / pw) * 100}%`,
          top: `${(y0 / ph) * 100}%`,
          width: `${((x1 - x0) / pw) * 100}%`,
          height: `${((y1 - y0) / ph) * 100}%`,
        }} />
      </div>
    )
  }

  const goToPrev = useCallback(() => {
    setCurrentPage(p => Math.max(1, p - 1))
  }, [])

  const goToNext = useCallback(() => {
    if (numPages == null) return
    setCurrentPage(p => Math.min(numPages, p + 1))
  }, [numPages])

  const goToPage = useCallback((p) => {
    if (numPages == null) return
    setCurrentPage(Math.max(1, Math.min(numPages, p)))
  }, [numPages])

  // PageUp/PageDown — only when no input focused
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement?.tagName === 'INPUT') return
      if (e.key === 'PageUp') { e.preventDefault(); goToPrev() }
      else if (e.key === 'PageDown') { e.preventDefault(); goToNext() }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [goToPrev, goToNext])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => clearTimeout(pageInputTimer.current)
  }, [])

  const handlePageInput = useCallback((e) => {
    const v = parseInt(e.target.value, 10)
    if (isNaN(v)) return
    clearTimeout(pageInputTimer.current)
    pageInputTimer.current = setTimeout(() => goToPage(v), 300)
  }, [goToPage])

  return (
    <div className="pdf-viewer-wrapper" onClick={onClick}>
      <div
        className="pdf-viewer-canvas-container"
        style={{
          transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
          cursor: isZoomed ? (dragging ? 'grabbing' : 'grab') : 'default',
        }}
      >
        <Document
          file={pdfUrl}
          onLoadSuccess={({ numPages: n }) => setNumPages(n)}
          onLoadError={(err) => { console.error('[PdfViewer] load error:', err); onError?.() }}
          loading={<div className="pdf-viewer-loading">Loading PDF...</div>}
          error={<div className="pdf-viewer-error">Failed to load PDF</div>}
        >
          <Page
            pageNumber={currentPage}
            height={PAGE_HEIGHT}
            renderTextLayer={true}
            renderAnnotationLayer={false}
            customTextRenderer={textRenderer}
            onLoadSuccess={(pageInfo) => setPageSize(pageInfo)}
            loading=""
          >
            {renderBboxOverlay()}
          </Page>
        </Document>
      </div>

      {numPages && numPages > 1 && (
        <div className="pdf-viewer-page-nav" onClick={e => e.stopPropagation()}>
          <button onClick={goToPrev} disabled={currentPage <= 1} title="Previous page (PageUp)">
            <ChevronLeft size={16} />
          </button>
          <span className="pdf-viewer-page-info">
            <input
              type="number"
              min={1}
              max={numPages}
              defaultValue={currentPage}
              key={currentPage}
              onBlur={handlePageInput}
              onKeyDown={e => { if (e.key === 'Enter') handlePageInput(e) }}
              className="pdf-viewer-page-input"
            />
            <span>/ {numPages}</span>
          </span>
          <button onClick={goToNext} disabled={currentPage >= numPages} title="Next page (PageDown)">
            <ChevronRight size={16} />
          </button>
          {currentPage !== initialPage && (
            <button
              onClick={() => goToPage(initialPage)}
              className="pdf-viewer-goto-source"
              title={`Jump to source (page ${initialPage})`}
            >
              Go to source
            </button>
          )}
        </div>
      )}
    </div>
  )
}
