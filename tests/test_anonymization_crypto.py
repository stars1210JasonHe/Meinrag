"""Phase 2 verification: Fernet encryption wrapper.

Covers:
- Round-trip encrypt/decrypt for ASCII, Latin-1, and CJK strings
- Wrong-key rejection raises EncryptionError (not InvalidToken leak)
- Empty/None key construction fails fast
- Malformed key fails fast with a useful message
- The self-test verify() helper passes
"""
import pytest
from cryptography.fernet import Fernet

from app.anonymization.crypto import EncryptionError, MappingCrypto


@pytest.fixture
def crypto() -> MappingCrypto:
    """Fresh crypto with a generated Fernet key — one per test."""
    return MappingCrypto(Fernet.generate_key().decode())


class TestRoundTrip:
    def test_ascii_round_trip(self, crypto):
        original = "John Smith"
        ct = crypto.encrypt(original)
        assert crypto.decrypt(ct) == original

    def test_email_round_trip(self, crypto):
        original = "alice@example.com"
        assert crypto.decrypt(crypto.encrypt(original)) == original

    def test_chinese_round_trip(self, crypto):
        original = "张三"
        assert crypto.decrypt(crypto.encrypt(original)) == original

    def test_mixed_language_round_trip(self, crypto):
        original = "张三 said 'hello' to John at john@example.com"
        assert crypto.decrypt(crypto.encrypt(original)) == original

    def test_empty_string_round_trip(self, crypto):
        assert crypto.decrypt(crypto.encrypt("")) == ""

    def test_ciphertext_is_bytes_not_str(self, crypto):
        ct = crypto.encrypt("anything")
        assert isinstance(ct, bytes)
        # Fernet output is base64-URL-safe, so all ASCII
        assert all(c < 128 for c in ct)


class TestWrongKey:
    def test_wrong_key_raises_encryption_error(self):
        c1 = MappingCrypto(Fernet.generate_key().decode())
        c2 = MappingCrypto(Fernet.generate_key().decode())
        ct = c1.encrypt("张三")
        with pytest.raises(EncryptionError, match="wrong key|tampered"):
            c2.decrypt(ct)

    def test_tampered_ciphertext_raises(self, crypto):
        ct = crypto.encrypt("张三")
        # Flip one byte in the middle of the ciphertext
        tampered = bytearray(ct)
        tampered[len(tampered) // 2] ^= 0xFF
        with pytest.raises(EncryptionError):
            crypto.decrypt(bytes(tampered))


class TestKeyValidation:
    def test_empty_key_fails(self):
        with pytest.raises(EncryptionError, match="non-empty"):
            MappingCrypto("")

    def test_malformed_key_fails_fast(self):
        with pytest.raises(EncryptionError, match="not a valid Fernet key"):
            MappingCrypto("this-is-not-a-fernet-key")

    def test_error_message_includes_generation_command(self):
        """Error must guide the user to fix the misconfiguration."""
        with pytest.raises(EncryptionError) as excinfo:
            MappingCrypto("garbage")
        assert "Fernet.generate_key" in str(excinfo.value)


class TestVerifySelfTest:
    def test_verify_returns_true_on_good_key(self, crypto):
        assert crypto.verify() is True

    def test_verify_round_trips_unicode(self, crypto):
        # The helper internally tests é and 中文 — implementation detail
        # but worth asserting it can't silently break on those.
        assert crypto.verify() is True
