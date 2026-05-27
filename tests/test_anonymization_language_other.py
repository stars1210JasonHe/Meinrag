"""language.py: 'other' detection for non-EN non-ZH content."""
from app.anonymization.language import detect_language, clear_cache


def setup_function():
    clear_cache()


def test_pure_english_returns_en():
    assert detect_language("Alice Smith filed a complaint on May 15.") == "en"


def test_pure_chinese_returns_zh():
    assert detect_language("张三在北京市朝阳区居住,身份证号是123。") == "zh"


def test_mixed_returns_mixed():
    assert detect_language("张三 sent an email to bob@example.com") == "mixed"


def test_french_returns_other():
    # French sentence: clearly Latin script but not English.
    assert detect_language(
        "Bonjour, je m'appelle Pierre Dupont et je travaille à Paris."
    ) == "other"


def test_german_returns_other():
    assert detect_language(
        "Guten Tag, mein Name ist Hans Müller und ich arbeite in Berlin."
    ) == "other"


def test_spanish_returns_other():
    assert detect_language(
        "Hola, me llamo Juan García y vivo en Madrid desde hace muchos años."
    ) == "other"


def test_short_ambiguous_text_defers_to_en():
    # Too short for langdetect to be confident — keep current EN fallback.
    assert detect_language("Hi") == "en"


def test_empty_returns_en():
    assert detect_language("") == "en"
    assert detect_language("   ") == "en"


import logging
import pytest


pytest.importorskip("presidio_analyzer")
pytest.importorskip("spacy")


def _make_engine(monkeypatch):
    from app.config import Settings
    from app.anonymization.engine import AnonymizationEngine
    settings = Settings(
        _env_file=None,
        anonymization_enabled=True,
        anonymization_encryption_key="fake-key-not-validated-in-this-test" + "x" * 20,
        anonymization_languages=["en"],
        openai_api_key="sk-not-used",
    )
    eng = AnonymizationEngine(settings)
    # Don't actually load spaCy — stub the analyzer with one that returns
    # empty results regardless of input.
    class _StubAnalyzer:
        def analyze(self, text, language):
            return []
    monkeypatch.setattr(eng, "_ensure_analyzer", lambda: None)
    eng._analyzer = _StubAnalyzer()
    eng._loaded_langs = {"en"}
    return eng


def test_other_lang_emits_warning_once(monkeypatch, caplog):
    from app.anonymization import engine as engine_mod
    from app.anonymization.registry import EntityRegistry
    # Reset the warn-once flag from any prior tests
    engine_mod._warned_other = False
    clear_cache()

    eng = _make_engine(monkeypatch)
    reg = EntityRegistry()

    with caplog.at_level(logging.WARNING, logger="app.anonymization.engine"):
        eng.analyze_and_anonymize(
            "Bonjour, je m'appelle Pierre Dupont et je travaille à Paris.",
            reg,
        )
        eng.analyze_and_anonymize(
            "Guten Tag, mein Name ist Hans Müller.",
            reg,
        )

    other_warnings = [r for r in caplog.records if "non-EN/ZH content" in r.message]
    assert len(other_warnings) == 1, (
        f"Expected exactly one 'other' warning per process; got "
        f"{len(other_warnings)}: {[r.message for r in other_warnings]}"
    )


def test_other_lang_returns_result_via_en_fallback(monkeypatch):
    from app.anonymization import engine as engine_mod
    from app.anonymization.registry import EntityRegistry
    engine_mod._warned_other = False
    clear_cache()

    eng = _make_engine(monkeypatch)
    reg = EntityRegistry()

    result = eng.analyze_and_anonymize(
        "Bonjour, je m'appelle Pierre Dupont.", reg,
    )
    assert result.language == "other"
    # Stub analyzer returns no results, so no entities replaced — but the
    # call should not crash and should run the EN branch.
    assert result.entity_count == 0
    assert result.text == "Bonjour, je m'appelle Pierre Dupont."
