import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


def test_state_has_engine_when_enabled(monkeypatch, tmp_path):
    """When ANONYMIZATION_ENABLED=true, the lifespan must construct an
    AnonymizationEngine and MappingCrypto on app.state."""
    fernet_key = Fernet.generate_key().decode()
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "true")
    monkeypatch.setenv("ANONYMIZATION_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VECTORSTORE_DIR", str(tmp_path / "vs"))
    from app.main import create_app
    app = create_app()
    with TestClient(app):
        assert hasattr(app.state, "anonymization_engine")
        assert hasattr(app.state, "mapping_crypto")
        assert app.state.anonymization_engine is not None
        # Crypto round-trips
        sample = "round-trip-é中文"
        ct = app.state.mapping_crypto.encrypt(sample)
        assert app.state.mapping_crypto.decrypt(ct) == sample


def test_state_omits_engine_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VECTORSTORE_DIR", str(tmp_path / "vs"))
    from app.main import create_app
    app = create_app()
    with TestClient(app):
        # Either attr is missing OR present-but-None — both acceptable
        assert getattr(app.state, "anonymization_engine", None) is None
        assert getattr(app.state, "mapping_crypto", None) is None
