import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Send, FileText, Loader2, X, History, Plus, Square } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { fetchSessions, fetchSessionMessages } from '@/lib/api'
import CitationBadge from '@/components/CitationBadge'
import SourceItem from '@/components/SourceItem'
import SourceViewer from '@/components/SourceViewer'
import QueryTypeBadges from '@/components/QueryTypeBadges'
import ConfidenceBadge from '@/components/ConfidenceBadge'
import { splitCitations } from '@/lib/citations'

const API_BASE = import.meta.env.VITE_API_URL
const USER_ID = 'admin'

// ── Markdown renderer with citation support ─────────────────────────────────

function renderTextWithCitations(text, onCitationClick) {
  if (typeof text !== 'string') return text
  const parts = splitCitations(text)
  if (parts.length === 1 && parts[0].type === 'text') return parts[0].value
  return parts.map((part, i) =>
    part.type === 'citation'
      ? <CitationBadge key={i} num={part.value} onClick={onCitationClick} />
      : part.value
  )
}

function makeMarkdownComponents(onCitationClick) {
  const pc = (children) => {
    if (!children) return children
    if (typeof children === 'string') return renderTextWithCitations(children, onCitationClick)
    if (Array.isArray(children)) return children.map((c, i) =>
      typeof c === 'string' ? <span key={i}>{renderTextWithCitations(c, onCitationClick)}</span> : c
    )
    return children
  }
  return {
    p: ({ children }) => <p className="mb-2 last:mb-0">{pc(children)}</p>,
    ul: ({ children }) => <ul className="list-disc pl-4 mb-2">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal pl-4 mb-2">{children}</ol>,
    li: ({ children }) => <li className="mb-0.5">{pc(children)}</li>,
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
    strong: ({ children }) => <strong className="font-semibold">{pc(children)}</strong>,
    h1: ({ children }) => <h1 className="text-base font-bold mb-2 mt-3 first:mt-0">{pc(children)}</h1>,
    h2: ({ children }) => <h2 className="text-sm font-bold mb-1.5 mt-3 first:mt-0">{pc(children)}</h2>,
    h3: ({ children }) => <h3 className="text-sm font-semibold mb-1 mt-2 first:mt-0">{pc(children)}</h3>,
  }
}

// ── Main ChatPage ───────────────────────────────────────────────────────────

