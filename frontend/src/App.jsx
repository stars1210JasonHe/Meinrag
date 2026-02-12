import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { Upload, Send, FolderOpen, FileText, Trash2, Loader2, Sparkles, Download, Edit3, RefreshCw, ChevronDown, ChevronRight, User, Plus } from 'lucide-react'
import axios from 'axios'
import './App.css'

const API_BASE = 'http://localhost:8000'

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [documents, setDocuments] = useState([])
  const [collections, setCollections] = useState({ taxonomy_categories: [], existing_collections: [] })
  const [selectedCollection, setSelectedCollection] = useState(null)
  const [sessionId] = useState('session-' + Date.now())
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [connectionError, setConnectionError] = useState(false)

  // User system
  const [users, setUsers] = useState([])
  const [currentUser, setCurrentUser] = useState(() => localStorage.getItem('meinrag_user') || 'admin')
  const [showUserMenu, setShowUserMenu] = useState(false)
  const [showNewUser, setShowNewUser] = useState(false)
  const [newUserId, setNewUserId] = useState('')
  const [newUserName, setNewUserName] = useState('')

  // Source expansion
  const [expandedSources, setExpandedSources] = useState({})

  // Collection editing
  const [editingDoc, setEditingDoc] = useState(null)
  const [editCollections, setEditCollections] = useState('')
  const [reclassifying, setReclassifying] = useState(null)

  const messagesEndRef = useRef(null)
  const userMenuRef = useRef(null)

  const apiHeaders = { 'X-User-Id': currentUser }

  const fetchAll = async () => {
    try {
      const [usersRes, docsRes, colsRes] = await Promise.all([
        axios.get(`${API_BASE}/users`, { headers: apiHeaders }),
        axios.get(`${API_BASE}/documents`, { headers: apiHeaders }),
        axios.get(`${API_BASE}/documents/collections`, { headers: apiHeaders }),
      ])
      setUsers(usersRes.data)
      setDocuments(docsRes.data.documents)
      setCollections(colsRes.data)
      setConnectionError(false)
    } catch (error) {
      console.error('Failed to connect to backend:', error)
      setConnectionError(true)
    }
  }

  useEffect(() => {
    fetchAll()
  }, [currentUser])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Close user menu on outside click
  useEffect(() => {
    const handler = (e) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setShowUserMenu(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const fetchDocuments = async () => {
    try {
      const response = await axios.get(`${API_BASE}/documents`, { headers: apiHeaders })
      setDocuments(response.data.documents)
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    }
  }

  const fetchCollections = async () => {
    try {
      const response = await axios.get(`${API_BASE}/documents/collections`, { headers: apiHeaders })
      setCollections(response.data)
    } catch (error) {
      console.error('Failed to fetch collections:', error)
    }
  }

  const fetchUsers = async () => {
    try {
      const response = await axios.get(`${API_BASE}/users`, { headers: apiHeaders })
      setUsers(response.data)
    } catch (error) {
      console.error('Failed to fetch users:', error)
    }
  }

  const switchUser = (userId) => {
    setCurrentUser(userId)
    localStorage.setItem('meinrag_user', userId)
    setShowUserMenu(false)
    setSelectedCollection(null)
    setMessages([])
  }

  const createUser = async () => {
    if (!newUserId.trim() || !newUserName.trim()) return
    try {
      await axios.post(`${API_BASE}/users`, {
        user_id: newUserId.trim(),
        display_name: newUserName.trim(),
      }, { headers: apiHeaders })
      setNewUserId('')
      setNewUserName('')
      setShowNewUser(false)
      await fetchUsers()
      switchUser(newUserId.trim())
    } catch (error) {
      alert(error.response?.data?.detail || 'Failed to create user')
    }
  }

  const uploadDocument = async (file, autoSuggest = false) => {
    const formData = new FormData()
    formData.append('file', file)

    try {
      setUploading(true)
      const params = new URLSearchParams()
      if (selectedCollection && !autoSuggest) {
        params.append('collections', selectedCollection)
      }
      if (autoSuggest) {
        params.append('auto_suggest', 'true')
      }

      const response = await axios.post(
        `${API_BASE}/documents/upload?${params.toString()}`,
        formData,
        { headers: { ...apiHeaders, 'Content-Type': 'multipart/form-data' } }
      )

      const result = response.data
      let message = `Uploaded: ${result.filename}`
      if (result.suggested_collections) {
        message += ` (AI suggested: ${result.suggested_collections.join(', ')})`
      }
      if (result.collections && result.collections.length > 0) {
        message += ` | Collections: ${result.collections.join(', ')}`
      }

      setMessages(prev => [...prev, { type: 'system', content: message }])
      await fetchDocuments()
      await fetchCollections()
    } catch (error) {
      setMessages(prev => [...prev, {
        type: 'system',
        content: `Upload failed: ${error.response?.data?.detail || error.message}`
      }])
    } finally {
      setUploading(false)
    }
  }

  const handleFileUpload = (e, autoSuggest = false) => {
    const file = e.target.files?.[0]
    if (file) {
      uploadDocument(file, autoSuggest)
      e.target.value = ''
    }
  }

  const deleteDocument = async (docId) => {
    if (!confirm('Delete this document? This cannot be undone.')) return
    try {
      await axios.delete(`${API_BASE}/documents/${docId}`, { headers: apiHeaders })
      setMessages(prev => [...prev, { type: 'system', content: `Deleted document: ${docId}` }])
      await fetchDocuments()
      await fetchCollections()
    } catch (error) {
      console.error('Failed to delete document:', error)
    }
  }

  const downloadDocument = async (docId, filename) => {
    try {
      const response = await axios.get(`${API_BASE}/documents/${docId}/download`, {
        headers: apiHeaders,
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Failed to download:', error)
    }
  }

  const startEditCollections = (doc) => {
    setEditingDoc(doc.doc_id)
    setEditCollections(doc.collections.join(', '))
  }

  const saveCollections = async (docId) => {
    const newCollections = editCollections.split(',').map(c => c.trim()).filter(c => c)
    if (newCollections.length === 0) return

    try {
      await axios.patch(`${API_BASE}/documents/${docId}`, {
        collections: newCollections,
      }, { headers: apiHeaders })
      setEditingDoc(null)
      await fetchDocuments()
      await fetchCollections()
    } catch (error) {
      console.error('Failed to update collections:', error)
    }
  }

  const reclassifyDocument = async (docId) => {
    try {
      setReclassifying(docId)
      const response = await axios.post(
        `${API_BASE}/documents/${docId}/reclassify`,
        null,
        { headers: apiHeaders }
      )
      setMessages(prev => [...prev, {
        type: 'system',
        content: `Reclassified: ${response.data.collections.join(', ')}`
      }])
      await fetchDocuments()
      await fetchCollections()
    } catch (error) {
      console.error('Failed to reclassify:', error)
    } finally {
      setReclassifying(null)
    }
  }

  const toggleSource = (msgIdx, sourceIdx) => {
    const key = `${msgIdx}-${sourceIdx}`
    setExpandedSources(prev => ({ ...prev, [key]: !prev[key] }))
  }

  const sendMessage = async () => {
    if (!input.trim() || loading) return

    const question = input.trim()
    setInput('')
    setLoading(true)

    setMessages(prev => [...prev, { type: 'user', content: question }])

    try {
      const requestBody = {
        question,
        session_id: sessionId,
        top_k: 8
      }

      if (selectedCollection) {
        requestBody.collection = selectedCollection
      }

      const response = await axios.post(`${API_BASE}/query`, requestBody, { headers: apiHeaders })
      const result = response.data

      setMessages(prev => [...prev, {
        type: 'assistant',
        content: result.answer,
        sources: result.sources
      }])
    } catch (error) {
      setMessages(prev => [...prev, {
        type: 'system',
        content: `Error: ${error.response?.data?.detail || error.message}`
      }])
    } finally {
      setLoading(false)
    }
  }

  // Build collection list for sidebar: merge taxonomy + existing
  const allCollections = useMemo(() =>
    [...new Set(collections.existing_collections)].sort(),
    [collections.existing_collections]
  )

  const getCollectionCount = useCallback((collectionName) => {
    return documents.filter(d => d.collections && d.collections.includes(collectionName)).length
  }, [documents])

  const filteredDocuments = useMemo(() =>
    selectedCollection
      ? documents.filter(doc => doc.collections && doc.collections.includes(selectedCollection))
      : documents,
    [documents, selectedCollection]
  )

  const currentUserObj = users.find(u => u.user_id === currentUser)
  const hasConversation = messages.some(m => m.type === 'user' || m.type === 'assistant')

  return (
    <div className="app">
      {/* Header */}
      <div className="header">
        <h1>MEINRAG</h1>
        <div className="header-info">
          <span>{documents.length} {documents.length === 1 ? 'document' : 'documents'}</span>
          {selectedCollection && (
            <span className="badge">{selectedCollection}</span>
          )}

          {/* User Selector */}
          <div className="user-selector" ref={userMenuRef}>
            <button
              className="user-btn"
              onClick={() => setShowUserMenu(!showUserMenu)}
            >
              <User size={16} />
              <span>{currentUserObj?.display_name || currentUser}</span>
              <ChevronDown size={14} />
            </button>

            {showUserMenu && (
              <div className="user-menu">
                {users.map(user => (
                  <button
                    key={user.user_id}
                    className={`user-menu-item ${user.user_id === currentUser ? 'active' : ''}`}
                    onClick={() => switchUser(user.user_id)}
                  >
                    <User size={14} />
                    <span>{user.display_name}</span>
                  </button>
                ))}
                <div className="user-menu-divider" />
                {!showNewUser ? (
                  <button className="user-menu-item add-user" onClick={() => setShowNewUser(true)}>
                    <Plus size={14} />
                    <span>New User</span>
                  </button>
                ) : (
                  <div className="new-user-form">
                    <input
                      type="text"
                      placeholder="user-id"
                      value={newUserId}
                      onChange={(e) => setNewUserId(e.target.value)}
                      className="new-user-input"
                    />
                    <input
                      type="text"
                      placeholder="Display Name"
                      value={newUserName}
                      onChange={(e) => setNewUserName(e.target.value)}
                      className="new-user-input"
                    />
                    <div className="new-user-actions">
                      <button className="btn-sm btn-primary" onClick={createUser}>Create</button>
                      <button className="btn-sm btn-ghost" onClick={() => setShowNewUser(false)}>Cancel</button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>

      {connectionError && (
        <div className="connection-error">
          Cannot connect to backend at {API_BASE}.
          <button onClick={fetchAll}>Retry</button>
        </div>
      )}

      <div className="main-container">
        {/* Sidebar */}
        <div className="sidebar">
          {/* Collections */}
          <div className="section">
            <h3><FolderOpen size={16} /> Collections</h3>
            <div className="collection-list">
              <button
                className={`collection-item ${!selectedCollection ? 'active' : ''}`}
                onClick={() => setSelectedCollection(null)}
              >
                All Documents ({documents.length})
              </button>
              {allCollections.map(col => {
                const count = getCollectionCount(col)
                return (
                  <button
                    key={col}
                    className={`collection-item ${selectedCollection === col ? 'active' : ''}`}
                    onClick={() => setSelectedCollection(col)}
                  >
                    {col} <span className="count">({count})</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Documents */}
          <div className="section">
            <h3><FileText size={16} /> Documents</h3>
            <div className="document-list">
              {filteredDocuments.map(doc => (
                <div key={doc.doc_id} className="document-item">
                  <div className="doc-info">
                    <div className="doc-name">{doc.filename}</div>
                    {/* Collection tags */}
                    {editingDoc === doc.doc_id ? (
                      <div className="edit-collections">
                        <input
                          type="text"
                          value={editCollections}
                          onChange={(e) => setEditCollections(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && saveCollections(doc.doc_id)}
                          className="edit-collections-input"
                          placeholder="tag1, tag2, ..."
                          autoFocus
                        />
                        <div className="edit-actions">
                          <button className="btn-sm btn-primary" onClick={() => saveCollections(doc.doc_id)}>Save</button>
                          <button className="btn-sm btn-ghost" onClick={() => setEditingDoc(null)}>Cancel</button>
                        </div>
                      </div>
                    ) : (
                      <div className="doc-tags">
                        {doc.collections && doc.collections.map(c => (
                          <span key={c} className="tag" onClick={() => setSelectedCollection(c)}>{c}</span>
                        ))}
                      </div>
                    )}
                    <div className="doc-meta">
                      {doc.chunk_count} {doc.chunk_count === 1 ? 'chunk' : 'chunks'}
                    </div>
                  </div>
                  <div className="doc-actions">
                    <button
                      className="btn-icon"
                      onClick={() => startEditCollections(doc)}
                      title="Edit collections"
                    >
                      <Edit3 size={13} />
                    </button>
                    <button
                      className="btn-icon"
                      onClick={() => reclassifyDocument(doc.doc_id)}
                      title="AI Reclassify"
                      disabled={reclassifying === doc.doc_id}
                    >
                      {reclassifying === doc.doc_id ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />}
                    </button>
                    <button
                      className="btn-icon"
                      onClick={() => downloadDocument(doc.doc_id, doc.filename)}
                      title="Download"
                    >
                      <Download size={13} />
                    </button>
                    <button
                      className="btn-icon btn-icon-danger"
                      onClick={() => deleteDocument(doc.doc_id)}
                      title="Delete"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Upload */}
          <div className="section upload-section">
            <h3><Upload size={16} /> Upload</h3>
            <div className="upload-buttons">
              <label className="btn btn-primary">
                <Upload size={16} /> Upload Document
                <input
                  type="file"
                  onChange={(e) => handleFileUpload(e, false)}
                  style={{ display: 'none' }}
                  accept=".pdf,.docx,.txt,.md,.html,.xlsx,.pptx"
                  disabled={uploading}
                />
              </label>
              <label className="btn btn-secondary">
                <Sparkles size={14} /> Auto-Categorize
                <input
                  type="file"
                  onChange={(e) => handleFileUpload(e, true)}
                  style={{ display: 'none' }}
                  accept=".pdf,.docx,.txt,.md,.html,.xlsx,.pptx"
                  disabled={uploading}
                />
              </label>
            </div>
            {uploading && (
              <div className="upload-hint">
                <Loader2 size={14} className="spin" /> Processing...
              </div>
            )}
            {selectedCollection && !uploading && (
              <div className="upload-hint">
                Uploading to: <strong>{selectedCollection}</strong>
              </div>
            )}
          </div>
        </div>

        {/* Chat Area */}
        <div className="chat-container">
          <div className="messages">
            {!hasConversation && (
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
                      <li><strong>Multi-Collection:</strong> Documents can belong to multiple categories with a full taxonomy</li>
                      <li><strong>User Profiles:</strong> Switch between users with isolated document spaces</li>
                      <li><strong>AI Classification:</strong> Auto-categorize documents using a hierarchical taxonomy</li>
                      <li><strong>Source Citations:</strong> Click to expand chunk text and download original files</li>
                    </ul>
                  </div>
                </div>
              </div>
            )}

            {messages.map((msg, idx) => (
              <div key={idx} className={`message message-${msg.type}`}>
                {msg.type === 'user' && (
                  <div className="message-content">
                    <div className="message-text">{msg.content}</div>
                  </div>
                )}
                {msg.type === 'assistant' && (
                  <div className="message-content">
                    <div className="message-text">
                      {msg.content}
                      {msg.sources && msg.sources.length > 0 && (
                        <div className="sources">
                          <div className="sources-title">Sources</div>
                          {msg.sources.map((source, i) => (
                            <div key={i} className="source-item">
                              <div
                                className="source-header"
                                onClick={() => toggleSource(idx, i)}
                              >
                                {expandedSources[`${idx}-${i}`]
                                  ? <ChevronDown size={14} />
                                  : <ChevronRight size={14} />}
                                <span className="source-file">{source.source_file}</span>
                                {source.chunk_index !== null && (
                                  <span className="source-chunk-idx">chunk {source.chunk_index}</span>
                                )}
                                {source.doc_id && (
                                  <button
                                    className="source-download"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      downloadDocument(source.doc_id, source.source_file)
                                    }}
                                    title="Download file"
                                  >
                                    <Download size={12} />
                                  </button>
                                )}
                              </div>
                              {expandedSources[`${idx}-${i}`] && (
                                <div className="source-content">
                                  {source.content}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
                {msg.type === 'system' && (
                  <div className="system-message">{msg.content}</div>
                )}
              </div>
            ))}

            {loading && (
              <div className="message message-assistant">
                <div className="message-content">
                  <div className="message-text loading">
                    <Loader2 size={16} className="spin" /> Thinking...
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="input-container">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && sendMessage()}
              placeholder={
                selectedCollection
                  ? `Ask about ${selectedCollection} documents...`
                  : "Ask a question..."
              }
              disabled={loading}
            />
            <button
              onClick={sendMessage}
              disabled={loading || !input.trim()}
              className="btn-send"
            >
              <Send size={18} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
