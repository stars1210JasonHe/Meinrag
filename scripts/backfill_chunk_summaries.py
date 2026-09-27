"""Regenerate per-chunk summaries for existing documents with the CONTEXTUAL prompt.

Why: chunk summaries feed the summary FAISS index that the dual-index search merges with
the raw index. The old prompt summarised each chunk in isolation, so the summary of a
statute clause could not say which statute it belonged to. The contextual prompt puts the
document opening in front of every chunk (see summary_generator.py). Documents ingested
before this change keep their old summaries until this script re-runs them.

Usage (from the repo root, inside the deployment's environment):
    uv run python scripts/backfill_chunk_summaries.py --collection legal --dry-run
    uv run python scripts/backfill_chunk_summaries.py --collection legal
    uv run python scripts/backfill_chunk_summaries.py --doc-ids abc123,def456
    uv run python scripts/backfill_chunk_summaries.py --all --limit 100

Per document: the document's vectors are removed from the summary store, then
generate_all_summaries() regenerates chunk summaries (contextual), writes them into the raw
docstore metadata, adds them to the summary store, and refreshes the document-level summary.
Progress is appended to a ledger file (one doc_id per line); re-running skips finished ids,
so an interrupted run resumes where it stopped. FAISS files are persisted every
``--persist-every`` documents and at the end, not per document.

Cost: one LLM call per chunk of at least SUMMARY_MIN_CHARS characters (gpt-4o-mini by
default). The dry run prints the document and chunk counts so the cost can be estimated
before anything is spent.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config import Settings
from app.db.models import DocumentCollectionModel, DocumentModel
from app.db.session import create_engine_and_session
from app.services.summary_generator import generate_all_summaries
from app.vectorstore.factory import create_vector_store_manager
from app.vectorstore.faiss_store import FAISSStoreManager


async def _select_doc_ids(settings: Settings, args) -> list[str]:
    if args.doc_ids:
        return [d.strip() for d in args.doc_ids.split(",") if d.strip()]
    engine, session_factory = create_engine_and_session(settings.database_url)
    try:
        async with session_factory() as db:
            if args.collection:
                stmt = (select(DocumentCollectionModel.doc_id)
                        .where(DocumentCollectionModel.collection == args.collection)
                        .order_by(DocumentCollectionModel.doc_id))
            else:
                stmt = select(DocumentModel.doc_id).order_by(DocumentModel.doc_id)
            rows = await db.execute(stmt)
            ids = [r[0] for r in rows.all()]
    finally:
        await engine.dispose()
    return ids


def _read_ledger(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


async def main(args) -> int:
    settings = Settings()
    if not settings.summary_contextual:
        print("SUMMARY_CONTEXTUAL is off in this environment; the regenerated summaries would be the "
              "old kind. Set SUMMARY_CONTEXTUAL=true or drop --require-contextual.")
        if args.require_contextual:
            return 2

    doc_ids = await _select_doc_ids(settings, args)
    ledger = Path(args.ledger)
    done = _read_ledger(ledger)
    todo = [d for d in doc_ids if d not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"documents selected={len(doc_ids)} already-done={len(doc_ids) - len(todo) if not args.limit else len(done & set(doc_ids))} "
          f"to-run={len(todo)} min_chars={settings.summary_min_chars} contextual={settings.summary_contextual}")

    from langchain_openai import OpenAIEmbeddings
    embeddings = OpenAIEmbeddings(model=settings.openai_embedding_model, api_key=settings.openai_api_key)
    vector_store = create_vector_store_manager(settings)
    vector_store.initialize(embeddings)
    summary_store = FAISSStoreManager(persist_directory=Path(settings.vectorstore_dir) / ".." / "vectorstore_summary")
    summary_store.initialize(embeddings)

    if args.dry_run:
        n_chunks = 0
        n_eligible = 0
        for d in todo:
            chunks = vector_store.get_chunks_by_doc(d)
            n_chunks += len(chunks)
            n_eligible += sum(1 for c in chunks
                              if c.metadata.get("chunk_type") in ("text", "table")
                              and len(c.page_content) >= settings.summary_min_chars)
        print(f"DRY RUN: {len(todo)} documents, {n_chunks} chunks, {n_eligible} eligible for a summary "
              f"(one LLM call each). Nothing written.")
        return 0

    t0 = time.time()
    ok = failed = 0
    since_persist = 0
    with ledger.open("a", encoding="utf-8") as led:
        for i, d in enumerate(todo, 1):
            try:
                summary_store.delete_document(d, persist=False)
                await generate_all_summaries(d, settings, vector_store=vector_store,
                                             summary_store=summary_store, persist=False)
                led.write(d + "\n")
                led.flush()
                ok += 1
                since_persist += 1
            except Exception as e:  # keep going; the ledger says what is done
                failed += 1
                print(f"  FAILED {d}: {type(e).__name__}: {e}")
            if since_persist >= args.persist_every:
                vector_store.persist()
                summary_store.persist()
                since_persist = 0
                print(f"  persisted after {i}/{len(todo)} ({time.time() - t0:.0f}s)")
    vector_store.persist()
    summary_store.persist()
    print(f"DONE ok={ok} failed={failed} in {time.time() - t0:.0f}s; ledger={ledger}")
    return 1 if failed else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--collection", help="every document in this collection")
    g.add_argument("--doc-ids", help="comma-separated doc_ids")
    g.add_argument("--all", action="store_true", help="every document in the registry")
    p.add_argument("--limit", type=int, default=0, help="stop after N documents (0 = no limit)")
    p.add_argument("--ledger", default="data/backfill_chunk_summaries.done", help="progress file; finished ids are skipped on re-run")
    p.add_argument("--persist-every", type=int, default=25, help="write the FAISS files every N documents")
    p.add_argument("--dry-run", action="store_true", help="count documents and eligible chunks; write nothing")
    p.add_argument("--require-contextual", action="store_true", default=True,
                   help="refuse to run when SUMMARY_CONTEXTUAL is off (default)")
    p.add_argument("--no-require-contextual", dest="require_contextual", action="store_false")
    sys.exit(asyncio.run(main(p.parse_args())))
