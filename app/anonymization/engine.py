"""AnonymizationEngine — Presidio wrapper for the MEINRAG pipeline.

Wraps the Presidio `AnalyzerEngine` + `AnonymizerEngine` with our
defaults (entity types from settings, custom Chinese recognizers, lazy
loading of the Chinese transformer NLP model). Exposes a small surface:

    engine = AnonymizationEngine(settings)
    anon_text, results = engine.analyze_and_anonymize(text, registry)

The engine itself holds no per-document state — the registry is passed
in by the caller. One engine instance lives on app.state for the
lifetime of the process.

Lazy-loading rationale (article §11.6 #2): `zh_core_web_trf` is ~500 MB
and adds 5-15 s to startup. We only construct the NLP engine on first
use, and only request the Chinese model when the active settings
include "zh".
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.anonymization.language import Lang, detect_language
from app.anonymization.recognizers import register_chinese_recognizers
from app.anonymization.registry import EntityRegistry

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)

# Module-level: warn at most once per process for non-EN/ZH content so
# operators notice but logs aren't flooded by long FR/DE/ES documents.
_warned_other = False


@dataclass
class AnonymizationResult:
    """Output of one chunk's analyze+anonymize pass."""
    text: str               # The pseudonymized text
    entity_count: int       # How many spans were replaced
    language: Lang          # Which detector branch fired


