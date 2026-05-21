/**
 * Find the first occurrence of `needle` text in `root`'s descendant
 * text nodes, returning a DOM Range that exactly covers it. Skips
 * matches that fall within any already-claimed Range in `takenRanges`.
 *
 * Handles needles that span multiple text nodes (e.g. when docx-preview
 * splits a run across <span> tags for bold/italic styling).
 *
 * Returns null if no unclaimed match exists.
 */
export function findFirstUnclaimedTextRange(root, needle, takenRanges) {
  if (!needle) return null

  // Collect all text nodes in document order, with their cumulative
  // offsets into the concatenated text. This lets us search the
  // whole rendered string and then map back to (node, offset) pairs.
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null)
  const nodes = []
  let cumulative = 0
  let n
  while ((n = walker.nextNode())) {
    nodes.push({ node: n, start: cumulative, end: cumulative + n.length })
    cumulative += n.length
  }
  if (nodes.length === 0) return null

  const fullText = nodes.map(x => x.node.textContent).join('')

  let searchFrom = 0
  while (true) {
    const idx = fullText.indexOf(needle, searchFrom)
    if (idx === -1) return null

    const range = buildRangeFromGlobalOffsets(nodes, idx, idx + needle.length)
    if (range && !rangeIntersectsAny(range, takenRanges)) return range
    searchFrom = idx + 1
  }
}

function buildRangeFromGlobalOffsets(nodes, globalStart, globalEnd) {
  const startInfo = locateNode(nodes, globalStart)
  const endInfo = locateNode(nodes, globalEnd)
  if (!startInfo || !endInfo) return null

  const range = document.createRange()
  range.setStart(startInfo.node, startInfo.offset)
  range.setEnd(endInfo.node, endInfo.offset)
  return range
}

function locateNode(nodes, globalOffset) {
  for (const info of nodes) {
    if (globalOffset >= info.start && globalOffset <= info.end) {
      return { node: info.node, offset: globalOffset - info.start }
    }
  }
  return null
}

function rangeIntersectsAny(range, taken) {
  for (const t of taken) {
    if (range.compareBoundaryPoints(Range.END_TO_START, t) >= 0) continue
    if (range.compareBoundaryPoints(Range.START_TO_END, t) <= 0) continue
    return true
  }
  return false
}
