"""When ANONYMIZATION_ENABLED=false at startup but the DB has rows in
anonymization_mappings, log a WARNING — those docs will surface
`[PERSON_N]` tokens in chat answers.

Uses the direct-INSERT approach (bypasses Presidio/spaCy) so the test
stays fast (~1s) while still exercising the real lifespan check path.
SQLite does not enforce FK constraints by default, so the orphan row is
valid for the purpose of this test.
"""
import logging
import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db.models import Base, AnonymizationMappingModel


@pytest.fixture
def app_with_anon_off_but_data(monkeypatch, tmp_path):
    """Create a SQLite DB that already has a row in anonymization_mappings,
    then create an app with ANONYMIZATION_ENABLED=false pointing at it."""
    import asyncio

    db_path = tmp_path / "db.sqlite"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    # --- seed the DB with one mapping row (no Presidio needed) ----------
    async def _seed():
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async_session = async_sessionmaker(engine, expire_on_commit=False)
        async with async_session() as session:
            key = Fernet.generate_key()
            fernet = Fernet(key)
            row = AnonymizationMappingModel(
                document_id="doc_seed_001",
                original_text_encrypted=fernet.encrypt(b"Alice Smith"),
                pseudonym="PERSON_1",
                entity_type="PERSON",
            )
            session.add(row)
            await session.commit()
        await engine.dispose()

    asyncio.run(_seed())

    # --- configure the app with flag OFF, pointing at the seeded DB -----
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")
    monkeypatch.delenv("ANONYMIZATION_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VECTORSTORE_DIR", str(tmp_path / "vs"))
    monkeypatch.setenv("PARSE_MODE", "default")
    monkeypatch.setenv("USER_ISOLATION", "none")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")

    from app.main import create_app
    return create_app()


def test_warning_logged_when_flag_off_but_mappings_exist(app_with_anon_off_but_data, caplog):
    from fastapi.testclient import TestClient

    caplog.set_level(logging.WARNING)
    with TestClient(app_with_anon_off_but_data):
        pass

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    msgs = [r.message for r in warnings]
    assert any(
        "anonymization_mappings" in m.lower() or "anonymized doc" in m.lower()
        for m in msgs
    ), f"No appropriate WARNING found in log records: {msgs}"