export default function ChatPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const scopeDocId = searchParams.get('doc')
  const scopeDocName = searchParams.get('name') || scopeDocId
  const scopeCollection = searchParams.get('collection')
  const prefillQuestion = searchParams.get('q')

  const [sessionId, setSessionId] = useState(null)
  const [showHistory, setShowHistory] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState(prefillQuestion || '')
  const [loading, setLoading] = useState(false)
  const [sources, setSources] = useState([])
  const [queryTypes, setQueryTypes] = useState([])
  const [confidenceTier, setConfidenceTier] = useState(null)
  const [selectedSource, setSelectedSource] = useState(null)
  const [showSources, setShowSources] = useState(false)
  const abortControllerRef = useRef(null)

  const citationComponents = useMemo(
    () => makeMarkdownComponents((sourceIndex) => {
      if (sourceIndex >= 0 && sourceIndex < sources.length) {
        setSelectedSource(sourceIndex)
        setShowSources(true)
      }
    }),
    [sources.length]
  )

  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions', USER_ID, scopeDocId, scopeCollection],
    queryFn: () => {
      if (scopeDocId) return fetchSessions(USER_ID, 'doc', scopeDocId)
      if (scopeCollection) return fetchSessions(USER_ID, 'collection', scopeCollection)
      return fetchSessions(USER_ID)
    },
    enabled: showHistory,
  })

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  // Reset session when document/collection scope changes
  useEffect(() => {
    setSessionId(null)
    setMessages([])
    setSources([])
    setQueryTypes([])
    setConfidenceTier(null)
    setSelectedSource(null)
    setShowSources(false)
  }, [scopeDocId, scopeCollection])

  const clearScope = () => {
    setSearchParams({})
  }

  const startNewChat = () => {
    setSessionId(null)
    setMessages([])
    setSources([])
    setQueryTypes([])
    setConfidenceTier(null)
    setSelectedSource(null)
    setShowSources(false)
  }

  const loadSession = async (sid) => {
    setSessionId(sid)
    try {
      const msgs = await fetchSessionMessages(sid, USER_ID)
      const restored = []
      let lastSources = null
      for (const m of msgs) {
        const entry = { role: m.role === 'human' ? 'user' : 'ai', content: m.content }
        restored.push(entry)
        if (m.role === 'ai' && m.sources) {
          try {
            lastSources = JSON.parse(m.sources)
          } catch { /* ignore malformed */ }
        }
      }
      setMessages(restored)
      if (lastSources) {
        setSources(lastSources)
        setShowSources(true)
      } else {
        setSources([])
        setShowSources(false)
      }
      setQueryTypes([])
      setConfidenceTier(null)
      setSelectedSource(null)
    } catch (err) {
      console.error('Failed to load session:', err)
    }
  }

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
    setConfidenceTier(null)
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

    const controller = new AbortController()
    abortControllerRef.current = controller

    try {
      const newSessionId = sessionId || `session-${Date.now()}`
      if (!sessionId) setSessionId(newSessionId)

      const resp = await fetch(`${API_BASE}/query/stream`, {
        method: 'POST',
        headers: { 'X-User-Id': USER_ID, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question, top_k: 8,
          session_id: newSessionId,
          ...(scopeDocId ? { doc_ids: [scopeDocId] } : {}),
          ...(scopeCollection ? { collection: scopeCollection } : {}),
        }),
        signal: controller.signal,
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
            if (data.confidence_tier) setConfidenceTier(data.confidence_tier)
          } else if (data.error) {
            toast.error(`Backend error: ${data.error}`)
            updateAi(msg => ({ ...msg, content: `Error: ${data.error}`, loading: false }))
          }
          // data.done — nothing extra needed
        }
      }

      // Clear loading flag in case we never got a token
      updateAi(msg => (msg.loading ? { ...msg, loading: false } : msg))
    } catch (err) {
      if (err.name === 'AbortError') {
        updateAi(msg => ({
          ...msg,
          content: msg.content || '_Stopped_',
          loading: false,
        }))
      } else {
        toast.error(`Request failed: ${err.message}`)
        updateAi(() => ({
          role: 'ai',
          content: `Failed to get response: ${err.message}`,
          loading: false,
        }))
      }
    } finally {
      setLoading(false)
      abortControllerRef.current = null
      inputRef.current?.focus()
    }
  }

  const handleStop = () => {
    abortControllerRef.current?.abort()
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
      if (e.key === 'ArrowUp' && selectedSource != null && selectedSource > 0) {
        e.preventDefault()
        setSelectedSource(selectedSource - 1)
      }
      if (e.key === 'ArrowDown' && selectedSource != null && selectedSource < sources.length - 1) {
        e.preventDefault()
        setSelectedSource(selectedSource + 1)
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
      {/* ── Session history panel ────────────────────────────── */}
      {showHistory && (
        <div
          className="w-56 border-r flex flex-col shrink-0"
          style={{ borderColor: 'hsl(217 33% 17%)', backgroundColor: 'hsl(222 47% 8%)' }}
        >
          <div className="p-2 border-b" style={{ borderColor: 'hsl(217 33% 17%)' }}>
            <button
              onClick={startNewChat}
              className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs"
              style={{ backgroundColor: 'hsl(250 80% 65%)', color: '#fff' }}
            >
              <Plus size={14} /> New Chat
            </button>
          </div>
          <div className="flex-1 overflow-auto py-1">
            {sessions.length === 0 ? (
              <p className="px-3 py-4 text-xs opacity-30 text-center">No sessions yet</p>
            ) : (
              sessions.map(s => (
                <button
                  key={s.session_id}
                  onClick={() => loadSession(s.session_id)}
                  className={cn(
                    'w-full px-3 py-2 text-left text-xs truncate transition-colors',
                    sessionId === s.session_id ? 'bg-white/10' : 'hover:bg-white/5'
                  )}
                  style={{ color: 'hsl(210 40% 98%)' }}
                >
                  <div className="truncate">{s.preview || '(empty)'}</div>
                  <div className="opacity-30 mt-0.5">
                    {new Date(s.last_access).toLocaleDateString()}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}

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
                            components={citationComponents}
                          >
                            {msg.content}
                          </ReactMarkdown>
                          {isLastAi && sources.length > 0 && (
                            <div className="flex items-center gap-1 mt-2 pt-2 border-t border-white/10 flex-wrap">
                              <span className="text-[11px] opacity-40 mr-1">Sources</span>
                              {sources.map((_, idx) => (
                                <CitationBadge key={idx} num={idx + 1} onClick={(i) => {
                                  setSelectedSource(i)
                                  setShowSources(true)
                                }} />
                              ))}
                            </div>
                          )}
                          {isLastAi && (queryTypes.length > 0 || confidenceTier) && (
                            <div className="flex flex-wrap items-center gap-2 mt-2">
                              {queryTypes.length > 0 && <QueryTypeBadges types={queryTypes} />}
                              {confidenceTier && <ConfidenceBadge tier={confidenceTier} />}
                            </div>
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

        {/* Scope indicator + Input bar */}
        <div className="px-4 py-3 border-t shrink-0" style={{ borderColor: 'hsl(217 33% 17%)' }}>
          {(scopeDocId || scopeCollection) && (
            <div className="max-w-3xl mx-auto mb-2 flex items-center gap-2 text-xs"
                 style={{ color: 'hsl(215 20% 65%)' }}>
              <FileText size={12} />
              <span>Searching in: <strong style={{ color: 'hsl(210 40% 98%)' }}>
                {scopeDocId ? scopeDocName : scopeCollection}
              </strong></span>
              <button onClick={clearScope} className="opacity-40 hover:opacity-100"><X size={12} /></button>
            </div>
          )}
          <div className="max-w-3xl mx-auto flex items-center gap-2">
            <button
              onClick={() => setShowHistory(h => !h)}
              className={cn(
                'p-2.5 rounded-lg transition-opacity',
                showHistory ? 'opacity-100' : 'opacity-40 hover:opacity-100'
              )}
              title="Chat history"
              style={{ color: 'hsl(210 40% 98%)' }}
            >
              <History size={16} />
            </button>
            {sources.length > 0 && (
              <button
                onClick={() => setShowSources(s => !s)}
                className={cn(
                  'p-2.5 rounded-lg transition-opacity',
                  showSources ? 'opacity-100' : 'opacity-40 hover:opacity-100'
                )}
                title={showSources ? 'Hide sources' : 'Show sources'}
                style={{ color: 'hsl(210 40% 98%)' }}
              >
                <FileText size={16} />
              </button>
            )}
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
            {loading ? (
              <button
                onClick={handleStop}
                className="p-2.5 rounded-lg transition-opacity hover:opacity-90"
                style={{
                  backgroundColor: 'hsl(0 84% 60%)',
                  color: 'hsl(210 40% 98%)',
                }}
                title="Stop generation"
              >
                <Square size={16} fill="currentColor" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="p-2.5 rounded-lg transition-opacity disabled:opacity-40"
                style={{
                  backgroundColor: 'hsl(250 80% 65%)',
                  color: 'hsl(210 40% 98%)',
                }}
              >
                <Send size={16} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Source panel ─────────────────────────────────────── */}
      {showSources && sources.length > 0 && (
        <div
          className={cn(selectedSource != null ? 'w-[60%]' : 'w-80', 'border-l flex flex-col shrink-0')}
          style={{ borderColor: 'hsl(217 33% 17%)', backgroundColor: 'hsl(222 47% 8%)', transition: 'width 0.2s ease' }}
        >
          {selectedSource != null ? (
            <SourceViewer
              source={sources[selectedSource]}
              sourceIndex={selectedSource}
              sources={sources}
              onBack={() => setSelectedSource(null)}
              onSelectSource={setSelectedSource}
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
