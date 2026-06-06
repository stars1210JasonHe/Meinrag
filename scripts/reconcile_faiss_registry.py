"""Reconcile FAISS chunks against the document registry (Bug 1 residual cleanup).

A FAISS delete that fails now hard-fails the request and KEEPS the registry row
(see app/routers/documents.py), so new orphans no longer accumulate. This sweep
finds orphans left by PRE-fix deletes:

  faiss_only    — doc_ids with chunks in FAISS but no registry row (delete chunks)
  registry_only — registry rows whose chunks are gone from FAISS (review/remove)

Usage:
    uv run python scripts/reconcile_faiss_registry.py            # report only
    uv run python scripts/reconcile_faiss_registry.py --fix      # delete faiss_only chunks
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from langchain_openai import OpenAIEmbeddings

from app.config import Settings
from app.db.models import DocumentModel
from app.db.session import create_engine_and_session
from app.services.reconcile import find_orphans
from app.vectorstore.factory import create_vector_store_manager


async def main(fix: bool = False) -> None:
    settings = Settings()
    embeddings = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
    )
    vector_store = create_vector_store_manager(settings)
    vector_store.initialize(embeddings)

    faiss_ids = {
        c.metadata.get("doc_id")
        for c in vector_store.get_all_documents()
        if c.metadata.get("doc_id")
    }

    engine, session_factory = create_engine_and_session(settings.database_url)
    async with session_factory() as session:
        rows = await session.execute(select(DocumentModel.doc_id))
        registry_ids = set(rows.scalars().all())

    faiss_only, registry_only = find_orphans(faiss_ids, registry_ids)

    print(f"FAISS doc_ids:    {len(faiss_ids)}")
    print(f"Registry doc_ids: {len(registry_ids)}")
    print(f"faiss_only (orphaned chunks):     {len(faiss_only)}")
    for d in sorted(faiss_only):
        print(f"    {d}")
    print(f"registry_only (missing chunks):   {len(registry_only)}")
    for d in sorted(registry_only):
        print(f"    {d}")

    if not fix:
        if faiss_only or registry_only:
            print("\n[report only] re-run with --fix to delete faiss_only orphan chunks")
        return

    if not faiss_only:
        print("\nNothing to fix.")
        return

    for d in sorted(faiss_only):
        vector_store.delete_document(d)
        print(f"  deleted FAISS chunks for {d}")
    from app.rag.chain import invalidate_bm25_cache
    invalidate_bm25_cache()
    print(f"\nDeleted {len(faiss_only)} orphan doc(s) from FAISS.")
    print("registry_only rows were NOT touched — review and remove manually if confirmed stale.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix", action="store_true", help="Delete faiss_only orphan chunks from the vector store")
    args = parser.parse_args()
    asyncio.run(main(fix=args.fix))
