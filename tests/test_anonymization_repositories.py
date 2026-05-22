import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select

from app.anonymization.crypto import MappingCrypto
from app.anonymization.registry import EntityMapping
from app.anonymization.repositories import AnonymizationMappingRepository
from app.db.models import Base, AnonymizationMappingModel, DocumentModel, UserModel
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
