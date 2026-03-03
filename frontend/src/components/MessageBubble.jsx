import { useState } from 'react'
import { Globe, Sparkles, ChevronDown, ChevronRight, Loader2, Image, Table2, FileText } from 'lucide-react'
import SourceCitation from './SourceCitation'
import MarkdownRenderer from './MarkdownRenderer'
import ImageGallery from './ImageGallery'
import TableGallery from './TableGallery'
import ContentLightbox from './ContentLightbox'

export default function MessageBubble({ msg, msgIdx, onDownloadDoc, onAskAboutChunk, onQuote, onAskAI }) {
  const [aiExpanded, setAiExpanded] = useState(true)
  const [lightboxState, setLightboxState] = useState({ type: null, index: null })
  const [sectionsOpen, setSectionsOpen] = useState({ images: false, tables: false, sources: false })

  if (msg.type === 'system') {
    return (
      <div className="message message-system">
        <div className="system-message">{msg.content}</div>
      </div>
    )
  }

  if (msg.type === 'user') {
    return (
      <div className="message message-user">
        <div className="message-content">
          <div className="message-text">{msg.content}</div>
        </div>
      </div>
    )
  }

  // assistant
  const showAskAIButton = msg.question && !msg.ai_answer && !msg.ai_loading && !msg.streaming

  const imageSources = (msg.sources || []).filter(s => s.chunk_type === 'image' && s.image_path)
  const tableSources = (msg.sources || []).filter(s => s.chunk_type === 'table')
  const textSources = (msg.sources || []).filter(
    s => s.chunk_type !== 'table' && !(s.chunk_type === 'image' && s.image_path)
  )

  // Determine which sources to pass to the lightbox
  const lightboxSources = lightboxState.type === 'image' ? imageSources
    : lightboxState.type === 'table' ? tableSources
    : lightboxState.type === 'text' ? textSources
    : []

  return (
    <div className="message message-assistant">
      <div className="message-content">
        <div className={`message-text${msg.streaming ? ' streaming' : ''}`}>
          {msg.web_search_used && (
            <span className="web-search-badge"><Globe size={12} /> Web Search</span>
          )}
          <MarkdownRenderer content={msg.content} />

          {!msg.streaming && imageSources.length > 0 && (
            <div className="collapsible-section">
              <div className="collapsible-header" onClick={() => setSectionsOpen(p => ({ ...p, images: !p.images }))}>
                {sectionsOpen.images ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Image size={14} />
                <span>Figures ({imageSources.length})</span>
              </div>
              {sectionsOpen.images && (
                <ImageGallery
                  imageSources={imageSources}
                  onOpenLightbox={(i) => setLightboxState({ type: 'image', index: i })}
                />
              )}
            </div>
          )}

          {!msg.streaming && tableSources.length > 0 && (
            <div className="collapsible-section">
              <div className="collapsible-header" onClick={() => setSectionsOpen(p => ({ ...p, tables: !p.tables }))}>
                {sectionsOpen.tables ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Table2 size={14} />
                <span>Tables ({tableSources.length})</span>
              </div>
              {sectionsOpen.tables && (
                <TableGallery
                  tableSources={tableSources}
                  onOpenLightbox={(i) => setLightboxState({ type: 'table', index: i })}
                />
              )}
            </div>
          )}

          {!msg.streaming && textSources.length > 0 && (
            <div className="collapsible-section">
              <div className="collapsible-header" onClick={() => setSectionsOpen(p => ({ ...p, sources: !p.sources }))}>
                {sectionsOpen.sources ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <FileText size={14} />
                <span>{msg.web_search_used ? 'Web Sources' : 'Sources'} ({textSources.length})</span>
              </div>
              {sectionsOpen.sources && (
                <div className="sources">
                  {textSources.map((source, i) => (
                    <SourceCitation
                      key={i}
                      source={source}
                      msgIdx={msgIdx}
                      sourceIdx={i}
                      onDownload={onDownloadDoc}
                      onAskAbout={onAskAboutChunk}
                      onQuote={onQuote}
                      onViewPdf={(idx) => setLightboxState({ type: 'text', index: idx })}
                    />
                  ))}
                </div>
              )}
            </div>
          )}

          {showAskAIButton && (
            <button className="ask-ai-btn" onClick={() => onAskAI(msgIdx)}>
              <Sparkles size={14} />
              Ask AI
            </button>
          )}

          {msg.ai_loading && (
            <div className="ai-answer-loading">
              <Loader2 size={16} className="spin" />
              <span>Getting AI answer...</span>
            </div>
          )}

          {msg.ai_answer && (
            <div className="ai-answer-section">
              <div className="ai-answer-header" onClick={() => setAiExpanded(!aiExpanded)}>
                {aiExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Sparkles size={14} />
                <span>AI Knowledge</span>
              </div>
              {aiExpanded && (
                <div className={`ai-answer-content${msg.ai_loading ? ' ai-streaming' : ''}`}><MarkdownRenderer content={msg.ai_answer} /></div>
              )}
            </div>
          )}
        </div>
      </div>

      <ContentLightbox
        sources={lightboxSources}
        currentIndex={lightboxState.index}
        onClose={() => setLightboxState({ type: null, index: null })}
        onNavigate={(i) => setLightboxState(prev => ({ ...prev, index: i }))}
        type={lightboxState.type}
      />
    </div>
  )
}