class AnonymizationEngine:
    """Top-level entry point for the pre-embedding stage.

    Constructs lazily — Presidio + spaCy are only imported the first
    time `analyze_and_anonymize` is called. App startup with
    `ANONYMIZATION_ENABLED=false` pays zero import cost.

    NOT thread-safe across analyze() calls if the same registry is shared.
    The pipeline guarantees one registry per document so this is fine.
    """

    def __init__(self, settings: "Settings"):
        self._settings = settings
        # Lazy-init backing fields
        self._analyzer = None
        self._loaded_langs: set[str] = set()
        # Guards _ensure_analyzer against concurrent first-call races —
        # two simultaneous uploads would otherwise both attempt to load
        # ~500 MB of spaCy models in parallel.
        self._init_lock = threading.Lock()

    # ─── Public API ─────────────────────────────────────────────────────

    def analyze_and_anonymize(
        self,
        text: str,
        registry: EntityRegistry,
    ) -> AnonymizationResult:
        """Detect PII spans, replace each with a registry-managed
        pseudonym, return the anonymized text plus metadata.

        Mixed-language chunks (language='mixed') run BOTH analyzers and
        dedupe overlapping spans by (start, entity_type) preferring the
        higher-confidence result.
        """
        if not text or not text.strip():
            return AnonymizationResult(text=text, entity_count=0, language="en")

        lang = detect_language(text)

        if lang == "mixed":
            results_en = self._analyze(text, language="en")
            results_zh = self._analyze(text, language="zh")
            results = _merge_overlapping(results_en + results_zh)
        elif lang == "other":
            global _warned_other
            if not _warned_other:
                preview = text[:60].replace("\n", " ")
                logger.warning(
                    "anonymization: non-EN/ZH content detected, "
                    "falling back to EN analyzer. Sample: %r. "
                    "Add the language to ANONYMIZATION_LANGUAGES + register "
                    "language-specific recognizers to improve accuracy.",
                    preview,
                )
                _warned_other = True
            results = self._analyze(text, language="en")
        else:
            results = self._analyze(text, language=lang)

        # Filter to user-allowed entity types (defaults in settings)
        allowed = set(self._settings.anonymization_entity_types)
        results = [r for r in results if r.entity_type in allowed]
        # Drop sub-threshold matches
        threshold = self._settings.anonymization_confidence_threshold
        results = [r for r in results if r.score >= threshold]

        # Replace from end to start so earlier offsets stay valid. Also
        # skip any span that overlaps a region we've already replaced —
        # _merge_overlapping only dedupes within the same entity_type, so
        # cross-type overlaps (e.g. PERSON nested inside an organization)
        # can still arrive here and would otherwise corrupt offsets.
        results = sorted(results, key=lambda r: r.start, reverse=True)
        anon_text = text
        replaced_regions: list[tuple[int, int]] = []
        actual_replacements = 0
        for r in results:
            if any(r.start < end and start < r.end
                   for start, end in replaced_regions):
                continue
            entity_text = text[r.start:r.end]
            pseudonym = registry.get_or_create_pseudonym(entity_text, r.entity_type)
            anon_text = anon_text[:r.start] + pseudonym + anon_text[r.end:]
            replaced_regions.append((r.start, r.end))
            actual_replacements += 1

        return AnonymizationResult(
            text=anon_text,
            entity_count=actual_replacements,
            language=lang,
        )

    # ─── Lazy initialization ────────────────────────────────────────────

    def _ensure_analyzer(self) -> None:
        """Build the Presidio analyzer + anonymizer on first use.

        Loads only the language models listed in
        `settings.anonymization_languages`. Adding ZH later is supported
        by extending the languages list and bouncing the process —
        runtime hot-reload of NLP models is out of scope for v1.
        """
        # Fast path: already built. The check is racy on its own, hence
        # the double-checked locking below.
        if self._analyzer is not None:
            return

        with self._init_lock:
            if self._analyzer is not None:
                return  # another thread won the race; reuse its result

            # Heavy imports deferred to first call — keeps the cold app
            # boot fast for OSS users with the flag off.
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider

            langs = list(self._settings.anonymization_languages)
            models: list[dict[str, str]] = []
            for lang in langs:
                if lang == "en":
                    models.append({"lang_code": "en", "model_name": "en_core_web_lg"})
                elif lang == "zh":
                    models.append({"lang_code": "zh", "model_name": "zh_core_web_trf"})
                else:
                    logger.warning("Unsupported anonymization language '%s' ignored", lang)

            if not models:
                raise RuntimeError(
                    "AnonymizationEngine: no usable languages in "
                    "settings.anonymization_languages — at least 'en' required."
                )

            nlp_config = {"nlp_engine_name": "spacy", "models": models}
            nlp_engine = NlpEngineProvider(nlp_configuration=nlp_config).create_engine()

            analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine,
                supported_languages=langs,
            )
            register_chinese_recognizers(analyzer)
            # Note: we deliberately do NOT construct Presidio's AnonymizerEngine.
            # Replacement is done inline in `analyze_and_anonymize` because we
            # need typed-placeholder pseudonyms produced by the per-doc
            # registry, not Presidio's built-in operators.
            self._loaded_langs = set(langs)
            # Publish the analyzer last so partial state isn't observable
            # to a racing reader on the fast path.
            self._analyzer = analyzer
            logger.info(
                "AnonymizationEngine ready: langs=%s, entity_types=%s",
                langs, self._settings.anonymization_entity_types,
            )

    def _analyze(self, text: str, language: str):
        """Run the Presidio analyzer for one language. Returns the raw
        list of RecognizerResult; filtering by entity type / threshold
        happens at the caller.
        """
        self._ensure_analyzer()
        if language not in self._loaded_langs:
            # User asked for a mixed-language chunk but didn't enable
            # both languages — fall back to a no-op for the missing one.
            logger.warning(
                "Language '%s' not loaded; skipping. Add to "
                "ANONYMIZATION_LANGUAGES to enable.",
                language,
            )
            return []
        return self._analyzer.analyze(text=text, language=language)


def _merge_overlapping(results: list) -> list:
    """For mixed-language chunks: when EN and ZH analyzers both flag
    overlapping spans of the same entity_type, keep the higher-score one.

    Compares by (start, end) overlap rather than exact equality —
    different language analyzers may return slightly different span
    boundaries for the same entity.
    """
    if not results:
        return []
    # Sort by score desc so the first kept hit wins on overlap
    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
    kept: list = []
    for r in sorted_results:
        overlaps_existing = False
        for k in kept:
            if r.entity_type != k.entity_type:
                continue
            # Overlap test: spans intersect at all
            if r.start < k.end and k.start < r.end:
                overlaps_existing = True
                break
        if not overlaps_existing:
            kept.append(r)
    # Caller expects start-ascending for safe substring replacement
    return sorted(kept, key=lambda r: r.start)
