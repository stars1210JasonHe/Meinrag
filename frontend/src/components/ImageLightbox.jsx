import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { X, ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw } from 'lucide-react'
import { API_BASE } from '../api/client'

export default function ImageLightbox({ imageSources, currentIndex, onClose, onNavigate }) {
  const isOpen = currentIndex !== null && !!imageSources && imageSources.length > 0
  const source = isOpen ? imageSources[currentIndex] : null
  const imageUrl = source?.image_path
    ? `${API_BASE}/documents/images/${source.image_path}`
    : null
  const hasPrev = isOpen && currentIndex > 0
  const hasNext = isOpen && currentIndex < imageSources.length - 1

  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const panStart = useRef({ x: 0, y: 0 })
  const imageAreaRef = useRef(null)

  // Reset zoom/pan when navigating to a different image
  useEffect(() => {
    setZoom(1)
    setPan({ x: 0, y: 0 })
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

  const handleImageClick = useCallback((e) => {
    // Double-click to toggle zoom
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

  // Attach wheel listener with passive: false to allow preventDefault
  useEffect(() => {
    if (!isOpen) return
    const el = imageAreaRef.current
    if (!el) return
    el.addEventListener('wheel', handleWheel, { passive: false })
    return () => el.removeEventListener('wheel', handleWheel)
  }, [isOpen, handleWheel])

  if (!isOpen) return null

  const isZoomed = zoom > 1

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
            ref={imageAreaRef}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
          >
            {imageUrl ? (
              <img
                src={imageUrl}
                alt={source.content || `Figure ${currentIndex + 1}`}
                className="lightbox-image"
                onClick={handleImageClick}
                style={{
                  transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
                  cursor: isZoomed ? (dragging ? 'grabbing' : 'grab') : 'zoom-in',
                }}
                draggable={false}
              />
            ) : (
              <div className="lightbox-no-image">Image not available</div>
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
            Figure {currentIndex + 1} of {imageSources.length}
            {source.source_file && ` \u00b7 ${source.source_file}`}
            {source.page != null && ` p.${source.page + 1}`}
          </div>
          {source.content && (
            <div className="lightbox-description">{source.content}</div>
          )}
          <div className="lightbox-hint">Scroll to zoom · Double-click to toggle · Drag to pan</div>
        </div>
      </div>
    </div>,
    document.body
  )
}
