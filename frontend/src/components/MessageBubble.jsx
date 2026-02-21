import { useState } from 'react'
import { Globe, Sparkles, ChevronDown, ChevronRight, Loader2 } from 'lucide-react'
import SourceCitation from './SourceCitation'
import MarkdownRenderer from './MarkdownRenderer'

export default function MessageBubble({ msg, msgIdx, onDownloadDoc, onAskAboutChunk, onQuote, onAskAI }) {
  const [aiExpanded, setAiExpanded] = useState(true)

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

  return (
    <div className="message message-assistant">
      <div className="message-content">
        <div className={`message-text${msg.streaming ? ' streaming' : ''}`}>
          {msg.web_search_used && (
            <span className="web-search-badge"><Globe size={12} /> Web Search</span>
          )}
          <MarkdownRenderer content={msg.content} />
          {!msg.streaming && msg.sources && msg.sources.length > 0 && (
            <div className="sources">
              <div className="sources-title">
                {msg.web_search_used ? 'Web Sources' : 'Sources'}
              </div>
              {msg.sources.map((source, i) => (
                <SourceCitation
                  key={i}
                  source={source}
                  msgIdx={msgIdx}
                  sourceIdx={i}
                  onDownload={onDownloadDoc}
                  onAskAbout={onAskAboutChunk}
                  onQuote={onQuote}
                />
              ))}
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
    </div>
  )
}
