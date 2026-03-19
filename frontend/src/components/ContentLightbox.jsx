import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X, ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react'
import { API_BASE } from '../api/client'
import MarkdownRenderer from './MarkdownRenderer'
import PdfViewer from './PdfViewer'

export default function ContentLightbox({ sources, currentIndex, onClose, onNavigate, type }) {
  const isOpen = currentIndex !== null && !!sources && sources.length > 0
  const source = isOpen ? sources[currentIndex] : null
  const hasPrev = isOpen && currentIndex > 0
  const hasNext = isOpen && currentIndex < sources.length - 1

  const [viewMode, setViewMode] = useState('content') // 'content' | 'pdf'
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const panStart = useRef({ x: 0, y: 0 })
  const contentAreaRef = useRef(null)

  const hasBbox = source?.bbox && source?.doc_id != null && source?.page != null
  const hasPdfView = source?.doc_id != null && source?.page != null
  const isText = type === 'text'

  // Reset state when navigating — default to 'pdf' for text sources
  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
    setViewMode(type === 'text' ? 'pdf' : 'content')
  }, [currentIndex, type])

  const zoomIn = useCallback(() => {
    setZoom(z => Math.min(z * 1.5, 8))
  }, [])

  const zoomOut = useCallback(() => {
    setZoom(z => {
      const next = z / 1.5
      if (next <= 1.05) {
        setPan({ x: 0, y: 0 })
        return 1
      }
      return next
    })
  }, [])

  const resetZoom = useCallback(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [])

  const handleWheel = useCallback((e) => {
    e.preventDefault()
    if (e.deltaY < 0) {
      setZoom(z => Math.min(z * 1.15, 8))
    } else {
      setZoom(z => {
        const next = z / 1.15
        if (next <= 1.05) {
          setPan({ x: 0, y: 0 })
          return 1
        }
        return next
      })
    }
  }, [])

  const handleMouseDown = useCallback((e) => {
    if (zoom <= 1) return
    e.preventDefault()
    setDragging(true)
    dragStart.current = { x: e.clientX, y: e.clientY }
    panStart.current = { ...pan }
  }, [zoom, pan])

  const handleMouseMove = useCallback((e) => {
    if (!dragging) return
    setPan({
      x: panStart.current.x + (e.clientX - dragStart.current.x),
      y: panStart.current.y + (e.clientY - dragStart.current.y),
    })
  }, [dragging])

  const handleMouseUp = useCallback(() => {
    setDragging(false)
  }, [])

  const handleContentClick = useCallback((e) => {
    if (e.detail === 2) {
      if (zoom > 1) {
        resetZoom()
      } else {
        setZoom(3)
      }
    }
  }, [zoom, resetZoom])

  const handleKeyDown = useCallback((e) => {
    if (!isOpen) return
    if (e.key === 'Escape') onClose()
    else if (e.key === 'ArrowLeft' && hasPrev) onNavigate(currentIndex - 1)
    else if (e.key === 'ArrowRight' && hasNext) onNavigate(currentIndex + 1)
    else if (e.key === '+' || e.key === '=') zoomIn()
    else if (e.key === '-') zoomOut()
    else if (e.key === '0') resetZoom()
  }, [isOpen, onClose, onNavigate, currentIndex, hasPrev, hasNext, zoomIn, zoomOut, resetZoom])

  useEffect(() => {
    if (!isOpen) return
    document.addEventListener('keydown', handleKeyDown)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [isOpen, handleKeyDown])

  useEffect(() => {
    if (!isOpen) return
    const el = contentAreaRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [isOpen, handleWheel])

  // Reset zoom when switching views
  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
  }, [viewMode])

  if (!isOpen) return null

  const isZoomed = zoom > 1
  const isImage = type === 'image'
  const isTable = type === 'table'

  const imageUrl = isImage && source?.image_path
    ? `${API_BASE}/documents/images/${source.image_path}`
    : null

  // Build PDF highlight URL: bbox → red rect, text → yellow highlight, or plain page
  // Truncate text to avoid URL length limits (~2000 chars encoded is safe)
  const MAX_TEXT_FOR_URL = 1500
  let pdfHighlightUrl = null
  if (hasPdfView) {
    const base = `${API_BASE}/documents/${source.doc_id}/page-highlight?page=${source.page}`
    if (hasBbox) {
      pdfHighlightUrl = `${base}&bbox=${source.bbox.join(',')}`
    } else if (source.content && source.content.trim()) {
      const textSnippet = source.content.length > MAX_TEXT_FOR_URL
        ? source.content.slice(0, MAX_TEXT_FOR_URL)
        : source.content
      pdfHighlightUrl = `${base}&text=${encodeURIComponent(textSnippet)}`
    } else {
      pdfHighlightUrl = base
    }
  }

  const typeLabel = isText ? 'Source' : isImage ? 'Figure' : 'Table'

  return createPortal(
    <div className="lightbox-overlay" onClick={onClose}>
      <div className="lightbox-container" onClick={(e) => e.stopPropagation()}>
        <button className="lightbox-close" onClick={onClose} aria-label="Close">
          <X size={24} />
        </button>

        {/* View toggle — show when PDF view is available */}
        {hasPdfView && (
          <div className="lightbox-view-toggle">
            <button
              className={viewMode === 'content' ? 'active' : ''}
              onClick={() => setViewMode('content')}
            >
              Content
            </button>
            <button
              className={viewMode === 'pdf' ? 'active' : ''}
              onClick={() => setViewMode('pdf')}
            >
              PDF Page
            </button>
          </div>
        )}

        <div className="lightbox-body">
          {hasPrev && (
            <button
              className="lightbox-nav lightbox-nav-prev"
              onClick={() => onNavigate(currentIndex - 1)}
              aria-label="Previous"
            >
              <ChevronLeft size={32} />
            </button>
          )}

          <div
            className={`lightbox-image-area ${isZoomed ? 'zoomed' : ''}`}
            ref={contentAreaRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            {viewMode === 'pdf' && hasPdfView ? (
              <PdfViewer
                docId={source.doc_id}
                page={source.page}
                bbox={source.bbox}
                zoom={zoom}
                pan={pan}
                dragging={dragging}
                onClick={handleContentClick}
              />
            ) : isImage && imageUrl ? (
              <img
                src={imageUrl}
                alt={source.content || `Figure ${currentIndex + 1}`}
                className="lightbox-image"
                onClick={handleContentClick}
                style={{
                  transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
                  cursor: isZoomed ? (dragging ? 'grabbing' : 'grab') : 'zoom-in',
                }}
                draggable={false}
              />
            ) : isTable ? (
              <div
                className="lightbox-table-content"
                onClick={handleContentClick}
                style={{
                  transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
                  cursor: isZoomed ? (dragging ? 'grabbing' : 'grab') : 'zoom-in',
                  transformOrigin: 'center center',
                }}
              >
                <MarkdownRenderer content={source.content || ''} />
              </div>
            ) : isText && source?.content ? (
              <div
                className="lightbox-text-content"
                onClick={handleContentClick}
                style={{
                  transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
                  cursor: isZoomed ? (dragging ? 'grabbing' : 'grab') : 'zoom-in',
                  transformOrigin: 'center center',
                }}
              >
                <div className="lightbox-text-body">{source.content}</div>
              </div>
            ) : (
              <div className="lightbox-no-image">Content not available</div>
            )}
          </div>

          {hasNext && (
            <button
              className="lightbox-nav lightbox-nav-next"
              onClick={() => onNavigate(currentIndex + 1)}
              aria-label="Next"
            >
              <ChevronRight size={32} />
            </button>
          )}
        </div>

        {/* Zoom controls */}
        <div className="lightbox-zoom-controls">
          <button onClick={zoomOut} title="Zoom out (-)"><ZoomOut size={18} /></button>
          <span className="lightbox-zoom-level">{Math.round(zoom * 100)}%</span>
          <button onClick={zoomIn} title="Zoom in (+)"><ZoomIn size={18} /></button>
          {isZoomed && (
            <button onClick={resetZoom} title="Reset (0)"><RotateCcw size={16} /></button>
          )}
        </div>

        <div className="lightbox-info">
          <div className="lightbox-counter">
            {typeLabel} {currentIndex + 1} of {sources.length}
            {source.source_file && ` \u00b7 ${source.source_file}`}
            {source.page != null && ` p.${source.page + 1}`}
          </div>
          {source.content && (
            <div className="lightbox-description">
              {isTable
                ? source.content.split('\n')[0].replace(/\|/g, ' ').trim()
                : source.content
              }
            </div>
          )}
          <div className="lightbox-hint">
            Scroll to zoom · Double-click to toggle · Drag to pan
            {hasPdfView && viewMode === 'content' && ' · Toggle to PDF Page for original context'}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}
