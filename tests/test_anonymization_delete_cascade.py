"""Verify deleting a document cleans its anonymization mappings AND
stamps `source_deleted_at` on the audit rows (which stay for compliance).
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from cryptography.fernet import Fernet

from app.anonymization.crypto import MappingCrypto
from app.anonymization.registry import EntityMapping
from app.anonymization.repositories import (
    AnonymizationMappingRepository, AnonymizationAuditRepository,
)
from app.db.models import (
    Base, AnonymizationMappingModel, AnonymizationAuditEntryModel,
    UserModel, DocumentModel,
)


@pytest_asyncio.fixture
async def engine_and_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_cascade_removes_mappings_keeps_audit(engine_and_session):
    engine, factory = engine_and_session
    crypto = MappingCrypto(Fernet.generate_key().decode())

    # Seed: user, doc, mappings, audit row
    async with factory() as s:
        s.add(UserModel(user_id="u1", display_name="U1"))
        s.add(DocumentModel(
            doc_id="doc1", filename="f", file_type=".txt",
            chunk_count=1, user_id="u1",
        ))
        await s.commit()

    async with factory() as s:
        mrepo = AnonymizationMappingRepository(s, crypto)
        arepo = AnonymizationAuditRepository(s)
        await mrepo.save_batch("doc1", [
            EntityMapping(original="Alice", pseudonym="[PERSON_1]", entity_type="PERSON"),
        ])
        await arepo.log("doc1", "u1", "anonymize", entity_count=1)
        await s.commit()

    # Simulate the delete-document flow: explicit mapping delete +
    # audit mark + parent document row delete (cascade handles mappings,
    # we test that the explicit calls are idempotent / harmless).
    async with factory() as s:
        mrepo = AnonymizationMappingRepository(s, crypto)
        arepo = AnonymizationAuditRepository(s)
        await mrepo.delete_for_doc("doc1")
        await arepo.mark_source_deleted("doc1")
        from sqlalchemy import delete
        await s.execute(delete(DocumentModel).where(DocumentModel.doc_id == "doc1"))
        await s.commit()

    async with factory() as s:
        mapping_rows = (await s.execute(
            select(AnonymizationMappingModel).where(
                AnonymizationMappingModel.document_id == "doc1"
            )
        )).scalars().all()
        audit_rows = (await s.execute(
            select(AnonymizationAuditEntryModel).where(
                AnonymizationAuditEntryModel.document_id == "doc1"
            )
        )).scalars().all()

    assert mapping_rows == []                          # mappings gone
    assert len(audit_rows) == 1                        # audit stays
    assert audit_rows[0].source_deleted_at is not None # marked
