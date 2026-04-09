/**
 * Citation parsing utilities for chat answers.
 *
 * Normalizes LLM citation formats into [N] patterns,
 * then splits text into parts for CitationBadge rendering.
 */

/**
 * Normalize and split text containing citation patterns.
 * Handles: [Source N: ...], (Source N: ...), [Source N], (Source N), [N], (N)
 *
 * @param {string} text - Raw text from LLM
 * @returns {string} - Text with all citation formats normalized to [N]
 */
export function normalizeCitations(text) {
  if (typeof text !== 'string') return text
  return text
    .replace(/[\[(]Source\s+(\d+)[^\])]*/g, '[$1')   // strip "Source N: details"
    .replace(/\[(\d+)[)\]]/g, '[$1]')                 // normalize closing bracket
    .replace(/\((\d+)\)/g, '[$1]')                     // (N) → [N]
}

/**
 * Split text into alternating text and [N] citation tokens.
 *
 * @param {string} text - Text (already normalized or raw)
 * @returns {Array<{type: 'text'|'citation', value: string|number}>}
 */
export function splitCitations(text) {
  const normalized = normalizeCitations(text)
  const parts = normalized.split(/(\[\d+\])/)
  if (parts.length === 1) return [{ type: 'text', value: normalized }]
  return parts.filter(Boolean).map(part => {
    const m = part.match(/^\[(\d+)\]$/)
    if (m) return { type: 'citation', value: parseInt(m[1], 10) }
    return { type: 'text', value: part }
  })
}
