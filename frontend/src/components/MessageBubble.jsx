import { Globe } from 'lucide-react'
import SourceCitation from './SourceCitation'

export default function MessageBubble({ msg, msgIdx, onDownloadDoc, onAskAboutChunk, onQuote }) {
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
  return (
    <div className="message message-assistant">
      <div className="message-content">
        <div className="message-text">
          {msg.web_search_used && (
            <span className="web-search-badge"><Globe size={12} /> Web Search</span>
          )}
          {msg.content}
          {msg.sources && msg.sources.length > 0 && (
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
        </div>
      </div>
    </div>
  )
}
