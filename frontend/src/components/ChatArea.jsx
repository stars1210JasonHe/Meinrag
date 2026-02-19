import { useRef, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import MessageBubble from './MessageBubble'
import InputBar from './InputBar'

export default function ChatArea({
  messages, loading, selectedFilter,
  onSendMessage, onDownloadDoc, onAskAboutChunk, onAskAI, onClearFilter,
}) {
  const messagesEndRef = useRef(null)
  const hasConversation = messages.some(m => m.type === 'user' || m.type === 'assistant')
  const [quotedText, setQuotedText] = useState('')

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleQuote = (text) => {
    setQuotedText(text)
  }

  return (
    <div className="chat-container">
      <div className="messages">
        {!hasConversation && <WelcomeScreen />}

        {messages.map((msg, idx) => (
          <MessageBubble
            key={idx}
            msg={msg}
            msgIdx={idx}
            onDownloadDoc={onDownloadDoc}
            onAskAboutChunk={onAskAboutChunk}
            onQuote={handleQuote}
            onAskAI={onAskAI}
          />
        ))}

        {loading && (
          <div className="thinking-indicator">
            <Loader2 size={24} className="spin" />
            <span>Thinking...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <InputBar
        loading={loading}
        selectedFilter={selectedFilter}
        onSendMessage={onSendMessage}
        onClearFilter={onClearFilter}
        quotedText={quotedText}
        onQuotedTextConsumed={() => setQuotedText('')}
      />
    </div>
  )
}

function WelcomeScreen() {
  return (
    <div className="welcome">
      <div className="welcome-header">
        <h1>Welcome to MEINRAG</h1>
        <p className="welcome-subtitle">Your intelligent document assistant</p>
      </div>
      <div className="welcome-content">
        <div className="intro-text">
          <p>Ask questions about your documents in natural language.</p>
          <p>Works with English and Chinese.</p>
        </div>
        <div className="quick-start">
          <h3>Get Started</h3>
          <ol>
            <li>Upload your documents using the sidebar</li>
            <li>Organize them into collections (or let AI categorize)</li>
            <li>Ask any question about your content</li>
          </ol>
        </div>
        <div className="features-list">
          <h3>Features</h3>
          <ul>
            <li><strong>Multi-Collection:</strong> Documents can belong to multiple categories</li>
            <li><strong>User Profiles:</strong> Isolated document spaces per user</li>
            <li><strong>AI Classification:</strong> Auto-categorize using taxonomy</li>
            <li><strong>Source Citations:</strong> Relevance scores, expandable chunks, downloads</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
