import { useState } from 'react'
import { ChevronDown, ChevronRight, Download, Globe, MessageCircleQuestion, Copy, Quote } from 'lucide-react'

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

export default function SourceCitation({ source, msgIdx, sourceIdx, onDownload, onAskAbout, onQuote }) {
  const [expanded, setExpanded] = useState(false)
  const [askInput, setAskInput] = useState('')
  const [showAskInput, setShowAskInput] = useState(false)
  const [copied, setCopied] = useState(false)
  const isWeb = source.source_type === 'web'

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

  return (
    <div className={`source-item ${isWeb ? 'source-web' : ''}`}>
      <div className="source-header" onClick={() => setExpanded(!expanded)}>
        {isWeb
          ? <Globe size={14} className="source-web-icon" />
          : expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />
        }
        <span className="source-file">{source.source_file}</span>
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
          <span className="source-chunk-idx">chunk {source.chunk_index}</span>
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
          title={copied ? 'Copied!' : 'Copy chunk text'}
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
      {expanded && (
        <div className="source-content">{source.content}</div>
      )}
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
