import { useState, useEffect, useRef } from 'react'
import { Send, FileText, FolderOpen, X, Globe } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { formatName } from '../taxonomy'

export default function InputBar({ loading, selectedFilter, onSendMessage, onClearFilter, quotedText, onQuotedTextConsumed }) {
  const { t } = useTranslation()
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
    if (selectedFilter.type === 'collection') return t('inputBar.askCollection', { collection: selectedFilter.value })
    if (selectedFilter.type === 'doc') return t('inputBar.askDocument')
    return t('inputBar.askQuestion')
  }

  return (
    <div className="input-bar">
      {selectedFilter.type !== 'all' && (
        <div className="scope-indicator">
          {selectedFilter.type === 'doc'
            ? <FileText size={13} />
            : <FolderOpen size={13} />
          }
          <span>{selectedFilter.type === 'doc' ? t('inputBar.filteredDocument') : formatName(selectedFilter.value)}</span>
          <button className="scope-clear" onClick={onClearFilter} title={t('inputBar.clearFilter')}>
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
          title={t('inputBar.webSearch')}
        >
          <Globe size={22} />
        </button>
        <button onClick={handleSend} disabled={loading || !input.trim()} className="btn-send">
          <Send size={22} />
        </button>
      </div>
    </div>
  )
}
