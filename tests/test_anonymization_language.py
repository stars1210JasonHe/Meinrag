"""Phase 2 verification: per-chunk language detection.

Covers:
- Pure English text → 'en'
- Pure Chinese text → 'zh'
- Mixed EN+ZH chunks → 'mixed'
- Empty/whitespace → safe fallback
- Cache isolation between tests
- Edge cases: short text, single non-Latin word, code-switching
"""
import pytest

from app.anonymization.language import clear_cache, detect_language


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear LRU cache between tests so order doesn't matter."""
    clear_cache()
    yield
    clear_cache()


class TestPureLanguages:
    def test_english_paragraph(self):
        text = (
            "The plaintiff, John Smith, contacted our office regarding "
            "a workplace injury filed last week."
        )
        assert detect_language(text) == "en"

    def test_chinese_paragraph(self):
        text = "原告张三于二零二六年三月十五日通过电子邮件向本所提交申诉材料。"
        assert detect_language(text) == "zh"

    def test_english_with_proper_nouns(self):
        text = "Microsoft and Google compete in cloud infrastructure."
        assert detect_language(text) == "en"


class TestMixedLanguage:
    def test_chinese_with_embedded_english_name(self):
        """Real-world law-doc pattern: Chinese paragraph naming an
        English party. Article §9.1 calls this 'mixed' — both
        analyzers should run."""
        text = "原告John Smith于上周提交了诉状, 并附上了证据。"
        assert detect_language(text) == "mixed"

    def test_english_with_embedded_chinese(self):
        text = "The witness, 张三, confirmed the events of last Tuesday."
        assert detect_language(text) == "mixed"

    def test_substantial_code_switching(self):
        text = "Counsel said the agreement (合同) was signed by Mr. 王五 in Beijing 北京."
        assert detect_language(text) == "mixed"


class TestEdgeCases:
    def test_empty_string(self):
        assert detect_language("") == "en"

    def test_whitespace_only(self):
        assert detect_language("   \n\t  ") == "en"

    def test_single_chinese_character_falls_back_safely(self):
        # langdetect is unreliable on very short text — we accept either
        # 'zh' (correct) or 'mixed' (cautious) but never 'en'
        result = detect_language("张")
        assert result in ("zh", "mixed")

    def test_unparseable_chars_dont_crash(self):
        """Pipeline must never crash on weird input."""
        result = detect_language("!@#$%^&*()")
        # Any valid value, no exception
        assert result in ("en", "zh", "mixed")


class TestCaching:
    def test_repeat_calls_return_same_result(self):
        """LRU cache should be deterministic across calls in one process."""
        text = "The plaintiff filed a complaint."
        r1 = detect_language(text)
        r2 = detect_language(text)
        assert r1 == r2

    def test_clear_cache_works(self):
        """Defensive: clear_cache must not raise even when cache is empty."""
        clear_cache()
        clear_cache()  # twice; idempotent
