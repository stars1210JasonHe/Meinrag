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
