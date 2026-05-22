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

    async def get_by_doc(self, doc_id: str) -> dict[str, str]:
        """Return all `{pseudonym: original_plaintext}` entries for a doc.

        Decrypts every row. Used at retrieval time to rebuild a registry
        so chunk text can be deanonymized before reaching the LLM prompt.
        """
        result = await self._session.execute(
            select(AnonymizationMappingModel).where(
                AnonymizationMappingModel.document_id == doc_id
            )
        )
        return {
            row.pseudonym: self._crypto.decrypt(row.original_text_encrypted)
            for row in result.scalars().all()
        }

    async def get_by_docs(self, doc_ids: list[str]) -> dict[str, dict[str, str]]:
        """Batch variant of get_by_doc.

        Returns `{doc_id: {pseudonym: original}}`. One SQL roundtrip across
        all requested doc_ids — used by the retrieval-time deanonymizer
        which gets a set of doc_ids from the retrieved chunks.
        """
        if not doc_ids:
            return {}
        result = await self._session.execute(
            select(AnonymizationMappingModel).where(
                AnonymizationMappingModel.document_id.in_(doc_ids)
            )
        )
        out: dict[str, dict[str, str]] = {d: {} for d in doc_ids}
        for row in result.scalars().all():
            out[row.document_id][row.pseudonym] = self._crypto.decrypt(
                row.original_text_encrypted
            )
        return out

    async def delete_for_doc(self, doc_id: str) -> int:
        """Remove all mapping rows for a document. Returns affected count.

        The migration's FK already has `ON DELETE CASCADE`, so this is
        usually a no-op (the row vanishes when documents.doc_id is deleted).
        Provided as an explicit cleanup path for the case where mappings
        outlive the parent doc (e.g. soft-delete experiments).
        """
        result = await self._session.execute(
            delete(AnonymizationMappingModel).where(
                AnonymizationMappingModel.document_id == doc_id
            )
        )
        await self._session.flush()
        return result.rowcount or 0


class AnonymizationAuditRepository:
    """Append-only audit log for anonymize/deanonymize/view events.

    Rows are retained past document deletion — `mark_source_deleted` stamps
    them with a timestamp so the trail survives the data it describes.
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def log(
        self,
        doc_id: str,
        user_id: str | None,
        action: str,
        entity_count: int | None = None,
    ) -> None:
        """Append one audit row. Caller handles the transaction commit.

        Allowed actions: 'anonymize', 'deanonymize', 'view'. The DB has a
        CHECK constraint — anything else raises an IntegrityError on commit.
        """
        self._session.add(
            AnonymizationAuditEntryModel(
                document_id=doc_id,
                user_id=user_id,
                action=action,
                entity_count=entity_count,
            )
        )
        await self._session.flush()

    async def mark_source_deleted(self, doc_id: str) -> int:
        """Stamp every audit row for this doc with `source_deleted_at=now`.

        Called from the document delete handler alongside the cascade —
        the rows themselves stay (compliance), but get marked so future
        readers can tell the source data is gone.
        """
        await self._session.execute(
            update(AnonymizationAuditEntryModel)
            .where(AnonymizationAuditEntryModel.document_id == doc_id)
            .values(source_deleted_at=datetime.now(timezone.utc))
        )
        await self._session.flush()
        return 1
