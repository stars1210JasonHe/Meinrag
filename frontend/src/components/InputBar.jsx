import { useState, useEffect, useRef } from 'react'
import { Send, FileText, FolderOpen, X, Globe } from 'lucide-react'
import { formatName } from '../taxonomy'

export default function InputBar({ loading, selectedFilter, onSendMessage, onClearFilter, quotedText, onQuotedTextConsumed }) {
  const [input, setInput] = useState('')
  const inputRef = useRef(null)

  // When quoted text arrives, prepend it to input and focus
  useEffect(() => {
    if (quotedText) {
      setInput(prev => quotedText + prev)
      onQuotedTextConsumed()
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [quotedText, onQuotedTextConsumed])

  const handleSend = () => {
    if (!input.trim() || loading) return
    onSendMessage(input.trim())
    setInput('')
  }

  const handleWebSearch = () => {
    if (!input.trim() || loading) return
    onSendMessage(input.trim(), { forceWebSearch: true })
    setInput('')
  }

  const getPlaceholder = () => {
    if (selectedFilter.type === 'collection') return `Ask about ${selectedFilter.value} documents...`
    if (selectedFilter.type === 'doc') return 'Ask about this document...'
    return 'Ask a question...'
  }

  return (
    <div className="input-bar">
      {selectedFilter.type !== 'all' && (
        <div className="scope-indicator">
          {selectedFilter.type === 'doc'
            ? <FileText size={13} />
            : <FolderOpen size={13} />
          }
          <span>{selectedFilter.type === 'doc' ? 'Filtered document' : formatName(selectedFilter.value)}</span>
          <button className="scope-clear" onClick={onClearFilter} title="Clear filter">
            <X size={12} />
          </button>
        </div>
      )}
      <div className="input-container">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSend()}
          placeholder={getPlaceholder()}
          disabled={loading}
        />
        <button
          onClick={handleWebSearch}
          disabled={loading || !input.trim()}
          className="btn-web-search"
          title="Search the web instead of documents"
        >
          <Globe size={16} />
        </button>
        <button onClick={handleSend} disabled={loading || !input.trim()} className="btn-send">
          <Send size={18} />
        </button>
      </div>
    </div>
  )
}
