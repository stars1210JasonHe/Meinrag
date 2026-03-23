"""Shared chunk quality utilities used by both docling and enhanced processors.

Functions:
- is_garbage_table: detect garbage markdown tables
- deduplicate_chunks: remove exact-duplicate chunks
- tag_reference_chunks: tag reference-section chunks in metadata
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
