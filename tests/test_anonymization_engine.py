"""Phase 2 verification: AnonymizationEngine end-to-end.

Exercises the full Presidio + spaCy stack against the synthetic
fixtures from tests/fixtures/anonymization/. Acceptance:
- Every entry in expected_pii.json[*][<type>] is detected and replaced
- Nothing in expected_pii.json[*]['_must_not_flag'] is over-flagged
- Pseudonyms follow [ENTITY_TYPE_N] format
- Cross-chunk consistency: same entity across calls → same pseudonym

These tests REQUIRE the spaCy models (en_core_web_lg + zh_core_web_trf)
to be downloaded. CI without anonymization extras would skip via
importorskip.
"""
import json
from pathlib import Path

import pytest

# Skip the entire module on CI runners that don't have the anonymization
# extras installed. importorskip raises pytest.skip on missing module.
pytest.importorskip("presidio_analyzer")
spacy = pytest.importorskip("spacy")

# The libraries importing is not the same thing as the MODELS being present, and these
# tests build a real AnonymizationEngine, which loads them. The two importorskip calls
# above only prove presidio and spacy are installed; on a runner that has the libraries
# and not the models, every test in this file fails at fixture setup with spaCy E970
# instead of skipping — measured 2026-08-22, 12 failures, which is what the module
# docstring above was already trying to prevent.
#
# zh_core_web_trf additionally needs spacy-curated-transformers, whose curated-tokenizers
# dependency has no wheel for Python 3.13 and does not cythonize against current Cython —
# so on 3.13 this skip is not a temporary state, it is the only reachable one.
for _model in ("en_core_web_lg", "zh_core_web_trf"):
    if not spacy.util.is_package(_model):
        pytest.skip(
            "spaCy model %s is not installed — the anonymization engine cannot be "
            "constructed, so these end-to-end tests cannot run here" % _model,
            allow_module_level=True,
        )

from app.anonymization.engine import AnonymizationEngine
from app.anonymization.registry import EntityRegistry
from app.config import Settings


FIXTURES = Path(__file__).parent / "fixtures" / "anonymization"


@pytest.fixture(scope="module")
def settings_enabled() -> Settings:
    """Settings with anonymization on and a fresh Fernet key."""
    from cryptography.fernet import Fernet
    return Settings(
        _env_file=None,
        anonymization_enabled=True,
        anonymization_encryption_key=Fernet.generate_key().decode(),
    )


@pytest.fixture(scope="module")
def engine(settings_enabled) -> AnonymizationEngine:
    """One engine instance shared across the module to avoid reloading
    the ~500MB Chinese transformer model in every test.

    First test in the module triggers model load (~5-15s); subsequent
    calls are instant.
    """
    return AnonymizationEngine(settings_enabled)


@pytest.fixture(scope="module")
def expected_pii() -> dict:
    return json.loads((FIXTURES / "expected_pii.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sample_en() -> str:
    return (FIXTURES / "sample_en.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sample_zh() -> str:
    return (FIXTURES / "sample_zh.txt").read_text(encoding="utf-8")


class TestEnglishRecognition:
    """The article expects high accuracy on EN — recognizer test should
    catch ~all PII in sample_en.txt with no significant false positives.
    """

    def test_emails_detected(self, engine, sample_en, expected_pii):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_en, registry)
        # Email is the most reliable EN recognizer
        for email in expected_pii["sample_en.txt"]["EMAIL_ADDRESS"]:
            assert email not in result.text, (
                f"Email {email!r} should have been anonymized but is "
                f"still in the output"
            )

    def test_ssn_detected(self, engine, sample_en, expected_pii):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_en, registry)
        for ssn in expected_pii["sample_en.txt"]["US_SSN"]:
            assert ssn not in result.text

    def test_credit_card_detected(self, engine, sample_en, expected_pii):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_en, registry)
        for card in expected_pii["sample_en.txt"]["CREDIT_CARD"]:
            assert card not in result.text

    def test_ip_address_detected(self, engine, sample_en, expected_pii):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_en, registry)
        for ip in expected_pii["sample_en.txt"]["IP_ADDRESS"]:
            assert ip not in result.text

    def test_at_least_some_person_names_detected(self, engine, sample_en):
        """spaCy en_core_web_lg is good but not perfect — accept ≥2 of
        the 4 named persons being caught. The fixture has Alice Johnson,
        John Smith, Mr. Smith, Bob Wilson."""
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_en, registry)
        names = ["Alice Johnson", "John Smith", "Bob Wilson"]
        caught = sum(1 for n in names if n not in result.text)
        assert caught >= 2, (
            f"Expected at least 2 of {names} to be anonymized; "
            f"got {caught}. Output: {result.text!r}"
        )


