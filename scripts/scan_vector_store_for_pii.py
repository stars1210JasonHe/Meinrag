"""Scan the vector store for raw PII that escaped anonymization.

Two modes:

  uv run python scripts/scan_vector_store_for_pii.py --doc <doc_id>
      Scan one document's chunks.

  uv run python scripts/scan_vector_store_for_pii.py --all
      Scan every chunk in the vector store.

Returns exit code 0 if zero hits found, 1 otherwise. CI-friendly.

The detection rules are deliberately simple — regex-only, no NER. This
is a backstop / health check, not a primary defense. A hit indicates
something went wrong in the anonymization pipeline.
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import TypedDict


class Finding(TypedDict):
    entity_type: str
    match: str
    start: int


_PATTERNS = {
    "EMAIL_ADDRESS": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CHINESE_ID_NUMBER": re.compile(r"\b\d{17}[\dXx]\b"),
    "CHINESE_PHONE": re.compile(r"\b1[3-9]\d{9}\b"),
    "US_PHONE": re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),
    # NOTE: deliberately no PERSON / ORG regex — those need NER.
}


_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")


def scan_text(text: str) -> list[Finding]:
    """Return all PII matches in `text`. Skips occurrences inside
    typed placeholders (e.g. `[PERSON_1]`) since those are by design.
    """
    findings: list[Finding] = []
    # Mask placeholders so they don't interfere with regex
    masked = _PLACEHOLDER_RE.sub(lambda m: "_" * len(m.group(0)), text)
    for entity_type, pattern in _PATTERNS.items():
        for match in pattern.finditer(masked):
            findings.append({
                "entity_type": entity_type,
                "match": match.group(0),
                "start": match.start(),
            })
    return findings


def _scan_chunks(chunks: list[dict]) -> dict:
    """Aggregate scan results across chunks. Returns a summary."""
    total_hits = 0
    by_doc: dict[str, list[dict]] = {}
    for ch in chunks:
        text = ch.get("content", "")
        doc_id = ch.get("doc_id") or ch.get("metadata", {}).get("doc_id", "unknown")
        hits = scan_text(text)
        if hits:
            total_hits += len(hits)
            by_doc.setdefault(doc_id, []).extend(hits)
    return {"total_hits": total_hits, "by_doc": by_doc, "scanned_chunks": len(chunks)}


def main() -> int:
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--doc", help="Scan one document's chunks (by doc_id)")
    g.add_argument("--all", action="store_true", help="Scan every chunk")
    args = parser.parse_args()

    # Late imports so unit tests of scan_text don't drag in app dependencies
    from app.config import get_settings
    from app.vectorstore.factory import create_vector_store_manager
    from app.llm.provider import create_embeddings

    settings = get_settings()
    if not settings.anonymization_enabled:
        print("WARNING: ANONYMIZATION_ENABLED=false — finding raw PII is expected.", file=sys.stderr)

    vs = create_vector_store_manager(settings)
    vs.initialize(create_embeddings(settings))

    docs = vs.get_all_documents()
    if args.doc:
        docs = [d for d in docs if d.metadata.get("doc_id") == args.doc]

    chunks = [{
        "content": d.page_content,
        "doc_id": d.metadata.get("doc_id"),
        "chunk_index": d.metadata.get("chunk_index"),
    } for d in docs]

    summary = _scan_chunks(chunks)
    print(f"Scanned {summary['scanned_chunks']} chunks across {len(summary['by_doc'])} doc(s).")
    print(f"Total PII hits: {summary['total_hits']}")
    for did, hits in summary["by_doc"].items():
        print(f"  doc {did}: {len(hits)} hit(s)")
        for h in hits[:5]:
            print(f"    - {h['entity_type']}: {h['match'][:60]!r}")
    return 0 if summary["total_hits"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
