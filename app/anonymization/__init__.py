"""PII anonymization plugin.

Pre-embedding pseudonymization gated by `settings.anonymization_enabled`.
See docs/plans/2026-05-21-anonymization-plugin.md for the architecture.

This package is import-light at the module level — heavy NER/Presidio
imports live inside the engine and are only triggered when the plugin is
actually invoked. OSS users with `anonymization_enabled=False` pay no
import cost.
"""

from app.anonymization.crypto import EncryptionError, MappingCrypto
from app.anonymization.engine import AnonymizationEngine, AnonymizationResult
from app.anonymization.language import detect_language
from app.anonymization.registry import EntityMapping, EntityRegistry

__all__ = [
    "AnonymizationEngine",
    "AnonymizationResult",
    "EncryptionError",
    "EntityMapping",
    "EntityRegistry",
    "MappingCrypto",
    "detect_language",
]
