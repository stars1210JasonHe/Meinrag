import { useState, useEffect, useRef, useCallback } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { API_BASE } from '../api/client'

// PDF.js setup
import * as pdfjsLib from 'pdfjs-dist'
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.mjs',
  import.meta.url,
).toString()

/**
 * In-browser PDF viewer with page navigation and bbox highlight overlay.
 *
 * Props:
 *   docId       - document ID for /documents/{docId}/pdf
 *   page        - 0-indexed page to show initially
 *   bbox        - [x0, y0, x1, y1] in PDF points to highlight (optional)
 *   zoom        - current zoom level (from parent)
 *   pan         - {x, y} pan offset (from parent)
 *   dragging    - whether user is dragging (from parent)
 *   onClick     - click handler (from parent, for double-click zoom)
 */
export default function PdfViewer({ docId, page, bbox, zoom, pan, dragging, onClick }) {
  const canvasRef = useRef(null)
  const overlayRef = useRef(null)
  const [pdfDoc, setPdfDoc] = useState(null)
  const [currentPage, setCurrentPage] = useState(page || 0)
  const [totalPages, setTotalPages] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const renderTaskRef = useRef(null)
  const pdfDocRef = useRef(null)
  const viewportRef = useRef(null)
  const initialPageRef = useRef(page || 0)
  const pageInputRef = useRef(null)
  const pageInputTimer = useRef(null)

  // Update initialPage when docId changes
  useEffect(() => {
    initialPageRef.current = page || 0
  }, [docId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Load PDF document — with proper cleanup/destroy
  useEffect(() => {
    if (!docId) return

    let cancelled = false
    setLoading(true)
    setError(null)

    const loadPdf = async () => {
      try {
        const url = `${API_BASE}/documents/${docId}/pdf`
        const doc = await pdfjsLib.getDocument(url).promise
        if (!cancelled) {
          // Destroy previous document if any
          if (pdfDocRef.current) {
            pdfDocRef.current.destroy()
          }
          pdfDocRef.current = doc
          setPdfDoc(doc)
          setTotalPages(doc.numPages)
          setCurrentPage(initialPageRef.current)
        } else {
          doc.destroy()
        }
      } catch (e) {
        if (!cancelled) {
          console.error('PDF load failed:', e)
          setError('Failed to load PDF')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadPdf()
    return () => {
      cancelled = true
      if (pdfDocRef.current) {
        pdfDocRef.current.destroy()
        pdfDocRef.current = null
      }
    }
  }, [docId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Render current page
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return

    const renderPage = async () => {
      if (renderTaskRef.current) {
        try { renderTaskRef.current.cancel() } catch {}
      }

      try {
        const pageObj = await pdfDoc.getPage(currentPage + 1) // 1-indexed
        const scale = 2
        const viewport = pageObj.getViewport({ scale })
        viewportRef.current = viewport

        const canvas = canvasRef.current
        if (!canvas) return
        canvas.width = viewport.width
        canvas.height = viewport.height

        const ctx = canvas.getContext('2d')
        const task = pageObj.render({ canvasContext: ctx, viewport })
        renderTaskRef.current = task

        await task.promise
        renderTaskRef.current = null
      } catch (e) {
        if (e?.name !== 'RenderingCancelledException') {
          console.error('Page render failed:', e)
        }
      }
    }

    renderPage()
  }, [pdfDoc, currentPage])

  // Draw bbox highlight — separate effect so it redraws when bbox changes
  useEffect(() => {
    const overlay = overlayRef.current
    const viewport = viewportRef.current
    if (!overlay || !viewport) return

    overlay.width = viewport.width
    overlay.height = viewport.height
    const ctx = overlay.getContext('2d')
    ctx.clearRect(0, 0, overlay.width, overlay.height)

    if (currentPage !== initialPageRef.current || !bbox || bbox.length !== 4) return

    const [x0, y0, x1, y1] = bbox

    // Use viewport.convertToViewportPoint for correct coordinate mapping
    // (handles rotation, non-zero MediaBox origin, scale)
    const [cx0, cy0] = viewport.convertToViewportPoint(x0, y0)
    const [cx1, cy1] = viewport.convertToViewportPoint(x1, y1)

    // Normalise in case point order reverses under rotation
    const rx = Math.min(cx0, cx1)
    const ry = Math.min(cy0, cy1)
    const rw = Math.abs(cx1 - cx0)
    const rh = Math.abs(cy1 - cy0)

    // Draw dashed red rectangle
    ctx.strokeStyle = 'rgba(220, 38, 38, 0.8)'
    ctx.lineWidth = 3
    ctx.setLineDash([6, 3])
    ctx.strokeRect(rx, ry, rw, rh)

    // Subtle red fill
    ctx.fillStyle = 'rgba(220, 38, 38, 0.08)'
    ctx.fillRect(rx, ry, rw, rh)
  }, [bbox, currentPage, pdfDoc])

  const goToPrev = useCallback(() => {
    setCurrentPage(p => Math.max(0, p - 1))
  }, [])

  const goToNext = useCallback(() => {
    if (totalPages == null) return
    setCurrentPage(p => Math.min(totalPages - 1, p + 1))
  }, [totalPages])

  const goToPage = useCallback((p) => {
    if (totalPages == null) return
    setCurrentPage(Math.max(0, Math.min(totalPages - 1, p)))
  }, [totalPages])

  // Keyboard: PageUp/PageDown — only when no input is focused
  useEffect(() => {
    const handler = (e) => {
      if (document.activeElement?.tagName === 'INPUT') return
      if (e.key === 'PageUp') { e.preventDefault(); goToPrev() }
      else if (e.key === 'PageDown') { e.preventDefault(); goToNext() }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [goToPrev, goToNext])

  // Debounced page input handler
  const handlePageInput = useCallback((e) => {
    const v = parseInt(e.target.value, 10)
    if (isNaN(v)) return
    clearTimeout(pageInputTimer.current)
    pageInputTimer.current = setTimeout(() => goToPage(v - 1), 300)
  }, [goToPage])

  if (loading) {
    return <div className="pdf-viewer-loading">Loading PDF...</div>
  }

  if (error) {
    return <div className="pdf-viewer-error">{error}</div>
  }

  const initialPage = initialPageRef.current

  return (
    <div className="pdf-viewer-wrapper" onClick={onClick}>
      <div
        className="pdf-viewer-canvas-container"
        style={{
          transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
          cursor: zoom > 1 ? (dragging ? 'grabbing' : 'grab') : 'zoom-in',
        }}
      >
        <canvas ref={canvasRef} className="pdf-viewer-canvas" />
        <canvas ref={overlayRef} className="pdf-viewer-overlay" />
      </div>

      {totalPages && totalPages > 1 && (
        <div className="pdf-viewer-page-nav" onClick={e => e.stopPropagation()}>
          <button
            onClick={goToPrev}
            disabled={currentPage <= 0}
            title="Previous page (PageUp)"
          >
            <ChevronLeft size={16} />
          </button>
          <span className="pdf-viewer-page-info">
            <input
              ref={pageInputRef}
              type="number"
              min={1}
              max={totalPages}
              defaultValue={currentPage + 1}
              key={currentPage}
              onBlur={handlePageInput}
              onKeyDown={e => { if (e.key === 'Enter') handlePageInput(e) }}
              className="pdf-viewer-page-input"
            />
            <span>/ {totalPages}</span>
          </span>
          <button
            onClick={goToNext}
            disabled={currentPage >= totalPages - 1}
            title="Next page (PageDown)"
          >
            <ChevronRight size={16} />
          </button>

          {currentPage !== initialPage && (
            <button
              onClick={() => goToPage(initialPage)}
              className="pdf-viewer-goto-source"
              title={`Jump to source (page ${initialPage + 1})`}
            >
              Go to source
            </button>
          )}
        </div>
      )}
    </div>
  )
}
