import { API_BASE } from '../api/client'

export default function ImageGallery({ imageSources, onOpenLightbox }) {
  if (!imageSources || imageSources.length === 0) return null

  return (
    <div className="image-gallery">
      <div className="image-gallery-header">
        Figures ({imageSources.length})
      </div>
      <div className="image-gallery-strip">
        {imageSources.map((source, i) => {
          const imageUrl = source.image_path
            ? `${API_BASE}/documents/images/${source.image_path}`
            : null

          return (
            <div
              key={i}
              className="image-gallery-card"
              onClick={() => onOpenLightbox(i)}
            >
              <div className="image-gallery-thumb-wrapper">
                {imageUrl ? (
                  <img
                    src={imageUrl}
                    alt={source.content || `Figure ${i + 1}`}
                    className="image-gallery-thumb"
                    loading="lazy"
                  />
                ) : (
                  <div className="image-gallery-thumb-placeholder">No image</div>
                )}
                <span className="image-gallery-figure-label">Fig. {i + 1}</span>
              </div>
              <div className="image-gallery-caption">
                {source.content || 'Image description unavailable'}
              </div>
              <div className="image-gallery-card-meta">
                {source.source_file && <span>{source.source_file}</span>}
                {source.page != null && <span>p.{source.page + 1}</span>}
                {source.score != null && (
                  <span>{Math.round(source.score * 100)}%</span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
