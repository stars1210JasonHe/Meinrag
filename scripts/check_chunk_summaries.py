"""One-shot diagnostic: do chunks have summaries populated?

For each indexed doc, prints:
  doc_id  filename                      total  with_summary  pct
  cdf...  attention_is_all_you_need     64     64            100%
  6a8...  ai_tool_verification_ttrl     78     0             0%      <- needs re-ingest

Run:
  uv run python scripts/check_chunk_summaries.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running as `uv run python scripts/check_chunk_summaries.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


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

    print(f"{'doc_id':<14} {'filename':<42} {'total':>5} {'w/summary':>9} {'pct':>5}")
    print("-" * 80)
    for d in docs:
        doc_id = d["doc_id"]
        chunks = vector_store.get_chunks_by_doc(doc_id)
        total = len(chunks)
        with_summary = sum(
            1 for c in chunks
            if (c.metadata or {}).get("summary")
        )
        pct = (100 * with_summary // total) if total else 0
        flag = "  <- needs re-ingest" if total > 0 and with_summary == 0 else ""
        print(f"{doc_id[:14]:<14} {d.get('filename','')[:42]:<42} {total:>5} {with_summary:>9} {pct:>4}%{flag}")


if __name__ == "__main__":
    asyncio.run(main())
