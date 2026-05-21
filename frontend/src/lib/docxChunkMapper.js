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

/**
 * Wrap the contents of `range` in a new <span> with chunk-marker
 * classes + data attributes. Returns the inserted span element.
 *
 * Caveat: if the range spans multiple parent elements (rare in
 * docx-preview output but possible with inline styling), the wrap
 * may not be semantically clean — but visually it still works
 * because we only add a left border + background.
 */
export function wrapRangeInSpan(range, chunkIndex, chunkType) {
  const span = document.createElement('span')
  span.classList.add('chunk-marker')
  span.setAttribute('data-chunk-index', String(chunkIndex))
  if (chunkType) span.setAttribute('data-chunk-type', chunkType)
  try {
    range.surroundContents(span)
  } catch {
    // surroundContents throws when the range partially selects a
    // non-text node. Fallback: extract + append, less clean but
    // works for our needs (the active highlight still attaches).
    const contents = range.extractContents()
    span.appendChild(contents)
    range.insertNode(span)
  }
  return span
}

/**
 * Mutate `range` in place to extend its end forward by `extraChars`
 * characters of visible text. Clamps to end-of-document if asked
 * to extend past the last text node.
 */
export function extendRangeForwards(range, extraChars) {
  if (extraChars <= 0) return

  let endNode = range.endContainer
  let endOffset = range.endOffset
  let remaining = extraChars
  let lastTextNode = endNode  // tracks the last text node we visited for EOD clamping

  // Determine the root for tree walking. Walk up from endNode's parent
  // to find a container that is likely to have more text nodes beyond the current one.
  // If endNode is a text node, start from its parent; then walk up to a reasonable level.
  let root = endNode.parentElement
  // Walk up one more level to escape single-element parents (e.g., <span>text</span>)
  if (root && root.parentElement) {
    root = root.parentElement
  }

  while (remaining > 0) {
    const available = endNode.length - endOffset
    if (available >= remaining) {
      range.setEnd(endNode, endOffset + remaining)
      return
    }
    remaining -= available
    const next = nextTextNode(endNode, root)
    if (!next) {
      // No more text nodes — clamp to the end of the LAST text node we
      // successfully visited (not the range's original endContainer).
      range.setEnd(lastTextNode, lastTextNode.length)
      return
    }
    lastTextNode = next
    endNode = next
    endOffset = 0
  }
}

function nextTextNode(from, root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null)
  walker.currentNode = from
  return walker.nextNode()
}
