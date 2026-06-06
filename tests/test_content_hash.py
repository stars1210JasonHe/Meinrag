"""Task 5: content_hash round-trips through the registry; Task 6: a second upload
whose CLEANED content matches an existing doc is rejected 409 even when raw bytes
(file_hash) differ."""
import os
import tempfile

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from fastapi.testclient import TestClient

from app.db.models import Base
from app.db.repositories import DocumentRepository, UserRepository
from tests.test_search_endpoint import _make_search_app


# ── Task 5: repository round-trip ────────────────────────────────────────────
@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_content_hash_round_trips(session):
    await UserRepository(session).ensure_exists("admin", "Admin")
    repo = DocumentRepository(session)
    await repo.add(
        doc_id="abc123def456", filename="d.txt", file_type=".txt",
        chunk_count=1, user_id="admin",
        file_hash="rawhash", content_hash="cleanhash",
    )
    await session.commit()
    got = await repo.get("abc123def456")
    assert got["content_hash"] == "cleanhash"
    assert got["file_hash"] == "rawhash"


# ── Task 6: upload dedup on cleaned content ──────────────────────────────────
def _upload(client, text):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        with open(path, "rb") as fh:
            return client.post("/documents/upload?auto_suggest=false",
                               files={"file": ("d.txt", fh, "text/plain")})
    finally:
        os.unlink(path)


def test_upload_rejects_content_dup_with_different_raw_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")
    monkeypatch.setenv("TEXT_CLEAN_ENABLED", "true")
    # clean() strips everything after the marker, so two files that differ only
    # after "###" clean to identical content (same content_hash, diff file_hash).
    import app.services.legal_text_clean as ltc
    monkeypatch.setattr(ltc, "clean", lambda t: t.split("###")[0])

    app = _make_search_app(tmp_path)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            base = "real legal content about contracts. " * 20
            r1 = _upload(client, base + "###variantA")
            assert r1.status_code == 200, r1.text
            r2 = _upload(client, base + "###variantB")     # different raw bytes
            assert r2.status_code == 409, r2.text
            assert "already" in r2.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
