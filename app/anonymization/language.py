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
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from langdetect import DetectorFactory

# Reproducible language detection — without this seed the lib randomly
# permutes feature orderings, making the same chunk sometimes go EN and
# sometimes go ZH. See https://github.com/Mimino666/langdetect#basic-usage
DetectorFactory.seed = 0

Lang = Literal["en", "zh", "mixed"]

# Unicode ranges for the most common CJK ideographs. We use this to
# detect "mixed" chunks where the text clearly contains both scripts.
_CJK_RANGE = re.compile(r"[一-鿿㐀-䶿]")
_LATIN_RANGE = re.compile(r"[A-Za-z]{3,}")  # words of 3+ Latin chars


@lru_cache(maxsize=1024)
def detect_language(text: str) -> Lang:
    """Return one of 'en', 'zh', or 'mixed'.

    'mixed' triggers running BOTH analyzers in the engine layer with
    span deduplication. Always-EN docs go straight to en_core_web_lg
    (fast). Always-ZH docs go to zh_core_web_trf (slower transformer).
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

    # Single-script quick paths — pure CJK or pure Latin is a confident
    # signal in itself, more reliable than langdetect's probability output
    # on short or technical text.
    if has_cjk and not has_latin:
        return "zh"
    if has_latin and not has_cjk:
        # Could be EN, DE, FR, etc. — anything non-CJK routes to the EN
        # pipeline for v1. v2 multi-language work expands this.
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
