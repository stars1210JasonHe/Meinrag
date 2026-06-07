"""Intra-document chunk dedup (DUP-PARA). Opt-in via settings.dedup_chunks_enabled
— the same paragraph at different positions can be legitimate context in general
corpora, so this is for deployments (e.g. legal) where extraction artifacts emit
a paragraph twice. Applied per upload, which is a single document."""
from langchain_core.documents import Document


def dedup_chunks(chunks: list[Document]) -> list[Document]:
    """Drop later chunks whose whitespace-normalized text was already seen.
    Preserves order; keeps the first occurrence."""
    seen: set[str] = set()
    out: list[Document] = []
    for c in chunks:
        key = " ".join((c.page_content or "").split())
        if not key:
            out.append(c)            # leave empties to the existing filters
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