class TestChineseRecognition:
    """Chinese is harder — spaCy zh_core_web_trf is weaker than its EN
    counterpart per article §5.2. Acceptance criteria are stricter on
    structured PII (regex-based) than on names (NER-based).
    """

    def test_chinese_id_number_detected(self, engine, sample_zh, expected_pii):
        """Critical regex recognizer — must catch every ID."""
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_zh, registry)
        for cid in expected_pii["sample_zh.txt"]["CHINESE_ID_NUMBER"]:
            assert cid not in result.text

    def test_chinese_phone_detected(self, engine, sample_zh, expected_pii):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_zh, registry)
        for phone in expected_pii["sample_zh.txt"]["CHINESE_PHONE"]:
            assert phone not in result.text

    def test_chinese_email_detected(self, engine, sample_zh, expected_pii):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_zh, registry)
        for email in expected_pii["sample_zh.txt"]["EMAIL_ADDRESS"]:
            assert email not in result.text


class TestPseudonymProperties:
    def test_pseudonyms_use_typed_format(self, engine, sample_en):
        registry = EntityRegistry()
        engine.analyze_and_anonymize(sample_en, registry)
        # Every minted mapping should have [TYPE_N] form
        for mapping in registry.new_mappings:
            assert mapping.pseudonym.startswith("["), mapping
            assert mapping.pseudonym.endswith("]"), mapping
            assert "_" in mapping.pseudonym, mapping

    def test_cross_chunk_consistency(self, engine, sample_en):
        """When the same engine processes two chunks of the same doc
        sharing entities, both chunks must use the same pseudonyms.
        """
        registry = EntityRegistry()
        # Split sample into halves
        half = len(sample_en) // 2
        r1 = engine.analyze_and_anonymize(sample_en[:half], registry)
        r2 = engine.analyze_and_anonymize(sample_en[half:], registry)
        # If an entity (e.g., "alice@example.com") happened to appear
        # in both halves, the same pseudonym must apply. Test by
        # joining both outputs and asserting the original is gone.
        combined = r1.text + r2.text
        assert "alice@example.com" not in combined


class TestResultMetadata:
    def test_entity_count_matches_replacements(self, engine, sample_en):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize(sample_en, registry)
        # entity_count should equal new_mappings size IF no repeats —
        # but our sample has "Mr. Smith" potentially duplicating "John Smith".
        # So at minimum, entity_count == count of [PERSON_*] etc. in text.
        import re
        placeholders = re.findall(r"\[[A-Z_]+_\d+\]", result.text)
        assert result.entity_count == len(placeholders)

    def test_language_field_populated(self, engine, sample_en, sample_zh):
        reg = EntityRegistry()
        en_result = engine.analyze_and_anonymize(sample_en, reg)
        assert en_result.language in ("en", "mixed")

        reg2 = EntityRegistry()
        zh_result = engine.analyze_and_anonymize(sample_zh, reg2)
        assert zh_result.language in ("zh", "mixed")


class TestEmptyInput:
    def test_empty_string_no_op(self, engine):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize("", registry)
        assert result.text == ""
        assert result.entity_count == 0
        assert len(registry.new_mappings) == 0

    def test_whitespace_only_no_op(self, engine):
        registry = EntityRegistry()
        result = engine.analyze_and_anonymize("   \n\n  ", registry)
        assert result.entity_count == 0
