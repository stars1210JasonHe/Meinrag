"""Fernet wrapper for encrypting the anonymization mapping table.

`anonymization_mappings.original_text_encrypted` stores Fernet ciphertext
of the original entity ("张三", "alice@example.com"). The vector store and
embedding API NEVER see plaintext — only authorized retrieval-time lookups
decrypt these entries.

Key management: the Fernet key lives in `ANONYMIZATION_ENCRYPTION_KEY`
(env var). Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Key rotation is out-of-scope for v1 (one-way). If the key is lost, all
mappings become unrecoverable — document this clearly in the README.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(RuntimeError):
    """Raised when encryption setup is misconfigured (bad key, etc.)."""


class MappingCrypto:
    """Stateless Fernet wrapper around a single key.

    Constructed once at app startup from the settings key; reused for
    every encrypt/decrypt. Thread-safe.

    Why not pgcrypto: avoids a PostgreSQL extension dependency. App-level
    Fernet keeps the encryption boundary inside Python — the DB only ever
    sees opaque ciphertext, which simplifies backups and key rotation
    procedures (DB doesn't need the key).
    """

    def __init__(self, key: str):
        if not key:
            raise EncryptionError(
                "MappingCrypto requires a non-empty Fernet key. "
                "Set ANONYMIZATION_ENCRYPTION_KEY in the environment."
            )
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError) as e:
            raise EncryptionError(
                f"ANONYMIZATION_ENCRYPTION_KEY is not a valid Fernet key: {e}. "
                'Generate a fresh one with: '
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            ) from e

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a UTF-8 string. Returns raw ciphertext bytes for DB storage."""
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        """Decrypt previously-encrypted bytes back to the original UTF-8 string.

        Raises EncryptionError on tampered or wrong-key ciphertext so the
        caller can audit + surface the integrity failure rather than crash
        the request with an opaque exception.
        """
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as e:
            raise EncryptionError(
                "Failed to decrypt mapping entry — wrong key, tampered "
                "ciphertext, or version mismatch."
            ) from e

    def verify(self) -> bool:
        """Self-test round-trip used by scripts/verify_anonymization_key.py.

        Catches misconfigured keys at startup rather than at first upload.
        """
        sample = "verify-round-trip-é中文"  # ASCII + Latin + CJK
        return self.decrypt(self.encrypt(sample)) == sample
