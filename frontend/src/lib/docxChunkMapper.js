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
  //
  // Skip text nodes that live inside an already-claimed chunk-marker span.
  // Without this filter, a second chunk whose text comes after a previously
  // wrapped span would get a cross-element range (span → next-p), which
  // makes surroundContents throw and corrupts the DOM.
  const chunkMarkerFilter = {
    acceptNode(node) {
      let p = node.parentElement
      while (p && p !== root) {
        if (p.classList && p.classList.contains('chunk-marker')) {
          return NodeFilter.FILTER_REJECT
        }
        p = p.parentElement
      }
      return NodeFilter.FILTER_ACCEPT
    },
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, chunkMarkerFilter)
  const nodes = []
  let cumulative = 0
  let n
  while ((n = walker.nextNode())) {
    // Skip zero-length text nodes (happy-dom creates these as split artifacts
    // after surroundContents). Including them causes locateNode to return the
    // wrong node for offset 0, producing cross-element ranges.
    if (n.length === 0) continue
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

/**
 * Find the FIRST unclaimed element of `tagName` (e.g. 'table', 'img')
 * inside `container` and wrap it in a marker element. Tables get a
 * <div> wrapper (block element, valid inside <body>); images get a
 * <span> wrapper (inline). Returns the wrapper element, or null if
 * no unclaimed element exists.
 *
 * "Unclaimed" = not already inside a `.chunk-marker` ancestor. Because
 * chunks are iterated in document order and each call claims one
 * element, repeated calls naturally walk through tables/images in
 * order: 1st call wraps the 1st <table>, 2nd call wraps the 2nd, etc.
 */
export function wrapFirstUnclaimedBlock(container, tagName, chunkIndex, chunkType) {
  const all = container.querySelectorAll(tagName)
  for (const el of all) {
    if (el.closest('.chunk-marker')) continue
    // <table> needs a block wrapper to stay valid HTML (a <span>
    // around a <table> is parser-invalid).
    const wrapperTag = tagName === 'table' ? 'div' : 'span'
    const wrapper = document.createElement(wrapperTag)
    wrapper.classList.add('chunk-marker')
    wrapper.setAttribute('data-chunk-index', String(chunkIndex))
    wrapper.setAttribute('data-chunk-type', chunkType)
    el.parentNode.insertBefore(wrapper, el)
    wrapper.appendChild(el)
    return wrapper
  }
  return null
}

const NEEDLE_LEN = 80

/**
 * Walk `container`'s DOM and wrap each chunk in a marker element.
 * Text chunks get a <span> wrapping the matched text range.
 * Table chunks get a <div> wrapping the Nth unclaimed <table>.
 * Image chunks get a <span> wrapping the Nth unclaimed <img>.
 * Returns a summary object with match counts and a list of skipped
 * chunk_index values (whose content didn't render verbatim or wasn't
 * found in the DOM).
 */
export function wrapChunkSpans(container, chunks) {
  const taken = []
  let matched = 0
  let skipped = 0
  const skippedChunks = []

  for (const chunk of chunks) {
    // ─── TEXT branch (unchanged from current implementation) ──────
    if (chunk.chunk_type === 'text') {
      const content = (chunk.content || '').trim()
      if (!content) {
        skipped++
        skippedChunks.push(chunk.chunk_index)
        continue
      }

      const needle = content.slice(0, Math.min(NEEDLE_LEN, content.length)).trim()
      const range = findFirstUnclaimedTextRange(container, needle, taken)
      if (!range) {
        console.warn(
          `[docxChunkMapper] chunk ${chunk.chunk_index} text not found in rendered doc; skipping highlight`
        )
        skipped++
        skippedChunks.push(chunk.chunk_index)
        continue
      }

      extendRangeForwards(range, Math.max(0, content.length - needle.length))
      // Clone the range before wrapping: surroundContents() mutates the range's
      // boundary points from text-node offsets to element offsets, which breaks
      // compareBoundaryPoints for subsequent taken-set checks.
      const claimedRange = range.cloneRange()
      wrapRangeInSpan(range, chunk.chunk_index, chunk.chunk_type)
      taken.push(claimedRange)
      matched++
      continue
    }

    // ─── TABLE branch (new) ──────────────────────────────────────
    if (chunk.chunk_type === 'table') {
      const wrapper = wrapFirstUnclaimedBlock(
        container, 'table', chunk.chunk_index, 'table',
      )
      if (!wrapper) {
        console.warn(
          `[docxChunkMapper] chunk ${chunk.chunk_index} table not found in rendered doc; skipping highlight`
        )
        skipped++
        skippedChunks.push(chunk.chunk_index)
        continue
      }
      matched++
      continue
    }

    // ─── IMAGE branch (new) ──────────────────────────────────────
    if (chunk.chunk_type === 'image') {
      const wrapper = wrapFirstUnclaimedBlock(
        container, 'img', chunk.chunk_index, 'image',
      )
      if (!wrapper) {
        console.warn(
          `[docxChunkMapper] chunk ${chunk.chunk_index} image not found in rendered doc; skipping highlight`
        )
        skipped++
        skippedChunks.push(chunk.chunk_index)
        continue
      }
      matched++
      continue
    }

    // ─── Unknown chunk_type (e.g. 'formula' in v2) ───────────────
    // Skip without warning — out-of-scope for v1 by design.
    skipped++
    skippedChunks.push(chunk.chunk_index)
  }

  return { matched, skipped, skippedChunks }
}
