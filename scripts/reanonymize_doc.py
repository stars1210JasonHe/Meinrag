"""Re-process an already-uploaded document through the anonymization pipeline.

USE CASE: you ingested 50 docs with ANONYMIZATION_ENABLED=false. You
flipped the flag to true today. Existing docs are unprotected. This
script lets you opt in per-doc: it deletes the doc's chunks from the
vector store, re-runs the document processor with anonymization on,
and re-saves.

USAGE:

  uv run python scripts/reanonymize_doc.py <doc_id>
      Re-anonymize one doc.

  uv run python scripts/reanonymize_doc.py --disable <doc_id>
      Reverse: re-ingest with anonymization OFF (used when reverting
      the feature flag — chunks currently contain pseudonyms that
      would surface as `[PERSON_1]` in chat answers).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path


# Make app importable when run via `python scripts/...`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def reanonymize(doc_id: str, disable: bool = False) -> int:
    from app.config import get_settings
    from app.db.session import create_engine_and_session
    from app.db.repositories import DocumentRepository
    from app.services.document_processor import DocumentProcessor
    from app.vectorstore.factory import create_vector_store_manager
    from app.llm.provider import create_chat_model, create_embeddings
    from langchain_core.documents import Document

    settings = get_settings()
    if disable:
        # Force the flag off for this run regardless of env
        settings.anonymization_enabled = False
    elif not settings.anonymization_enabled:
        print(
            "ERROR: ANONYMIZATION_ENABLED=false. Set it in .env or pass --disable.",
            file=sys.stderr,
        )
        return 2

    engine_db, factory = create_engine_and_session(settings.database_url)
    embeddings = create_embeddings(settings)
    vector_store = create_vector_store_manager(settings)
    vector_store.initialize(embeddings)
    llm = create_chat_model(settings)

    crypto = None
    anon_engine = None
    if settings.anonymization_enabled:
        from app.anonymization import AnonymizationEngine, MappingCrypto
        crypto = MappingCrypto(settings.anonymization_encryption_key)
        anon_engine = AnonymizationEngine(settings)

    async with factory() as session:
        repo = DocumentRepository(session)
        doc = await repo.get(doc_id)
        if not doc:
            print(f"ERROR: doc_id {doc_id!r} not found.", file=sys.stderr)
            return 3

        upload_path = Path(settings.upload_dir) / f"{doc_id}_{doc['filename']}"
        if not upload_path.exists():
            print(
                f"ERROR: original file missing: {upload_path}",
                file=sys.stderr,
            )
            return 4

        # 1. Delete vector store entries for this doc
        vector_store.delete_document(doc_id)

        # 2. Delete existing mapping rows (if any)
        mapping_repo = None
        if settings.anonymization_enabled and crypto is not None:
            from app.anonymization.repositories import AnonymizationMappingRepository
            mapping_repo = AnonymizationMappingRepository(session, crypto)
            await mapping_repo.delete_for_doc(doc_id)

        # 3. Re-run document processor + optional anonymization
        processor = DocumentProcessor(settings)
        chunks = await processor.load_and_split(upload_path, doc_id=doc_id, llm=llm)

        if settings.anonymization_enabled and anon_engine is not None and mapping_repo is not None:
            from app.anonymization import EntityRegistry
            from app.anonymization.repositories import AnonymizationAuditRepository

            registry = EntityRegistry()
            new_chunks: list[Document] = []
            total_entities = 0
            for chunk in chunks:
                result = anon_engine.analyze_and_anonymize(chunk.page_content, registry)
                total_entities += result.entity_count
                new_chunks.append(Document(
                    page_content=result.text,
                    metadata={
                        **chunk.metadata,
                        "anonymized": True,
                        "entity_count": result.entity_count,
                        "language": result.language,
                    },
                ))
            chunks = new_chunks
            await mapping_repo.save_batch(doc_id, registry.new_mappings)
            audit_repo = AnonymizationAuditRepository(session)
            await audit_repo.log(
                doc_id, "reanonymize_script", "anonymize", entity_count=total_entities,
            )
            print(
                f"Re-anonymized {len(chunks)} chunks, {total_entities} entities."
            )
        else:
            print(f"Re-ingested {len(chunks)} chunks (anonymization OFF).")

        # 4. Re-add to vector store
        vector_store.add_documents(chunks, doc_id=doc_id)
        await session.commit()

    await engine_db.dispose()
    print(f"Done — doc {doc_id} re-ingested.")
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Re-process an already-uploaded document through the anonymization pipeline.",
    )
    parser.add_argument("doc_id", help="doc_id to re-ingest")
    parser.add_argument(
        "--disable", action="store_true",
        help="Re-ingest WITHOUT anonymization (revert mode)",
    )
    args = parser.parse_args()
    return asyncio.run(reanonymize(args.doc_id, disable=args.disable))


if __name__ == "__main__":
    sys.exit(main())
