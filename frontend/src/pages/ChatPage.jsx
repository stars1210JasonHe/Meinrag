import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Send, FileText, Loader2, X, History, Plus, Square } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { fetchSessions, fetchSessionMessages } from '@/lib/api'
import CitationBadge from '@/components/CitationBadge'
import QueryTypeBadges from '@/components/QueryTypeBadges'
import ConfidenceBadge from '@/components/ConfidenceBadge'
import ContextTag from '@/components/ContextTag'
import SupplementActions from '@/components/SupplementActions'
import FastPathBadge from '@/components/FastPathBadge'
import { useDocTabs } from '@/hooks/useDocTabs'
import SourceTabs from '@/components/SourceTabs'
import TextDocViewer from '@/components/TextDocViewer'
import SourceCard from '@/components/SourceCard'
import PdfViewer from '@/components/PdfViewer'
import ChatEmptyState from '@/components/ChatEmptyState'

// Substring that identifies a corpus-refusal answer. Anchored to the exact
// phrase the RAG_SYSTEM_PROMPT instructs the LLM to emit.
const REFUSAL_MARKER = 'do not contain information'
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
          style={{ backgroundColor: 'var(--bg, #08080a)' }}
        >
          {children}
        </code>
      ) : (
        <code
          className="px-1 py-0.5 rounded text-xs"
          style={{ backgroundColor: 'var(--bg, #08080a)' }}
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
  const { t } = useTranslation()
  const [searchParams, setSearchParams] = useSearchParams()
  const scopeDocId = searchParams.get('doc')
  const scopeDocName = searchParams.get('name') || scopeDocId
  const scopeCollection = searchParams.get('collection')
  // Multi-select: Dashboard's "Ask" button sends ?doc_ids=a,b,c
  const scopeDocIdsParam = searchParams.get('doc_ids')
  const scopeDocIds = useMemo(
    () => (scopeDocIdsParam ? scopeDocIdsParam.split(',').filter(Boolean) : null),
    [scopeDocIdsParam]
  )
  const prefillQuestion = searchParams.get('q')

  const [sessionId, setSessionId] = useState(null)
  const [showHistory, setShowHistory] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState(prefillQuestion || '')
  const [loading, setLoading] = useState(false)
  const [sources, setSources] = useState([])
  const [queryTypes, setQueryTypes] = useState([])
  const [confidenceTier, setConfidenceTier] = useState(null)
  const [fastPath, setFastPath] = useState(false)
  const [contextInfo, setContextInfo] = useState(null)
  const [selectedSource, setSelectedSource] = useState(null)
  const abortControllerRef = useRef(null)

  const {
    tabs,
    activeDocId,
    activeTab,
    openTab,
    closeTab,
    activateTab,
    resetTabs,
    openTabsForSources,
  } = useDocTabs()

  // Sources are sent in "lost in the middle" U-shape order for the LLM
  // (best first, 2nd-best last). Display them sorted by score instead, while
  // keeping the original array index as the click target so citations [N]
  // in the answer text still resolve to the correct source.
  const displaySources = useMemo(
    () => sources
      .map((s, i) => ({ source: s, originalIndex: i }))
      .sort((a, b) => (b.source.score ?? 0) - (a.source.score ?? 0)),
    [sources]
  )

  // Citation [N] click: ensure tab is open, activate it, and select the source
  // (drives PdfViewer page+bbox highlight or TextDocViewer chunk scroll).
  // CitationBadge converts 1-based [N] to 0-based ORIGINAL array index before
  // invoking this callback.
  const onCitationClick = useCallback((originalIndex) => {
    if (originalIndex < 0 || originalIndex >= sources.length) return
    const source = sources[originalIndex]
    openTab({
      doc_id: source.doc_id,
      filename: source.source_file,
      file_type: null, // useDocTabs infers from filename extension
    })
    activateTab(source.doc_id)
    setSelectedSource(originalIndex)
  }, [sources, openTab, activateTab])

  const citationComponents = useMemo(
    () => makeMarkdownComponents(onCitationClick),
    [onCitationClick],
  )

  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions', USER_ID],
    queryFn: () => fetchSessions(USER_ID),
    enabled: showHistory,
  })

  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  // Reset session when document/collection scope changes
  useEffect(() => {
    resetTabs()
    setSessionId(null)
    setMessages([])
    setSources([])
    setQueryTypes([])
    setConfidenceTier(null)
    setFastPath(false)
    setContextInfo(null)
    setSelectedSource(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeDocId, scopeCollection, scopeDocIdsParam])

  const clearScope = () => {
    setSearchParams({})
  }

  const startNewChat = () => {
    resetTabs()
    setSessionId(null)
    setMessages([])
    setSources([])
    setQueryTypes([])
    setConfidenceTier(null)
    setFastPath(false)
    setContextInfo(null)
    setSelectedSource(null)
  }

  const loadSession = async (sid) => {
    resetTabs()
    setSessionId(sid)
    try {
      const msgs = await fetchSessionMessages(sid, USER_ID)
      const restored = []
      let lastSources = null
      let lastUserQuestion = null
      for (const m of msgs) {
        const role = m.role === 'human' ? 'user' : 'ai'
        const entry = { role, content: m.content }
        if (role === 'user') {
          lastUserQuestion = m.content
        } else {
          // Re-derive refusal flag from text (not persisted in DB). Carry the
          // preceding user question so the supplement buttons can resend it.
          if (typeof m.content === 'string' && m.content.toLowerCase().includes(REFUSAL_MARKER)) {
            entry.refusal = true
            entry.originalQuestion = lastUserQuestion
          }
          if (m.sources) {
            try {
              lastSources = JSON.parse(m.sources)
            } catch { /* ignore malformed */ }
          }
        }
        restored.push(entry)
      }
      setMessages(restored)
      if (lastSources) {
        setSources(lastSources)
        const firstDocId = openTabsForSources(lastSources)
        if (firstDocId && !activeDocId) {
          activateTab(firstDocId)
        }
      } else {
        setSources([])
      }
      setQueryTypes([])
      setConfidenceTier(null)
    setFastPath(false)
    setContextInfo(null)
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
    setFastPath(false)
    setContextInfo(null)
    setSelectedSource(null)

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
          ...(scopeDocIds ? { doc_ids: scopeDocIds }
                : scopeDocId ? { doc_ids: [scopeDocId] }
                : {}),
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
            // Open tabs for any new docs cited; activate first one if no tab was active
            const firstDocId = openTabsForSources(data.sources)
            if (firstDocId && !activeDocId) {
              activateTab(firstDocId)
            }
          } else if (data.token) {
            fullAnswer += data.token
            updateAi(msg => ({ ...msg, content: fullAnswer, loading: false }))
          } else if (data.types) {
            setQueryTypes(data.types)
            if (data.confidence_tier) setConfidenceTier(data.confidence_tier)
            if (data.fast_path) setFastPath(true)
            else if (data.fast_path === false) setFastPath(false)
            if (data.chunks_included != null) {
              setContextInfo({
                chunks: data.chunks_included,
                available: data.chunks_available,
                tokens: data.context_used_tokens,
                budget: data.context_budget_tokens,
                mode: data.context_mode,
              })
            }
          } else if (data.error) {
            toast.error(t('chat.backendError', { message: data.error }))
            updateAi(msg => ({ ...msg, content: t('chat.inlineError', { message: data.error }), loading: false }))
          }
          // data.done — nothing extra needed
        }
      }

      // Clear loading flag in case we never got a token
      updateAi(msg => (msg.loading ? { ...msg, loading: false } : msg))

      // Flag the AI message as a refusal if the LLM said it couldn't answer
      // from the corpus. UI will render SupplementActions below it.
      if (fullAnswer.toLowerCase().includes(REFUSAL_MARKER)) {
        updateAi(msg => ({ ...msg, refusal: true, originalQuestion: question }))
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        updateAi(msg => ({
          ...msg,
          content: msg.content || t('chat.stopped'),
          loading: false,
        }))
      } else {
        toast.error(t('chat.requestFailed', { message: err.message }))
        updateAi(() => ({
          role: 'ai',
          content: t('chat.responseFailed', { message: err.message }),
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

  /**
   * Run a supplement query when the corpus refused. Appends a NEW ai message
   * with a `supplementSource` marker (UI renders a "From general AI" /
   * "From web search" badge). Marks the originating refusal message so the
   * action buttons hide.
   *
   * @param {number} refusalMsgIdx - index of the ai message flagged refusal
   * @param {string} question - original user question
   * @param {"ai"|"web"} source - which endpoint to use
   */
  const handleSupplement = async (refusalMsgIdx, question, source) => {
    if (loading) return

    // Clear stale sidebar state from the previous corpus query — the supplement
    // message won't have these (ask-ai has no sources; web has its own).
    setSources([])
    setQueryTypes([])
    setConfidenceTier(null)
    setFastPath(false)
    setContextInfo(null)
    setSelectedSource(null)

    // Mark original refusal message as acted-upon (hides buttons)
    setMessages(prev => prev.map((m, i) =>
      i === refusalMsgIdx ? { ...m, supplementUsed: true } : m
    ))

    // Append a new assistant placeholder with the supplement source + a
    // loading banner message so the user sees "Fetching AI knowledge..." /
    // "Searching the web..." while the stream spins up.
    setMessages(prev => [
      ...prev,
      {
        role: 'ai',
        content: '',
        loading: true,
        supplementSource: source,
        supplementBanner: source === 'ai'
          ? t('supplement.fetchingAi', { defaultValue: 'Fetching AI knowledge…' })
          : t('supplement.fetchingWeb', { defaultValue: 'Searching the web…' }),
      },
    ])

    setLoading(true)
    const controller = new AbortController()
    abortControllerRef.current = controller

    const updateLast = (updater) =>
      setMessages(prev => {
        const updated = [...prev]
        const last = updated.length - 1
        if (updated[last]?.role === 'ai') {
          updated[last] = updater(updated[last])
        }
        return updated
      })

    try {
      const url = source === 'ai'
        ? `${API_BASE}/query/ask-ai/stream`
        : `${API_BASE}/query/stream`
      const body = source === 'ai'
        ? { question, session_id: sessionId }
        : {
            question, top_k: 8,
            session_id: sessionId,
            force_web_search: true,
          }

      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'X-User-Id': USER_ID, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
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
          if (line.startsWith('event:')) continue
          if (!line.startsWith('data:')) continue
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          let data
          try { data = JSON.parse(dataStr) } catch { continue }
          if (data.token) {
            fullAnswer += data.token
            updateLast(msg => ({ ...msg, content: fullAnswer, loading: false }))
          } else if (data.sources && source === 'web') {
            // Web search sources attach to this supplement message
            updateLast(msg => ({ ...msg, sources: data.sources }))
          } else if (data.error) {
            toast.error(t('chat.backendError', { message: data.error }))
          }
        }
      }
      updateLast(msg => (msg.loading ? { ...msg, loading: false } : msg))
    } catch (err) {
      if (err.name !== 'AbortError') {
        toast.error(t('chat.requestFailed', { message: err.message }))
        updateLast(() => ({
          role: 'ai',
          content: t('chat.responseFailed', { message: err.message }),
          loading: false,
          supplementSource: source,
        }))
      }
    } finally {
      setLoading(false)
      abortControllerRef.current = null
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
      // ArrowUp/Down step through the visually-displayed (score-sorted) order,
      // not the raw array order — selectedSource stores the original array index.
      if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && selectedSource != null) {
        const displayPos = displaySources.findIndex(d => d.originalIndex === selectedSource)
        if (displayPos < 0) return
        const nextPos = e.key === 'ArrowUp' ? displayPos - 1 : displayPos + 1
        if (nextPos < 0 || nextPos >= displaySources.length) return
        e.preventDefault()
        setSelectedSource(displaySources[nextPos].originalIndex)
      }
      if (e.key === 'Escape') {
        if (selectedSource != null) {
          setSelectedSource(null)
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [sources, selectedSource, displaySources])

  return (
    // overflow-hidden so the inner areas control their own scrolling
    <div className="flex h-full overflow-hidden">
      {/* ── Session history panel ────────────────────────────── */}
      {showHistory && (
        <div
          className="w-56 border-r flex flex-col shrink-0"
          style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))', backgroundColor: 'var(--bg-1, #0c0c0f)' }}
        >
          <div className="p-2 border-b" style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}>
            <button
              onClick={startNewChat}
              className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs"
              style={{ backgroundColor: 'var(--signature, #5b7ec9)', color: '#fff' }}
            >
              <Plus size={14} /> {t('chat.newChat')}
            </button>
          </div>
          <div className="flex-1 overflow-auto py-1">
            {sessions.length === 0 ? (
              <p className="px-3 py-4 text-xs opacity-30 text-center">{t('chat.noSessionsYet')}</p>
            ) : (
              sessions.map(s => (
                <button
                  key={s.session_id}
                  onClick={() => loadSession(s.session_id)}
                  className={cn(
                    'w-full px-3 py-2 text-left text-xs truncate transition-colors',
                    sessionId === s.session_id ? 'bg-white/10' : 'hover:bg-white/5'
                  )}
                  style={{ color: 'var(--fg, #f4f2ee)' }}
                >
                  <div className="truncate">{s.preview || t('common.empty')}</div>
                  <div className="opacity-30 mt-0.5">
                    {new Date(s.last_access).toLocaleDateString()}
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* ── Main area: tabs + viewer ─────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">
        {tabs.length === 0 ? (
          <div
            className="flex-1 flex items-center justify-center text-sm opacity-40 px-8 text-center"
            style={{ color: 'var(--fg, #f4f2ee)' }}
          >
            {t('chat.emptyMain', { defaultValue: 'Your source documents will appear here when you ask a question.' })}
          </div>
        ) : (
          <>
            <SourceTabs
              tabs={tabs}
              activeDocId={activeDocId}
              onActivate={activateTab}
              onClose={closeTab}
            />
            <div className="flex-1 overflow-hidden">
              {/* Mount EVERY open tab; hide inactive ones with display:none.
                  Keeps each viewer's internal state (currentPage, zoom,
                  scroll, pageSize cache) alive across tab switches so the
                  user returns to where they left off. */}
              {tabs.map(tab => {
                const isActive = tab.doc_id === activeDocId
                const srcForTab =
                  selectedSource != null && sources[selectedSource]?.doc_id === tab.doc_id
                    ? sources[selectedSource]
                    : null
                return (
                  <div
                    key={tab.doc_id}
                    style={{ display: isActive ? 'block' : 'none', height: '100%' }}
                  >
                    {tab.file_type === 'pdf' ? (
                      <PdfViewer
                        docId={tab.doc_id}
                        page={srcForTab?.page ?? null}
                        highlights={
                          srcForTab
                            ? [{
                                bbox: srcForTab.bbox,
                                isActive: true,
                                colorIndex: selectedSource,
                              }]
                            : []
                        }
                      />
                    ) : (
                      <TextDocViewer
                        docId={tab.doc_id}
                        activeChunkIndex={srcForTab?.chunk_index ?? null}
                        activeSourceColorIndex={selectedSource ?? 0}
                      />
                    )}
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>

      {/* ── Chat sidebar (right) ─────────────────────────────── */}
      <div
        className="w-[360px] border-l flex flex-col shrink-0"
        style={{
          borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
          backgroundColor: 'var(--bg-1, #0c0c0f)',
        }}
      >
        {/* Chat messages */}
        <div className="flex-1 overflow-y-auto px-3 py-3">
          {messages.length === 0 ? (
            <ChatEmptyState onSuggestionClick={(text) => {
              setInput(text)
              inputRef.current?.focus()
            }} />
          ) : (
            <div className="space-y-3">
              {messages.map((msg, i) => {
                const isLastAi = msg.role === 'ai' && i === messages.length - 1
                return (
                  <div
                    key={i}
                    className={cn('flex', msg.role === 'user' ? 'justify-end' : 'justify-start')}
                  >
                    <div
                      className={cn(
                        'max-w-[92%] rounded-lg px-3 py-2 text-sm',
                        msg.role === 'user' ? 'rounded-br-sm' : 'rounded-bl-sm'
                      )}
                      style={{
                        backgroundColor:
                          msg.role === 'user'
                            ? 'var(--signature, #5b7ec9)'
                            : 'var(--bg-2, #111115)',
                        color: 'var(--fg, #f4f2ee)',
                      }}
                    >
                      {msg.loading ? (
                        msg.supplementBanner ? (
                          <div className="flex items-center gap-2 text-sm"
                               style={{ color: 'var(--fg-dim, #9a9690)' }}>
                            <Loader2 size={14} className="animate-spin" />
                            <span>{msg.supplementBanner}</span>
                          </div>
                        ) : (
                          <Loader2 size={16} className="animate-spin opacity-40" />
                        )
                      ) : msg.role === 'ai' ? (
                        <>
                          {msg.supplementSource && (
                            <div className="mb-2 flex items-center gap-1 text-[10px] uppercase tracking-wider"
                                 style={{ color: 'var(--fg-dim, #9a9690)', fontFamily: 'var(--mono)' }}>
                              <span className="inline-block w-1.5 h-1.5 rounded-full"
                                    style={{ backgroundColor: msg.supplementSource === 'ai'
                                      ? 'var(--signature, #5b7ec9)'
                                      : '#10b981' }} />
                              {msg.supplementSource === 'ai'
                                ? t('supplement.fromAi', { defaultValue: 'From general AI knowledge (not your documents)' })
                                : t('supplement.fromWeb', { defaultValue: 'From web search' })}
                            </div>
                          )}
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={citationComponents}
                          >
                            {msg.content}
                          </ReactMarkdown>
                          {msg.refusal && !msg.supplementUsed && (
                            <SupplementActions
                              question={msg.originalQuestion}
                              busy={loading ? 'loading' : null}
                              onAskAi={(q) => handleSupplement(i, q, 'ai')}
                              onSearchWeb={(q) => handleSupplement(i, q, 'web')}
                            />
                          )}
                          {isLastAi && sources.length > 0 && (
                            <div className="flex items-center gap-1 mt-2 pt-2 border-t border-white/10 flex-wrap">
                              <span className="text-[11px] opacity-40 mr-1">{t('chat.sourcesLabel')}</span>
                              {sources.map((_, idx) => (
                                <CitationBadge key={idx} num={idx + 1} onClick={onCitationClick} />
                              ))}
                            </div>
                          )}
                          {isLastAi && (queryTypes.length > 0 || confidenceTier || contextInfo) && (
                            <div className="flex flex-wrap items-center gap-2 mt-2">
                              {queryTypes.length > 0 && <QueryTypeBadges types={queryTypes} />}
                              {confidenceTier && <ConfidenceBadge tier={confidenceTier} />}
                              {fastPath && <FastPathBadge />}
                              {contextInfo && <ContextTag {...contextInfo} />}
                            </div>
                          )}
                        </>
                      ) : (
                        <p style={{
                          fontFamily: "var(--display, 'Fraunces'), Georgia, serif",
                          fontStyle: 'italic',
                          fontWeight: 400,
                          letterSpacing: '-0.01em',
                          lineHeight: 1.45,
                        }}>{msg.content}</p>
                      )}
                    </div>
                  </div>
                )
              })}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        {/* Sources compact list — between messages and input */}
        {sources.length > 0 && (
          <div
            className="border-t shrink-0 max-h-[40%] overflow-y-auto"
            style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
          >
            <div
              className="px-3 py-2 text-[10px] uppercase tracking-wider opacity-40 sticky top-0"
              style={{ backgroundColor: 'var(--bg-1, #0c0c0f)' }}
            >
              {t('chat.sourcesWithCount', { count: sources.length })}
            </div>
            {displaySources.map(({ source: s, originalIndex }) => (
              <SourceCard
                key={originalIndex}
                source={s}
                index={originalIndex}
                isActive={originalIndex === selectedSource}
                onClick={() => {
                  setSelectedSource(originalIndex)
                  openTab({
                    doc_id: s.doc_id,
                    filename: s.source_file,
                    file_type: null,
                  })
                  activateTab(s.doc_id)
                }}
              />
            ))}
          </div>
        )}

        {/* Scope indicator + Input bar */}
        <div
          className="px-3 py-3 border-t shrink-0"
          style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
        >
          {(scopeDocId || scopeCollection || scopeDocIds) && (
            <div className="mb-2 flex items-center gap-2 text-xs"
                 style={{ color: 'var(--fg-dim, #9a9690)' }}>
              <FileText size={12} />
              <span className="truncate">{t('chat.searchingIn')} <strong style={{ color: 'var(--fg, #f4f2ee)' }}>
                {scopeDocIds
                  ? t('chat.nDocs', { count: scopeDocIds.length, defaultValue: `${scopeDocIds.length} selected documents` })
                  : scopeDocId ? scopeDocName
                  : scopeCollection}
              </strong></span>
              <button onClick={clearScope} className="opacity-40 hover:opacity-100 shrink-0"><X size={12} /></button>
            </div>
          )}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowHistory(h => !h)}
              className={cn(
                'p-2 rounded-lg transition-opacity shrink-0',
                showHistory ? 'opacity-100' : 'opacity-40 hover:opacity-100'
              )}
              title={t('chat.chatHistory')}
              style={{ color: 'var(--fg, #f4f2ee)' }}
            >
              <History size={16} />
            </button>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('chat.askPlaceholder')}
              disabled={loading}
              className="flex-1 min-w-0 px-3 py-2 rounded-lg text-sm outline-none disabled:opacity-50"
              style={{
                backgroundColor: 'var(--border-strong, rgba(255,255,255,0.14))',
                color: 'var(--fg, #f4f2ee)',
                border: '1px solid var(--border-strong, rgba(255,255,255,0.18))',
              }}
            />
            {loading ? (
              <button
                onClick={handleStop}
                className="p-2 rounded-lg transition-opacity hover:opacity-90 shrink-0"
                style={{
                  backgroundColor: 'var(--bad)',
                  color: 'var(--fg, #f4f2ee)',
                }}
                title={t('chat.stopGeneration')}
              >
                <Square size={16} fill="currentColor" />
              </button>
            ) : (
              <button
                onClick={handleSend}
                disabled={!input.trim()}
                className="p-2 rounded-lg transition-colors shrink-0"
                style={
                  input.trim()
                    ? {
                        backgroundColor: 'var(--signature)',
                        color: '#fff',
                        border: '1px solid var(--signature)',
                      }
                    : {
                        backgroundColor: 'transparent',
                        color: 'var(--signature)',
                        border: '1px solid var(--signature)',
                        opacity: 0.5,
                      }
                }
              >
                <Send size={16} />
              </button>
            )}
          </div>
        </div>
      </div>

    </div>
  )
}
