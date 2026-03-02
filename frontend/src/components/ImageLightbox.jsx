import { useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { X, ChevronLeft, ChevronRight } from 'lucide-react'
import { API_BASE } from '../api/client'

export default function ImageLightbox({ imageSources, currentIndex, onClose, onNavigate }) {
  const isOpen = currentIndex !== null && !!imageSources && imageSources.length > 0
  const source = isOpen ? imageSources[currentIndex] : null
  const imageUrl = source?.image_path
    ? `${API_BASE}/documents/images/${source.image_path}`
    : null
  const hasPrev = isOpen && currentIndex > 0
  const hasNext = isOpen && currentIndex < imageSources.length - 1

  const handleKeyDown = useCallback((e) => {
    if (!isOpen) return
    if (e.key === 'Escape') onClose()
    else if (e.key === 'ArrowLeft' && hasPrev) onNavigate(currentIndex - 1)
    else if (e.key === 'ArrowRight' && hasNext) onNavigate(currentIndex + 1)
  }, [isOpen, onClose, onNavigate, currentIndex, hasPrev, hasNext])

  useEffect(() => {
    if (!isOpen) return
    document.addEventListener('keydown', handleKeyDown)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [isOpen, handleKeyDown])

  if (!isOpen) return null

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

          <div className="lightbox-image-area">
            {imageUrl ? (
              <img
                src={imageUrl}
                alt={source.content || `Figure ${currentIndex + 1}`}
                className="lightbox-image"
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

        <div className="lightbox-info">
          <div className="lightbox-counter">
            Figure {currentIndex + 1} of {imageSources.length}
            {source.source_file && ` \u00b7 ${source.source_file}`}
            {source.page != null && ` p.${source.page + 1}`}
          </div>
          {source.content && (
            <div className="lightbox-description">{source.content}</div>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}
