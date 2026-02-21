import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'
import 'highlight.js/styles/github-dark.css'

import Header from './components/Header'
import Sidebar from './components/Sidebar'
import ChatArea from './components/ChatArea'

import { fetchDocuments, fetchCollections, uploadDocument, deleteDocument, downloadDocument, patchDocumentCollections, reclassifyDocument } from './api/documents'
import { fetchUsers, createUser } from './api/users'
import { listSessions, getSessionMessages, deleteSession } from './api/sessions'
import { sendQuery, sendQueryStream, sendChunkContextQuery, sendAskAI, sendAskAIStream } from './api/query'
import { API_BASE } from './api/client'

function App() {
  // Global state
  const [currentUser, setCurrentUser] = useState(() => localStorage.getItem('meinrag_user') || 'admin')
  const [users, setUsers] = useState([])
  const [documents, setDocuments] = useState([])
  const [collections, setCollections] = useState({ taxonomy_categories: [], existing_collections: [] })
  const [sessions, setSessions] = useState([])

  // Chat state
  const [sessionId, setSessionId] = useState('session-' + Date.now())
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)

  // Filter state: { type: 'all' | 'collection' | 'doc' | 'category', value: string | null }
  const [selectedFilter, setSelectedFilter] = useState({ type: 'all', value: null })

  // UI state
  const [uploading, setUploading] = useState(false)
  const [connectionError, setConnectionError] = useState(false)
  const [showUserMenu, setShowUserMenu] = useState(false)

  const userMenuRef = useRef(null)

  // --- Data fetching ---
  const refreshAll = useCallback(async () => {
    try {
      const [u, d, c] = await Promise.all([
        fetchUsers(currentUser),
        fetchDocuments(currentUser),
        fetchCollections(currentUser),
      ])
      setUsers(u)
      setDocuments(d)
      setCollections(c)
      setConnectionError(false)
      // Sessions fetch is non-critical — don't block the whole UI if it fails
      try {
        const s = await listSessions(currentUser)
        setSessions(s)
      } catch {
        setSessions([])
      }
    } catch {
      setConnectionError(true)
    }
  }, [currentUser])

  useEffect(() => { refreshAll() }, [refreshAll])

  // Close user menu on outside click
  useEffect(() => {
    const handler = e => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setShowUserMenu(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // --- User actions ---
  const switchUser = (userId) => {
    setCurrentUser(userId)
    localStorage.setItem('meinrag_user', userId)
    setShowUserMenu(false)
    setSelectedFilter({ type: 'all', value: null })
    setMessages([])
    setSessionId('session-' + Date.now())
  }

  const handleCreateUser = async (id, name) => {
    await createUser(id, name, currentUser)
    switchUser(id)
  }

  // --- Chat actions ---
  const startNewChat = () => {
    setSessionId('session-' + Date.now())
    setMessages([])
  }

  const selectSession = async (sid) => {
    try {
      const msgs = await getSessionMessages(sid, currentUser)
      setSessionId(sid)
      setMessages(msgs.map(m => ({
        type: m.role === 'human' ? 'user' : 'assistant',
        content: m.content,
        sources: [],
      })))
    } catch {
      console.error('Failed to load session')
    }
  }

  const handleDeleteSession = async (sid) => {
    try {
      await deleteSession(sid, currentUser)
      setSessions(prev => prev.filter(s => s.session_id !== sid))
      if (sid === sessionId) startNewChat()
    } catch {
      console.error('Failed to delete session')
    }
  }

  const handleSendMessage = async (question, { forceWebSearch = false } = {}) => {
    if (loading) return
    setLoading(true)
    setMessages(prev => [...prev, { type: 'user', content: question }])

    // Add placeholder assistant message for streaming
    const assistantMsg = {
      type: 'assistant',
      content: '',
      sources: [],
      web_search_used: false,
      streaming: true,
      question,
      ai_answer: null,
      ai_loading: false,
    }
    setMessages(prev => [...prev, assistantMsg])

    const queryOpts = { sessionId, userId: currentUser, forceWebSearch }
    if (selectedFilter.type === 'collection') queryOpts.collection = selectedFilter.value
    if (selectedFilter.type === 'doc') queryOpts.docIds = [selectedFilter.value]

    try {
      await sendQueryStream(question, queryOpts, {
        onSources: (data) => {
          setMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last?.streaming) {
              updated[updated.length - 1] = { ...last, sources: data.sources || [], web_search_used: data.web_search_used || false }
            }
            return updated
          })
        },
        onToken: (token) => {
          setMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last?.streaming) {
              updated[updated.length - 1] = { ...last, content: last.content + token }
            }
            return updated
          })
        },
        onDone: () => {
          setMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last?.streaming) {
              updated[updated.length - 1] = { ...last, streaming: false }
            }
            return updated
          })
        },
        onError: (data) => {
          setMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last?.streaming) {
              updated[updated.length - 1] = { ...last, content: last.content || `Error: ${data.detail}`, streaming: false }
            }
            return updated
          })
        },
      })
      listSessions(currentUser).then(setSessions).catch(() => {})
    } catch (error) {
      // Fallback to non-streaming if stream fails
      try {
        const result = await sendQuery(question, queryOpts)
        setMessages(prev => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last?.streaming) {
            updated[updated.length - 1] = {
              ...last,
              content: result.answer,
              sources: result.sources,
              web_search_used: result.web_search_used || false,
              streaming: false,
            }
          }
          return updated
        })
        listSessions(currentUser).then(setSessions).catch(() => {})
      } catch (fallbackErr) {
        setMessages(prev => {
          const updated = [...prev]
          const last = updated[updated.length - 1]
          if (last?.streaming) {
            updated[updated.length - 1] = {
              ...last,
              content: `Error: ${fallbackErr.response?.data?.detail || fallbackErr.message}`,
              streaming: false,
            }
          }
          return updated
        })
      }
    } finally {
      setLoading(false)
    }
  }

  const handleAskAboutChunk = async (source, question) => {
    if (loading) return
    setLoading(true)
    setMessages(prev => [...prev, { type: 'user', content: question }])

    try {
      const result = await sendChunkContextQuery(question, {
        sourceType: source.source_type || 'document',
        docId: source.doc_id,
        chunkIndex: source.chunk_index,
        url: source.url,
        sessionId,
        userId: currentUser,
      })
      setMessages(prev => [...prev, {
        type: 'assistant',
        content: result.answer,
        sources: [],
      }])
      listSessions(currentUser).then(setSessions).catch(() => {})
    } catch (error) {
      setMessages(prev => [...prev, {
        type: 'system',
        content: `Error: ${error.response?.data?.detail || error.message}`,
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleAskAI = async (msgIdx) => {
    const msg = messages[msgIdx]
    if (!msg || msg.type !== 'assistant' || msg.ai_answer || msg.ai_loading) return
    const question = msg.question
    if (!question) return

    setMessages(prev => prev.map((m, i) =>
      i === msgIdx ? { ...m, ai_loading: true, ai_answer: '' } : m
    ))

    try {
      await sendAskAIStream(question, { userId: currentUser }, {
        onToken: (token) => {
          setMessages(prev => prev.map((m, i) =>
            i === msgIdx ? { ...m, ai_answer: (m.ai_answer || '') + token } : m
          ))
        },
        onDone: () => {
          setMessages(prev => prev.map((m, i) =>
            i === msgIdx ? { ...m, ai_loading: false } : m
          ))
        },
        onError: (data) => {
          setMessages(prev => prev.map((m, i) =>
            i === msgIdx ? { ...m, ai_answer: `Error: ${data.detail}`, ai_loading: false } : m
          ))
        },
      })
    } catch (error) {
      // Fallback to non-streaming
      try {
        const result = await sendAskAI(question, { userId: currentUser })
        setMessages(prev => prev.map((m, i) =>
          i === msgIdx ? { ...m, ai_answer: result.answer, ai_loading: false } : m
        ))
      } catch (fallbackErr) {
        setMessages(prev => prev.map((m, i) =>
          i === msgIdx ? { ...m, ai_answer: `Error: ${fallbackErr.response?.data?.detail || fallbackErr.message}`, ai_loading: false } : m
        ))
      }
    }
  }

  // --- Document actions ---
  const handleUpload = async (file, collection) => {
    try {
      setUploading(true)
      const targetCollection = collection || (selectedFilter.type === 'collection' ? selectedFilter.value : undefined)
      const result = await uploadDocument(file, currentUser, { collection: targetCollection })
      let message = `Uploaded: ${result.filename}`
      if (result.suggested_collections) message += ` (AI suggested: ${result.suggested_collections.join(', ')})`
      if (result.collections?.length) message += ` | Collections: ${result.collections.join(', ')}`
      setMessages(prev => [...prev, { type: 'system', content: message }])
      await refreshAll()
    } catch (error) {
      setMessages(prev => [...prev, { type: 'system', content: `Upload failed: ${error.response?.data?.detail || error.message}` }])
    } finally {
      setUploading(false)
    }
  }

  const handleAutoUpload = async (file) => {
    try {
      setUploading(true)
      const result = await uploadDocument(file, currentUser, { autoSuggest: true })
      let message = `Uploaded: ${result.filename}`
      if (result.suggested_collections) message += ` (AI suggested: ${result.suggested_collections.join(', ')})`
      if (result.collections?.length) message += ` | Collections: ${result.collections.join(', ')}`
      setMessages(prev => [...prev, { type: 'system', content: message }])
      await refreshAll()
    } catch (error) {
      setMessages(prev => [...prev, { type: 'system', content: `Upload failed: ${error.response?.data?.detail || error.message}` }])
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteDoc = async (docId) => {
    if (!confirm('Delete this document? This cannot be undone.')) return
    try {
      await deleteDocument(docId, currentUser)
      setMessages(prev => [...prev, { type: 'system', content: `Deleted document: ${docId}` }])
      await refreshAll()
    } catch {
      console.error('Failed to delete document')
    }
  }

  const handleDownloadDoc = async (docId, filename) => {
    try { await downloadDocument(docId, filename, currentUser) } catch { console.error('Download failed') }
  }

  const handleEditCollections = async (doc) => {
    const input = prompt('Edit collections (comma-separated):', doc.collections.join(', '))
    if (input === null) return
    const newCols = input.split(',').map(c => c.trim()).filter(Boolean)
    if (newCols.length === 0) return
    try {
      await patchDocumentCollections(doc.doc_id, newCols, currentUser)
      await refreshAll()
    } catch { console.error('Failed to update') }
  }

  const handleReclassify = async (docId) => {
    try {
      const result = await reclassifyDocument(docId, currentUser)
      setMessages(prev => [...prev, { type: 'system', content: `Reclassified: ${result.collections.join(', ')}` }])
      await refreshAll()
    } catch { console.error('Reclassify failed') }
  }

  const currentUserObj = users.find(u => u.user_id === currentUser)

  return (
    <div className="app">
      <Header
        documentCount={documents.length}
        currentUser={currentUser}
        currentUserObj={currentUserObj}
        users={users}
        showUserMenu={showUserMenu}
        setShowUserMenu={setShowUserMenu}
        onSwitchUser={switchUser}
        onCreateUser={handleCreateUser}
        userMenuRef={userMenuRef}
      />

      {connectionError && (
        <div className="connection-error">
          Cannot connect to backend at {API_BASE}.
          <button onClick={refreshAll}>Retry</button>
        </div>
      )}

      <div className="main-container">
        <Sidebar
          sessions={sessions}
          currentSessionId={sessionId}
          onNewChat={startNewChat}
          onSelectSession={selectSession}
          onDeleteSession={handleDeleteSession}
          documents={documents}
          collections={collections}
          selectedFilter={selectedFilter}
          onSelectFilter={setSelectedFilter}
          onUpload={handleUpload}
          onAutoUpload={handleAutoUpload}
          onDeleteDoc={handleDeleteDoc}
          onDownloadDoc={handleDownloadDoc}
          onEditCollections={handleEditCollections}
          onReclassify={handleReclassify}
          uploading={uploading}
        />

        <ChatArea
          messages={messages}
          loading={loading}
          selectedFilter={selectedFilter}
          onSendMessage={handleSendMessage}
          onDownloadDoc={handleDownloadDoc}
          onAskAboutChunk={handleAskAboutChunk}
          onAskAI={handleAskAI}
          onClearFilter={() => setSelectedFilter({ type: 'all', value: null })}
        />
      </div>
    </div>
  )
}

export default App
