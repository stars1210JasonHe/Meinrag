import { useState, useCallback, useMemo } from 'react'

/**
 * Manages which documents are open as tabs in the Chat page's main area.
 *
 * Tabs persist across chat turns within a session. Sources from each answer
 * trigger auto-open + activation. User can close via X.
 *
 * Tab shape: { doc_id: string, filename: string, file_type: string, pinned: boolean }
 *   - file_type: the raw type string from backend (e.g. "pdf", "docx")
 *   - pinned: when true, the tab refuses to close until unpinned (matches
 *     browser tab pin semantics — protects against accidental close).
 *   - Renderer decides which component to use based on file_type.
 *
 * Sort invariant: pinned tabs come first (in insertion order), then
 * unpinned tabs (in insertion order). Pin/unpin re-sorts in place.
 */
export function useDocTabs() {
  const [tabs, setTabs] = useState([])           // ordered list of tabs
  const [activeDocId, setActiveDocId] = useState(null)

  /**
   * Open (or activate existing) tab for this doc.
   * If a tab for doc_id already exists, just activate it.
   * Otherwise, push a new tab to the end (after any pinned tabs) and activate it.
   */
  const openTab = useCallback((doc) => {
    if (!doc || !doc.doc_id) return
    setTabs(prev => {
      const exists = prev.some(t => t.doc_id === doc.doc_id)
      if (exists) return prev
      const newTab = {
        doc_id: doc.doc_id,
        filename: doc.filename || doc.source_file || doc.doc_id,
        file_type: doc.file_type || _inferTypeFromFilename(doc.filename || doc.source_file),
        pinned: false,
      }
      // Insert after the last pinned tab so pinned stays first.
      const lastPinned = prev.findLastIndex(t => t.pinned)
      const insertAt = lastPinned >= 0 ? lastPinned + 1 : prev.length
      return [...prev.slice(0, insertAt), newTab, ...prev.slice(insertAt)]
    })
    setActiveDocId(doc.doc_id)
  }, [])

  /**
   * Close a tab. Refuses if pinned. If it was active, fall back to the
   * tab to its left (or null if none left).
   */
  const closeTab = useCallback((doc_id) => {
    const target = tabs.find(t => t.doc_id === doc_id)
    if (!target || target.pinned) return  // pinned tabs refuse to close
    setTabs(prev => {
      const idx = prev.findIndex(t => t.doc_id === doc_id)
      if (idx === -1) return prev
      return prev.filter(t => t.doc_id !== doc_id)
    })
    setActiveDocId(current => {
      if (current !== doc_id) return current
      const remaining = tabs.filter(t => t.doc_id !== doc_id)
      if (remaining.length === 0) return null
      const idx = tabs.findIndex(t => t.doc_id === doc_id)
      const nextActive = remaining[Math.max(0, idx - 1)]
      return nextActive?.doc_id ?? null
    })
  }, [tabs])

  /**
   * Toggle pinned state on a tab. Re-sorts so pinned-first invariant holds.
   */
  const togglePin = useCallback((doc_id) => {
    setTabs(prev => {
      const idx = prev.findIndex(t => t.doc_id === doc_id)
      if (idx === -1) return prev
      const target = { ...prev[idx], pinned: !prev[idx].pinned }
      const others = prev.filter((_, i) => i !== idx)
      // Re-insert at the boundary between pinned and unpinned.
      if (target.pinned) {
        const lastPinned = others.findLastIndex(t => t.pinned)
        const insertAt = lastPinned >= 0 ? lastPinned + 1 : 0
        return [...others.slice(0, insertAt), target, ...others.slice(insertAt)]
      } else {
        // Becoming unpinned — slot in just after the last pinned tab.
        const lastPinned = others.findLastIndex(t => t.pinned)
        const insertAt = lastPinned >= 0 ? lastPinned + 1 : 0
        return [...others.slice(0, insertAt), target, ...others.slice(insertAt)]
      }
    })
  }, [])

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
        pinned: false,
      })
    }
    if (newTabs.length === 0) return null
    setTabs(prev => {
      const existingIds = new Set(prev.map(t => t.doc_id))
      const toAdd = newTabs.filter(t => !existingIds.has(t.doc_id))
      // Slot new tabs after the last pinned tab so pinned-first holds.
      const lastPinned = prev.findLastIndex(t => t.pinned)
      const insertAt = lastPinned >= 0 ? lastPinned + 1 : prev.length
      return [...prev.slice(0, insertAt), ...toAdd, ...prev.slice(insertAt)]
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
    togglePin,
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
