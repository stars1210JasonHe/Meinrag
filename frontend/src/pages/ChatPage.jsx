import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Send, FileText, Loader2, X, Square, PanelRightClose, PanelRightOpen } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { fetchSessionMessages, fetchDocumentChunks } from '@/lib/api'
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
import { ParagraphSkeleton, SourceCardSkeleton } from '@/components/skeletons'

// Substrings that identify a corpus-refusal answer. The English marker is
// anchored to the exact phrase the RAG_SYSTEM_PROMPT instructs the LLM to
// emit; the Chinese markers cover the localised refusal output. We match
// any of them. (Long-term fix: have the backend set an explicit
// `is_refusal: bool` flag in the response so this isn't substring-based.)
const REFUSAL_MARKERS = [
  'do not contain information',  // EN canonical
  '不包含',                       // ZH "do not contain"
  '没有相关',                      // ZH "no relevant"
  '无法回答',                      // ZH "cannot answer"
]
function _isRefusal(text) {
  if (typeof text !== 'string') return false
  const lower = text.toLowerCase()
  return REFUSAL_MARKERS.some(m => lower.includes(m.toLowerCase()))
}
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
  // G2: ?suggest= renders a *soft* ghost-text suggestion the user can dismiss
  // (whereas ?q= still hard-prefills for legacy callers like Dashboard's Ask).
  // ?chunk= opens that chunk's PDF tab + bbox highlight on mount.
  const suggestion = searchParams.get('suggest')
  const urlChunkParam = searchParams.get('chunk')
  const urlChunkIndex = urlChunkParam != null ? parseInt(urlChunkParam, 10) : null
  const urlSessionId = searchParams.get('session')

  const [sessionId, setSessionId] = useState(null)
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

  // Right-side chat panel collapse — persisted in localStorage so users
  // who prefer a wide PDF view can leave it hidden across sessions.
  const [chatCollapsed, setChatCollapsed] = useState(() => {
    if (typeof localStorage === 'undefined') return false
    return localStorage.getItem('meinrag.chatPanel.collapsed') === '1'
  })
  useEffect(() => {
    localStorage.setItem('meinrag.chatPanel.collapsed', chatCollapsed ? '1' : '0')
  }, [chatCollapsed])

  const {
    tabs,
    activeDocId,
    activeTab,
    openTab,
    closeTab,
    activateTab,
    resetTabs,
    openTabsForSources,
    togglePin,
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

  // When arriving at /chat?doc=<id>, open + activate that doc's PDF tab
  // immediately, even if there's no ?chunk= param. Without this the chat
  // panel renders but the doc area stays empty until the user runs a query.
  // The G2 chunk-jump effect below still adds the bbox highlight on top
  // when ?chunk= is also present.
  useEffect(() => {
    if (!scopeDocId) return
    openTab({
      doc_id: scopeDocId,
      filename: scopeDocName,
      file_type: null,
    })
    activateTab(scopeDocId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeDocId])

  // G2: when arriving with ?chunk=N, fetch the chunk metadata and seed sources
  // with a synthetic entry so PdfViewer/TextDocViewer jumps + bbox-highlights
  // before the user sends their first query. The first real query response
  // will replace this with actual citation sources.
  useEffect(() => {
    if (!scopeDocId || urlChunkIndex == null || Number.isNaN(urlChunkIndex)) return
    let cancelled = false
    ;(async () => {
      try {
        const data = await fetchDocumentChunks(scopeDocId, undefined, USER_ID)
        if (cancelled) return
        const match = (data?.chunks || []).find(c => c.chunk_index === urlChunkIndex)
        if (!match) return
        const synthetic = {
          doc_id: scopeDocId,
          chunk_index: match.chunk_index,
          page: match.page,
          bbox: match.bbox,
          source_file: match.source_file || scopeDocName,
          content: match.content || '',
        }
        setSources([synthetic])
        setSelectedSource(0)
        openTab({
          doc_id: scopeDocId,
          filename: synthetic.source_file,
          file_type: null,
        })
        activateTab(scopeDocId)
      } catch (err) {
        // Non-fatal — user just won't get the auto-jump. Don't disrupt.
        console.warn('chunk-jump: failed to fetch chunks', err)
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeDocId, urlChunkIndex])

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
          if (_isRefusal(m.content)) {
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

  // URL-driven session load: when ?session=<id> changes (set by HistoryPanel
  // in AppLayout), load that session's messages. Skip if it's already loaded.
  useEffect(() => {
    if (urlSessionId && urlSessionId !== sessionId) {
      loadSession(urlSessionId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSessionId])

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
      if (_isRefusal(fullAnswer)) {
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
      {/* History panel now lives in AppLayout (mounted only on /chat).
          It writes ?session=<id> to the URL; ChatPage reacts via the
          URL-sync effect above. */}

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
              onTogglePin={togglePin}
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

      {/* ── Chat sidebar (right) — collapsible ───────────────── */}
      {chatCollapsed ? (
        <aside
          className="w-8 border-l flex flex-col items-center shrink-0 py-2 gap-2"
          style={{
            borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
            backgroundColor: 'var(--bg-1, #0c0c0f)',
          }}
        >
          <button
            type="button"
            onClick={() => setChatCollapsed(false)}
            className="p-1.5 rounded transition-colors hover:bg-white/5"
            title={t('chat.expandChat', { defaultValue: 'Show chat' })}
            aria-label={t('chat.expandChat', { defaultValue: 'Show chat' })}
            style={{ color: 'var(--fg-dim)' }}
          >
            <PanelRightOpen size={14} />
          </button>
        </aside>
      ) : (
      <div
        className="w-[360px] border-l flex flex-col shrink-0"
        style={{
          borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
          backgroundColor: 'var(--bg-1, #0c0c0f)',
        }}
      >
        {/* Collapse toggle in a thin top bar */}
        <div
          className="flex items-center justify-end px-2 py-1 border-b shrink-0"
          style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
        >
          <button
            type="button"
            onClick={() => setChatCollapsed(true)}
            className="p-1.5 rounded transition-colors hover:bg-white/5"
            title={t('chat.collapseChat', { defaultValue: 'Hide chat' })}
            aria-label={t('chat.collapseChat', { defaultValue: 'Hide chat' })}
            style={{ color: 'var(--fg-dim)' }}
          >
            <PanelRightClose size={14} />
          </button>
        </div>

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
                          <>
                            {!msg.content && <ParagraphSkeleton />}
                            <Loader2 size={16} className="animate-spin opacity-40" />
                          </>
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
        {(sources.length > 0 || (loading && sources.length === 0)) && (
          <div
            className="border-t shrink-0 max-h-[40%] overflow-y-auto"
            style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
          >
            <div
              className="px-3 py-2 text-[10px] uppercase tracking-wider opacity-40 sticky top-0"
              style={{ backgroundColor: 'var(--bg-1, #0c0c0f)' }}
            >
              {sources.length > 0 ? t('chat.sourcesWithCount', { count: sources.length }) : t('chat.sourcesLabel')}
            </div>
            {loading && sources.length === 0 ? (
              <>
                <SourceCardSkeleton />
                <SourceCardSkeleton />
                <SourceCardSkeleton />
              </>
            ) : (
              displaySources.map(({ source: s, originalIndex }) => (
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
              ))
            )}
          </div>
        )}

        {/* Input bar with inline scope chip (F07) */}
        <div
          className="px-3 py-3 border-t shrink-0"
          style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}
        >
          <div className="flex items-center gap-2">
            {(scopeDocId || scopeCollection || scopeDocIds) && (
              <div
                className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] shrink-0 max-w-[40%]"
                style={{
                  backgroundColor: 'var(--signature-soft)',
                  color: 'var(--signature)',
                  border: '1px solid var(--signature)',
                }}
                title={
                  scopeDocIds
                    ? t('chat.nDocs', { count: scopeDocIds.length, defaultValue: `${scopeDocIds.length} selected documents` })
                    : scopeDocId ? scopeDocName
                    : scopeCollection
                }
              >
                <FileText size={11} className="shrink-0" />
                <span className="truncate">
                  {scopeDocIds
                    ? t('chat.nDocs', { count: scopeDocIds.length, defaultValue: `${scopeDocIds.length} selected documents` })
                    : scopeDocId ? scopeDocName
                    : scopeCollection}
                </span>
                <button
                  type="button"
                  onClick={clearScope}
                  className="opacity-60 hover:opacity-100 shrink-0"
                  aria-label={t('inputBar.clearFilter')}
                >
                  <X size={10} />
                </button>
              </div>
            )}
            <div className="flex-1 min-w-0 relative">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                /* G2: when a soft suggestion is showing, blank the placeholder
                   so the two texts don't visually overlap. */
                placeholder={suggestion && !input && !loading ? '' : t('chat.askPlaceholder')}
                disabled={loading}
                className="w-full px-3 py-2 rounded-lg text-sm outline-none disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--border-strong, rgba(255,255,255,0.14))',
                  color: 'var(--fg, #f4f2ee)',
                  border: '1px solid var(--border-strong, rgba(255,255,255,0.18))',
                }}
              />
              {/* G2: soft ghost-text suggestion. Visible only when the input is
                  empty AND a ?suggest= param is set. Click → fill input, focus.
                  Typing dismisses it implicitly (input no longer empty).
                  Italic + --fg-1 (full opacity) keeps contrast in BOTH themes. */}
              {suggestion && !input && !loading && (
                <button
                  type="button"
                  onClick={() => {
                    setInput(suggestion)
                    inputRef.current?.focus()
                  }}
                  title={t('graph.openChunkSuggestion')}
                  className="absolute inset-0 flex items-center px-3 text-sm text-left italic cursor-pointer rounded-lg"
                  style={{
                    color: 'var(--fg-1)',
                    background: 'transparent',
                    pointerEvents: 'auto',
                  }}
                >
                  <span className="truncate">{suggestion}</span>
                </button>
              )}
            </div>
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
      )}

    </div>
  )
}
