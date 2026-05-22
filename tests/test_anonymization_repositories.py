import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.anonymization.crypto import MappingCrypto
from app.anonymization.registry import EntityMapping
from app.anonymization.repositories import AnonymizationMappingRepository, AnonymizationAuditRepository
from app.db.models import Base, AnonymizationMappingModel, AnonymizationAuditEntryModel, DocumentModel, UserModel
from cryptography.fernet import Fernet


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_doc(session_factory):
    """Insert a parent user + document so FK constraints don't reject the mapping rows."""
    async with session_factory() as s:
        s.add(UserModel(user_id="u1", display_name="U1"))
        s.add(DocumentModel(
            doc_id="doc1", filename="f", file_type=".txt",
            chunk_count=1, user_id="u1",
        ))
        await s.commit()
    return "doc1"


@pytest.fixture
def crypto():
    return MappingCrypto(Fernet.generate_key().decode())


@pytest.mark.asyncio
async def test_save_batch_persists_encrypted_originals(session_factory, seeded_doc, crypto):
    mappings = [
        EntityMapping(original="Alice Smith", pseudonym="[PERSON_1]", entity_type="PERSON"),
        EntityMapping(original="bob@x.com",   pseudonym="[EMAIL_1]",  entity_type="EMAIL_ADDRESS"),
    ]
    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        await repo.save_batch(seeded_doc, mappings)
        await s.commit()

    async with session_factory() as s:
        rows = (await s.execute(
            select(AnonymizationMappingModel).where(
                AnonymizationMappingModel.document_id == seeded_doc
            ).order_by(AnonymizationMappingModel.pseudonym)
        )).scalars().all()

    assert len(rows) == 2
    assert {r.pseudonym for r in rows} == {"[PERSON_1]", "[EMAIL_1]"}
    # Ciphertext is bytes, not the original plaintext
    assert all(isinstance(r.original_text_encrypted, bytes) for r in rows)
    assert all(b"Alice Smith" not in r.original_text_encrypted for r in rows)
    # Round-trip decrypt recovers originals
    by_pseudonym = {r.pseudonym: crypto.decrypt(r.original_text_encrypted) for r in rows}
    assert by_pseudonym["[PERSON_1]"] == "Alice Smith"
    assert by_pseudonym["[EMAIL_1]"] == "bob@x.com"


@pytest.mark.asyncio
async def test_get_by_doc_returns_pseudonym_to_original_map(session_factory, seeded_doc, crypto):
    mappings = [
        EntityMapping(original="张三",        pseudonym="[PERSON_1]", entity_type="PERSON"),
        EntityMapping(original="13800138000", pseudonym="[PHONE_1]",  entity_type="PHONE_NUMBER"),
    ]
    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        await repo.save_batch(seeded_doc, mappings)
        await s.commit()

    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        result = await repo.get_by_doc(seeded_doc)

    assert result == {"[PERSON_1]": "张三", "[PHONE_1]": "13800138000"}


@pytest.mark.asyncio
async def test_get_by_doc_returns_empty_dict_when_no_rows(session_factory, seeded_doc, crypto):
    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        result = await repo.get_by_doc(seeded_doc)
    assert result == {}


@pytest.mark.asyncio
async def test_get_by_doc_does_not_leak_other_doc_rows(session_factory, seeded_doc, crypto):
    """Cross-doc isolation: a query for doc1 must not return doc2's rows.

    Regression guard against an accidental change to the WHERE clause —
    that would be a PII leak across documents.
    """
    # Seed a second doc (seeded_doc fixture already created doc1 + user u1)
    async with session_factory() as s:
        s.add(DocumentModel(
            doc_id="doc2", filename="g", file_type=".txt",
            chunk_count=1, user_id="u1",
        ))
        await s.commit()

    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        await repo.save_batch(seeded_doc, [
            EntityMapping(original="Alice", pseudonym="[PERSON_1]", entity_type="PERSON"),
        ])
        await repo.save_batch("doc2", [
            EntityMapping(original="Bob", pseudonym="[PERSON_1]", entity_type="PERSON"),
        ])
        await s.commit()

    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        result = await repo.get_by_doc(seeded_doc)

    assert result == {"[PERSON_1]": "Alice"}
    assert "Bob" not in result.values()


