// THROWAWAY harness to verify the production MarkmapView in isolation (no backend).
// Route: /spike-markmapview. Delete with the rest of _spike in Phase 3.
import { useState } from 'react'
import MarkmapView from '../markmap/MarkmapView'
import sample from './sample.json'

const treeWithCJK = {
  ...sample,
  branches: [
    ...sample.branches,
    {
      name: '量子壳模型（中文测试）',
      chunk_indices: null,
      children: [{ name: '基态能量精度（中文叶子）', chunk_indices: [7, 8] }],
    },
  ],
}

export default function MarkmapViewHarness() {
  const [clicks, setClicks] = useState([])
  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column' }}>
      <div
        id="clicklog"
        data-clicks={JSON.stringify(clicks)}
        style={{ padding: 8, color: 'var(--fg)', fontSize: 13 }}
      >
        onLeafClick payloads: {JSON.stringify(clicks)}
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        {/* selectedChunkIds [15,19] intersects the "Basic Concepts" leaf (15,19,20) → highlight */}
        <MarkmapView
          tree={treeWithCJK}
          mode="single"
          selectedChunkIds={[15, 19]}
          onLeafClick={(p) => setClicks((c) => [...c, p])}
        />
      </div>
    </div>
  )
}
