import MarkdownRenderer from './MarkdownRenderer'

export default function TableGallery({ tableSources, onOpenLightbox }) {
  if (!tableSources || tableSources.length === 0) return null

  return (
    <div className="table-gallery">
      <div className="table-gallery-header">
        Tables ({tableSources.length})
      </div>
      <div className="table-gallery-strip">
        {tableSources.map((source, i) => (
          <div
            key={i}
            className="table-gallery-card"
            onClick={() => onOpenLightbox(i)}
          >
            <div className="table-gallery-thumb-wrapper">
              <div className="table-gallery-preview">
                <MarkdownRenderer content={source.content || ''} />
              </div>
              <span className="table-gallery-table-label">Tbl. {i + 1}</span>
            </div>
            <div className="table-gallery-caption">
              {source.content
                ? source.content.split('\n')[0].replace(/\|/g, ' ').trim().slice(0, 80)
                : 'Table content unavailable'}
            </div>
            <div className="table-gallery-card-meta">
              {source.source_file && <span>{source.source_file}</span>}
              {source.page != null && <span>p.{source.page + 1}</span>}
              {source.score != null && source.score > 0 && (
                <span>{Math.round(source.score * 100)}%</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
