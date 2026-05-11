// Doc-identity colour resolution for the multi-doc chunk graph.
//
// Each doc gets ONE colour:
// 1. Preferred: `tree.palette.central` from the doc's mindmap response
//    (LLM-suggested, content-aware).
// 2. Fallback: deterministic pick from `--mm-hue-1..5` based on a hash of
//    doc_id, so the same doc always lands on the same hue even before its
//    mindmap is generated.

import { cssVar } from './cssVar'

// 5 mindmap hue CSS vars — defined in index.css, theme-aware (dark + light
// variants). Read once via getComputedStyle; safe to call repeatedly.
function fallbackPaletteHexes() {
  return [
    cssVar('--mm-hue-1', '#6b8fd6'),
    cssVar('--mm-hue-2', '#d4a64a'),
    cssVar('--mm-hue-3', '#4ade80'),
    cssVar('--mm-hue-4', '#f472b6'),
    cssVar('--mm-hue-5', '#a78bfa'),
  ]
}

// Simple deterministic hash → bucket of fallbackPaletteHexes() length.
// Used only when the mindmap palette isn't available yet (cold start /
// uncached doc). Once mindmap is generated the LLM colour takes over.
function hashBucket(str, mod) {
  let h = 0
  for (let i = 0; i < str.length; i += 1) {
    h = (h * 31 + str.charCodeAt(i)) >>> 0
  }
  return h % mod
}

/**
 * Resolve a doc's identity colour.
 *
 * @param {string} docId
 * @param {object|null} mindmapTree  the `tree` field from /documents/{id}/mindmap
 * @returns {string}  #rrggbb hex
 */
export function resolveDocColor(docId, mindmapTree) {
  const central = mindmapTree?.palette?.central
  if (typeof central === 'string' && /^#[0-9a-fA-F]{6}$/.test(central)) {
    return central
  }
  const fallback = fallbackPaletteHexes()
  return fallback[hashBucket(String(docId), fallback.length)]
}

/**
 * Build a {docId: color} map from a list of doc_ids and their (optional)
 * mindmap trees. Used by MultiDocLegend + the canvas renderer.
 *
 * @param {Array<{doc_id: string, tree?: object}>} entries
 * @returns {Record<string, string>}
 */
export function buildDocColorMap(entries) {
  const map = {}
  for (const e of entries) {
    map[e.doc_id] = resolveDocColor(e.doc_id, e.tree)
  }
  return map
}
