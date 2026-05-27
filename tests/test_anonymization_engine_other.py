"""engine.py: warn-once + EN fallback when detect_language returns 'other'.

Kept in its own file (separate from test_anonymization_language_other.py)
because the module-level pytest.importorskip("presidio_analyzer") below
would otherwise skip the unrelated language-detection tests on stripped-
down environments that have langdetect but not Presidio + spaCy.
"""
import logging

import pytest

pytest.importorskip("presidio_analyzer")
pytest.importorskip("spacy")

from app.anonymization.language import clear_cache


def _make_engine(monkeypatch):
    """Build an AnonymizationEngine with a stub analyzer so tests don't
    pay the ~5-15s spaCy load. Stubs out three private attributes:
    `_ensure_analyzer`, `_analyzer`, `_loaded_langs`. If those names
    change in the production class, this helper needs an update.
    """
    from app.config import Settings
    from app.anonymization.engine import AnonymizationEngine
    settings = Settings(
        _env_file=None,
        anonymization_enabled=True,
        # Passes the current truthiness check in
        # Settings._validate_anonymization_key. If that validator is
        # tightened to require a valid Fernet key, update this to a real
        # `Fernet.generate_key().decode()` call.
        anonymization_encryption_key="fake-key-not-validated-in-this-test" + "x" * 20,
        anonymization_languages=["en"],
        openai_api_key="sk-not-used",
    )
    eng = AnonymizationEngine(settings)

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

    # Reset module-level state from any prior tests
    engine_mod._warned_other = False
    clear_cache()

    eng = _make_engine(monkeypatch)
    reg = EntityRegistry()

    # The stub returns no spans, so entity_count is always 0 — the test
    # therefore isolates the warn-once behaviour cleanly.
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


def test_other_lang_warning_does_not_leak_chunk_content(monkeypatch, caplog):
    """Privacy invariant: the 'other' warning MUST NOT include the chunk's
    raw text. The whole pipeline exists to keep raw PII out of downstream
    sinks, and logs are a downstream sink.
    """
    from app.anonymization import engine as engine_mod
    from app.anonymization.registry import EntityRegistry

    engine_mod._warned_other = False
    clear_cache()

    eng = _make_engine(monkeypatch)
    reg = EntityRegistry()

    sentinel_name = "Pierre Dupont"  # name embedded in a "other"-detected chunk
    with caplog.at_level(logging.WARNING, logger="app.anonymization.engine"):
        eng.analyze_and_anonymize(
            f"Bonjour, je m'appelle {sentinel_name} et je travaille à Paris.",
            reg,
        )

    for record in caplog.records:
        assert sentinel_name not in record.getMessage(), (
            f"PII leak: chunk content appears in warning log: {record.getMessage()!r}"
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
    # Detection metadata stays "other" so downstream callers can tell the
    # chunk was routed via fallback, not natively analyzed as English.
    assert result.language == "other"
    # Stub analyzer returns no results, so no entities replaced — but the
    # call should not crash and should run the EN branch.
    assert result.entity_count == 0
    assert result.text == "Bonjour, je m'appelle Pierre Dupont."
