import { describe, it, expect } from 'vitest'
import { treeToINode } from './treeToINode'

const single = (tree) => treeToINode(tree, 'single')
const multi = (tree, palette) => treeToINode(tree, 'multi', palette)

describe('treeToINode — leaf judgment (R12, payload-driven)', () => {
  it('treats a populated chunk_indices as a leaf', () => {
    const r = single({ central: 'C', branches: [{ name: 'L', chunk_indices: [1, 2] }] })
    expect(r.children[0].content).toContain('data-chunks="1,2"')
    expect(r.children[0].content).toContain('mm-leaf')
  })

  it('does NOT treat malformed empty children as a leaf (cached bad JSON)', () => {
    const r = single({ central: 'C', branches: [{ name: 'B', children: [] }] })
    expect(r.children[0].content).not.toContain('data-chunks')
    expect(r.children[0].content).not.toContain('mm-leaf')
  })

  it('treats a node with chunk_indices AND children as internal (chunk_indices null on internals in real data)', () => {
    // Internal nodes carry chunk_indices: null in real backend data (verified).
    const r = single({ central: 'C', branches: [{ name: 'B', chunk_indices: null, children: [{ name: 'L', chunk_indices: [3] }] }] })
    expect(r.children[0].content).not.toContain('data-chunks')           // internal
    expect(r.children[0].children[0].content).toContain('data-chunks="3"') // its leaf
  })
})

describe('treeToINode — count badge', () => {
  it('single: badge = number of chunk_indices', () => {
    const r = single({ central: 'C', branches: [{ name: 'L', chunk_indices: [1, 2, 3] }] })
    expect(r.children[0].content).toMatch(/mm-count-badge[^>]*>3</)
  })

  it('multi: badge = total chunks across docs', () => {
    const r = multi({ central: 'C', branches: [{ name: 'L', chunks_by_doc: { d1: [1], d2: [2, 3] } }] })
    expect(r.children[0].content).toMatch(/mm-count-badge[^>]*>3</)
  })
})

describe('treeToINode — multi-doc payload + coverage swatch', () => {
  it('encodes chunks_by_doc as a parseable attribute', () => {
    const r = multi({ central: 'C', branches: [{ name: 'L', chunks_by_doc: { d1: [1], d2: [2, 3] } }] })
    const m = r.children[0].content.match(/data-chunks-by-doc='([^']*)'/)
    expect(m).toBeTruthy()
    expect(JSON.parse(m[1].replace(/&quot;/g, '"').replace(/&amp;/g, '&'))).toEqual({ d1: [1], d2: [2, 3] })
  })

  it('renders a coverage swatch only for docs in the palette', () => {
    const r = multi({ central: 'C', branches: [{ name: 'L', chunks_by_doc: { d1: [1] } }] }, { d1: '#3366cc' })
    expect(r.children[0].content).toContain('#3366cc')
  })
})

describe('treeToINode — security (markmap injects content via .html())', () => {
  it('escapes HTML in node names (XSS surface)', () => {
    const r = single({ central: '<img src=x onerror=alert(1)>', branches: [] })
    expect(r.content).not.toContain('<img')
    expect(r.content).toContain('&lt;img')
  })

  it('escapes quotes in names so they cannot break out of attributes/markup', () => {
    const r = single({ central: 'a"b\'c', branches: [{ name: 'x</span><script>', chunk_indices: [1] }] })
    expect(r.children[0].content).not.toContain('<script>')
  })

  it('rejects/escapes a palette value that is not a safe colour (CSS injection)', () => {
    const r = multi(
      { central: 'C', branches: [{ name: 'L', chunks_by_doc: { d1: [1] } }] },
      { d1: 'red;background:url(javascript:alert(1))' },
    )
    expect(r.children[0].content).not.toContain('javascript:')
  })
})

