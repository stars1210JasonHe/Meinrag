"""Rebuild similar_to edges for all existing documents.

Use this after changing `GRAPH_SIMILAR_MIN_SCORE` or `top_k` in edge_builder.
Deletes all current similar_to edges, then recomputes them with current settings.

Run:
    uv run python scripts/rebuild_similar_edges.py
"""

import asyncio
import sys
from pathlib import Path
import warnings
warnings.filterwarnings("ignore")

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, delete
from app.config import get_settings
from app.db.session import create_engine_and_session
from app.db.models import DocumentModel, ChunkEdgeModel
from app.llm.provider import create_embeddings
from app.vectorstore.factory import create_vector_store_manager
from app.services.edge_builder import build_cross_doc_edges


async def rebuild():
    settings = get_settings()
    print(f"Settings: graph_similar_min_score = {settings.graph_similar_min_score}")

    # Vector store + embeddings
    embeddings = create_embeddings(settings)
    vector_store = create_vector_store_manager(settings)
    vector_store.initialize(embeddings)

    # DB
    engine, session_factory = create_engine_and_session(settings.database_url)

    async with session_factory() as db:
        # 1. Count existing similar_to edges
        old_count_stmt = select(ChunkEdgeModel).where(
            ChunkEdgeModel.relation == "similar_to",
        )
        old_edges = (await db.execute(old_count_stmt)).scalars().all()
        print(f"\nBefore: {len(old_edges)} similar_to edges in DB")

        # 2. Delete all similar_to edges
        await db.execute(delete(ChunkEdgeModel).where(ChunkEdgeModel.relation == "similar_to"))
        await db.commit()
        print(f"Deleted {len(old_edges)} edges.")

        # 3. For each document, rebuild
        docs = (await db.execute(select(DocumentModel))).scalars().all()
        print(f"\nRebuilding for {len(docs)} documents...")

        total_built = 0
        for i, doc in enumerate(docs, 1):
            chunks = vector_store.get_chunks_by_doc(doc.doc_id)
            if not chunks:
                print(f"  [{i}/{len(docs)}] {doc.filename}: no chunks, skip")
                continue

            new_edges = build_cross_doc_edges(
                doc.doc_id, chunks, vector_store,
                top_k=5,
                min_score=settings.graph_similar_min_score,
            )

            if new_edges:
                from app.db.repositories import EdgeRepository
                repo = EdgeRepository(db)
                inserted = await repo.bulk_insert(new_edges)
                await db.commit()
                total_built += inserted
                print(f"  [{i}/{len(docs)}] {doc.filename}: +{inserted} edges")
            else:
                print(f"  [{i}/{len(docs)}] {doc.filename}: 0 edges (all below threshold)")

        print(f"\n=== DONE ===")
        print(f"Before: {len(old_edges)} edges")
        print(f"After:  {total_built} edges")
        if len(old_edges) > 0:
            retained = 100.0 * total_built / len(old_edges)
            print(f"Retained: {retained:.1f}%")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(rebuild())
