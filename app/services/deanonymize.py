"""Retrieval-time deanonymization helper.

Takes chunks fetched from the vector store + the encrypted mapping table
contents (already decrypted into `{pseudonym: original}` per doc), and
replaces pseudonyms with originals on each chunk's `page_content`.

The replacement is longest-pseudonym-first to avoid `[PERSON_1]` being
a prefix-substring of `[PERSON_12]`. Metadata is preserved verbatim.

Used at the retrieval boundary so the LLM prompt + the API response see
real text, while the vector store + embedding API never have.
"""
from __future__ import annotations

from langchain_core.documents import Document


def deanonymize_chunks(
    chunks: list[Document],
    mappings_by_doc: dict[str, dict[str, str]],
) -> list[Document]:
    """Return new Document objects with pseudonyms replaced.

    `mappings_by_doc[doc_id]` is a `{pseudonym: original}` dict — fetch
    via `AnonymizationMappingRepository.get_by_docs(doc_ids)`. Chunks
    whose doc_id has no entry in mappings_by_doc are passed through
    unchanged (e.g. pre-anonymization legacy docs, or non-anonymized
    chunks).
    """
    out: list[Document] = []
    for chunk in chunks:
        doc_id = chunk.metadata.get("doc_id")
        mapping = mappings_by_doc.get(doc_id) if doc_id else None
        # Empty dict is legitimate: doc was anonymized but had no PII
        # detected (e.g., a public arXiv paper). Passthrough is correct
        # in both the missing-key (None) and empty ({}) cases — the
        # downstream string-replace loop would no-op anyway.
        if not mapping:
            out.append(chunk)
            continue
        text = chunk.page_content
        for pseudonym in sorted(mapping.keys(), key=len, reverse=True):
            text = text.replace(pseudonym, mapping[pseudonym])
        # Shallow copy is safe: chunk metadata values in this codebase
        # are scalars or JSON-string blobs, never live mutable containers.
        out.append(Document(page_content=text, metadata=dict(chunk.metadata)))
    return out
