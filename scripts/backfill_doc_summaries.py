"""Backfill documents.summary for docs that have per-chunk summaries in the
summary FAISS store but NULL doc-level summary in PostgreSQL.

Context: the compiled-layer pipeline generates chunk summaries during upload
and writes a doc-level summary at the end. A bug in generate_all_summaries
(fixed 2026-04-20) meant the doc-level summary was built from only the first
chunk per section_type — which collapsed to one chunk when docling didn't
populate section_type (most real corpora). Existing docs ended up with NULL
documents.summary despite having per-chunk summaries stored.

This script reads chunk summaries from the summary FAISS store and calls the
(fixed) generate_doc_summary aggregation to populate the DB column. Safe to
re-run — skips docs whose summary is already non-empty.

Usage:
    uv run python scripts/backfill_doc_summaries.py [--force]

    --force  Regenerate even for docs that already have summary populated.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.vectorstore.factory import create_vector_store_manager
from app.vectorstore.faiss_store import FAISSStoreManager
from app.services.summary_generator import generate_doc_summary, generate_all_summaries
from app.db.session import create_engine_and_session
from app.db.models import DocumentModel
from sqlalchemy import update, select
from langchain_openai import OpenAIEmbeddings, ChatOpenAI


MAX_CHUNKS_FOR_OVERVIEW = 30


async def main(force: bool = False) -> None:
    settings = Settings()
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small", api_key=settings.openai_api_key,
    )
    vector_store = create_vector_store_manager(settings)
    vector_store.initialize(embeddings)
    summary_store = FAISSStoreManager(
        persist_directory=Path(settings.vectorstore_dir) / ".." / "vectorstore_summary",
    )
    summary_store.initialize(embeddings)

    # Build an index of which doc_ids already have chunk summaries
    all_summary_chunks = summary_store.get_all_documents()
    has_chunk_summaries: dict[str, list] = {}
    for d in all_summary_chunks:
        did = d.metadata.get("doc_id")
        if did:
            has_chunk_summaries.setdefault(did, []).append(d)

    # Full list of docs from DB — we process every one
    engine, session_factory = create_engine_and_session(settings.database_url)
    async with session_factory() as db:
        result = await db.execute(select(DocumentModel.doc_id, DocumentModel.summary))
        all_docs = result.all()

    llm = ChatOpenAI(model="gpt-4o-mini", api_key=settings.openai_api_key)

    total = 0
    skipped = 0
    updated = 0
    failed = 0

    for doc_id, existing_summary in all_docs:
        total += 1
        if existing_summary and not force:
            print(f"[skip] {doc_id}: summary already populated (use --force to regenerate)")
            skipped += 1
            continue

        chunk_sums = has_chunk_summaries.get(doc_id, [])

        if not chunk_sums:
            # No chunk summaries at all — run the full pipeline (chunk + doc summaries).
            # This is expensive (~$0.01-0.15 per doc depending on size).
            print(f"[full] {doc_id}: no chunk summaries in FAISS — running full generate_all_summaries")
            try:
                await generate_all_summaries(
                    doc_id, settings,
                    vector_store=vector_store,
                    summary_store=summary_store,
                )
            except Exception as e:
                print(f"[fail] {doc_id}: full pipeline failed: {e}")
                failed += 1
                continue
            # generate_all_summaries already writes to DB — re-check
            async with session_factory() as db:
                result = await db.execute(
                    select(DocumentModel.summary).where(DocumentModel.doc_id == doc_id)
                )
                new_summary = result.scalar_one_or_none()
            if new_summary:
                updated += 1
                print(f"[done] {doc_id}: full pipeline wrote {len(new_summary)} chars")
            else:
                failed += 1
                print(f"[fail] {doc_id}: full pipeline completed but DB still has NULL summary")
            continue

        # Chunk summaries exist — just backfill doc-level summary
        sampled = chunk_sums[:MAX_CHUNKS_FOR_OVERVIEW]
        section_sums = {f"part_{i}": c.page_content for i, c in enumerate(sampled)}

        print(f"[gen]  {doc_id}: combining {len(sampled)} existing chunk summaries")
        try:
            doc_summary = await generate_doc_summary(section_sums, settings, llm=llm)
        except Exception as e:
            print(f"[fail] {doc_id}: {e}")
            failed += 1
            continue

        if not doc_summary:
            print(f"[fail] {doc_id}: generator returned None")
            failed += 1
            continue

        async with session_factory() as db:
            await db.execute(
                update(DocumentModel)
                .where(DocumentModel.doc_id == doc_id)
                .values(summary=doc_summary)
            )
            await db.commit()
        updated += 1
        print(f"[done] {doc_id}: {len(doc_summary)} chars — {doc_summary[:120]}...")

    await engine.dispose()
    print(f"\n[summary] total={total} updated={updated} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="regenerate even if summary exists")
    args = parser.parse_args()
    asyncio.run(main(force=args.force))
