import { useState, useCallback, useMemo } from 'react'

/**
 * Manages which documents are open as tabs in the Chat page's main area.
 *
 * Tabs persist across chat turns within a session. Sources from each answer
 * trigger auto-open + activation. User can close via X.
 *
 * Tab shape: { doc_id: string, filename: string, file_type: string }
 *   - file_type: the raw type string from backend (e.g. "pdf", "docx")
 *   - Renderer decides which component to use based on file_type
 */
export function useDocTabs() {
  const [tabs, setTabs] = useState([])           // ordered list of tabs
  const [activeDocId, setActiveDocId] = useState(null)

  /**
   * Open (or activate existing) tab for this doc.
   * If a tab for doc_id already exists, just activate it.
   * Otherwise, push a new tab to the end and activate it.
   */
  const openTab = useCallback((doc) => {
    if (!doc || !doc.doc_id) return
    setTabs(prev => {
      const exists = prev.some(t => t.doc_id === doc.doc_id)
      if (exists) return prev
      return [...prev, {
        doc_id: doc.doc_id,
        filename: doc.filename || doc.source_file || doc.doc_id,
        file_type: doc.file_type || _inferTypeFromFilename(doc.filename || doc.source_file),
      }]
    })
    setActiveDocId(doc.doc_id)
  }, [])

  /**
   * Close a tab. If it was active, fall back to the tab to its left
   * (or null if none left).
   */
  const closeTab = useCallback((doc_id) => {
    setTabs(prev => {
      const idx = prev.findIndex(t => t.doc_id === doc_id)
      if (idx === -1) return prev
      const next = prev.filter(t => t.doc_id !== doc_id)
      return next
    })
    setActiveDocId(current => {
      if (current !== doc_id) return current
      // Pick the tab that would remain to the left of the closed one
      const remaining = tabs.filter(t => t.doc_id !== doc_id)
      if (remaining.length === 0) return null
      const idx = tabs.findIndex(t => t.doc_id === doc_id)
      const nextActive = remaining[Math.max(0, idx - 1)]
      return nextActive?.doc_id ?? null
    })
  }, [tabs])

  /**
   * Switch to tab by doc_id. No-op if not open.
   */
  const activateTab = useCallback((doc_id) => {
    if (!doc_id) return
    setActiveDocId(current => {
      if (current === doc_id) return current
      // Only switch if tab is actually open
      const exists = tabs.some(t => t.doc_id === doc_id)
      return exists ? doc_id : current
    })
  }, [tabs])

  /**
   * Reset everything (e.g. on session switch).
   */
  const resetTabs = useCallback(() => {
    setTabs([])
    setActiveDocId(null)
  }, [])

  /**
   * Given an array of source objects (from a chat answer), open tabs for
   * every unique doc_id. Returns the first doc_id encountered — caller
   * can choose to activate it or not.
   */
  const openTabsForSources = useCallback((sources) => {
    if (!sources || sources.length === 0) return null
    const seen = new Set()
    const newTabs = []
    for (const s of sources) {
      if (!s.doc_id || seen.has(s.doc_id)) continue
      seen.add(s.doc_id)
      newTabs.push({
        doc_id: s.doc_id,
        filename: s.source_file || s.doc_id,
        file_type: _inferTypeFromFilename(s.source_file),
      })
    }
    if (newTabs.length === 0) return null
    setTabs(prev => {
      const existingIds = new Set(prev.map(t => t.doc_id))
      const toAdd = newTabs.filter(t => !existingIds.has(t.doc_id))
      return [...prev, ...toAdd]
    })
    return newTabs[0].doc_id
  }, [])

  const activeTab = useMemo(
    () => tabs.find(t => t.doc_id === activeDocId) || null,
    [tabs, activeDocId],
  )

  return {
    tabs,
    activeDocId,
    activeTab,
    openTab,
    closeTab,
    activateTab,
    resetTabs,
    openTabsForSources,
  }
}

function _inferTypeFromFilename(filename) {
  if (!filename) return 'unknown'
  const lower = filename.toLowerCase()
  for (const ext of ['pdf', 'docx', 'doc', 'txt', 'md', 'html', 'xlsx', 'xls', 'pptx', 'ppt']) {
    if (lower.endsWith('.' + ext)) return ext
  }
  return 'unknown'
}
