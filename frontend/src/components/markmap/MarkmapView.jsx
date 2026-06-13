import { useEffect, useRef, useCallback } from 'react'
import { Markmap } from 'markmap-view'
import { treeToINode } from './treeToINode'
import './MarkmapView.css'

// 5-hue rotation (same vars as the legacy tree). Returned as CSS-var strings so
// branch line/circle colours are theme-aware without re-running setOptions.
const HUE_VARS = ['--mm-hue-1', '--mm-hue-2', '--mm-hue-3', '--mm-hue-4', '--mm-hue-5']

// markmap node.state.path looks like "1.3.2" (root . branch . child …). The 2nd
// segment identifies the top-level branch → pick its hue; deeper nodes inherit
// via colorFreezeLevel. Defensive: any parse failure falls back to the signature.
function colorForNode(node) {
  try {
    const seg = String(node?.state?.path || '').split('.')
    const branchIdx = seg.length >= 2 ? (parseInt(seg[1], 10) || 0) : 0
    return `var(${HUE_VARS[branchIdx % HUE_VARS.length]})`
  } catch {
    return 'var(--signature)'
  }
}

/**
 * MarkmapView — markmap rendering of the LLM concept tree (single + multi doc).
 * Replaces MindmapTree / MultiDocMindmapTree. Backwards-compatible callback:
 * onLeafClick receives { chunkIndices } (single) or { chunksByDoc } (multi),
 * matching the legacy nodeDatum.__chunk_indices / __chunks_by_doc contract.
 */
export default function MarkmapView({
  tree,
  mode = 'single',
  palette,
  selectedChunkIds = [],
  onLeafClick,
  initialExpandLevel = 2,
}) {
  const svgRef = useRef(null)
  const mmRef = useRef(null)
  const observerRef = useRef(null)
  const onLeafClickRef = useRef(onLeafClick)
  onLeafClickRef.current = onLeafClick
  const selectedRef = useRef(selectedChunkIds)
  selectedRef.current = selectedChunkIds

  // Re-apply selection highlight + ARIA after every markmap render. markmap owns
  // its DOM and re-renders on setData/fold with NO callback, so we observe the
  // <svg> subtree and re-stamp. (setData resets fold, so highlight MUST be a
  // post-render class, never a rebuild+setData — confirmed in the Phase 0 spike.)
  const restamp = useCallback(() => {
    const svg = svgRef.current
    if (!svg) return
    // Pause the observer so our own mutations don't re-trigger it (would loop).
    observerRef.current?.disconnect()
    try {
      const selected = new Set((selectedRef.current || []).map(Number))
      svg.querySelectorAll('g.markmap-node').forEach((g) => {
        // ARIA (R6): markmap emits none. role/aria-level are attributes markmap
        // never overwrites (it only rewrites class), so they persist.
        g.setAttribute('role', 'treeitem')
        const depth = g.getAttribute('data-depth')
        if (depth != null) g.setAttribute('aria-level', String(Number(depth) + 1))
      })
      // Selection highlight goes on OUR span (markmap rewrites the g's class each
      // render but not the span content after enter), so it survives re-render.
      svg.querySelectorAll('.mm-leaf').forEach((el) => {
        let hit = false
        if (selected.size) {
          const raw = el.getAttribute('data-chunks')
          if (raw) hit = raw.split(',').some((n) => selected.has(Number(n)))
        }
        el.classList.toggle('mm-selected-leaf', hit)
      })
    } finally {
      if (svg.isConnected) observerRef.current?.observe(svg, { childList: true, subtree: true })
    }
  }, [])

  // mount once
  useEffect(() => {
    if (!svgRef.current) return
    const mm = Markmap.create(svgRef.current, {
      initialExpandLevel,
      colorFreezeLevel: 2,
      color: colorForNode,
      duration: 200,
      paddingX: 12,
    })
    mmRef.current = mm

    // delegated click → source jump (survives setData; markmap doesn't stop
    // `click` on the node foreignObject — verified in markmap-view source + spike)
    const svg = svgRef.current
    const onClick = (e) => {
      const el = e.target.closest('.mm-leaf')
      if (!el) return
      const single = el.getAttribute('data-chunks')
      const multi = el.getAttribute('data-chunks-by-doc')
      // Payload carries both new keys and the legacy nodeDatum field names so the
      // existing GraphPage onLeafClick (reads __chunk_indices / __chunks_by_doc)
      // works unchanged for both renderers.
      if (single != null) {
        const ids = single ? single.split(',').map(Number).filter(Number.isInteger) : []
        onLeafClickRef.current?.({ chunkIndices: ids, __chunk_indices: ids })
      } else if (multi != null) {
        try {
          const cbd = JSON.parse(multi)
          onLeafClickRef.current?.({ chunksByDoc: cbd, __chunks_by_doc: cbd })
        } catch { /* malformed */ }
      }
    }
    svg.addEventListener('click', onClick)

    observerRef.current = new MutationObserver(() => restamp())
    observerRef.current.observe(svg, { childList: true, subtree: true })

    return () => {
      svg.removeEventListener('click', onClick)
      observerRef.current?.disconnect()
      mm.destroy()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // (re)load data when the tree / mode / palette changes
  useEffect(() => {
    const mm = mmRef.current
    if (!mm || !tree) return
    mm.setData(treeToINode(tree, mode, palette)).then(() => {
      mm.fit()
      restamp()
    })
  }, [tree, mode, palette, restamp])

  // selection change without new data → just re-stamp
  useEffect(() => { restamp() }, [selectedChunkIds, restamp])

  const empty = !tree || !Array.isArray(tree.branches) || tree.branches.length === 0
  return (
    <div className="markmap-view-container">
      {empty && <div className="markmap-empty">No mind map available.</div>}
      <svg ref={svgRef} className="markmap-view-svg" style={{ width: '100%', height: '100%' }} />
    </div>
  )
}
