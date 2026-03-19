# Plan: Chunk Quality Filter, Reference Detection, Raw Cosine Scores

**Date**: 2026-03-19
**Status**: Planned

---

## Problems

### 1. Junk chunks in vector store

Docling's HybridChunker produces tiny garbage chunks from markdown formatting:

```
3 chars: ```
7 chars: ### (a)
8 chars: Figure 6
22 chars: ```markdown\n# References
```

28 out of 353 chunks are under 50 chars. These pollute retrieval — when a vague query has low similarity to everything, garbage chunks rank near the top because their embeddings are generic (close to the centroid of embedding space).

### 2. Reference detection misses docling format

Current regex: `^-?\s*\[\d+\]\s+[A-Z]` matches `- [1] Author, Title...`

Docling wraps references in markdown:
```
```markdown
# References
```

The heading `# References` is never detected. The actual reference entries may also be formatted differently by docling's HybridChunker.

### 3. Score display is misleading

Current formula:
```python
cosine = 1 - L²/2
score = clamp((cosine - 0.15) / 0.50)   # rescale [0.15, 0.65] → [0, 1]
```

Problems:
- A 0.64 cosine becomes 98% — grossly inflated
- A 0.40 cosine becomes 50% — looks mediocre when it's actually decent
- Cross-language queries (Chinese→English) land below 0.15 cosine → always show 0%
- The floor/range were guessed, not calibrated

**Fix**: Show raw cosine directly. No rescaling. Honest numbers.

---

## Changes

### Step 1: Raw cosine scores

**File**: `app/vectorstore/base.py`

Replace:
```python
_COSINE_FLOOR = 0.15
_COSINE_RANGE = 0.50

def l2sq_to_score(l2_squared_dist: float) -> float:
    cosine = 1.0 - l2_squared_dist / 2.0
    return min(1.0, max(0.0, (cosine - _COSINE_FLOOR) / _COSINE_RANGE))
```

With:
```python
def l2sq_to_score(l2_squared_dist: float) -> float:
    """Convert L2² distance to cosine similarity [0, 1].

    For unit-normalized vectors: cosine = 1 - L²/2
    """
    return max(0.0, 1.0 - l2_squared_dist / 2.0)
```

No floor, no range, no rescaling. Raw cosine similarity.

User sees:
- 60%+ = highly relevant
- 30-60% = moderately relevant
- <20% = weak match

### Step 2: Minimum chunk length filter

**File**: `app/services/docling_processor.py`

In `_chunk_text_elements()`, after creating each text chunk, skip if content is too short:

```python
MIN_CHUNK_LENGTH = 50

# In the chunking loop:
if len(chunk.text.strip()) < MIN_CHUNK_LENGTH:
    continue
```

Also filter in the main `process()` function before appending image/table/formula chunks — skip if content is just a bare label like "Figure 6":

```python
# For image chunks: skip if caption is generic placeholder AND no image_path
if not image_path and len(caption) < 20:
    continue
```

This won't affect existing data in the vector store — user needs to re-upload documents to get clean chunks. But new uploads will be clean.

### Step 3: Improved reference detection

**File**: `app/rag/chain.py`

Expand `is_reference_entry()` to also detect:
- `# References` heading (with optional markdown fencing)
- `## References`
- `## Bibliography`
- Chunks that start with these headings and contain reference-like content

```python
_REF_HEADING_RE = re.compile(r"^[`#\s]*#+\s*(?:References|Bibliography)\s*$", re.MULTILINE | re.IGNORECASE)

def is_reference_entry(text: str) -> bool:
    stripped = text.strip().strip('`').strip()

    # Check for reference heading
    if _REF_HEADING_RE.search(stripped):
        return True

    # Check for reference list entries (existing logic)
    lines = stripped.split("\n")
    if not lines:
        return False
    ref_lines = sum(1 for line in lines if _REF_LINE_RE.match(line.strip()))
    return ref_lines > 0 and ref_lines >= len(lines) * 0.5
```

---

## Files Changed

| File | Change | Effort |
|------|--------|--------|
| `app/vectorstore/base.py` | Remove rescaling, return raw cosine | Small |
| `app/services/docling_processor.py` | Add min chunk length filter (50 chars) | Small |
| `app/rag/chain.py` | Expand reference detection to match headings | Small |
| `tests/test_reranker.py` | Update score assertion if any test checks score values | Small |

---

## After deployment

- **Existing documents**: scores will change immediately (no re-upload needed for score fix)
- **Chunk quality**: requires re-upload to get filtered chunks
- **Reference detection**: works immediately on existing chunks at retrieval time

---

## Not in scope

- Query rewriting for vague/generic queries (future)
- Dynamic score calibration per query
- Chunk deduplication in vector store
