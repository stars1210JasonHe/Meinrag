"""Backfill ``documents.primary_category`` and ``documents.subtags`` for docs
that pre-date the T1 schema migration (2026-04-29).

Strategy per document:
  1. Read existing rows in ``document_collections`` (legacy AI-written labels).
  2. If any string matches a ``PRIMARY_CATEGORIES`` entry → set ``primary_category``,
     drop that string from the junction.
  3. For each remaining string: if it's in ``ALL_TAGS`` (taxonomy domains +
     sub-domains) → append to ``subtags``, drop from junction.
  4. The string "other" is dropped silently (legacy junk-drawer label).
  5. Anything still in the junction stays — it's user-curated.
  6. If ``primary_category`` is still NULL after step 2, run the embedding
     classifier on chunks from the vector store and use its prediction.

Idempotent — re-running is safe (skips docs whose ``primary_category`` is set,
unless ``--force``).

Usage:
    uv run python scripts/backfill_primary_category.py [--force] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload
from langchain_openai import OpenAIEmbeddings

from app.config import Settings
from app.classification import PRIMARY_CATEGORIES, ALL_TAGS
from app.db.models import DocumentModel, DocumentCollectionModel
from app.db.session import create_engine_and_session
from app.services.embedding_classifier import classify_by_embedding, clear_cache
from app.vectorstore.factory import create_vector_store_manager
from langchain_core.documents import Document


def _classify_collections(existing: list[str]) -> tuple[str | None, list[str], list[str]]:
    """Split a flat list of legacy collection strings into the three layers.

    Returns ``(primary_category, subtags, kept_user_collections)``.
    """
    primary: str | None = None
    subtags: list[str] = []
    kept: list[str] = []

    for raw in existing:
        s = raw.strip().lower()
        if not s or s == "other":
            continue
        if primary is None and s in PRIMARY_CATEGORIES:
            primary = s
        elif s in PRIMARY_CATEGORIES:
            # Second primary-shape string — demote to subtag if it also fits the vocab,
            # else drop. (The taxonomy never overlaps primary names with sub-tags.)
            continue
        elif s in ALL_TAGS:
            if s not in subtags:
                subtags.append(s)
        else:
            kept.append(raw)
    return primary, subtags, kept


async def main(force: bool = False, dry_run: bool = False) -> None:
    settings = Settings()
    embeddings = OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        api_key=settings.openai_api_key,
    )
    vector_store = create_vector_store_manager(settings)
    vector_store.initialize(embeddings)

    clear_cache()

    engine, session_factory = create_engine_and_session(settings.database_url)

    rewrites = 0
    fallback_classifier_calls = 0
    skipped_already_set = 0
    skipped_no_chunks = 0

    async with session_factory() as session:
        stmt = select(DocumentModel).options(selectinload(DocumentModel.collections))
        result = await session.execute(stmt)
        docs: list[DocumentModel] = list(result.scalars().all())

        print(f"Backfilling {len(docs)} documents...\n")

        for doc in docs:
            existing = [dc.collection for dc in doc.collections]

            if doc.primary_category and not force:
                skipped_already_set += 1
                continue

            primary, subtags, kept = _classify_collections(existing)

            # ── LLM fallback when no primary derivable from existing labels ────
            if primary is None:
                all_chunks = vector_store.get_all_documents()
                doc_chunks: list[Document] = [
                    c for c in all_chunks if c.metadata.get("doc_id") == doc.doc_id
                ]
                if not doc_chunks:
                    print(f"  [skip] {doc.doc_id} {doc.filename!r} — no chunks in vector store")
                    skipped_no_chunks += 1
                    continue
                fallback = classify_by_embedding(doc_chunks, embeddings)
                fallback_classifier_calls += 1
                if fallback is not None:
                    primary = fallback.primary_category
                    # Merge fallback subtags with whatever we found in legacy strings
                    for tag in fallback.subtags:
                        if tag not in subtags:
                            subtags.append(tag)

            print(
                f"  {doc.doc_id} {doc.filename[:55]:<55} → "
                f"primary={primary or '(none)'} subtags={subtags} kept={kept}"
            )

            if dry_run:
                continue

            doc.primary_category = primary
            doc.subtags = subtags

            # Rewrite junction: drop everything, then re-insert kept user-curated collections
            await session.execute(
                delete(DocumentCollectionModel).where(
                    DocumentCollectionModel.doc_id == doc.doc_id
                )
            )
            for col in kept:
                session.add(DocumentCollectionModel(doc_id=doc.doc_id, collection=col))

            rewrites += 1

        if not dry_run:
            await session.commit()

    print()
    print(f"Rewrites:                {rewrites}")
    print(f"Fallback classifier:     {fallback_classifier_calls}")
    print(f"Skipped (already set):   {skipped_already_set}")
    print(f"Skipped (no chunks):     {skipped_no_chunks}")
    if dry_run:
        print("[dry-run] no changes committed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-classify even docs that already have primary_category set")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing")
    args = parser.parse_args()
    asyncio.run(main(force=args.force, dry_run=args.dry_run))
