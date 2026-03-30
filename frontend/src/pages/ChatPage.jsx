import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Send, FileText, Table2, Image, Calculator, ChevronLeft,
  ExternalLink, Loader2,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

const API_BASE = import.meta.env.VITE_API_URL
const USER_ID = 'admin'

const TYPE_ICONS = {
  text: FileText,
  table: Table2,
  image: Image,
  formula: Calculator,
}

const TYPE_COLORS = {
  fact: 'hsl(168 84% 40%)',
  overview: 'hsl(250 80% 65%)',
  reference: 'hsl(45 93% 47%)',
  exploratory: 'hsl(199 89% 48%)',
}

// ── Source list item ────────────────────────────────────────────────────────

function SourceItem({ source, index, onClick }) {
  const Icon = TYPE_ICONS[source.chunk_type] || FileText
  const label =
    source.chunk_type === 'text'
      ? (source.content?.slice(0, 60) ?? '') + '…'
      : source.label || source.source_file || `${source.chunk_type} chunk`

  return (
    <button
      onClick={() => onClick(index)}
      className="flex items-start gap-2 w-full px-3 py-2.5 text-left rounded-lg transition-colors hover:bg-white/5"
    >
      <Icon size={14} className="mt-0.5 shrink-0 opacity-60" />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium truncate" style={{ color: 'hsl(210 40% 98%)' }}>
          [{index + 1}] {label}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          {source.score != null && (
            <span className="text-xs" style={{ color: 'hsl(168 84% 40%)' }}>
              {Math.round(source.score)}%
            </span>
          )}
          {source.page != null && (
            <span className="text-xs opacity-40">p.{source.page + 1}</span>
          )}
        </div>
      </div>
    </button>
  )
}

// ── PDF preview placeholder ─────────────────────────────────────────────────

