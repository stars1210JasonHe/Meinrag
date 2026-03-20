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

const HIGHLIGHT_COLORS = [
  { bg: 'rgba(250, 204, 21, 0.35)', border: 'rgba(234, 179, 8, 0.8)',   mark: 'rgba(250, 204, 21, 0.40)' },
  { bg: 'rgba(96, 165, 250, 0.25)',  border: 'rgba(59, 130, 246, 0.7)',  mark: 'rgba(96, 165, 250, 0.35)' },
  { bg: 'rgba(167, 139, 250, 0.25)', border: 'rgba(139, 92, 246, 0.7)', mark: 'rgba(167, 139, 250, 0.35)' },
  { bg: 'rgba(52, 211, 153, 0.25)',  border: 'rgba(16, 185, 129, 0.7)', mark: 'rgba(52, 211, 153, 0.35)' },
  { bg: 'rgba(251, 146, 60, 0.25)',  border: 'rgba(249, 115, 22, 0.7)', mark: 'rgba(251, 146, 60, 0.35)' },
]

/**
 * In-browser PDF viewer using react-pdf.
 * Text selection, page navigation, bbox + text highlighting.
 */
export default function PdfViewer({
  docId, page, highlights, zoom, pan, dragging, onClick, onError, onHighlightClick
}) {
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

  // Custom text renderer for multi-color text highlights (only on source page, only for chunks without bbox)
  const textRenderer = useMemo(() => {
    if (!isSourcePage) return undefined
    const textHighlights = (highlights || [])
      .filter(h => h.chunkText && (!h.bbox || h.bbox.length !== 4))
      .map(h => ({
        fragments: buildFragments(h.chunkText),
        color: HIGHLIGHT_COLORS[h.colorIndex % HIGHLIGHT_COLORS.length],
        isActive: h.isActive,
      }))
      .filter(h => h.fragments.length > 0)

    if (textHighlights.length === 0) return undefined

    // Sort once: active highlights first so they win on overlap
    const sorted = [...textHighlights].sort((a, b) => (b.isActive ? 1 : 0) - (a.isActive ? 1 : 0))

    return ({ str }) => {
      const norm = str.replace(/\s+/g, ' ').trim().toLowerCase()
      if (norm.length < 4) return escapeHtml(str)

      for (const hl of sorted) {
        if (hl.fragments.some(f => f.includes(norm))) {
          const bg = hl.isActive ? hl.color.mark : hl.color.mark.replace(/[\d.]+\)$/, '0.2)')
          return `<mark style="background:${bg}">${escapeHtml(str)}</mark>`
        }
      }
      return escapeHtml(str)
    }
  }, [isSourcePage, highlights])

  // Render multiple bbox highlight overlays with per-source colors
  const renderBboxOverlays = () => {
    if (!isSourcePage || !pageSize) return null
    const bboxHighlights = (highlights || []).filter(h => h.bbox && h.bbox.length === 4)
    if (bboxHighlights.length === 0) return null

    const pw = pageSize.originalWidth
    const ph = pageSize.originalHeight

    return (
      <div className="pdf-highlight-overlay">
        {bboxHighlights.map((h) => {
          const [x0, y0, x1, y1] = h.bbox
          const color = HIGHLIGHT_COLORS[h.colorIndex % HIGHLIGHT_COLORS.length]
          const opacity = h.isActive ? 1 : 0.5
          return (
            <div key={h.sourceIndex}>
              <div
                className={`pdf-highlight-bbox ${h.isActive ? 'active' : 'inactive'}`}
                style={{
                  left: `${(x0 / pw) * 100}%`,
                  top: `${(y0 / ph) * 100}%`,
                  width: `${((x1 - x0) / pw) * 100}%`,
                  height: `${((y1 - y0) / ph) * 100}%`,
                  borderColor: color.border,
                  backgroundColor: color.bg,
                  opacity,
                  pointerEvents: h.isActive ? 'none' : 'auto',
                  cursor: h.isActive ? 'default' : 'pointer',
                }}
                onClick={(e) => {
                  if (!h.isActive && onHighlightClick) {
                    e.stopPropagation()
                    onHighlightClick(h.sourceIndex)
                  }
                }}
              />
              {!h.isActive && h.label && (
                <div
                  className="pdf-highlight-label"
                  style={{
                    left: `${(x0 / pw) * 100}%`,
                    top: `${(y0 / ph) * 100}%`,
                    backgroundColor: color.border,
                  }}
                >
                  {h.label}
                </div>
              )}
            </div>
          )
        })}
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
            {renderBboxOverlays()}
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
