import { useState } from 'react'
import { ChevronDown, ChevronRight, Download, Globe, MessageCircleQuestion, Copy, Quote, FileText } from 'lucide-react'
import MarkdownRenderer from './MarkdownRenderer'
import { API_BASE } from '../api/client'

function scoreColor(score) {
  if (score >= 0.85) return '#e8f5e9' // green
  if (score >= 0.65) return '#fff3e0' // orange
  return '#fce4ec'                     // red
}

function scoreTextColor(score) {
  if (score >= 0.85) return '#2e7d32'
  if (score >= 0.65) return '#e65100'
  return '#c62828'
}

function ChunkTypeBadge({ chunkType }) {
  if (!chunkType || chunkType === 'text') return null
  const config = {
    table: { label: 'Table', className: 'source-chunk-type-table' },
    image: { label: 'Image', className: 'source-chunk-type-image' },
  }
  const { label, className } = config[chunkType] || {}
  if (!label) return null
  return <span className={`source-chunk-type ${className}`}>{label}</span>
}

export default function SourceCitation({ source, msgIdx, sourceIdx, onDownload, onAskAbout, onQuote, onViewPdf }) {
  const [expanded, setExpanded] = useState(false)
  const [askInput, setAskInput] = useState('')
  const [showAskInput, setShowAskInput] = useState(false)
  const [copied, setCopied] = useState(false)
  const isWeb = source.source_type === 'web'
  const isTable = source.chunk_type === 'table'
  const isImage = source.chunk_type === 'image'

  const handleAskSubmit = () => {
    if (!askInput.trim()) return
    onAskAbout(source, askInput.trim())
    setAskInput('')
    setShowAskInput(false)
  }

  const handleCopy = (e) => {
    e.stopPropagation()
    navigator.clipboard.writeText(source.content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  const handleQuote = (e) => {
    e.stopPropagation()
    // Truncate long content for the quote
    const excerpt = source.content.length > 200
      ? source.content.slice(0, 200) + '...'
      : source.content
    const quoted = `"${excerpt}" — `
    onQuote(quoted)
  }

  const renderExpandedContent = () => {
    if (isTable) {
      return (
        <div className="source-content source-content-table">
          <MarkdownRenderer content={source.content} />
        </div>
      )
    }
    if (isImage) {
      return (
        <div className="source-content source-content-image">
          {source.image_path && (
            <img
              className="source-image"
              src={`${API_BASE}/documents/images/${source.image_path}`}
              alt="Extracted from document"
              loading="lazy"
            />
          )}
          <div className="source-image-description">{source.content}</div>
        </div>
      )
    }
    return <div className="source-content">{source.content}</div>
  }

  return (
    <div className={`source-item ${isWeb ? 'source-web' : ''}`}>
      <div className="source-header" onClick={() => setExpanded(!expanded)}>
        {isWeb
          ? <Globe size={14} className="source-web-icon" />
          : expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
        }
        <span className="source-file">{source.source_file}</span>
        <ChunkTypeBadge chunkType={source.chunk_type} />
        {source.page != null && (
          <span className="source-page">p.{source.page + 1}</span>
        )}
        {source.score != null && (
          <span
            className="source-score"
            style={{
              background: scoreColor(source.score),
              color: scoreTextColor(source.score),
            }}
          >
            {Math.round(source.score * 100)}%
          </span>
        )}
        {source.chunk_index != null && (
          <span className="source-chunk-idx">#{source.chunk_index + 1}</span>
        )}
        <button
          className="source-ask-btn"
          onClick={e => { e.stopPropagation(); setShowAskInput(!showAskInput) }}
          title="Ask about this source"
        >
          <MessageCircleQuestion size={13} />
        </button>
        <button
          className="source-copy-btn"
          onClick={handleCopy}
          title={copied ? 'Copied!' : 'Copy source text'}
        >
          <Copy size={12} />
          {copied && <span className="copied-badge">Copied</span>}
        </button>
        <button
          className="source-quote-btn"
          onClick={handleQuote}
          title="Quote in input"
        >
          <Quote size={12} />
        </button>
        {source.doc_id && source.page != null && !isWeb && onViewPdf && (
          <button
            className="source-view-pdf-btn"
            onClick={e => { e.stopPropagation(); onViewPdf(sourceIdx) }}
            title="View highlighted in PDF"
          >
            <FileText size={13} />
            <span>PDF</span>
          </button>
        )}
        {source.doc_id && (
          <button
            className="source-download"
            onClick={e => { e.stopPropagation(); onDownload(source.doc_id, source.source_file) }}
            title="Download file"
          >
            <Download size={12} />
          </button>
        )}
      </div>
      {expanded && renderExpandedContent()}
      {showAskInput && (
        <div className="source-ask-input">
          <input
            type="text"
            value={askInput}
            onChange={e => setAskInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleAskSubmit()}
            placeholder="Ask about this source..."
            autoFocus
          />
          <button onClick={handleAskSubmit} disabled={!askInput.trim()}>Ask</button>
        </div>
      )}
    </div>
  )
}
