import { useState, useEffect, useRef } from 'react'
import { Upload, Send, FolderOpen, FileText, Trash2, Loader2, Sparkles } from 'lucide-react'
import axios from 'axios'
import './App.css'

const API_BASE = 'http://localhost:8000'

function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [documents, setDocuments] = useState([])
  const [collections, setCollections] = useState([])
  const [selectedCollection, setSelectedCollection] = useState(null)
  const [sessionId] = useState('user-' + Date.now())
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const messagesEndRef = useRef(null)

  useEffect(() => {
    fetchDocuments()
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    // Extract unique collections from documents
    const uniqueCollections = [...new Set(
      documents
        .map(doc => doc.collection)
        .filter(c => c !== null && c !== undefined)
    )]
    setCollections(uniqueCollections)
  }, [documents])

  const fetchDocuments = async () => {
    try {
      const response = await axios.get(`${API_BASE}/documents`)
      setDocuments(response.data.documents)
    } catch (error) {
      console.error('Failed to fetch documents:', error)
    }
  }

  const uploadDocument = async (file, autoSuggest = false) => {
    const formData = new FormData()
    formData.append('file', file)

    try {
      setUploading(true)
      const params = new URLSearchParams()
      if (selectedCollection && !autoSuggest) {
        params.append('collection', selectedCollection)
      }
      if (autoSuggest) {
        params.append('auto_suggest', 'true')
      }

      const response = await axios.post(
        `${API_BASE}/documents/upload?${params.toString()}`,
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' }
        }
      )

      const result = response.data
      let message = `✅ Uploaded: ${result.filename}`
      if (result.suggested_collection) {
        message += ` (AI suggested: ${result.suggested_collection})`
      }
      if (result.collection) {
        message += ` → Collection: ${result.collection}`
      }

      setMessages(prev => [...prev, {
        type: 'system',
        content: message
      }])

      await fetchDocuments()
    } catch (error) {
      setMessages(prev => [...prev, {
        type: 'system',
        content: `❌ Upload failed: ${error.response?.data?.detail || error.message}`
      }])
    } finally {
      setUploading(false)
    }
  }

  const handleFileUpload = (e, autoSuggest = false) => {
    const file = e.target.files?.[0]
    if (file) {
      uploadDocument(file, autoSuggest)
      e.target.value = '' // Reset input
    }
  }

  const deleteDocument = async (docId) => {
    try {
      await axios.delete(`${API_BASE}/documents/${docId}`)
      setMessages(prev => [...prev, {
        type: 'system',
        content: `🗑️ Deleted document: ${docId}`
      }])
      await fetchDocuments()
    } catch (error) {
      console.error('Failed to delete document:', error)
    }
  }

  const sendMessage = async () => {
    if (!input.trim() || loading) return

    const question = input.trim()
    setInput('')
    setLoading(true)

    // Add user message
    setMessages(prev => [...prev, {
      type: 'user',
      content: question
    }])

    try {
      const requestBody = {
        question,
        session_id: sessionId,
        top_k: 8
      }

      if (selectedCollection) {
        requestBody.collection = selectedCollection
      }

      const response = await axios.post(`${API_BASE}/query`, requestBody)
      const result = response.data

      // Add AI response
      setMessages(prev => [...prev, {
        type: 'assistant',
        content: result.answer,
        sources: result.sources
      }])
    } catch (error) {
      setMessages(prev => [...prev, {
        type: 'system',
        content: `❌ Error: ${error.response?.data?.detail || error.message}`
      }])
    } finally {
      setLoading(false)
    }
  }

  const filteredDocuments = selectedCollection
    ? documents.filter(doc => doc.collection === selectedCollection)
    : documents

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
        </div>
      </div>

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
              {collections.map(collection => {
                const count = documents.filter(d => d.collection === collection).length
                return (
                  <button
                    key={collection}
                    className={`collection-item ${selectedCollection === collection ? 'active' : ''}`}
                    onClick={() => setSelectedCollection(collection)}
                  >
                    {collection} <span className="count">({count})</span>
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
                    {doc.collection && (
                      <div className="doc-collection">{doc.collection}</div>
                    )}
                    <div className="doc-meta">
                      {doc.chunk_count} {doc.chunk_count === 1 ? 'chunk' : 'chunks'}
                    </div>
                  </div>
                  <button
                    className="btn-icon"
                    onClick={() => deleteDocument(doc.doc_id)}
                    title="Delete"
                  >
                    <Trash2 size={14} />
                  </button>
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
            {selectedCollection && (
              <div className="upload-hint">
                Uploading to: <strong>{selectedCollection}</strong>
              </div>
            )}
          </div>
        </div>

        {/* Chat Area */}
        <div className="chat-container">
          <div className="messages">
            {messages.length === 0 && (
              <div className="welcome">
                <div className="welcome-header">
                  <h1>Welcome to MEINRAG</h1>
                  <p className="welcome-subtitle">Your intelligent document assistant</p>
                </div>

                <div className="welcome-content">
                  <div className="intro-text">
                    <p>Ask questions about your documents in natural language.</p>
                    <p>Works with English and Chinese (中文).</p>
                  </div>

                  <div className="quick-start">
                    <h3>Get Started</h3>
                    <ol>
                      <li>Upload your documents using the sidebar</li>
                      <li>Organize them into collections (optional)</li>
                      <li>Ask any question about your content</li>
                    </ol>
                  </div>

                  <div className="features-list">
                    <h3>Features</h3>
                    <ul>
                      <li><strong>Smart Collections:</strong> Organize documents by topic or let AI suggest categories automatically</li>
                      <li><strong>Contextual Conversations:</strong> Ask follow-up questions and maintain conversation context</li>
                      <li><strong>Intelligent Search:</strong> Combines semantic understanding with keyword matching for better results</li>
                      <li><strong>Source Citations:</strong> Every answer includes references to the source documents</li>
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
                              {source.source_file}
                              {source.chunk_index !== null && ` (chunk ${source.chunk_index})`}
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
                  : "Ask a question... (支持中文)"
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