function PdfPreview({ source, onBack }) {
  const navigate = useNavigate()
  return (
    <div className="flex flex-col h-full">
      <div
        className="flex items-center gap-2 px-3 py-2 border-b shrink-0"
        style={{ borderColor: 'hsl(217 33% 17%)' }}
      >
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-xs opacity-60 hover:opacity-100 transition-opacity"
        >
          <ChevronLeft size={14} /> Sources
        </button>
        <div className="flex-1" />
        <button
          onClick={() => navigate(`/pdf/${source.doc_id}`)}
          className="flex items-center gap-1 text-xs opacity-60 hover:opacity-100 transition-opacity"
        >
          Open full PDF <ExternalLink size={12} />
        </button>
      </div>

      <div className="flex-1 flex items-center justify-center p-4">
        <div className="text-center opacity-40">
          <FileText size={32} className="mx-auto mb-2" />
          <p className="text-sm">PDF Preview</p>
          <p className="text-xs mt-1">
            {source.source_file} · Page {(source.page ?? 0) + 1}
          </p>
          <button
            onClick={() => navigate(`/pdf/${source.doc_id}`)}
            className="mt-3 px-3 py-1.5 rounded text-xs transition-opacity hover:opacity-80"
            style={{ backgroundColor: 'hsl(250 80% 65%)', color: 'hsl(210 40% 98%)' }}
          >
            Open in PDF Viewer
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Query type badges ───────────────────────────────────────────────────────

function QueryTypeBadges({ types }) {
  if (!types || types.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {types.map(t => (
        <span
          key={t}
          className="px-1.5 py-0.5 rounded text-[10px] font-medium"
          style={{ backgroundColor: TYPE_COLORS[t] ?? 'hsl(217 33% 17%)', color: '#fff' }}
        >
          {t}
        </span>
      ))}
    </div>
  )
}

// ── Markdown renderer ───────────────────────────────────────────────────────

const markdownComponents = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="list-disc pl-4 mb-2">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 mb-2">{children}</ol>,
  li: ({ children }) => <li className="mb-0.5">{children}</li>,
  code: ({ children, className }) =>
    className ? (
      <code
        className={cn('block p-2 rounded text-xs my-2 overflow-x-auto', className)}
        style={{ backgroundColor: 'hsl(222 47% 6%)' }}
      >
        {children}
      </code>
    ) : (
      <code
        className="px-1 py-0.5 rounded text-xs"
        style={{ backgroundColor: 'hsl(222 47% 6%)' }}
      >
        {children}
      </code>
    ),
  pre: ({ children }) => <>{children}</>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  h1: ({ children }) => <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="text-sm font-bold mb-1.5 mt-3 first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{children}</h3>,
}

// ── Main ChatPage ───────────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sources, setSources] = useState([])
  const [queryTypes, setQueryTypes] = useState([])
  const [selectedSource, setSelectedSource] = useState(null)
  const [showSources, setShowSources] = useState(false)

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  const handleSend = async () => {
    const question = input.trim()
    if (!question || loading) return

    setInput('')
    setLoading(true)
    setSources([])
    setQueryTypes([])
    setSelectedSource(null)
    setShowSources(false)

    // Add user message, then placeholder AI message
    setMessages(prev => [
      ...prev,
      { role: 'user', content: question },
      { role: 'ai', content: '', loading: true },
    ])

    // The AI message will be at index (prev.length + 1) but we track via
    // functional updates to avoid stale closure over aiIdx.
    const updateAi = (updater) =>
      setMessages(prev => {
        const updated = [...prev]
        const last = updated.length - 1
        if (updated[last]?.role === 'ai') {
          updated[last] = updater(updated[last])
        }
        return updated
      })

    try {
      const resp = await fetch(`${API_BASE}/query/stream`, {
        method: 'POST',
        headers: { 'X-User-Id': USER_ID, 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, top_k: 8 }),
      })

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let fullAnswer = ''

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          // Skip event: lines — we use field names in data payloads instead
          if (line.startsWith('event:')) continue
          if (!line.startsWith('data:')) continue

          const dataStr = line.slice(5).trim()
          if (!dataStr) continue

          let data
          try {
            data = JSON.parse(dataStr)
          } catch {
            continue
          }

          if (data.sources) {
            setSources(data.sources)
            setShowSources(true)
          } else if (data.token) {
            fullAnswer += data.token
            updateAi(msg => ({ ...msg, content: fullAnswer, loading: false }))
          } else if (data.types) {
            setQueryTypes(data.types)
          } else if (data.error) {
            updateAi(msg => ({ ...msg, content: `Error: ${data.error}`, loading: false }))
          }
          // data.done — nothing extra needed
        }
      }

      // Clear loading flag in case we never got a token
      updateAi(msg => (msg.loading ? { ...msg, loading: false } : msg))
    } catch (err) {
      updateAi(() => ({
        role: 'ai',
        content: `Failed to get response: ${err.message}`,
        loading: false,
      }))
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Keyboard shortcuts: 1-9 selects source, Escape closes source panel
  useEffect(() => {
    const handler = (e) => {
      const tag = document.activeElement?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return

      const num = parseInt(e.key, 10)
      if (num >= 1 && num <= 9 && num <= sources.length) {
        setSelectedSource(num - 1)
        return
      }
      if (e.key === 'Escape') {
        if (selectedSource != null) {
          setSelectedSource(null)
        } else {
          setShowSources(false)
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [sources, selectedSource])

  return (
    // overflow-hidden so the inner areas control their own scrolling
    <div className="flex h-full overflow-hidden">
      {/* ── Chat area ───────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Message list */}
        <div className="flex-1 overflow-y-auto px-4 py-6">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full opacity-40">
              <FileText size={48} className="mb-4" />
              <p className="text-lg">Ask anything about your documents</p>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-4">
              {messages.map((msg, i) => {
                const isLastAi = msg.role === 'ai' && i === messages.length - 1
                return (
                  <div
                    key={i}
                    className={cn('flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}
                  >
                    <div
                      className={cn(
                        'max-w-[85%] rounded-lg px-4 py-3 text-sm',
                        msg.role === 'user' ? 'rounded-br-sm' : 'rounded-bl-sm'
                      )}
                      style={{
                        backgroundColor:
                          msg.role === 'user'
                            ? 'hsl(250 80% 65%)'
                            : 'hsl(222 47% 12%)',
                        color: 'hsl(210 40% 98%)',
                      }}
                    >
                      {msg.loading ? (
                        <Loader2 size={16} className="animate-spin opacity-40" />
                      ) : msg.role === 'ai' ? (
                        <>
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={markdownComponents}
                          >
                            {msg.content}
                          </ReactMarkdown>
                          {isLastAi && queryTypes.length > 0 && (
                            <QueryTypeBadges types={queryTypes} />
                          )}
                        </>
                      ) : (
                        <p>{msg.content}</p>
                      )}
                    </div>
                  </div>
                )
              })}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Input bar */}
        <div className="px-4 py-3 border-t shrink-0" style={{ borderColor: 'hsl(217 33% 17%)' }}>
          <div className="max-w-3xl mx-auto flex items-center gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask anything about your documents…"
              disabled={loading}
              className="flex-1 px-4 py-2.5 rounded-lg text-sm outline-none disabled:opacity-50"
              style={{
                backgroundColor: 'hsl(217 33% 17%)',
                color: 'hsl(210 40% 98%)',
                border: '1px solid hsl(217 33% 22%)',
              }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || loading}
              className="p-2.5 rounded-lg transition-opacity disabled:opacity-40"
              style={{
                backgroundColor: 'hsl(250 80% 65%)',
                color: 'hsl(210 40% 98%)',
              }}
            >
              {loading ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Send size={16} />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* ── Source panel ─────────────────────────────────────── */}
      {showSources && sources.length > 0 && (
        <div
          className="w-80 border-l flex flex-col shrink-0"
          style={{
            borderColor: 'hsl(217 33% 17%)',
            backgroundColor: 'hsl(222 47% 8%)',
          }}
        >
          {selectedSource != null ? (
            <PdfPreview
              source={sources[selectedSource]}
              onBack={() => setSelectedSource(null)}
            />
          ) : (
            <>
              <div
                className="px-3 py-2.5 border-b text-xs font-medium uppercase tracking-wider opacity-40 shrink-0"
                style={{ borderColor: 'hsl(217 33% 17%)' }}
              >
                Sources ({sources.length})
              </div>
              <div className="flex-1 overflow-y-auto py-1">
                {sources.map((s, i) => (
                  <SourceItem key={i} source={s} index={i} onClick={setSelectedSource} />
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
