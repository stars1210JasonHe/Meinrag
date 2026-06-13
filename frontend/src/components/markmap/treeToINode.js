// Serialize the backend mindmap JSON (MindmapTree / MultiMindmapTree) into a
// markmap INode tree. markmap renders node `content` via d3 `.html()`, so every
// interpolated string here is an injection surface and MUST be escaped — node
// names come from an LLM, palette values from the backend.
//
// Leaf judgment (R12 + review findings): the backend marks leaf-vs-internal
// ASYMMETRICALLY by mode, so we match each mode's real schema:
//   single — internal nodes carry chunk_indices: null; leaves carry an ARRAY
//            ([] for zero-coverage, [..] otherwise). So `Array.isArray` is the
//            exact discriminator (and ignores cached malformed `children: []`,
//            which lack the chunk_indices array → classified internal).
//   multi  — both internals AND zero-coverage leaves carry chunks_by_doc: null
//            (an empty dict collapses to None in the backend), so payload value
//            cannot distinguish them. The only signal is `children`: a node is
//            internal iff it has a non-empty children array; otherwise it is a
//            leaf (a populated payload also forces leaf, so a stray children
//            array can't strand real provenance).
// chunk ids are LOAD-BEARING RAG-citation provenance; they are integer-filtered
// + de-duped on both paths so the click consumer never sees junk.

const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => HTML_ESCAPES[c])

// Only allow #rgb / #rgba / #rrggbb / #rrggbbaa — reject anything else so a
// palette value can't smuggle CSS (e.g. `url(javascript:...)`).
const HEX_COLOR = /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/
const safeColor = (c) => (typeof c === 'string' && HEX_COLOR.test(c.trim()) ? c.trim() : null)

const isPlainObject = (v) => v != null && typeof v === 'object' && !Array.isArray(v)
const isObjectNode = (v) => v != null && typeof v === 'object'   // array or object — a usable node
const hasRealChildren = (node) => Array.isArray(node.children) && node.children.length > 0

const intIds = (arr) => [...new Set((Array.isArray(arr) ? arr : []).filter(Number.isInteger))]

function badge(count) {
  return count ? `<span class="mm-count-badge">${count}</span>` : ''
}

function leafContentSingle(node) {
  const ids = intIds(node.chunk_indices)
  return `<span class="mm-node mm-leaf" data-chunks="${ids.join(',')}">`
    + `${escapeHtml(node.name)}${badge(ids.length)}</span>`
}

function leafContentMulti(node, palette) {
  // Tolerate chunks_by_doc that is null / non-object / arrays-of-junk — render a
  // zero-coverage leaf rather than throwing or emitting corrupt provenance.
  const raw = isPlainObject(node.chunks_by_doc) ? node.chunks_by_doc : {}
  const clean = {}
  for (const [docId, arr] of Object.entries(raw)) {
    const ids = intIds(arr)
    if (ids.length) clean[docId] = ids
  }
  const count = Object.values(clean).reduce((t, ids) => t + ids.length, 0)
  const attr = escapeHtml(JSON.stringify(clean))            // JSON in a single-quoted attr; ' < > & " all escaped
  const swatches = Object.keys(clean)
    .map((docId) => {
      const col = safeColor(palette?.[docId])
      return col ? `<span class="mm-swatch" style="background:${col}"></span>` : ''
    })
    .join('')
  return `<span class="mm-node mm-leaf" data-chunks-by-doc='${attr}'>`
    + `${swatches}${escapeHtml(node.name)}${badge(count)}</span>`
}

function nodeToINode(node, mode, palette) {
  // multi: a NON-EMPTY payload forces leaf; otherwise leaf iff no real children
  // (so an empty {} with real children stays internal and keeps them — F3).
  const populatedMulti = isPlainObject(node.chunks_by_doc) && Object.keys(node.chunks_by_doc).length > 0
  const isLeaf = mode === 'single'
    ? Array.isArray(node.chunk_indices)
    : populatedMulti || !hasRealChildren(node)

  if (isLeaf) {
    return {
      content: mode === 'single' ? leafContentSingle(node) : leafContentMulti(node, palette),
      children: [],
    }
  }
  const kids = Array.isArray(node.children) ? node.children.filter(isObjectNode) : []
  return {
    content: `<span class="mm-node">${escapeHtml(node.name)}</span>`,
    children: kids.map((c) => nodeToINode(c, mode, palette)),
  }
}

/**
 * @param {object} tree    backend MindmapTree / MultiMindmapTree ({ central, branches[] })
 * @param {'single'|'multi'} mode
 * @param {Record<string,string>} [palette] multi-doc docId→hex (coverage swatch)
 * @returns markmap INode ({ content, children })
 */
export function treeToINode(tree, mode, palette) {
  const branches = Array.isArray(tree?.branches) ? tree.branches.filter(isObjectNode) : []
  return {
    content: `<span class="mm-node mm-central">${escapeHtml(tree?.central)}</span>`,
    children: branches.map((b) => nodeToINode(b, mode, palette)),
  }
}
