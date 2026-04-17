import { useState } from 'react'
import { ChevronDown, ChevronRight, Download, Globe, MessageCircleQuestion, Copy, Quote, FileText } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import MarkdownRenderer from './MarkdownRenderer'
import { API_BASE } from '../api/client'

function scoreColor(score) {
  // score is 0-100 from backend
  if (score >= 85) return '#e8f5e9' // green
  if (score >= 65) return '#fff3e0' // orange
  return '#fce4ec'                   // red
}

function scoreTextColor(score) {
  if (score >= 85) return '#2e7d32'
  if (score >= 65) return '#e65100'
  return '#c62828'
}

function ChunkTypeBadge({ chunkType }) {
  const { t } = useTranslation()
  if (!chunkType || chunkType === 'text') return null
  const config = {
    table: { labelKey: 'sourceCitation.table', className: 'source-chunk-type-table' },
    image: { labelKey: 'sourceCitation.image', className: 'source-chunk-type-image' },
  }
  const { labelKey, className } = config[chunkType] || {}
  if (!labelKey) return null
  return <span className={`source-chunk-type ${className}`}>{t(labelKey)}</span>
}

export default function SourceCitation({ source, msgIdx, sourceIdx, onDownload, onAskAbout, onQuote, onViewPdf }) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const [askInput, setAskInput] = useState('')
  const [showAskInput, setShowAskInput] = useState(false)
  const [copied, setCopied] = useState(false)
  const isWeb = source.source_type === 'web'
  const isTable = source.chunk_type === 'table'
  const isImage = source.chunk_type === 'image'
  const hasPdf = source.doc_id && source.page != null && !isWeb && onViewPdf
  const displayName = source.source_file?.replace(/\.[^.]+$/, '') || t('common.unknown')
  const heading = source.headings?.split(' > ').pop()

  const handleHeaderClick = () => {
    if (hasPdf) {
      onViewPdf(sourceIdx)
    } else {
      setExpanded(!expanded)
    }
  }

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
              alt={t('sourceCitation.extractedImage')}
              loading="lazy"
            />
          )}
          <div className="source-image-description">{source.content}</div>
        </div>
      )
    }
    return (
      <div className="source-content">
        {source.summary && (
          <div className="source-summary">{t('sourceCitation.tldr')} {source.summary}</div>
        )}
        {source.content}
      </div>
    )
  }

  return (
    <div className={`source-item ${isWeb ? 'source-web' : ''}`}>
      <div className="source-header" onClick={handleHeaderClick}>
        {isWeb
          ? <Globe size={14} className="source-web-icon" />
          : hasPdf
            ? <FileText size={14} className="source-pdf-icon" />
            : expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
        }
        <span className="source-file">{displayName}</span>
        <ChunkTypeBadge chunkType={source.chunk_type} />
        {source.page != null && (
          <span className="source-page">p.{source.page + 1}</span>
        )}
        {heading && (
          <span className="source-heading" title={source.headings}>{heading}</span>
        )}
        {source.score != null && (
          <span
            className="source-score"
            style={{
              background: scoreColor(source.score),
              color: scoreTextColor(source.score),
            }}
          >
            {Math.round(source.score)}%
          </span>
        )}
        {source.chunk_index != null && (
          <span className="source-chunk-idx">#{source.chunk_index + 1}</span>
        )}
        {/* Copy/Quote/Ask only for non-PDF sources — PDF sources have these in the viewer */}
        {!hasPdf && (
          <>
            <button
              className="source-ask-btn"
              onClick={e => { e.stopPropagation(); setShowAskInput(!showAskInput) }}
              title={t('sourceCitation.askSource')}
            >
              <MessageCircleQuestion size={13} />
            </button>
            <button
              className="source-copy-btn"
              onClick={handleCopy}
              title={copied ? t('sourceCitation.copied') : t('sourceCitation.copy')}
            >
              <Copy size={12} />
              {copied && <span className="copied-badge">{t('sourceCitation.copiedShort')}</span>}
            </button>
            <button
              className="source-quote-btn"
              onClick={handleQuote}
              title={t('sourceCitation.quote')}
            >
              <Quote size={12} />
            </button>
          </>
        )}
        {source.doc_id && (
          <button
            className="source-download"
            onClick={e => { e.stopPropagation(); onDownload(source.doc_id, source.source_file) }}
            title={t('sourceCitation.downloadFile')}
          >
            <Download size={12} />
          </button>
        )}
      </div>
      {/* Expand only for non-PDF sources */}
      {!hasPdf && expanded && renderExpandedContent()}
      {showAskInput && (
        <div className="source-ask-input">
          <input
            type="text"
            value={askInput}
            onChange={e => setAskInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleAskSubmit()}
            placeholder={t('sourceCitation.askSourcePlaceholder')}
            autoFocus
          />
          <button onClick={handleAskSubmit} disabled={!askInput.trim()}>{t('sourceCitation.ask')}</button>
        </div>
      )}
    </div>
  )
}
