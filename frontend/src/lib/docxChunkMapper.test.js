import { describe, it, expect } from 'vitest'
import { findFirstUnclaimedTextRange, wrapRangeInSpan } from './docxChunkMapper'

describe('findFirstUnclaimedTextRange', () => {
  it('finds a unique needle in a single text node', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>The plaintiff filed a claim against Acme.</p>'

    const range = findFirstUnclaimedTextRange(root, 'plaintiff filed', [])

    expect(range).not.toBeNull()
    expect(range.toString()).toBe('plaintiff filed')
  })

  it('skips a needle occurrence already claimed by takenRanges', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>本条 first hit and 本条 second hit.</p>'

    const first = findFirstUnclaimedTextRange(root, '本条', [])
    expect(first.toString()).toBe('本条')
    expect(first.startOffset).toBe(0)

    const second = findFirstUnclaimedTextRange(root, '本条', [first])
    expect(second).not.toBeNull()
    expect(second.toString()).toBe('本条')
    expect(second.startOffset).toBeGreaterThan(first.endOffset)
  })

  it('finds a needle that spans two adjacent text nodes', () => {
    const root = document.createElement('div')
    // docx-preview often splits text across <span> tags for styling.
    // The visible text is "The plaintiff filed" but it's two text nodes.
    root.innerHTML = '<p><span>The plaintiff </span><span>filed a claim</span></p>'

    const range = findFirstUnclaimedTextRange(root, 'plaintiff filed', [])

    expect(range).not.toBeNull()
    expect(range.toString().replace(/\s+/g, ' ')).toBe('plaintiff filed')
  })
})

describe('wrapRangeInSpan', () => {
  it('wraps a range in a span with data-chunk-index attribute', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>The plaintiff filed a claim.</p>'
    const range = findFirstUnclaimedTextRange(root, 'plaintiff filed', [])

    const span = wrapRangeInSpan(range, 5, 'text')

    expect(span.tagName).toBe('SPAN')
    expect(span.getAttribute('data-chunk-index')).toBe('5')
    expect(span.getAttribute('data-chunk-type')).toBe('text')
    expect(span.classList.contains('chunk-marker')).toBe(true)
    expect(span.textContent).toBe('plaintiff filed')
  })
})
