import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X, ChevronLeft, ChevronRight, ChevronDown, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react'
import { API_BASE } from '../api/client'
import MarkdownRenderer from './MarkdownRenderer'
import PdfViewer from './PdfViewer'

export default function ContentLightbox({ sources, currentIndex, onClose, onNavigate, type }) {
  const isOpen = currentIndex !== null && !!sources && sources.length > 0
  const source = isOpen ? sources[currentIndex] : null
  const hasPrev = isOpen && currentIndex > 0
  const hasNext = isOpen && currentIndex < sources.length - 1

  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const [chunkPanelOpen, setChunkPanelOpen] = useState(false)
  const [pdfFailed, setPdfFailed] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const panStart = useRef({ x: 0, y: 0 })
  const contentAreaRef = useRef(null)

  const hasPdfView = source?.doc_id != null && source?.page != null && !pdfFailed
  const isImage = type === 'image'
  const isTable = type === 'table'

  // Reset state when navigating
  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
    setChunkPanelOpen(false)
    setPdfFailed(false)
  }, [currentIndex])

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

  if (!isOpen) return null

  const isZoomed = zoom > 1

  const imageUrl = isImage && source?.image_path
    ? `${API_BASE}/documents/images/${source.image_path}`
    : null

  const typeLabel = type === 'text' ? 'Source' : isImage ? 'Figure' : 'Table'

  // Fallback rendering for non-PDF sources
  const renderFallback = () => {
    const transformStyle = {
      transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
      cursor: isZoomed ? (dragging ? 'grabbing' : 'grab') : 'zoom-in',
      transformOrigin: 'center center',
    }

    if (isImage && imageUrl) {
      return (
        <img
          src={imageUrl}
          alt={source.content || `Figure ${currentIndex + 1}`}
          className="lightbox-image"
          onClick={handleContentClick}
          style={transformStyle}
          draggable={false}
        />
      )
    }
    if (isTable && source?.content) {
      return (
        <div className="lightbox-table-content" onClick={handleContentClick} style={transformStyle}>
          <MarkdownRenderer content={source.content} />
        </div>
      )
    }
    if (source?.content) {
      return (
        <div className="lightbox-text-content" onClick={handleContentClick} style={transformStyle}>
          <div className="lightbox-text-body">{source.content}</div>
        </div>
      )
    }
    return <div className="lightbox-no-image">Content not available</div>
  }

  return createPortal(
    <div className="lightbox-overlay" onClick={onClose}>
      <div className="lightbox-container" onClick={(e) => e.stopPropagation()}>
        <button className="lightbox-close" onClick={onClose} aria-label="Close">
          <X size={24} />
        </button>

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
            {hasPdfView ? (
              <PdfViewer
                docId={source.doc_id}
                page={source.page}
                bbox={source.bbox}
                zoom={zoom}
                pan={pan}
                dragging={dragging}
                onClick={handleContentClick}
                onError={() => setPdfFailed(true)}
              />
            ) : (
              renderFallback()
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

        {/* Collapsible chunk text panel */}
        {source.content && hasPdfView && (
          <div className="lightbox-chunk-panel">
            <button
              className="lightbox-chunk-toggle"
              onClick={() => setChunkPanelOpen(!chunkPanelOpen)}
            >
              <ChevronDown
                size={14}
                style={{ transform: chunkPanelOpen ? 'rotate(0)' : 'rotate(-90deg)', transition: 'transform 0.15s' }}
              />
              Chunk Text
            </button>
            {chunkPanelOpen && (
              <div className="lightbox-chunk-content">
                {isTable
                  ? <MarkdownRenderer content={source.content} />
                  : <pre>{source.content}</pre>
                }
              </div>
            )}
          </div>
        )}

        <div className="lightbox-info">
          <div className="lightbox-counter">
            {typeLabel} {currentIndex + 1} of {sources.length}
            {source.source_file && ` \u00b7 ${source.source_file}`}
            {source.page != null && ` p.${source.page + 1}`}
          </div>
          <div className="lightbox-hint">
            {hasPdfView
              ? 'Select text on page \u00b7 Scroll to zoom \u00b7 Double-click to toggle zoom \u00b7 PageUp/PageDown for pages'
              : 'Scroll to zoom \u00b7 Double-click to toggle \u00b7 Drag to pan'
            }
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}
