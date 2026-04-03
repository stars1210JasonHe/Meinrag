import { useState, useRef, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Send, FileText, Table2, Image, Calculator, ChevronLeft,
  Loader2, X, History, Plus, ChevronRight, ZoomIn, ZoomOut,
} from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQuery } from '@tanstack/react-query'
import { cn } from '@/lib/utils'
import { fetchSessions, fetchSessionMessages } from '@/lib/api'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'

pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`

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

// ── Source viewer (real PDF + bbox) ────────────────────────────────────────

const TYPE_BBOX_COLORS = {
  text: '#3b82f6',
  table: '#f59e0b',
  formula: '#a855f7',
  image: '#10b981',
}

function SourceViewer({ source, sourceIndex, sources, onBack, onSelectSource }) {
  const containerRef = useRef(null)
  const [numPages, setNumPages] = useState(null)
  const [currentPage, setCurrentPage] = useState((source.page ?? 0) + 1)
  const [zoom, setZoom] = useState(1.0)
  const [pageSize, setPageSize] = useState(null)
  const [containerWidth, setContainerWidth] = useState(500)

  const isPdf = source.source_file?.toLowerCase().endsWith('.pdf')
  const isImage = source.chunk_type === 'image' && source.image_path
  const pdfUrl = isPdf ? `${API_BASE}/documents/${source.doc_id}/pdf` : null

  // Measure container width
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => setContainerWidth(el.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Jump to source page when source changes
  useEffect(() => {
    setCurrentPage((source.page ?? 0) + 1)
  }, [source])

  // Scroll wheel zoom
  const handleWheel = useCallback((e) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault()
      setZoom(z => Math.min(3, Math.max(0.3, z + (e.deltaY > 0 ? -0.1 : 0.1))))
    }
  }, [])

  // Bbox overlay
  const renderBbox = () => {
    if (!source.bbox || source.bbox.length !== 4 || !pageSize) return null
    if (currentPage !== (source.page ?? 0) + 1) return null
    const [x0, y0, x1, y1] = source.bbox
    const pw = pageSize.originalWidth
    const ph = pageSize.originalHeight
    const color = TYPE_BBOX_COLORS[source.chunk_type] || '#3b82f6'
    return (
      <div style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
        <div style={{
          position: 'absolute',
          left: `${(x0 / pw) * 100}%`,
          top: `${(y0 / ph) * 100}%`,
          width: `${((x1 - x0) / pw) * 100}%`,
          height: `${((y1 - y0) / ph) * 100}%`,
          border: `3px solid ${color}`,
          backgroundColor: `${color}22`,
          borderRadius: '2px',
        }}>
          <span style={{
            position: 'absolute', top: -18, left: -1,
            backgroundColor: color, color: '#fff',
            fontSize: '10px', padding: '1px 5px', borderRadius: '2px',
          }}>
            [{sourceIndex + 1}]
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header: back + source mini-list + nav */}
      <div className="flex items-center gap-1 px-2 py-1.5 border-b shrink-0"
           style={{ borderColor: 'hsl(217 33% 17%)' }}>
        <button onClick={onBack}
                className="flex items-center gap-0.5 text-xs opacity-60 hover:opacity-100 shrink-0"
                style={{ color: 'hsl(210 40% 98%)' }}>
          <ChevronLeft size={14} /> Sources
        </button>

        <div className="flex-1" />

        {/* Source mini-list */}
        <div className="flex items-center gap-0.5">
          {sources.map((s, i) => {
            const Icon = TYPE_ICONS[s.chunk_type] || FileText
            const isActive = i === sourceIndex
            return (
              <button key={i} onClick={() => onSelectSource(i)}
                      className={cn('p-1 rounded transition-opacity', isActive ? 'opacity-100' : 'opacity-30 hover:opacity-60')}
                      style={{ color: isActive ? TYPE_BBOX_COLORS[s.chunk_type] || '#3b82f6' : 'hsl(210 40% 98%)' }}
                      title={`[${i+1}] ${s.chunk_type}`}>
                <Icon size={12} />
              </button>
            )
          })}
        </div>

        <div className="flex-1" />

        {/* Page nav (PDF only) */}
        {isPdf && numPages && (
          <div className="flex items-center gap-0.5 shrink-0">
            <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage <= 1}
                    className="p-0.5 opacity-40 hover:opacity-100 disabled:opacity-10">
              <ChevronLeft size={12} />
            </button>
            <span className="text-[10px] tabular-nums" style={{ color: 'hsl(210 40% 98%)' }}>
              {currentPage}/{numPages}
            </span>
            <button onClick={() => setCurrentPage(p => Math.min(numPages, p + 1))} disabled={currentPage >= numPages}
                    className="p-0.5 opacity-40 hover:opacity-100 disabled:opacity-10">
              <ChevronRight size={12} />
            </button>
          </div>
        )}

        {/* Zoom */}
        <div className="flex items-center gap-0.5 shrink-0 ml-1">
          <button onClick={() => setZoom(z => Math.max(0.3, z - 0.2))} className="p-0.5 opacity-40 hover:opacity-100">
            <ZoomOut size={12} />
          </button>
          <span className="text-[10px] tabular-nums w-7 text-center" style={{ color: 'hsl(210 40% 98%)' }}>
            {Math.round(zoom * 100)}%
          </span>
          <button onClick={() => setZoom(z => Math.min(3, z + 0.2))} className="p-0.5 opacity-40 hover:opacity-100">
            <ZoomIn size={12} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto" ref={containerRef} onWheel={handleWheel}>
        {isImage ? (
          /* Image source: show image directly */
          <div className="flex items-center justify-center p-4 h-full">
            <img src={`${API_BASE}/documents/images/${source.image_path}`}
                 alt={source.content?.slice(0, 50) || 'Image'}
                 className="max-w-full max-h-full object-contain rounded" />
          </div>
        ) : isPdf && pdfUrl ? (
          /* PDF source: render actual PDF page */
          <div className="flex justify-center py-2">
            <Document file={pdfUrl}
                      onLoadSuccess={(pdf) => setNumPages(pdf.numPages)}
                      loading={<div className="p-8 flex items-center justify-center opacity-40"><Loader2 size={20} className="animate-spin" /></div>}
                      error={<div className="p-8 text-center opacity-40 text-xs">Failed to load PDF</div>}>
              <Page pageNumber={currentPage}
                    width={containerWidth * zoom * 0.95}
                    renderTextLayer={false}
                    renderAnnotationLayer={false}
                    onLoadSuccess={(info) => setPageSize(info)}
                    loading="">
                {renderBbox()}
              </Page>
            </Document>
          </div>
        ) : (
          /* Non-PDF source: show chunk text */
          <div className="p-4 text-sm leading-relaxed" style={{ color: 'hsl(210 40% 98%)' }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {source.content || 'No content available'}
            </ReactMarkdown>
          </div>
        )}
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
  const [searchParams, setSearchParams] = useSearchParams()
  const scopeDocId = searchParams.get('doc')
  const scopeDocName = searchParams.get('name') || scopeDocId
  const scopeCollection = searchParams.get('collection')

  const [sessionId, setSessionId] = useState(null)
  const [showHistory, setShowHistory] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [sources, setSources] = useState([])
  const [queryTypes, setQueryTypes] = useState([])
  const [selectedSource, setSelectedSource] = useState(null)
  const [showSources, setShowSources] = useState(false)

  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions', USER_ID],
    queryFn: () => fetchSessions(USER_ID),
    enabled: showHistory,
  })

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  const clearScope = () => {
    setSearchParams({})
  }

  const startNewChat = () => {
    setSessionId(null)
    setMessages([])
    setSources([])
    setQueryTypes([])
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
