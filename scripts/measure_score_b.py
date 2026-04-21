"""Score-B instrumentation — measure which signal causes false-high confidence
on nonsense queries.

Runs 5 queries known to be outside the corpus's content, captures the composite
breakdown for each, and prints a diagnostic table. No code changes, no fix —
just measurement. Use the output to decide the fix direction next session.

Usage:
    uv run python scripts/measure_score_b.py
    uv run python scripts/measure_score_b.py --against-live   # hits live backend instead of test corpus
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, ParseMode
from app.services.retrieval import retrieve_and_rank
from app.db.session import create_engine_and_session
from app.db.repositories import EdgeRepository
from app.llm.provider import create_embeddings, create_chat_model


# Queries deliberately outside any plausible corpus content.
# Mix of topics so we can see if the false-high is consistent across domains.
NONSENSE_QUERIES = [
    "What traditional Ottoman Empire architectural design does the corpus describe?",
    "Explain the recipe for traditional French bouillabaisse stew.",
    "How did medieval Japanese tea ceremonies evolve?",
    "What are the migration patterns of Arctic terns?",
    "Describe the basics of calligraphy in Persian scripts.",
]

# A sanity query that SHOULD match the test corpus — baseline for comparison.
SANITY_QUERY = "What does the Transformer architecture use for attention?"


async def run_one(q: str, settings, store, llm, embeddings, session_factory, all_doc_ids):
    """Run one query, capture the per-chunk breakdown via DEBUG log."""
    # Redirect DEBUG logs to a buffer so we can parse them
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    retrieval_logger = logging.getLogger("app.services.retrieval")
    prev_level = retrieval_logger.level
    retrieval_logger.addHandler(handler)
    retrieval_logger.setLevel(logging.DEBUG)

    try:
        async with session_factory() as db:
            edge_repo = EdgeRepository(db)
            result = await retrieve_and_rank(
                question=q,
                top_k=6,
                doc_ids=all_doc_ids,
                user_scoped=False,  # auto-isolated: wider retrieval
                llm=llm,
                vector_store=store,
                embeddings=embeddings,
                edge_repo=edge_repo,
                settings=settings,
                force_web_search=False,
                summary_store=None,
                chat_history=None,
            )
    finally:
        retrieval_logger.removeHandler(handler)
        retrieval_logger.setLevel(prev_level)

    logs = buf.getvalue()
    # Parse SCORE-B BREAKDOWN lines into dicts
    rows = []
    for m in re.finditer(
        r"\[([a-f0-9]+):(\d+)\] sim=([\d.]+)\(x([\d.]+)=([\d.]+)\) graph=([\d.]+)\(x([\d.]+)=([\d.]+)\) \| composite=([\d.]+)",
        logs,
    ):
        rows.append({
            "doc": m.group(1)[:12],
            "idx": int(m.group(2)),
            "sim": float(m.group(3)),
            "w_sim": float(m.group(4)),
            "sim_contrib": float(m.group(5)),
            "graph_score": float(m.group(6)),
            "w_graph": float(m.group(7)),
            "graph_contrib": float(m.group(8)),
            "composite": float(m.group(9)),
        })

    return {
        "question": q,
        "top_rows": rows,
        "confidence_tier": result.confidence_tier,
        "n_sources": len(result.sources),
    }


async def main(against_live: bool = False):
    settings = Settings()
    settings.summary_enabled = False
    if not against_live:
        settings.parse_mode = ParseMode.DEFAULT

    embeddings = create_embeddings(settings)

    if against_live:
        from app.vectorstore.factory import create_vector_store_manager
        store = create_vector_store_manager(settings)
        store.initialize(embeddings)
        db_url = settings.database_url
    else:
        from app.vectorstore.chroma_store import ChromaStoreManager
        chroma_dir = Path("data/test_queries/query_test_chroma")
        store = ChromaStoreManager(persist_directory=chroma_dir)
        store.initialize(embeddings)
        db_url = "sqlite+aiosqlite:///data/test_queries/query_test.db"

    llm = create_chat_model(settings)
    engine, session_factory = create_engine_and_session(db_url)

    async with session_factory() as db:
        from sqlalchemy import select
        from app.db.models import DocumentModel
        r = await db.execute(select(DocumentModel.doc_id).where(DocumentModel.user_id == "admin"))
        all_doc_ids = [row[0] for row in r.all()]
    print(f"Corpus: {len(all_doc_ids)} docs in {'live' if against_live else 'test'} DB\n")

    results = []

    print(f"=== SANITY: {SANITY_QUERY}")
    sanity = await run_one(SANITY_QUERY, settings, store, llm, embeddings, session_factory, all_doc_ids)
    print(f"  confidence_tier={sanity['confidence_tier']} n_sources={sanity['n_sources']}")
    if sanity["top_rows"]:
        top = sanity["top_rows"][0]
        print(f"  TOP chunk: sim={top['sim']:.3f} graph={top['graph_score']:.3f} composite={top['composite']:.3f}")
    print()

    print(f"=== NONSENSE QUERIES ({len(NONSENSE_QUERIES)})\n")
    for q in NONSENSE_QUERIES:
        print(f"Q: {q}")
        res = await run_one(q, settings, store, llm, embeddings, session_factory, all_doc_ids)
        results.append(res)
        print(f"  confidence_tier={res['confidence_tier']} n_sources={res['n_sources']}")
        if res["top_rows"]:
            top = res["top_rows"][0]
            print(f"  TOP: sim={top['sim']:.3f} (×{top['w_sim']:.2f} = {top['sim_contrib']:.3f})")
            print(f"       graph={top['graph_score']:.3f} (×{top['w_graph']:.2f} = {top['graph_contrib']:.3f})")
            print(f"       composite={top['composite']:.3f}")
        print()

    # Aggregate table
    print("\n=== SUMMARY: nonsense-query top-chunk signal contributions ===")
    print(f"{'query':<48} {'tier':<8} {'sim':<8} {'graph':<8} {'composite':<10}")
    print("-" * 85)
    for r in results:
        q = r["question"][:45]
        tier = r["confidence_tier"] or "—"
        if r["top_rows"]:
            top = r["top_rows"][0]
            print(f"{q:<48} {tier:<8} {top['sim']:.3f}   {top['graph_score']:.3f}   {top['composite']:.3f}")
        else:
            print(f"{q:<48} {tier:<8} —       —       —")

    print("\n=== VERDICT ===")
    high_nonsense = [r for r in results if r["confidence_tier"] == "high"]
    print(f"Nonsense queries returning 'high confidence': {len(high_nonsense)} / {len(results)}")
    if high_nonsense:
        avg_sim = sum(r["top_rows"][0]["sim"] for r in high_nonsense if r["top_rows"]) / max(1, len(high_nonsense))
        avg_graph = sum(r["top_rows"][0]["graph_score"] for r in high_nonsense if r["top_rows"]) / max(1, len(high_nonsense))
        print(f"  Avg top-chunk similarity on false-high: {avg_sim:.3f}")
        print(f"  Avg top-chunk graph_score on false-high: {avg_graph:.3f}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--against-live", action="store_true", help="measure against live backend DB, not test corpus")
    args = parser.parse_args()
    asyncio.run(main(against_live=args.against_live))
