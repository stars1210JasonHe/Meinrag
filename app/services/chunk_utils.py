"""Shared chunk quality utilities used by both docling and enhanced processors.

Functions:
- is_garbage_table: detect garbage markdown tables
- deduplicate_chunks: remove exact-duplicate chunks
- tag_reference_chunks: tag reference-section chunks in metadata
- classify_section_type: classify a heading into a section type
- classify_section_from_headings: classify from a heading chain string
- enrich_section_metadata: add section_type metadata to all chunks
"""
import re
import logging

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_GENERIC_COL_RE = re.compile(r"^col\d+$", re.IGNORECASE)

_REF_HEADING_KEYWORDS = re.compile(
    r"\b(references|bibliography|works\s+cited)\b", re.IGNORECASE
)


def is_garbage_table(markdown: str) -> bool:
    """Detect garbage tables that should be filtered out during ingestion.

    Returns True (garbage) for:
    - Empty / whitespace-only tables
    - Tables with 3+ generic column headers (Col1, Col2, ...)
    - Tables where >60% of cells are 1-2 chars AND total cells > 10
    """
    if not markdown or not markdown.strip():
        return True

    lines = [line.strip() for line in markdown.strip().splitlines() if line.strip()]
    if not lines:
        return True

    all_cells: list[str] = []
    header_cells: list[str] = []
    for idx, line in enumerate(lines):
        if re.fullmatch(r"[|\s:-]+", line):
            continue
        cells = [c.strip() for c in line.split("|") if c.strip()]
        all_cells.extend(cells)
        if idx == 0:
            header_cells = cells

    if not all_cells:
        return True

    generic_count = sum(1 for c in header_cells if _GENERIC_COL_RE.match(c))
    if generic_count >= 3:
        return True

    if len(all_cells) > 10:
        tiny = sum(1 for c in all_cells if len(c) <= 2)
        if tiny / len(all_cells) > 0.6:
            return True

    return False


def deduplicate_chunks(chunks: list[Document]) -> list[Document]:
    """Remove exact-duplicate chunks (after whitespace normalisation).

    Keeps the first occurrence.
    """
    seen: set[str] = set()
    result: list[Document] = []
    for chunk in chunks:
        key = " ".join(chunk.page_content.split()).strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(chunk)
    return result


def tag_reference_chunks(chunks: list[Document]) -> None:
    """Tag reference-section chunks in-place with metadata["section"] = "references".

    Detection methods (in order):
    1. Heading-based: chunk metadata["headings"] contains References / Bibliography / Works Cited
    2. Text-based fallback: uses is_reference_entry() from app.rag.chain
    """
    from app.rag.chain import is_reference_entry

    for chunk in chunks:
        if chunk.metadata.get("section") == "references":
            continue
        headings = chunk.metadata.get("headings", "")
        if headings and _REF_HEADING_KEYWORDS.search(headings):
            chunk.metadata["section"] = "references"
        elif is_reference_entry(chunk.page_content):
            chunk.metadata["section"] = "references"


# ── Section type classifier ───────────────────────────────────────────────

# Prefix pattern: optional leading section number like "3", "3.1", "3.1.2 "
_SEC_NUM = r"(?:^|\d+(?:\.\d+)*[\.\s]*)"

_SECTION_PATTERNS = [
    ("abstract",       re.compile(_SEC_NUM + r"abstract", re.IGNORECASE)),
    ("introduction",   re.compile(_SEC_NUM + r"introduction", re.IGNORECASE)),
    ("related_work",   re.compile(_SEC_NUM + r"(?:related\s+work|background|prior\s+work)", re.IGNORECASE)),
    ("methods",        re.compile(_SEC_NUM + r"(?:method|model|architecture|approach|framework|system|design|formulation|proposed)", re.IGNORECASE)),
    ("training",       re.compile(_SEC_NUM + r"(?:training|implementation|setup|configuration)", re.IGNORECASE)),
    ("results",        re.compile(_SEC_NUM + r"(?:result|experiment|evaluation|empirical|ablation|analysis|performance)", re.IGNORECASE)),
    ("discussion",     re.compile(_SEC_NUM + r"(?:discussion|conclusion|future\s+work|limitation|summary)", re.IGNORECASE)),
    ("references",     re.compile(_SEC_NUM + r"(?:references|bibliography|works\s+cited)", re.IGNORECASE)),
    ("appendix",       re.compile(_SEC_NUM + r"(?:appendix|supplementary|supplemental)", re.IGNORECASE)),
    ("acknowledgment", re.compile(_SEC_NUM + r"(?:acknowledg)", re.IGNORECASE)),
]


def classify_section_type(heading: str | None) -> str:
    """Classify a heading into a section type.

    Returns one of: abstract, introduction, related_work, methods, training,
    results, discussion, references, appendix, acknowledgment, body.
    """
    if not heading:
        return "body"
    cleaned = heading.strip()
    for pattern_name, pattern in _SECTION_PATTERNS:
        if pattern.search(cleaned):
            return pattern_name
    return "body"


def classify_section_from_headings(headings_str: str | None) -> str:
    """Classify from a heading chain like '3 Model Architecture > 3.1 Attention'.

    Uses the top-level (first) heading for classification.
    """
    if not headings_str:
        return "body"
    top = headings_str.split(" > ")[0].strip()
    return classify_section_type(top)


def enrich_section_metadata(chunks: list[Document]) -> None:
    """Add ``section_type`` metadata to all chunks in-place.

    - Text chunks with ``headings``: classified via :func:`classify_section_from_headings`
    - Text chunks already tagged ``section=references``: set ``section_type=references``
    - Visual chunks (table/image/formula) without headings: inherit from nearest
      text chunk by page proximity
    """
    # First pass: classify text chunks that have headings or reference tags
    for chunk in chunks:
        if chunk.metadata.get("headings"):
            chunk.metadata["section_type"] = classify_section_from_headings(
                chunk.metadata["headings"]
            )
        elif chunk.metadata.get("section") == "references":
            chunk.metadata["section_type"] = "references"

    # Second pass: visual chunks inherit from nearest text chunk
    page_sections: dict[int, str] = {}
    for chunk in chunks:
        if chunk.metadata.get("chunk_type") == "text" and "section_type" in chunk.metadata:
            page = chunk.metadata.get("page", 0)
            page_sections[page] = chunk.metadata["section_type"]

    for chunk in chunks:
        if "section_type" in chunk.metadata:
            continue
        page = chunk.metadata.get("page", 0)
        best_section = "body"
        best_dist = float("inf")
        for p, sec in page_sections.items():
            dist = abs(p - page)
            if dist < best_dist or (dist == best_dist and p <= page):
                best_dist = dist
                best_section = sec
        chunk.metadata["section_type"] = best_section