@pytest_asyncio.fixture
async def two_seeded_docs(session_factory):
    async with session_factory() as s:
        s.add(UserModel(user_id="u2", display_name="U2"))
        s.add(DocumentModel(doc_id="docA", filename="a", file_type=".txt", chunk_count=1, user_id="u2"))
        s.add(DocumentModel(doc_id="docB", filename="b", file_type=".txt", chunk_count=1, user_id="u2"))
        await s.commit()
    return ["docA", "docB"]


@pytest.mark.asyncio
async def test_get_by_docs_returns_nested_map_per_doc(session_factory, two_seeded_docs, crypto):
    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        await repo.save_batch("docA", [
            EntityMapping(original="Alice", pseudonym="[PERSON_1]", entity_type="PERSON"),
        ])
        await repo.save_batch("docB", [
            EntityMapping(original="Bob",   pseudonym="[PERSON_1]", entity_type="PERSON"),
        ])
        await s.commit()

    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        result = await repo.get_by_docs(["docA", "docB"])

    assert result == {
        "docA": {"[PERSON_1]": "Alice"},
        "docB": {"[PERSON_1]": "Bob"},
    }


@pytest.mark.asyncio
async def test_get_by_docs_empty_input_returns_empty_dict(session_factory, crypto):
    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        result = await repo.get_by_docs([])
    assert result == {}


@pytest.mark.asyncio
async def test_audit_log_writes_row(session_factory, seeded_doc):
    async with session_factory() as s:
        audit = AnonymizationAuditRepository(s)
        await audit.log(seeded_doc, user_id="u1", action="anonymize", entity_count=7)
        await s.commit()

    async with session_factory() as s:
        rows = (await s.execute(
            select(AnonymizationAuditEntryModel).where(
                AnonymizationAuditEntryModel.document_id == seeded_doc
            )
        )).scalars().all()

    assert len(rows) == 1
    assert rows[0].action == "anonymize"
    assert rows[0].entity_count == 7
    assert rows[0].user_id == "u1"
    assert rows[0].timestamp is not None


@pytest.mark.asyncio
async def test_audit_mark_source_deleted_sets_timestamp(session_factory, seeded_doc):
    async with session_factory() as s:
        audit = AnonymizationAuditRepository(s)
        await audit.log(seeded_doc, user_id="u1", action="anonymize", entity_count=3)
        await audit.log(seeded_doc, user_id="u1", action="deanonymize", entity_count=3)
        await s.commit()

    # Confirm rows start with source_deleted_at == None so the after-check is meaningful
    async with session_factory() as s:
        pre_rows = (await s.execute(
            select(AnonymizationAuditEntryModel).where(
                AnonymizationAuditEntryModel.document_id == seeded_doc
            )
        )).scalars().all()
    assert all(r.source_deleted_at is None for r in pre_rows)

    async with session_factory() as s:
        audit = AnonymizationAuditRepository(s)
        affected = await audit.mark_source_deleted(seeded_doc)
        await s.commit()
    assert affected == 2  # rowcount is the actual UPDATE count, not a literal 1

    async with session_factory() as s:
        rows = (await s.execute(
            select(AnonymizationAuditEntryModel).where(
                AnonymizationAuditEntryModel.document_id == seeded_doc
            )
        )).scalars().all()

    assert len(rows) == 2  # audit rows survive doc delete (compliance trail)
    assert all(r.source_deleted_at is not None for r in rows)


@pytest.mark.asyncio
async def test_mapping_delete_for_doc_removes_rows(session_factory, seeded_doc, crypto):
    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        await repo.save_batch(seeded_doc, [
            EntityMapping(original="X", pseudonym="[PERSON_1]", entity_type="PERSON"),
        ])
        await s.commit()

    async with session_factory() as s:
        repo = AnonymizationMappingRepository(s, crypto)
        count = await repo.delete_for_doc(seeded_doc)
        await s.commit()
    assert count == 1  # delete_for_doc returns rowcount

    async with session_factory() as s:
        rows = (await s.execute(
            select(AnonymizationMappingModel).where(
                AnonymizationMappingModel.document_id == seeded_doc
            )
        )).scalars().all()
    assert rows == []
