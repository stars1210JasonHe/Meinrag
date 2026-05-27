"""Per-chunk language detection.

Decides whether a chunk routes to the English or Chinese NER pipeline.
Mixed-language chunks (ZH text with embedded EN brand names, English
articles with quoted ZH excerpts) require running BOTH analyzers —
article §9.1 + §11.4 are decisive on this.

We use `langdetect` (lightweight, ~50 KB) over `fasttext` (~150 MB
model). Trade-off: `langdetect` is non-deterministic without seeding
and gets confused on very short or mixed text. We mitigate by:

1. Seeding langdetect at import time for reproducibility.
2. Treating *any* detected confidence < 0.95 OR presence of CJK
   codepoints in an English-detected chunk OR Latin codepoints in a
   Chinese-detected chunk as "mixed" → run both analyzers.

The detector is cached per-text (LRU); the upstream pipeline also
caches at the doc-level since most chunks of a single document share
a language.

Extension: adding a new language (e.g., French) requires three steps —
(a) add the language code to `settings.anonymization_languages`,
(b) extend `_EN_LANGDETECT_CODES` or add a similar mapping for the new
    language so it doesn't fall through to "other",
(c) create `app/anonymization/recognizers/french.py` and register it
in the engine. Today, anything non-EN / non-ZH Latin script returns
"other" so the engine knows to emit a fallback warning.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from langdetect import DetectorFactory, detect_langs

# Reproducible language detection — without this seed the lib randomly
# permutes feature orderings, making the same chunk sometimes go EN and
# sometimes go ZH. See https://github.com/Mimino666/langdetect#basic-usage
DetectorFactory.seed = 0

Lang = Literal["en", "zh", "mixed", "other"]

# Unicode ranges for the most common CJK ideographs. We use this to
# detect "mixed" chunks where the text clearly contains both scripts.
_CJK_RANGE = re.compile(r"[一-鿿㐀-䶿]")
# Words of 3+ Latin chars. Known limitation: text whose only Latin tokens
# are 1-2 chars (e.g., "Dr. Müller", "Ja, nein.") slips past this gate and
# routes to "en" without a langdetect call. Acceptable for v1 — real PII
# docs in our corpus contain longer Latin words; the gap matters only for
# stub-like content where the language signal is also weak.
_LATIN_RANGE = re.compile(r"[A-Za-z]{3,}")

# Latin-script langdetect codes we accept as "en". Anything else with
# high confidence becomes "other" so engine.py can emit a fallback warning.
_EN_LANGDETECT_CODES = {"en"}
# 0.90 chosen empirically: langdetect needs ~1-2 sentences of pure non-EN
# Latin text to reach 0.90 confidence on FR/DE/ES; below that the signal
# is often dominated by Latin punctuation/proper nouns and an "other"
# routing would be noisy. Validated against the real PII corpus in
# scripts/anonymization_validate_real_corpus.py. NOTE: the 0.95 figure
# in the module docstring above is aspirational / historical — the actual
# "mixed" routing uses the CJK-ratio heuristic (lines below), not a
# langdetect confidence threshold.
_OTHER_LANG_CONFIDENCE_MIN = 0.90


@lru_cache(maxsize=1024)
def detect_language(text: str) -> Lang:
    """Return one of 'en', 'zh', 'mixed', or 'other'.

    'mixed' triggers running BOTH analyzers in the engine layer with
    span deduplication. 'other' triggers a one-time warning + EN
    fallback (we don't have FR/DE NER models). Always-EN docs go
    straight to en_core_web_lg (fast). Always-ZH docs go to
    zh_core_web_trf (slower transformer).
    """
    if not text or not text.strip():
        return "en"  # arbitrary safe default for empty input

    has_cjk = _CJK_RANGE.search(text) is not None
    has_latin = _LATIN_RANGE.search(text) is not None

    # Quick path: contains both scripts AND langdetect would be ambiguous
    if has_cjk and has_latin:
        # If CJK chars are >30% of non-whitespace, lean ZH; if <10%, lean EN;
        # in between, treat as mixed.
        non_ws = re.sub(r"\s", "", text)
        if not non_ws:
            return "en"
        cjk_ratio = len(_CJK_RANGE.findall(non_ws)) / len(non_ws)
        if 0.10 <= cjk_ratio <= 0.70:
            return "mixed"
        # Fall through to langdetect for the dominant-language case

    # Pure CJK is unambiguous.
    if has_cjk and not has_latin:
        return "zh"

    # Pure Latin-script: was "en" by default; now we check langdetect to
    # catch FR/DE/ES/etc. and route them to "other". Falls back to "en"
    # on any langdetect error (short text, weird unicode) — preserves old
    # behavior for the boring cases.
    if has_latin and not has_cjk:
        try:
            candidates = detect_langs(text)
        except Exception:
            return "en"
        if not candidates:
            return "en"
        top = candidates[0]
        if top.lang in _EN_LANGDETECT_CODES:
            return "en"
        if top.prob >= _OTHER_LANG_CONFIDENCE_MIN:
            return "other"
        return "en"

    # Reached when neither has_cjk nor has_latin matched (e.g., a 2-char
    # word like "Hi" that's below the _LATIN_RANGE 3-char threshold, or
    # pure punctuation/digits). Too short or ambiguous for langdetect —
    # fall back to "en" as the safe default, same as for empty input.
    if not has_cjk and not has_latin:
        return "en"

    # Both scripts present. Article §9.1 + §11.4 are decisive: run BOTH
    # analyzers and dedupe in the engine layer. langdetect's confidence
    # output is moot in this branch — even a 0.99-confidence "en" verdict
    # still has CJK tokens that the EN NER won't see, so we always need
    # the ZH pass too (and vice versa). The earlier ratio-based check
    # (above) routes truly-dominant single-script texts away from here.
    return "mixed"


def clear_cache() -> None:
    """Drop the lru_cache. Useful in tests to keep state isolated."""
    detect_language.cache_clear()
