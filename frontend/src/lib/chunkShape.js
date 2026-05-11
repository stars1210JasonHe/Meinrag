// Pure canvas drawing for chunk nodes in the multi-doc graph.
//
// Dual visual encoding:
//   colour  = doc identity (resolved upstream from mindmap palette)
//   shape   = chunk type
// Splitting these onto two channels means we can show "which doc" and
// "what kind of chunk" without two competing colour scales.
//
//   text     → circle    (default — most chunks are body text)
//   table    → square
//   image    → triangle
//   formula  → diamond
//   other    → circle    (anything unrecognised falls back gracefully)

const SQRT3 = Math.sqrt(3)

/**
 * Draw one chunk node on the force-graph-2d canvas.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {{x: number, y: number, chunk_type?: string}} node
 * @param {number} radius        node radius in canvas units (force-graph
 *                                already scaled for zoom)
 * @param {string} fill          hex colour for the shape body
 * @param {string} stroke        hex colour for the border
 * @param {number} strokeWidth   border width
 */
export function drawChunkShape(ctx, node, radius, fill, stroke, strokeWidth = 1) {
  const { x, y } = node
  const type = node.chunk_type || 'text'
  ctx.fillStyle = fill
  ctx.strokeStyle = stroke
  ctx.lineWidth = strokeWidth

  ctx.beginPath()
  if (type === 'table') {
    // Square: side = 2*radius
    ctx.rect(x - radius, y - radius, radius * 2, radius * 2)
  } else if (type === 'image') {
    // Equilateral triangle pointing up
    const h = radius * SQRT3
    ctx.moveTo(x, y - h * 2 / 3)
    ctx.lineTo(x - radius, y + h / 3)
    ctx.lineTo(x + radius, y + h / 3)
    ctx.closePath()
  } else if (type === 'formula') {
    // Diamond (square rotated 45°)
    ctx.moveTo(x, y - radius)
    ctx.lineTo(x + radius, y)
    ctx.lineTo(x, y + radius)
    ctx.lineTo(x - radius, y)
    ctx.closePath()
  } else {
    // Default: circle (text + unknown types)
    ctx.arc(x, y, radius, 0, Math.PI * 2)
  }
  ctx.fill()
  if (strokeWidth > 0) ctx.stroke()
}

// Hit-target radius for pointer events — uniform circle covering the
// largest shape. force-graph-2d's nodePointerAreaPaint expects the
// "what is clickable" footprint, which we keep simple as a circle.
export function drawChunkHitArea(ctx, node, radius, color) {
  ctx.fillStyle = color
  ctx.beginPath()
  ctx.arc(node.x, node.y, radius, 0, Math.PI * 2)
  ctx.fill()
}
