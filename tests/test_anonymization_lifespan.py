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


def test_bad_fernet_key_raises_at_startup(monkeypatch, tmp_path):
    """Malformed Fernet key (parses as a string but isn't valid Fernet)
    must surface at lifespan startup, not first upload. MappingCrypto's
    __init__ catches this — pydantic's empty-string validator does not.
    """
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "true")
    monkeypatch.setenv("ANONYMIZATION_ENCRYPTION_KEY", "not-a-valid-fernet-key")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VECTORSTORE_DIR", str(tmp_path / "vs"))
    from app.main import create_app
    app = create_app()
    with pytest.raises(Exception, match="not a valid Fernet key"):
        with TestClient(app):
            pass


def test_missing_key_raises_before_lifespan(monkeypatch, tmp_path):
    """ANONYMIZATION_ENABLED=true + empty key must fail before the app
    starts. Pydantic's _validate_anonymization_key fires at Settings()
    construction, so create_app() itself raises — never reaches lifespan.
    """
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "true")
    monkeypatch.delenv("ANONYMIZATION_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("VECTORSTORE_DIR", str(tmp_path / "vs"))
    from app.main import create_app
    with pytest.raises(Exception, match="ANONYMIZATION_ENCRYPTION_KEY"):
        create_app()
