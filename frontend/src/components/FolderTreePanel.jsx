import { useState, useMemo, useCallback } from 'react'
import { ChevronDown, ChevronRight, FolderOpen, FileText, Upload, Sparkles, Loader2, Trash2, Download, Edit3, RefreshCw } from 'lucide-react'
import { TAXONOMY, findCategoryForCollection, formatName } from '../taxonomy'

export default function FolderTreePanel({
  documents, collections, selectedFilter, onSelectFilter,
  onUpload, onAutoUpload, onDeleteDoc, onDownloadDoc,
  onEditCollections, onReclassify, uploading,
}) {
  const [expandedCategories, setExpandedCategories] = useState({})
  const [expandedDomains, setExpandedDomains] = useState({})
  const [dragOverTarget, setDragOverTarget] = useState(null)

  // Build tree: group documents under taxonomy categories
  const { tree, uncategorized } = useMemo(() => {
    const existingCols = new Set(collections.existing_collections || [])
    const treeData = {}
    const uncatDocs = []

    // Only show categories that have matching collections with docs
    for (const doc of documents) {
      let placed = false
      for (const col of (doc.collections || [])) {
        const match = findCategoryForCollection(col)
        if (match) {
          const cat = match.category
          if (!treeData[cat]) treeData[cat] = {}
          const domain = match.domain || col
          if (!treeData[cat][domain]) treeData[cat][domain] = []
          treeData[cat][domain].push(doc)
          placed = true
        }
      }
      if (!placed) uncatDocs.push(doc)
    }

    return { tree: treeData, uncategorized: uncatDocs }
  }, [documents, collections])

  const toggleCategory = (cat) => {
    setExpandedCategories(prev => ({ ...prev, [cat]: !prev[cat] }))
  }

  const toggleDomain = (domain) => {
    setExpandedDomains(prev => ({ ...prev, [domain]: !prev[domain] }))
  }

  const getCategoryDocCount = useCallback((cat) => {
    if (!tree[cat]) return 0
    const ids = new Set()
    Object.values(tree[cat]).forEach(docs => docs.forEach(d => ids.add(d.doc_id)))
    return ids.size
  }, [tree])

  const handleDrop = (e, collection) => {
    e.preventDefault()
    setDragOverTarget(null)
    const files = e.dataTransfer.files
    if (files.length > 0) {
      onUpload(files[0], collection)
    }
  }

  const handleDragOver = (e, target) => {
    e.preventDefault()
    setDragOverTarget(target)
  }

  const handleDragLeave = () => {
    setDragOverTarget(null)
  }

  const isFilterActive = (type, value) => {
    return selectedFilter.type === type && selectedFilter.value === value
  }

  return (
    <div className="folder-tree-panel">
      <div className="panel-header">
        <span className="panel-title">Categories</span>
      </div>

      {/* Upload buttons */}
      <div className="tree-upload-bar">
        <label className="tree-upload-btn">
          <Upload size={13} /> Upload
          <input type="file" onChange={e => { if (e.target.files[0]) { onUpload(e.target.files[0]); e.target.value = '' } }}
            style={{ display: 'none' }} accept=".pdf,.docx,.txt,.md,.html,.xlsx,.pptx" disabled={uploading} />
        </label>
        <label className="tree-upload-btn tree-auto-btn">
          <Sparkles size={13} /> Auto
          <input type="file" onChange={e => { if (e.target.files[0]) { onAutoUpload(e.target.files[0]); e.target.value = '' } }}
            style={{ display: 'none' }} accept=".pdf,.docx,.txt,.md,.html,.xlsx,.pptx" disabled={uploading} />
        </label>
        {uploading && <Loader2 size={14} className="spin" />}
      </div>

      {/* All Documents */}
      <div className="tree-content">
        <div
          className={`tree-node tree-all ${isFilterActive('all', null) ? 'active' : ''}`}
          onClick={() => onSelectFilter({ type: 'all', value: null })}
        >
          <FolderOpen size={14} />
          <span>All Documents ({documents.length})</span>
        </div>

        {/* Taxonomy tree */}
        {Object.keys(TAXONOMY).map(category => {
          const count = getCategoryDocCount(category)
          if (count === 0 && category !== 'other') return null
          const isExpanded = expandedCategories[category]

          return (
            <div key={category}>
              <div
                className={`tree-node tree-category ${isFilterActive('category', category) ? 'active' : ''} ${dragOverTarget === category ? 'drag-over' : ''}`}
                onClick={() => toggleCategory(category)}
                onDragOver={e => handleDragOver(e, category)}
                onDragLeave={handleDragLeave}
                onDrop={e => handleDrop(e, category)}
              >
                {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                <FolderOpen size={13} />
                <span className="tree-label">{formatName(category)}</span>
                <span className="tree-count">({count})</span>
              </div>

              {isExpanded && tree[category] && Object.entries(tree[category]).map(([domain, docs]) => {
                const isDomainExpanded = expandedDomains[domain]
                return (
                  <div key={domain} className="tree-domain-group">
                    <div
                      className={`tree-node tree-domain ${isFilterActive('collection', domain) ? 'active' : ''} ${dragOverTarget === domain ? 'drag-over' : ''}`}
                      onClick={() => { toggleDomain(domain); onSelectFilter({ type: 'collection', value: domain }) }}
                      onDragOver={e => handleDragOver(e, domain)}
                      onDragLeave={handleDragLeave}
                      onDrop={e => handleDrop(e, domain)}
                    >
                      {isDomainExpanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                      <span className="tree-label">{formatName(domain)}</span>
                      <span className="tree-count">({docs.length})</span>
                    </div>

                    {isDomainExpanded && docs.map(doc => (
                      <DocNode
                        key={`${domain}-${doc.doc_id}`}
                        doc={doc}
                        isActive={isFilterActive('doc', doc.doc_id)}
                        onSelect={() => onSelectFilter({ type: 'doc', value: doc.doc_id })}
                        onDelete={() => onDeleteDoc(doc.doc_id)}
                        onDownload={() => onDownloadDoc(doc.doc_id, doc.filename)}
                        onEdit={() => onEditCollections(doc)}
                        onReclassify={() => onReclassify(doc.doc_id)}
                      />
                    ))}
                  </div>
                )
              })}
            </div>
          )
        })}

        {/* Uncategorized */}
        {uncategorized.length > 0 && (
          <div>
            <div className="tree-node tree-category uncategorized">
              <FolderOpen size={13} />
              <span className="tree-label">Uncategorized</span>
              <span className="tree-count">({uncategorized.length})</span>
            </div>
            {uncategorized.map(doc => (
              <DocNode
                key={`uncat-${doc.doc_id}`}
                doc={doc}
                isActive={isFilterActive('doc', doc.doc_id)}
                onSelect={() => onSelectFilter({ type: 'doc', value: doc.doc_id })}
                onDelete={() => onDeleteDoc(doc.doc_id)}
                onDownload={() => onDownloadDoc(doc.doc_id, doc.filename)}
                onEdit={() => onEditCollections(doc)}
                onReclassify={() => onReclassify(doc.doc_id)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function DocNode({ doc, isActive, onSelect, onDelete, onDownload, onEdit, onReclassify }) {
  return (
    <div className={`tree-node tree-file ${isActive ? 'active' : ''}`} onClick={onSelect}>
      <FileText size={12} />
      <span className="tree-file-name" title={doc.filename}>
        {doc.filename.length > 22 ? doc.filename.slice(0, 20) + '...' : doc.filename}
      </span>
      <div className="tree-file-actions">
        <button onClick={e => { e.stopPropagation(); onEdit() }} title="Edit collections"><Edit3 size={11} /></button>
        <button onClick={e => { e.stopPropagation(); onReclassify() }} title="AI Reclassify"><RefreshCw size={11} /></button>
        <button onClick={e => { e.stopPropagation(); onDownload() }} title="Download"><Download size={11} /></button>
        <button className="danger" onClick={e => { e.stopPropagation(); onDelete() }} title="Delete"><Trash2 size={11} /></button>
      </div>
    </div>
  )
}
