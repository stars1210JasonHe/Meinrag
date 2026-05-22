import { describe, it, expect } from 'vitest'
import { findFirstUnclaimedTextRange, wrapRangeInSpan, extendRangeForwards, wrapChunkSpans } from './docxChunkMapper'

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

describe('extendRangeForwards', () => {
  it('extends a range forward by the given character count', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>The plaintiff filed a claim against Acme on Monday.</p>'
    const range = findFirstUnclaimedTextRange(root, 'plaintiff filed', [])

    extendRangeForwards(range, 21) // " a claim against Acme"

    expect(range.toString()).toBe('plaintiff filed a claim against Acme')
  })

  it('clamps at end of document', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>Short.</p>'
    const range = findFirstUnclaimedTextRange(root, 'Short', [])

    extendRangeForwards(range, 9999)
    expect(range.toString()).toBe('Short.')
  })

  it('clamps to end of last text node when document has multiple text nodes', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p><span>First </span><span>middle </span><span>last</span></p>'
    const range = findFirstUnclaimedTextRange(root, 'First', [])

    extendRangeForwards(range, 9999)

    // Should cover "First middle last" — extending across all three text nodes.
    expect(range.toString()).toBe('First middle last')
  })
})

describe('wrapChunkSpans', () => {
  it('wraps multiple chunks into the container', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<p>The plaintiff filed a claim against Acme.</p>' +
      '<p>The defendant denied all allegations.</p>'

    const chunks = [
      { chunk_index: 0, chunk_type: 'text', content: 'The plaintiff filed a claim against Acme.' },
      { chunk_index: 1, chunk_type: 'text', content: 'The defendant denied all allegations.' },
    ]

    const result = wrapChunkSpans(root, chunks)

    expect(result.matched).toBe(2)
    expect(result.skipped).toBe(0)
    const spans = root.querySelectorAll('span.chunk-marker')
    expect(spans.length).toBe(2)
    expect(spans[0].getAttribute('data-chunk-index')).toBe('0')
    expect(spans[1].getAttribute('data-chunk-index')).toBe('1')
  })

  it('logs and skips chunks whose text does not render verbatim', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>Only this paragraph exists.</p>'

    const chunks = [
      { chunk_index: 0, chunk_type: 'text', content: 'Only this paragraph exists.' },
      { chunk_index: 1, chunk_type: 'text', content: 'A chunk that was never rendered.' },
    ]

    const result = wrapChunkSpans(root, chunks)

    expect(result.matched).toBe(1)
    expect(result.skipped).toBe(1)
    expect(result.skippedChunks).toEqual([1])
  })

  it('skips image and table chunks (handled separately in v2)', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>Body text.</p>'

    const chunks = [
      { chunk_index: 0, chunk_type: 'text', content: 'Body text.' },
      { chunk_index: 1, chunk_type: 'image', content: 'Figure 1' },
      { chunk_index: 2, chunk_type: 'table', content: '| h1 | h2 |' },
    ]

    const result = wrapChunkSpans(root, chunks)

    expect(result.matched).toBe(1)
    expect(result.skipped).toBe(2)
  })
})

describe('wrapChunkSpans — table + image', () => {
  it('wraps the Nth table chunk into the Nth <table> in DOM', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<p>Intro text.</p>' +
      '<table><tr><td>First table cell</td></tr></table>' +
      '<p>Middle text.</p>' +
      '<table><tr><td>Second table cell</td></tr></table>' +
      '<p>Trailing text.</p>'

    const chunks = [
      { chunk_index: 0, chunk_type: 'text',  content: 'Intro text.' },
      { chunk_index: 1, chunk_type: 'table', content: '| First table cell |' },
      { chunk_index: 2, chunk_type: 'text',  content: 'Middle text.' },
      { chunk_index: 3, chunk_type: 'table', content: '| Second table cell |' },
      { chunk_index: 4, chunk_type: 'text',  content: 'Trailing text.' },
    ]

    const result = wrapChunkSpans(root, chunks)

    expect(result.matched).toBe(5)
    expect(result.skipped).toBe(0)

    // Markers exist for both tables, with correct chunk_index attribution
    const table1Marker = root.querySelector('[data-chunk-index="1"]')
    const table2Marker = root.querySelector('[data-chunk-index="3"]')
    expect(table1Marker).not.toBeNull()
    expect(table2Marker).not.toBeNull()
    expect(table1Marker.getAttribute('data-chunk-type')).toBe('table')
    expect(table2Marker.getAttribute('data-chunk-type')).toBe('table')

    // The first marker's content includes the first table's text; the second
    // marker's content includes the second table's text.
    expect(table1Marker.textContent).toContain('First table cell')
    expect(table2Marker.textContent).toContain('Second table cell')
  })

  it('wraps the Nth image chunk into the Nth <img> in DOM', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<p>Before figures.</p>' +
      '<img src="data:image/png;base64,iVBORw0KGgo=" alt="Figure 1" />' +
      '<p>Between figures.</p>' +
      '<img src="data:image/png;base64,iVBORw0KGgo=" alt="Figure 2" />' +
      '<p>After figures.</p>'

    const chunks = [
      { chunk_index: 0, chunk_type: 'text',  content: 'Before figures.' },
      { chunk_index: 1, chunk_type: 'image', content: 'Figure 1' },
      { chunk_index: 2, chunk_type: 'text',  content: 'Between figures.' },
      { chunk_index: 3, chunk_type: 'image', content: 'Figure 2' },
      { chunk_index: 4, chunk_type: 'text',  content: 'After figures.' },
    ]

    const result = wrapChunkSpans(root, chunks)

    expect(result.matched).toBe(5)
    expect(result.skipped).toBe(0)

    const img1Marker = root.querySelector('[data-chunk-index="1"]')
    const img2Marker = root.querySelector('[data-chunk-index="3"]')
    expect(img1Marker).not.toBeNull()
    expect(img2Marker).not.toBeNull()
    expect(img1Marker.getAttribute('data-chunk-type')).toBe('image')
    expect(img2Marker.getAttribute('data-chunk-type')).toBe('image')

    // Each marker wraps exactly one <img>
    expect(img1Marker.querySelectorAll('img').length).toBe(1)
    expect(img2Marker.querySelectorAll('img').length).toBe(1)
    expect(img1Marker.querySelector('img').getAttribute('alt')).toBe('Figure 1')
    expect(img2Marker.querySelector('img').getAttribute('alt')).toBe('Figure 2')
  })
})
