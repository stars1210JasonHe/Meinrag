import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from fastapi import Depends

from app.dependencies import (
    get_anonymization_engine,
)


def test_get_anonymization_engine_returns_none_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "u"))
    monkeypatch.setenv("VECTORSTORE_DIR", str(tmp_path / "vs"))

    from app.main import create_app
    app = create_app()

    @app.get("/_probe")
    def probe(engine=Depends(get_anonymization_engine)):
        return {"engine": engine}

    with TestClient(app) as c:
        r = c.get("/_probe")
        assert r.status_code == 200
        assert r.json()["engine"] is None


def test_get_anonymization_engine_returns_engine_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "true")
    monkeypatch.setenv("ANONYMIZATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "u"))
    monkeypatch.setenv("VECTORSTORE_DIR", str(tmp_path / "vs"))

    from app.main import create_app
    app = create_app()

    @app.get("/_probe")
    def probe(engine=Depends(get_anonymization_engine)):
        return {"has_engine": engine is not None}

    with TestClient(app) as c:
        r = c.get("/_probe")
        assert r.status_code == 200
        assert r.json()["has_engine"] is True
