import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Search, Upload, MoreVertical, Trash2, Download, RefreshCw, FileText, X, MessageSquare } from 'lucide-react'
import { fetchDocuments, fetchCollections, deleteDocument } from '@/lib/api'
import { cn } from '@/lib/utils'

const USER_ID = 'admin' // TODO: from context

export default function DashboardPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [activeFilters, setActiveFilters] = useState([])
  const [menuOpen, setMenuOpen] = useState(null)
  const [uploading, setUploading] = useState(false)

  const { data: documentsData, isLoading } = useQuery({
    queryKey: ['documents', USER_ID],
    queryFn: () => fetchDocuments(USER_ID),
  })
  const documents = documentsData?.documents || documentsData || []

  const { data: collectionsData } = useQuery({
    queryKey: ['collections', USER_ID],
    queryFn: () => fetchCollections(USER_ID),
  })

  const deleteMutation = useMutation({
    mutationFn: (docId) => deleteDocument(docId, USER_ID),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['documents'] }),
  })

  // Build available filter tags from collections data
  const availableTags = useMemo(() => {
    if (!collectionsData) return []
    const tags = new Set()
    if (collectionsData.taxonomy_categories) {
      collectionsData.taxonomy_categories.forEach(c => tags.add(c))
    }
    if (collectionsData.existing_collections) {
      collectionsData.existing_collections.forEach(c => tags.add(c))
    }
    return [...tags].sort()
  }, [collectionsData])

  // Filter documents
  const filtered = useMemo(() => {
    let docs = Array.isArray(documents) ? documents : []
    if (search) {
      const q = search.toLowerCase()
      docs = docs.filter(d =>
        d.filename?.toLowerCase().includes(q) ||
        d.collections?.some(c => c.toLowerCase().includes(q))
      )
    }
    if (activeFilters.length > 0) {
      docs = docs.filter(d =>
        activeFilters.some(f => d.collections?.includes(f))
      )
    }
    return docs
  }, [documents, search, activeFilters])

  const toggleFilter = (tag) => {
    setActiveFilters(prev =>
      prev.includes(tag) ? prev.filter(t => t !== tag) : [...prev, tag]
    )
  }

  const handleUpload = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      const API_BASE = import.meta.env.VITE_API_URL
      const formData = new FormData()
      formData.append('file', file)
      const resp = await fetch(`${API_BASE}/documents/upload?auto_suggest=true`, {
        method: 'POST',
        headers: { 'X-User-Id': USER_ID },
        body: formData,
      })
      if (!resp.ok) throw new Error('Upload failed')
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      queryClient.invalidateQueries({ queryKey: ['collections'] })
    } catch (err) {
      console.error('Upload error:', err)
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  const handleDelete = (docId) => {
    if (confirm('Delete this document?')) {
      deleteMutation.mutate(docId)
    }
    setMenuOpen(null)
  }

  const handleDownload = (docId) => {
    const API_BASE = import.meta.env.VITE_API_URL
    window.open(`${API_BASE}/documents/${docId}/download`, '_blank')
    setMenuOpen(null)
  }

  const formatDate = (iso) => {
    if (!iso) return ''
    const d = new Date(iso)
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search bar */}
      <div className="p-4 border-b" style={{ borderColor: 'hsl(217 33% 17%)' }}>
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 opacity-40" />
          <input
            type="text"
            placeholder="Search documents, domains, topics..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: 'hsl(217 33% 17%)',
              color: 'hsl(210 40% 98%)',
              border: '1px solid hsl(217 33% 22%)',
            }}
          />
        </div>
      </div>

      {/* Filter tags */}
      {availableTags.length > 0 && (
        <div className="px-4 py-2 flex flex-wrap gap-1.5 border-b" style={{ borderColor: 'hsl(217 33% 17%)' }}>
          {availableTags.map(tag => (
            <button
              key={tag}
              onClick={() => toggleFilter(tag)}
              className={cn(
                'px-2.5 py-1 rounded-full text-xs transition-colors flex items-center gap-1',
                activeFilters.includes(tag) ? 'font-medium' : 'opacity-60 hover:opacity-100'
              )}
              style={{
                backgroundColor: activeFilters.includes(tag) ? 'hsl(250 80% 65%)' : 'hsl(217 33% 17%)',
                color: 'hsl(210 40% 98%)',
              }}
            >
              {tag}
              {activeFilters.includes(tag) && <X size={10} />}
            </button>
          ))}
          {activeFilters.length > 0 && (
            <>
              <button
                onClick={() => navigate(`/chat?collection=${encodeURIComponent(activeFilters[0])}`)}
                className="px-2.5 py-1 rounded-full text-xs flex items-center gap-1"
                style={{ backgroundColor: 'hsl(168 84% 40%)', color: '#fff' }}
              >
                <MessageSquare size={10} /> Chat
              </button>
              <button
                onClick={() => setActiveFilters([])}
                className="px-2 py-1 text-xs opacity-40 hover:opacity-100"
                style={{ color: 'hsl(210 40% 98%)' }}
              >
                Clear all
              </button>
            </>
          )}
        </div>
      )}

      {/* Document list */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="p-8 text-center opacity-40">Loading documents...</div>
        ) : filtered.length === 0 ? (
          <div className="p-8 text-center opacity-40">
            {search || activeFilters.length ? 'No documents match your filters.' : 'No documents yet. Upload one to get started.'}
          </div>
        ) : (
          <div className="divide-y" style={{ borderColor: 'hsl(217 33% 12%)' }}>
            {filtered.map(doc => (
              <div
                key={doc.doc_id}
                className="flex items-center gap-3 px-4 py-3 hover:bg-white/5 cursor-pointer transition-colors group"
                onClick={() => navigate(`/pdf/${doc.doc_id}`)}
              >
                <FileText size={18} className="shrink-0 opacity-40" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate" style={{ color: 'hsl(210 40% 98%)' }}>
                    {doc.filename}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    {doc.collections?.map(c => (
                      <span key={c} className="text-xs px-1.5 py-0.5 rounded"
                            style={{ backgroundColor: 'hsl(217 33% 17%)', color: 'hsl(215 20% 65%)' }}>
                        {c}
                      </span>
                    ))}
                  </div>
                </div>
                <span className="text-xs opacity-40 shrink-0">{formatDate(doc.uploaded_at)}</span>
                <span className="text-xs opacity-40 shrink-0">{doc.chunk_count} chunks</span>

                {/* Chat button */}
                <button
                  onClick={(e) => { e.stopPropagation(); navigate(`/chat?doc=${doc.doc_id}&name=${encodeURIComponent(doc.filename)}`) }}
                  className="p-1 rounded opacity-0 group-hover:opacity-60 hover:opacity-100 transition-opacity"
                  title="Chat about this document"
                >
                  <MessageSquare size={14} />
                </button>

                {/* Actions menu */}
                <div className="relative">
                  <button
                    onClick={(e) => { e.stopPropagation(); setMenuOpen(menuOpen === doc.doc_id ? null : doc.doc_id) }}
                    className="p-1 rounded opacity-0 group-hover:opacity-60 hover:opacity-100 transition-opacity"
                  >
                    <MoreVertical size={14} />
                  </button>
                  {menuOpen === doc.doc_id && (
                    <div className="absolute right-0 top-8 z-10 rounded-lg shadow-lg py-1 min-w-[140px]"
                         style={{ backgroundColor: 'hsl(222 47% 12%)', border: '1px solid hsl(217 33% 22%)' }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDownload(doc.doc_id) }}
                        className="flex items-center gap-2 px-3 py-2 text-sm w-full hover:bg-white/5"
                        style={{ color: 'hsl(210 40% 98%)' }}
                      >
                        <Download size={14} /> Download
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(doc.doc_id) }}
                        className="flex items-center gap-2 px-3 py-2 text-sm w-full hover:bg-white/5"
                        style={{ color: 'hsl(0 84% 60%)' }}
                      >
                        <Trash2 size={14} /> Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Upload button */}
      <div className="p-4 border-t" style={{ borderColor: 'hsl(217 33% 17%)' }}>
        <label className={cn(
          'flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm cursor-pointer transition-colors',
          uploading ? 'opacity-50 pointer-events-none' : 'hover:opacity-90'
        )}
        style={{ backgroundColor: 'hsl(250 80% 65%)', color: 'hsl(210 40% 98%)' }}>
          {uploading ? <RefreshCw size={16} className="animate-spin" /> : <Upload size={16} />}
          {uploading ? 'Uploading...' : 'Upload Document'}
          <input type="file" className="hidden" onChange={handleUpload} disabled={uploading}
                 accept=".pdf,.docx,.txt,.md,.html,.xlsx,.pptx" />
        </label>
      </div>
    </div>
  )
}
