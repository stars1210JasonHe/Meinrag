import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'

/**
 * Multi-select state for the Dashboard → Ask/Visualize/Save flow.
 *
 * State model (atomic for v1):
 *   { docs: Set<doc_id>, collections: Set<collection_name> }
 *
 * - Shift-click a doc toggles docs set entry
 * - Shift-click a collection folder toggles the collection entry (atomic — all-or-nothing)
 * - Collections are expanded to doc_ids at action time (Ask / Visualize / Save)
 *
 * Persistence:
 *   localStorage key `meinrag.selection.${userId}` — per-user so switching users doesn't leak.
 *   Multi-tab sync via 'storage' events.
 *
 * Undo:
 *   `clearWithUndo()` saves snapshot; `undo()` restores. Toast-based elsewhere.
 */

const SelectionContext = createContext(null)

function makeStorageKey(userId) {
  return `meinrag.selection.${userId || 'admin'}`
}

function loadFromStorage(userId) {
  try {
    const raw = localStorage.getItem(makeStorageKey(userId))
    if (!raw) return { docs: new Set(), collections: new Set() }
    const parsed = JSON.parse(raw)
    return {
      docs: new Set(parsed.docs || []),
      collections: new Set(parsed.collections || []),
    }
  } catch {
    return { docs: new Set(), collections: new Set() }
  }
}

function saveToStorage(userId, state) {
  try {
    localStorage.setItem(makeStorageKey(userId), JSON.stringify({
      docs: [...state.docs],
      collections: [...state.collections],
    }))
  } catch {
    // ignore (private mode / quota)
  }
}

export function SelectionProvider({ userId = 'admin', children }) {
  const [state, setState] = useState(() => loadFromStorage(userId))
  const snapshotRef = useRef(null) // for undo
  const userIdRef = useRef(userId)

  // Reset state if userId changes (user switch)
  useEffect(() => {
    if (userIdRef.current !== userId) {
      userIdRef.current = userId
      setState(loadFromStorage(userId))
    }
  }, [userId])

  // Persist on change
  useEffect(() => {
    saveToStorage(userId, state)
  }, [userId, state])

  // Multi-tab sync
  useEffect(() => {
    const key = makeStorageKey(userId)
    const handler = (e) => {
      if (e.key !== key) return
      if (!e.newValue) {
        setState({ docs: new Set(), collections: new Set() })
        return
      }
      try {
        const parsed = JSON.parse(e.newValue)
        setState({
          docs: new Set(parsed.docs || []),
          collections: new Set(parsed.collections || []),
        })
      } catch {
        /* ignore malformed */
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [userId])

  const api = useMemo(() => ({
    docs: state.docs,
    collections: state.collections,
    count: state.docs.size + state.collections.size,
    hasDoc: (id) => state.docs.has(id),
    hasCollection: (name) => state.collections.has(name),

    toggleDoc: (docId) => {
      setState((prev) => {
        const next = new Set(prev.docs)
        if (next.has(docId)) next.delete(docId)
        else next.add(docId)
        return { ...prev, docs: next }
      })
    },

    toggleCollection: (name) => {
      setState((prev) => {
        const next = new Set(prev.collections)
        if (next.has(name)) next.delete(name)
        else next.add(name)
        return { ...prev, collections: next }
      })
    },

    addDocs: (docIds) => {
      setState((prev) => {
        const next = new Set(prev.docs)
        docIds.forEach((id) => next.add(id))
        return { ...prev, docs: next }
      })
    },

    clear: () => {
      setState({ docs: new Set(), collections: new Set() })
    },

    clearWithUndo: () => {
      snapshotRef.current = { docs: new Set(state.docs), collections: new Set(state.collections) }
      setState({ docs: new Set(), collections: new Set() })
    },

    undo: () => {
      if (snapshotRef.current) {
        setState(snapshotRef.current)
        snapshotRef.current = null
        return true
      }
      return false
    },

    /**
     * Expand selection to a flat list of doc_ids.
     * @param docsByCollection map of collection_name -> array of doc objects with .doc_id
     * @returns {string[]} unique doc_ids from direct selection + expanded collections
     */
    expandedDocIds: (docsByCollection) => {
      const ids = new Set(state.docs)
      for (const name of state.collections) {
        const docs = docsByCollection?.[name] || []
        for (const d of docs) {
          if (d?.doc_id) ids.add(d.doc_id)
        }
      }
      return [...ids]
    },
  }), [state])

  return (
    <SelectionContext.Provider value={api}>
      {children}
    </SelectionContext.Provider>
  )
}

export function useSelection() {
  const ctx = useContext(SelectionContext)
  if (!ctx) {
    throw new Error('useSelection must be used inside <SelectionProvider>')
  }
  return ctx
}
