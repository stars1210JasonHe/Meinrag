import subprocess
import sys
from cryptography.fernet import Fernet


def test_verify_key_returns_0_for_valid_key(monkeypatch):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "true")
    monkeypatch.setenv("ANONYMIZATION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    r = subprocess.run(
        [sys.executable, "scripts/verify_anonymization_key.py"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "OK" in r.stdout or "OK" in r.stderr


def test_verify_key_returns_nonzero_for_bad_key(monkeypatch):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "true")
    monkeypatch.setenv("ANONYMIZATION_ENCRYPTION_KEY", "obviously-not-a-fernet-key")
    r = subprocess.run(
        [sys.executable, "scripts/verify_anonymization_key.py"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0


def test_verify_key_returns_nonzero_for_disabled(monkeypatch):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")
    monkeypatch.delenv("ANONYMIZATION_ENCRYPTION_KEY", raising=False)
    r = subprocess.run(
        [sys.executable, "scripts/verify_anonymization_key.py"],
        capture_output=True, text=True,
    )
    # When disabled, the script reports a warning and exits non-zero —
    # there's nothing to verify.
    assert r.returncode != 0
