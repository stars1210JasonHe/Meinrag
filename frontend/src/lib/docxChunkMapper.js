/**
 * Find the first occurrence of `needle` text in `root`'s descendant
 * text nodes, returning a DOM Range that exactly covers it. Skips
 * matches that fall within any already-claimed Range in `takenRanges`.
 *
 * Returns null if no unclaimed match exists.
 */
export function findFirstUnclaimedTextRange(root, needle, takenRanges) {
  if (!needle) return null

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null)
  let node
  while ((node = walker.nextNode())) {
    const idx = node.textContent.indexOf(needle)
    if (idx === -1) continue

    const range = document.createRange()
    range.setStart(node, idx)
    range.setEnd(node, idx + needle.length)

    if (rangeIntersectsAny(range, takenRanges)) continue
    return range
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
