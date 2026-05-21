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
})
