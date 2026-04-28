"""Diagnostic: do chunks carry the `headings` metadata?

For each indexed doc, prints:
  doc_id  filename                      total  with_headings  pct  max_depth
  ...

The mindmap depth-from-headings approach (2026-04-28 design discussion)
needs this metadata. If most docs have 0% coverage we fall back to a
chunk-count heuristic instead.

Run:
  uv run python scripts/check_chunk_headings.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _heading_depth(headings) -> int:
    """Return the depth of a `headings` value.

    The docling integration stores headings as a ' > '-joined string
    (see app/services/docling_processor.py:313). So 'Section > Subsection'
    is depth 2.

    Also tolerates list / JSON / empty for safety.
    """
    if not headings:
        return 0
    if isinstance(headings, str):
        # Most common case (docling): " > "-joined path
        if " > " in headings:
            return len([p for p in headings.split(" > ") if p.strip()])
        # JSON fallback
        if headings.startswith("["):
            import json as _json
            try:
                headings = _json.loads(headings)
            except (ValueError, _json.JSONDecodeError):
                return 1  # single heading string
        else:
            return 1  # single heading string, no separator
    if isinstance(headings, list):
        if not headings:
            return 0
        if isinstance(headings[0], dict):
            levels = [h.get("level", 0) for h in headings if isinstance(h, dict)]
            return max(levels) if levels else 0
        return len(headings)
    return 0


async def main():
    from app.config import get_settings
    from app.vectorstore.factory import create_vector_store_manager
    from app.llm.provider import create_embeddings
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.repositories import DocumentRepository

    settings = get_settings()
    vector_store = create_vector_store_manager(settings)
    embeddings = create_embeddings(settings)
    vector_store.initialize(embeddings)

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        repo = DocumentRepository(session)
        docs = await repo.list_all()

    print(
        f"{'doc_id':<14} {'filename':<42} {'total':>5} {'w/head':>7} {'pct':>5} {'maxD':>5}"
    )
    print("-" * 84)

    for d in docs:
        doc_id = d["doc_id"]
        chunks = vector_store.get_chunks_by_doc(doc_id)
        total = len(chunks)
        depths = []
        with_headings = 0
        for c in chunks:
            h = (c.metadata or {}).get("headings")
            depth = _heading_depth(h)
            if depth > 0:
                with_headings += 1
                depths.append(depth)
        pct = (100 * with_headings // total) if total else 0
        max_depth = max(depths) if depths else 0
        flag = ""
        if total > 0 and pct == 0:
            flag = "  <- no heading metadata"
        elif pct < 30:
            flag = "  <- sparse"
        print(
            f"{doc_id[:14]:<14} {d.get('filename','')[:42]:<42} "
            f"{total:>5} {with_headings:>7} {pct:>4}% {max_depth:>5}{flag}"
        )


if __name__ == "__main__":
    asyncio.run(main())