describe('treeToINode — review regressions (F1–F9)', () => {
  it('F1: multi zero-coverage leaf (chunks_by_doc null, no children) is a LEAF, not a dangling internal', () => {
    const r = multi({ central: 'C', branches: [{ name: 'L', chunks_by_doc: null, children: null }] })
    const node = r.children[0]
    expect(node.content).toContain('mm-leaf')              // clickable leaf, provenance path intact
    expect(node.content).toContain("data-chunks-by-doc='{}'")
    expect(node.children).toEqual([])
  })

  it('F3/F6: multi node with empty/array payload BUT real children stays internal (children kept)', () => {
    const r = multi({ central: 'C', branches: [
      { name: 'B', chunks_by_doc: {}, children: [{ name: 'L', chunks_by_doc: { d1: [1] } }] },
    ]})
    expect(r.children[0].content).not.toContain('mm-leaf') // internal
    expect(r.children[0].children).toHaveLength(1)          // children NOT dropped
    const r2 = multi({ central: 'C', branches: [
      { name: 'B', chunks_by_doc: [1, 2], children: [{ name: 'L', chunks_by_doc: { d1: [1] } }] },
    ]})
    expect(r2.children[0].content).not.toContain('mm-leaf')
    expect(r2.children[0].children).toHaveLength(1)
  })

  it('F2: a null/primitive element anywhere does not throw and does not abort the tree', () => {
    expect(() => single({ central: 'C', branches: [null, { name: 'L', chunk_indices: [1] }, 'junk'] }))
      .not.toThrow()
    const r = single({ central: 'C', branches: [null, { name: 'L', chunk_indices: [1] }] })
    expect(r.children).toHaveLength(1)                      // null filtered, real leaf survives
    expect(r.children[0].content).toContain('data-chunks="1"')
  })

  it('F9: duplicate chunk ids are de-duped (order preserved), single + multi', () => {
    const r = single({ central: 'C', branches: [{ name: 'L', chunk_indices: [1, 1, 2, 2, 3] }] })
    expect(r.children[0].content).toContain('data-chunks="1,2,3"')
    const m = multi({ central: 'C', branches: [{ name: 'L', chunks_by_doc: { d1: [5, 5, 6] } }] })
    expect(m.children[0].content).toMatch(/\[5,6\]/)
  })

  it('F4/F8: non-integer chunk ids are filtered, and badge count == serialized payload (multi)', () => {
    const m = multi({ central: 'C', branches: [{ name: 'L', chunks_by_doc: { d1: [1, 'x', 2, null, 1] } }] })
    expect(m.children[0].content).toMatch(/\[1,2\]/)        // 'x'/null dropped, dupe removed
    expect(m.children[0].content).toMatch(/mm-count-badge[^>]*>2</) // count matches sanitized payload
  })

  it('F7: single-quote / special chars in a docId round-trip through the attribute', () => {
    const m = multi({ central: 'C', branches: [{ name: 'L', chunks_by_doc: { "d'1": [1] } }] })
    const raw = m.children[0].content.match(/data-chunks-by-doc='([^']*)'/)[1]
    // decode the HTML attribute exactly as the browser would
    const decoded = raw.replace(/&#39;/g, "'").replace(/&quot;/g, '"')
      .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    expect(JSON.parse(decoded)).toEqual({ "d'1": [1] })
  })
})

describe('treeToINode — structure', () => {
  it('root content uses central, children come from branches', () => {
    const r = single({ central: 'Root', branches: [{ name: 'B', chunk_indices: [1] }] })
    expect(r.content).toContain('Root')
    expect(r.content).toContain('mm-central')
    expect(r.children).toHaveLength(1)
  })

  it('recurses through nested children', () => {
    const r = single({ central: 'C', branches: [
      { name: 'B', chunk_indices: null, children: [
        { name: 'B2', chunk_indices: null, children: [{ name: 'L', chunk_indices: [9] }] },
      ] },
    ]})
    expect(r.children[0].children[0].children[0].content).toContain('data-chunks="9"')
  })

  it('handles a tree with no branches', () => {
    const r = single({ central: 'C' })
    expect(r.children).toEqual([])
  })
})
