import { describe, it, expect } from 'vitest'
import { findFirstUnclaimedTextRange } from './docxChunkMapper'

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
