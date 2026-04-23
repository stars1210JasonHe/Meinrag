import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { ChevronLeft, ChevronRight, Search, X } from 'lucide-react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'
import { API_BASE } from '../api/client'

// Worker — must match react-pdf's bundled pdfjs-dist version (not top-level)
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// Default fallback width if container measurement isn't ready
const DEFAULT_WIDTH = 800

const HIGHLIGHT_COLORS = [
  { bg: 'rgba(250, 204, 21, 0.35)', border: 'rgba(234, 179, 8, 0.8)' },
  { bg: 'rgba(96, 165, 250, 0.25)',  border: 'rgba(59, 130, 246, 0.7)' },
  { bg: 'rgba(167, 139, 250, 0.25)', border: 'rgba(139, 92, 246, 0.7)' },
  { bg: 'rgba(52, 211, 153, 0.25)',  border: 'rgba(16, 185, 129, 0.7)' },
  { bg: 'rgba(251, 146, 60, 0.25)',  border: 'rgba(249, 115, 22, 0.7)' },
]

const SEARCH_MATCH_BG = 'rgba(34, 197, 94, 0.35)'

/**
 * In-browser PDF viewer using react-pdf.
 * Text selection, page navigation, bbox + text highlighting.
 */
export default function PdfViewer({
  docId, page, highlights, zoom, onClick, onError
}) {
  const [numPages, setNumPages] = useState(null)
  const [currentPage, setCurrentPage] = useState((page || 0) + 1) // react-pdf is 1-indexed
  const [pageSize, setPageSize] = useState(null)
  const [pageTexts, setPageTexts] = useState([])       // [{pageNum, text}] for all pages
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchMatches, setSearchMatches] = useState([]) // [{pageNum, charIndex}] all matches
  const [activeMatchIdx, setActiveMatchIdx] = useState(0)
  const [containerWidth, setContainerWidth] = useState(DEFAULT_WIDTH)
  const pageInputTimer = useRef(null)
  const containerRef = useRef(null)

  const pdfUrl = useMemo(() => `${API_BASE}/documents/${docId}/pdf`, [docId])
  const initialPage = (page || 0) + 1
  const isSourcePage = currentPage === initialPage

  // Measure container width dynamically
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => setContainerWidth(el.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Reset page when docId OR source page changes.
  // The `page` prop reflects the currently-selected source's target page;
  // when the user clicks a different citation (even in the same doc),
  // we need to jump to the new source's page.
  useEffect(() => {
    setCurrentPage((page || 0) + 1)
  }, [docId, page])

  // Extract text from all pages on PDF load for search
  const cancelledRef = useRef(false)
  useEffect(() => {
    cancelledRef.current = false
    return () => { cancelledRef.current = true }
  }, [docId])

  const handleDocLoad = useCallback(async (pdf) => {
    setNumPages(pdf.numPages)

    const texts = []
    for (let i = 1; i <= pdf.numPages; i++) {
      if (cancelledRef.current) return
      try {
        const pg = await pdf.getPage(i)
        const content = await pg.getTextContent()
        const text = content.items.map(item => item.str).join(' ')
        texts.push({ pageNum: i, text })
      } catch {
        texts.push({ pageNum: i, text: '' })
      }
    }
    if (!cancelledRef.current) setPageTexts(texts)
  }, [])

  // Custom text renderer: search highlights only (Ctrl+F)
  const textRenderer = useMemo(() => {
    const hasSearch = searchOpen && searchQuery.trim().length > 0
    if (!hasSearch) return undefined

    const searchLower = searchQuery.toLowerCase()
    return ({ str }) => {
      const escaped = escapeHtml(str)
      const norm = str.replace(/\s+/g, ' ').trim().toLowerCase()
      if (norm.length >= 2 && norm.includes(searchLower)) {
        return `<mark style="background:${SEARCH_MATCH_BG}">${escaped}</mark>`
      }
      return escaped
    }
  }, [searchOpen, searchQuery])

  // Render bbox overlay for the active source only
  const renderBboxOverlays = () => {
    if (!isSourcePage || !pageSize) return null
    const active = (highlights || []).find(h => h.isActive && h.bbox && h.bbox.length === 4)
    if (!active) return null

    const pw = pageSize.originalWidth
    const ph = pageSize.originalHeight
    const [x0, y0, x1, y1] = active.bbox
    const color = HIGHLIGHT_COLORS[active.colorIndex % HIGHLIGHT_COLORS.length]

    return (
      <div className="pdf-highlight-overlay">
        <div
          className="pdf-highlight-bbox active"
          style={{
            left: `${(x0 / pw) * 100}%`,
            top: `${(y0 / ph) * 100}%`,
            width: `${((x1 - x0) / pw) * 100}%`,
            height: `${((y1 - y0) / ph) * 100}%`,
            borderColor: color.border,
            backgroundColor: color.bg,
          }}
        />
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

  // Search match computation
  useEffect(() => {
    if (!searchQuery.trim() || pageTexts.length === 0) {
      setSearchMatches([])
      setActiveMatchIdx(0)
      return
    }
    const q = searchQuery.toLowerCase()
    const matches = []
    for (const { pageNum, text } of pageTexts) {
      const lower = text.toLowerCase()
      let startIdx = 0
      while (true) {
        const idx = lower.indexOf(q, startIdx)
        if (idx === -1) break
        matches.push({ pageNum, charIndex: idx })
        startIdx = idx + 1
      }
    }
    setSearchMatches(matches)
    setActiveMatchIdx(0)
    if (matches.length > 0) {
      setCurrentPage(matches[0].pageNum)
    }
  }, [searchQuery, pageTexts])

  const goToNextMatch = useCallback(() => {
    if (searchMatches.length === 0) return
    const next = (activeMatchIdx + 1) % searchMatches.length
    setActiveMatchIdx(next)
    setCurrentPage(searchMatches[next].pageNum)
  }, [searchMatches, activeMatchIdx])

  const goToPrevMatch = useCallback(() => {
    if (searchMatches.length === 0) return
    const prev = (activeMatchIdx - 1 + searchMatches.length) % searchMatches.length
    setActiveMatchIdx(prev)
    setCurrentPage(searchMatches[prev].pageNum)
  }, [searchMatches, activeMatchIdx])

  const closeSearch = useCallback(() => {
    setSearchOpen(false)
    setSearchQuery('')
    setSearchMatches([])
  }, [])

  // Keyboard shortcuts: PageUp/PageDown, Ctrl+F, Escape, search navigation
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement?.tagName === 'INPUT') {
        if (searchOpen) {
          if (e.key === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); closeSearch() }
          else if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); goToPrevMatch() }
          else if (e.key === 'Enter') { e.preventDefault(); goToNextMatch() }
        }
        return
      }
      if (e.key === 'PageUp') { e.preventDefault(); goToPrev() }
      else if (e.key === 'PageDown') { e.preventDefault(); goToNext() }
      else if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault()
        e.stopImmediatePropagation()
        setSearchOpen(true)
      }
      else if (e.key === 'Escape' && searchOpen) {
        e.stopImmediatePropagation()
        closeSearch()
      }
    }
    // Use capture phase so this handler fires BEFORE ContentLightbox's handler
    document.addEventListener('keydown', handler, true)
    return () => document.removeEventListener('keydown', handler, true)
  }, [goToPrev, goToNext, searchOpen, closeSearch, goToNextMatch, goToPrevMatch])

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
    <div className="pdf-viewer-wrapper" onClick={onClick} ref={containerRef}>
      <div className="pdf-viewer-canvas-container">
        <Document
          file={pdfUrl}
          onLoadSuccess={handleDocLoad}
          onLoadError={(err) => { console.error('[PdfViewer] load error:', err); onError?.() }}
          loading={<div className="pdf-viewer-loading">Loading PDF...</div>}
          error={<div className="pdf-viewer-error">Failed to load PDF</div>}
        >
          <Page
            pageNumber={currentPage}
            width={containerWidth * zoom}
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

      {searchOpen && (
        <div className="pdf-search-bar" onClick={e => e.stopPropagation()}>
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search in PDF..."
            autoFocus
            className="pdf-search-input"
          />
          {searchQuery && (
            <span className="pdf-search-count">
              {searchMatches.length > 0
                ? `${activeMatchIdx + 1} / ${searchMatches.length}`
                : 'No matches'}
            </span>
          )}
          <button onClick={goToPrevMatch} disabled={searchMatches.length === 0} title="Previous (Shift+Enter)">
            <ChevronLeft size={14} />
          </button>
          <button onClick={goToNextMatch} disabled={searchMatches.length === 0} title="Next (Enter)">
            <ChevronRight size={14} />
          </button>
          <button onClick={closeSearch} title="Close (Esc)" className="pdf-search-close">
            <X size={14} />
          </button>
        </div>
      )}

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
          <button onClick={() => setSearchOpen(o => !o)} title="Search (Ctrl+F)" className="pdf-viewer-search-btn">
            <Search size={14} />
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
