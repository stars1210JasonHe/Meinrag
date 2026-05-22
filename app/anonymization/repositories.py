"""Async PostgreSQL repositories for the anonymization plugin.

Persists per-document pseudonym↔original mappings (Fernet-encrypted) and
the append-only audit log of anonymize/deanonymize/view events.

Construction takes an `AsyncSession` so this fits the same per-request
pattern as `DocumentRepository`. `MappingCrypto` is injected to keep the
encryption boundary explicit — the repo never touches plaintext that
isn't routed through the crypto wrapper.
"""
from __future__ import annotations

from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.anonymization.crypto import MappingCrypto
from app.anonymization.registry import EntityMapping
from app.db.models import AnonymizationMappingModel, AnonymizationAuditEntryModel


class AnonymizationMappingRepository:
    """Repository for `anonymization_mappings` — encrypted pseudonym lookup."""

    def __init__(self, session: AsyncSession, crypto: MappingCrypto):
        self._session = session
        self._crypto = crypto

    async def save_batch(self, doc_id: str, mappings: list[EntityMapping]) -> None:
        """Encrypt each mapping's `original` field and bulk-insert.

        No-op on empty input. Caller is responsible for transaction commit.
        """
        if not mappings:
            return
        rows = [
            AnonymizationMappingModel(
                document_id=doc_id,
                original_text_encrypted=self._crypto.encrypt(m.original),
                pseudonym=m.pseudonym,
                entity_type=m.entity_type,
            )
            for m in mappings
        ]
        self._session.add_all(rows)
        await self._session.flush()
