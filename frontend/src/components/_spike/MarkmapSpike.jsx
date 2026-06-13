// THROWAWAY Phase 0 spike — de-risks R1/R2/R3 for the markmap migration.
// Route: /spike-markmap. Delete after Phase 0 findings are recorded.
// Self-reporting: click leaves + use the buttons, read the verdict log.
import { useEffect, useRef, useState, useCallback } from 'react'
import { Markmap } from 'markmap-view'
import sample from './sample.json'

// Inject a CJK branch so we can verify Chinese rendering (local samples are EN).
const treeWithCJK = {
  ...sample,
  branches: [
    ...sample.branches,
    {
      name: '量子壳模型（中文测试）',
      children: [
        { name: '基态能量精度（中文叶子）', chunk_indices: [7, 8] },
        { name: '魔数与幻数', chunk_indices: [9] },
      ],
    },
  ],
}

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

// payload-driven leaf judgment (R12): leaf iff chunk_indices is a populated array
function nodeToINode(node) {
  const ci = node.chunk_indices
  const isLeaf = Array.isArray(ci)
  const count = isLeaf ? ci.length : 0
  const chunkAttr = isLeaf ? ` data-chunks="${ci.join(',')}"` : ''
  const badge = isLeaf && count ? `<span class="mm-badge">${count}</span>` : ''
  const kids = node.children || []
  return {
    content: `<span class="mm-node${isLeaf ? ' mm-leaf' : ''}"${chunkAttr}>${esc(node.name)}${badge}</span>`,
    children: kids.map(nodeToINode),
    payload: { fold: isLeaf ? 0 : undefined },
  }
}
function treeToINode(tree) {
  return {
    content: `<span class="mm-node mm-central">${esc(tree.central)}</span>`,
    children: (tree.branches || []).map(nodeToINode),
  }
}

export default function MarkmapSpike() {
  const svgRef = useRef(null)
  const mmRef = useRef(null)
  const rootRef = useRef(null)
  const [log, setLog] = useState([])
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || 'dark')
  const say = useCallback((m) => setLog((l) => [`${new Date().toISOString().slice(11, 19)}  ${m}`, ...l].slice(0, 40)), [])

  // mount once
  useEffect(() => {
    if (!svgRef.current) return
    const mm = Markmap.create(svgRef.current, {
      initialExpandLevel: 2,          // R5: does this hide leaves but show root+branches?
      colorFreezeLevel: 2,
      duration: 200,
    })
    mmRef.current = mm
    rootRef.current = treeToINode(treeWithCJK)
    mm.setData(rootRef.current).then(() => mm.fit())
    say('mounted + setData(initialExpandLevel=2). Note which depths are visible (R5).')

    // R1: delegated click listener on the svg — does a leaf-span click fire?
    const onClick = (e) => {
      const span = e.target.closest('.mm-leaf')
      if (span) {
        say(`R1 ✅ leaf click FIRED: "${span.textContent}" data-chunks=${span.getAttribute('data-chunks')}`)
      }
    }
    svgRef.current.addEventListener('click', onClick)
    return () => { svgRef.current?.removeEventListener('click', onClick); mm.destroy() }
  }, [say])

  // R2 helper: flip <html data-theme> and observe
  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    setTheme(next)
    say(`R2: theme→${next}. Check (a) node text colour follows, (b) fold/zoom NOT reset.`)
  }

  // R3a: native highlight API (markmap-view exposes setHighlight/findElement)
  const tryNativeHighlight = () => {
    const mm = mmRef.current
    try {
      // highlight the first leaf node found in the data tree
      const root = rootRef.current
      let target = null
      const find = (n) => { if (target) return; if (/mm-leaf/.test(n.content)) target = n; (n.children || []).forEach(find) }
      find(root)
      if (target && typeof mm.setHighlight === 'function') {
        mm.setHighlight(target)
        say('R3a: called mm.setHighlight(firstLeaf). Did a node get visibly highlighted?')
      } else {
        say('R3a: setHighlight unavailable or no leaf found.')
      }
    } catch (err) { say(`R3a ERROR: ${err.message}`) }
  }

  // R3b: re-setData and see if fold/zoom survives
  const reSetData = () => {
    const mm = mmRef.current
    mm.setData(rootRef.current).then(() => say('R3b: re-setData done. Did fold/zoom/pan RESET? Did highlight survive? Click a leaf again to confirm R1 survives re-render.'))
  }

  // fold the first branch to set up a view-state observation
  const foldFirst = () => {
    const mm = mmRef.current
    try {
      const first = rootRef.current.children?.[0]
      if (first) { mm.toggleNode(first); say('Folded first branch. Now toggle theme / re-setData and watch if it re-expands (view-state loss).') }
    } catch (err) { say(`fold ERROR: ${err.message}`) }
  }

  return (
    <div style={{ padding: 16 }}>
      <h2 style={{ color: 'var(--fg)' }}>markmap Phase 0 spike</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
        <button onClick={toggleTheme}>R2: toggle theme (now: {theme})</button>
        <button onClick={foldFirst}>fold first branch</button>
        <button onClick={tryNativeHighlight}>R3a: native setHighlight</button>
        <button onClick={reSetData}>R3b: re-setData</button>
      </div>
      <p style={{ color: 'var(--fg-1)', fontSize: 13 }}>
        Click any leaf node (the deepest ones) to test R1. Verify the 中文 branch renders correctly (CJK). Read the log ↓
      </p>
      <div style={{ border: '1px solid var(--border)', borderRadius: 8, height: 460, marginBottom: 12 }}>
        <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
      </div>
      <pre style={{ background: 'var(--bg-1)', color: 'var(--fg)', padding: 12, borderRadius: 8, fontSize: 12, maxHeight: 240, overflow: 'auto' }}>
        {log.join('\n') || '(verdict log — interactions append here)'}
      </pre>
      <style>{`
        .mm-node { font: inherit; color: var(--fg); cursor: pointer; }
        .mm-leaf { text-decoration: underline; text-underline-offset: 3px; }
        .mm-central { font-weight: 600; }
        .mm-badge { display:inline-block; margin-left:6px; padding:0 6px; border-radius:9px;
                    background: var(--signature); color:#fff; font-size:11px; }
      `}</style>
    </div>
  )
}
