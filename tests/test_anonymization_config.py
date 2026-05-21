"""Phase 1 verification: Settings validator + default values.

Covers the locked-in design decisions from
docs/plans/2026-05-21-anonymization-plugin.md:
- ANONYMIZATION_ENABLED defaults to False (OSS users see no extra burden)
- Enabling without an encryption key is a fail-fast error
- Default language list is EN + ZH
- Default entity types match article §11.2 recommendation
"""
import pytest
from pydantic import ValidationError

from app.config import Settings


def _make(**overrides):
    """Build a Settings with no .env reads — pure overrides."""
    return Settings(_env_file=None, **overrides)


class TestAnonymizationDefaults:
    def test_disabled_by_default(self):
        s = _make()
        assert s.anonymization_enabled is False

    def test_encryption_key_none_by_default(self):
        s = _make()
        assert s.anonymization_encryption_key is None

    def test_default_languages_are_en_and_zh(self):
        s = _make()
        assert s.anonymization_languages == ["en", "zh"]

    def test_default_confidence_threshold(self):
        s = _make()
        assert s.anonymization_confidence_threshold == 0.7

    def test_default_entity_types_include_irreducible_pii(self):
        """Per article §11.2: default-enabled set covers irreducibly-
        identifying PII; orgs/locations/dates excluded by default
        (they carry high semantic value for retrieval).
        """
        s = _make()
        # Must-haves for any plausible PII corpus
        must_have = {
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
            "US_SSN", "CREDIT_CARD",
            "CHINESE_ID_NUMBER", "CHINESE_PHONE",
        }
        assert must_have.issubset(set(s.anonymization_entity_types))
        # Must-NOT-haves (default-off because semantic value > PII risk)
        must_not_have = {"LOCATION", "DATE_TIME", "ORGANIZATION", "NRP"}
        assert must_not_have.isdisjoint(set(s.anonymization_entity_types))


class TestAnonymizationValidator:
    def test_enabled_without_key_fails(self):
        """Fail-fast: missing key at startup beats opaque crash at first upload."""
        with pytest.raises(ValidationError) as excinfo:
            _make(anonymization_enabled=True)
        # Error message must guide the user to the fix
        msg = str(excinfo.value)
        assert "ANONYMIZATION_ENCRYPTION_KEY" in msg
        assert "Fernet" in msg

    def test_enabled_with_key_succeeds(self):
        s = _make(
            anonymization_enabled=True,
            anonymization_encryption_key="some-fernet-key-here",
        )
        assert s.anonymization_enabled is True
        assert s.anonymization_encryption_key == "some-fernet-key-here"

    def test_disabled_with_key_succeeds(self):
        """Disabled-with-key is fine — user might be staging the key
        before flipping the flag on. No validator complaint."""
        s = _make(
            anonymization_enabled=False,
            anonymization_encryption_key="key-staged-but-flag-off",
        )
        assert s.anonymization_enabled is False
        # Key still readable; just unused
        assert s.anonymization_encryption_key == "key-staged-but-flag-off"

    def test_disabled_without_key_succeeds(self):
        """Default state — OSS user with no PII concerns."""
        s = _make()
        assert s.anonymization_enabled is False
        assert s.anonymization_encryption_key is None
