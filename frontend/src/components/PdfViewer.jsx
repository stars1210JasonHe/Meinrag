import { useState, useEffect, useRef, useCallback } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { API_BASE } from '../api/client'

// PDF.js setup
import * as pdfjsLib from 'pdfjs-dist'
import { TextLayer } from 'pdfjs-dist'
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.mjs',
  import.meta.url,
).toString()

/**
 * In-browser PDF viewer with text selection, page navigation, and bbox highlight.
 */
export default function PdfViewer({ docId, page, bbox, zoom, pan, dragging, onClick, onError }) {
  const canvasRef = useRef(null)
  const overlayRef = useRef(null)
  const textLayerRef = useRef(null)
  const [pdfDoc, setPdfDoc] = useState(null)
  const [currentPage, setCurrentPage] = useState(page || 0)
  const [totalPages, setTotalPages] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  // Viewport stored in state (not ref) so bbox effect triggers after render completes
  const [renderedViewport, setRenderedViewport] = useState(null)
  const renderTaskRef = useRef(null)
  const textLayerInstanceRef = useRef(null)
  const pdfDocRef = useRef(null)
  const initialPageRef = useRef(page || 0)
  const pageInputTimer = useRef(null)

  // Capture initial page when docId changes (intentionally excludes `page` from deps)
  useEffect(() => {
    initialPageRef.current = page || 0
  }, [docId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Load PDF document
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
          if (pdfDocRef.current) pdfDocRef.current.destroy()
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
          onError?.()
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
      setPdfDoc(null)
    }
  }, [docId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Render current page + text layer
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return

    const renderPage = async () => {
      // Cancel pending render
      if (renderTaskRef.current) {
        try { renderTaskRef.current.cancel() } catch {}
      }
      // Cancel pending text layer
      if (textLayerInstanceRef.current) {
        try { textLayerInstanceRef.current.cancel() } catch {}
        textLayerInstanceRef.current = null
      }

      try {
        const pageObj = await pdfDoc.getPage(currentPage + 1)
        const scale = 2
        const viewport = pageObj.getViewport({ scale })

        // Render canvas
        const canvas = canvasRef.current
        if (!canvas) return
        canvas.width = viewport.width
        canvas.height = viewport.height

        const ctx = canvas.getContext('2d')
        const task = pageObj.render({ canvasContext: ctx, viewport })
        renderTaskRef.current = task
        await task.promise
        renderTaskRef.current = null

        // Signal bbox effect that canvas is ready
        setRenderedViewport(viewport)

        // Render text layer for selection (pdfjs-dist v5: constructor + render())
        const textDiv = textLayerRef.current
        if (textDiv) {
          textDiv.innerHTML = ''
          textDiv.style.width = `${viewport.width}px`
          textDiv.style.height = `${viewport.height}px`
          const textContent = await pageObj.getTextContent()
          const tl = new TextLayer({
            textContentSource: textContent,
            container: textDiv,
            viewport,
          })
          textLayerInstanceRef.current = tl
          await tl.render()
        }
      } catch (e) {
        if (e?.name !== 'RenderingCancelledException') {
          console.error('Page render failed:', e)
        }
      }
    }

    renderPage()
  }, [pdfDoc, currentPage])

  // Draw bbox highlight — triggers only after canvas render completes (via renderedViewport state)
  useEffect(() => {
    const overlay = overlayRef.current
    if (!overlay || !renderedViewport) return

    overlay.width = renderedViewport.width
    overlay.height = renderedViewport.height
    const ctx = overlay.getContext('2d')
    ctx.clearRect(0, 0, overlay.width, overlay.height)

    if (currentPage !== initialPageRef.current || !bbox || bbox.length !== 4) return

    const [x0, y0, x1, y1] = bbox
    const [cx0, cy0] = renderedViewport.convertToViewportPoint(x0, y0)
    const [cx1, cy1] = renderedViewport.convertToViewportPoint(x1, y1)

    const rx = Math.min(cx0, cx1)
    const ry = Math.min(cy0, cy1)
    const rw = Math.abs(cx1 - cx0)
    const rh = Math.abs(cy1 - cy0)

    ctx.strokeStyle = 'rgba(220, 38, 38, 0.8)'
    ctx.lineWidth = 3
    ctx.setLineDash([6, 3])
    ctx.strokeRect(rx, ry, rw, rh)

    ctx.fillStyle = 'rgba(220, 38, 38, 0.08)'
    ctx.fillRect(rx, ry, rw, rh)
  }, [bbox, currentPage, renderedViewport])

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

  // Cleanup page input debounce timer on unmount
  useEffect(() => {
    return () => clearTimeout(pageInputTimer.current)
  }, [])

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
  const isZoomed = zoom > 1

  return (
    <div className="pdf-viewer-wrapper" onClick={onClick}>
      <div
        className="pdf-viewer-canvas-container"
        style={{
          transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
          cursor: isZoomed ? (dragging ? 'grabbing' : 'grab') : 'default',
        }}
      >
        <canvas ref={canvasRef} className="pdf-viewer-canvas" />
        <canvas ref={overlayRef} className="pdf-viewer-overlay" />
        {/* Text layer: selectable at 1x zoom, disabled when panning at zoom>1 */}
        <div
          ref={textLayerRef}
          className="textLayer"
          style={{ pointerEvents: isZoomed ? 'none' : 'all' }}
        />
      </div>

      {totalPages && totalPages > 1 && (
        <div className="pdf-viewer-page-nav" onClick={e => e.stopPropagation()}>
          <button onClick={goToPrev} disabled={currentPage <= 0} title="Previous page (PageUp)">
            <ChevronLeft size={16} />
          </button>
          <span className="pdf-viewer-page-info">
            <input
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
          <button onClick={goToNext} disabled={currentPage >= totalPages - 1} title="Next page (PageDown)">
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
