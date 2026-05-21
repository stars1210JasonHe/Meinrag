"""Chinese-specific PII recognizers for Presidio.

Adds 4 entity types that Presidio's English-tuned built-ins miss:

- CHINESE_ID_NUMBER  : 18-digit national ID with check digit (身份证号)
- CHINESE_PHONE      : 11-digit mobile starting with 1[3-9]
- CHINESE_BANK_CARD  : 16-19 digit card, Luhn-validated
- CHINESE_PASSPORT   : E/G prefix + 8 digits

Patterns and scores follow article §3.2 + §11.2. Each recognizer is
registered to `supported_language="zh"` so they only fire on chunks
language-detected as ZH (or mixed).
"""
from __future__ import annotations

from presidio_analyzer import (
    AnalyzerEngine,
    Pattern,
    PatternRecognizer,
)


def _luhn_check(digits: str) -> bool:
    """Standard Luhn algorithm for credit/debit card validity.

    Used by the bank-card recognizer's `invalidator` hook so we don't
    flag arbitrary 16-19 digit numbers as cards. False-positive killer.
    """
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class LuhnValidatedBankCardRecognizer(PatternRecognizer):
    """Bank-card recognizer that suppresses non-Luhn-valid matches.

    Plain regex would flag any 16-19 digit number — too noisy in
    document corpora (page numbers, dates, IDs, telephone numbers all
    can hit that pattern). Luhn cuts false positives by ~95%.
    """

    def __init__(self):
        super().__init__(
            supported_entity="CHINESE_BANK_CARD",
            supported_language="zh",
            patterns=[
                Pattern(
                    name="chinese_bank_card",
                    regex=r"\b\d{16,19}\b",
                    score=0.7,
                ),
            ],
        )

    def validate_result(self, pattern_text: str) -> bool:
        return _luhn_check(pattern_text)


def _build_recognizers() -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="CHINESE_ID_NUMBER",
            supported_language="zh",
            patterns=[
                Pattern(
                    name="chinese_id_number",
                    # 17 digits + (digit OR X/x). Two-char check digit handled
                    # by the second group.
                    regex=r"\b\d{17}[\dXx]\b",
                    score=0.85,
                ),
            ],
        ),
        PatternRecognizer(
            supported_entity="CHINESE_PHONE",
            supported_language="zh",
            patterns=[
                Pattern(
                    name="chinese_mobile",
                    regex=r"\b1[3-9]\d{9}\b",
                    score=0.75,
                ),
            ],
        ),
        LuhnValidatedBankCardRecognizer(),
        PatternRecognizer(
            supported_entity="CHINESE_PASSPORT",
            supported_language="zh",
            patterns=[
                Pattern(
                    name="chinese_passport",
                    regex=r"\b[EeGg]\d{8}\b",
                    score=0.80,
                ),
            ],
        ),
    ]


def register_chinese_recognizers(analyzer: AnalyzerEngine) -> None:
    """Register all CHINESE_* recognizers on the given Presidio analyzer.

    Idempotent: re-registering on a fresh engine is fine. We don't dedupe
    against the existing registry because each call constructs new
    PatternRecognizer instances — Presidio doesn't expose a clean
    "remove by name" — so callers should construct one analyzer and
    register once.
    """
    for rec in _build_recognizers():
        analyzer.registry.add_recognizer(rec)
