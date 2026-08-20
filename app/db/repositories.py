"""Async PostgreSQL-backed repositories.

Same public interface as the old JSON/in-memory classes,
but all methods are async and use SQLAlchemy sessions.
"""
import logging
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, BaseMessage
from sqlalchemy import select, delete, func, update, or_, cast, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    DocumentModel,
    DocumentCollectionModel,
    UserModel,
    ChatSessionModel,
    ChatMessageModel,
    ChunkEdgeModel,
)

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Async PostgreSQL-backed document metadata store."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(
        self,
        doc_id: str,
        filename: str,
        file_type: str,
        chunk_count: int,
        collections: list[str] | None = None,
        user_id: str = "admin",
        file_hash: str | None = None,
        content_hash: str | None = None,
        primary_category: str | None = None,
        subtags: list[str] | None = None,
    ) -> None:
        doc = DocumentModel(
            doc_id=doc_id,
            filename=filename,
            file_type=file_type,
            chunk_count=chunk_count,
            user_id=user_id,
            file_hash=file_hash,
            content_hash=content_hash,
            primary_category=primary_category,
            subtags=list(subtags or []),
        )
        self._session.add(doc)
        for coll_name in (collections or []):
            self._session.add(
                DocumentCollectionModel(doc_id=doc_id, collection=coll_name)
            )
        await self._session.flush()

    async def remove(self, doc_id: str) -> bool:
        result = await self._session.execute(
            delete(DocumentModel).where(DocumentModel.doc_id == doc_id)
        )
        await self._session.flush()
        return result.rowcount > 0

    async def get(self, doc_id: str) -> dict | None:
        stmt = (
            select(DocumentModel)
            .options(selectinload(DocumentModel.collections))
            .where(DocumentModel.doc_id == doc_id)
        )
        result = await self._session.execute(stmt)
        doc = result.scalar_one_or_none()
        return doc.to_dict() if doc else None

    async def list_all(self, user_id: str | None = None) -> list[dict]:
        stmt = select(DocumentModel).options(selectinload(DocumentModel.collections))
        if user_id:
            stmt = stmt.where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [doc.to_dict() for doc in result.scalars().all()]

    async def list_by_collection(
        self, collection: str, user_id: str | None = None
    ) -> list[dict]:
        stmt = (
            select(DocumentModel)
            .options(selectinload(DocumentModel.collections))
            .join(DocumentCollectionModel)
            .where(DocumentCollectionModel.collection == collection)
        )
        if user_id:
            stmt = stmt.where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [doc.to_dict() for doc in result.unique().scalars().all()]

    async def list_by_subtag(
        self, subtag: str, user_id: str | None = None
    ) -> list[dict]:
        """Docs whose subtags JSON contains `subtag` (case-insensitive substring,
        the same match used by the subtag branch of search_by_text). Parallels
        list_by_collection so the query router can resolve a subtag filter to
        doc_ids exactly the way it resolves a collection filter."""
        import json as _json
        # subtags is a JSON column whose ::text is unicode-escaped (ensure_ascii), so a raw
        # CJK LIKE never matches what was stored. Match BOTH the raw and the escaped JSON
        # form (ASCII is identical in both) so a CJK matter/case tag is filterable too.
        raw = f"%{subtag.lower()}%"
        esc = f"%{_json.dumps(subtag)[1:-1].replace(chr(92), chr(92) * 2).lower()}%"
        col = func.lower(cast(DocumentModel.subtags, String))
        stmt = (
            select(DocumentModel)
            .options(selectinload(DocumentModel.collections))
            .where(or_(col.like(raw), col.like(esc)))
        )
        if user_id:
            stmt = stmt.where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [doc.to_dict() for doc in result.unique().scalars().all()]

    async def search_by_text(
        self,
        query: str,
        user_id: str | None = None,
        collection: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Case-insensitive substring search across filename, primary_category,
        subtags (cast to text), and summary. Optionally restrict to a collection.

        Returns (rows, total_match_count). Used by the short-query branch of
        GET /documents?search= — long queries fall back to semantic search via
        the chunk-summary FAISS index in the router layer.
        """
        pattern = f"%{query.lower()}%"
        base = (
            select(DocumentModel)
            .options(selectinload(DocumentModel.collections))
        )
        if collection:
            base = base.join(DocumentCollectionModel).where(
                DocumentCollectionModel.collection == collection
            )
        if user_id:
            base = base.where(DocumentModel.user_id == user_id)
        base = base.where(
            or_(
                func.lower(DocumentModel.filename).like(pattern),
                func.lower(func.coalesce(DocumentModel.primary_category, "")).like(pattern),
                func.lower(cast(DocumentModel.subtags, String)).like(pattern),
                func.lower(func.coalesce(DocumentModel.summary, "")).like(pattern),
            )
        )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self._session.execute(count_stmt)).scalar_one()

        page_stmt = (
            base.order_by(DocumentModel.uploaded_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(page_stmt)
        rows = [doc.to_dict() for doc in result.unique().scalars().all()]
        return rows, total

    async def get_many_by_ids(
        self, doc_ids: list[str], user_id: str | None = None
    ) -> list[dict]:
        """Bulk fetch by doc_id list, preserving the input order.

        Used by the semantic-search branch of GET /documents?search= where the
        ranking order is determined upstream (chunk-summary FAISS aggregation).
        """
        if not doc_ids:
            return []
        stmt = (
            select(DocumentModel)
            .options(selectinload(DocumentModel.collections))
            .where(DocumentModel.doc_id.in_(doc_ids))
        )
        if user_id:
            stmt = stmt.where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        by_id = {doc.doc_id: doc.to_dict() for doc in result.unique().scalars().all()}
        return [by_id[d] for d in doc_ids if d in by_id]

    async def update_collections(self, doc_id: str, collections: list[str]) -> bool:
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.doc_id == doc_id)
        )
        if not result.scalar_one_or_none():
            return False
        await self._session.execute(
            delete(DocumentCollectionModel).where(
                DocumentCollectionModel.doc_id == doc_id
            )
        )
        for coll_name in collections:
            self._session.add(
                DocumentCollectionModel(doc_id=doc_id, collection=coll_name)
            )
        await self._session.flush()
        return True

    async def update_classification(
        self,
        doc_id: str,
        primary_category: str | None,
        subtags: list[str],
    ) -> bool:
        """Replace ``primary_category`` and ``subtags`` on a document. Does not
        touch ``document_collections`` (those are user-curated)."""
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.doc_id == doc_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            return False
        doc.primary_category = primary_category
        doc.subtags = list(subtags or [])
        await self._session.flush()
        return True

    async def get_all_collections(self, user_id: str | None = None) -> list[str]:
        stmt = select(DocumentCollectionModel.collection).distinct()
        if user_id:
            stmt = stmt.join(DocumentModel).where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return sorted(result.scalars().all())

    async def add_docs_to_collection(
        self, collection: str, doc_ids: list[str], user_id: str | None = None,
    ) -> tuple[int, int]:
        """Add each doc to the collection if not already assigned.

        Returns (added_count, skipped_existing_count). Validates user ownership
        when user_id is provided. Atomic within the current session's transaction.
        """
        if not doc_ids:
            return 0, 0

        # Validate docs exist and belong to user (if scoped)
        stmt = select(DocumentModel.doc_id).where(DocumentModel.doc_id.in_(doc_ids))
        if user_id:
            stmt = stmt.where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        valid_ids = set(result.scalars().all())

        if not valid_ids:
            return 0, 0

        # Fetch existing junction rows to avoid duplicate inserts
        existing_stmt = select(DocumentCollectionModel.doc_id).where(
            DocumentCollectionModel.collection == collection,
            DocumentCollectionModel.doc_id.in_(valid_ids),
        )
        existing_result = await self._session.execute(existing_stmt)
        existing_ids = set(existing_result.scalars().all())

        to_add = valid_ids - existing_ids
        for did in to_add:
            self._session.add(
                DocumentCollectionModel(doc_id=did, collection=collection)
            )
        await self._session.flush()
        return len(to_add), len(existing_ids)

    async def get_by_id(self, doc_id: str) -> dict | None:
        """Alias for get() — returns document as dict or None."""
        return await self.get(doc_id)

    async def update_status(self, doc_id: str, status: str) -> None:
        """Update the processing status of a document."""
        await self._session.execute(
            update(DocumentModel).where(DocumentModel.doc_id == doc_id).values(status=status)
        )
        await self._session.flush()

    async def count(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(DocumentModel)
        )
        return result.scalar_one()


class UserRepository:
    """Async PostgreSQL-backed user store."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, user_id: str, display_name: str) -> dict:
        user = UserModel(user_id=user_id, display_name=display_name)
        self._session.add(user)
        await self._session.flush()
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        }

    async def get(self, user_id: str) -> dict | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        }

    async def ensure_exists(self, user_id: str, display_name: str) -> None:
        """Create user if not exists. Safe under concurrent access."""
        if await self.exists(user_id):
            return
        try:
            async with self._session.begin_nested():
                self._session.add(
                    UserModel(user_id=user_id, display_name=display_name)
                )
        except IntegrityError:
            pass  # Already exists from concurrent creation

    async def exists(self, user_id: str) -> bool:
        result = await self._session.execute(
            select(func.count()).select_from(UserModel).where(
                UserModel.user_id == user_id
            )
        )
        return result.scalar_one() > 0

    async def list_all(self) -> list[dict]:
        result = await self._session.execute(select(UserModel))
        return [
            {
                "user_id": u.user_id,
                "display_name": u.display_name,
                "created_at": u.created_at.isoformat(),
            }
            for u in result.scalars().all()
        ]


class ChatSessionRepository:
    """Async PostgreSQL-backed chat session store.

    Same interface as SessionMemoryManager: get_history() and add_exchange().
    """

    def __init__(self, session: AsyncSession, max_messages: int = 20, session_ttl: int = 3600):
        self._session = session
        self._max_messages = max_messages
        self._session_ttl = session_ttl

    async def get_history(self, session_id: str) -> list[BaseMessage]:
        result = await self._session.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id
            )
        )
        chat_session = result.scalar_one_or_none()
        if not chat_session:
            return []

        # Update last access
        chat_session.last_access = datetime.now(timezone.utc)

        # Fetch messages ordered by created_at
        msg_result = await self._session.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at)
        )
        messages: list[BaseMessage] = []
        for msg in msg_result.scalars().all():
            if msg.role == "human":
                messages.append(HumanMessage(content=msg.content))
            else:
                messages.append(AIMessage(content=msg.content))
        return messages

    async def list_sessions(
        self,
        user_id: str,
        scope_type: str | None = None,
        scope_value: str | None = None,
    ) -> list[dict]:
        """Return metadata for all sessions belonging to user_id, most recent first.

        When scope_type + scope_value are provided, return only sessions for that
        specific scope plus legacy (scope_type=None) sessions.
        When scope_type == "global", return global + legacy sessions.
        No filter params = return all (backward compat).
        """
        from sqlalchemy import or_
        stmt = (
            select(ChatSessionModel)
            .where(ChatSessionModel.user_id == user_id)
            .order_by(ChatSessionModel.last_access.desc())
        )

        if scope_type and scope_value:
            # Specific doc/collection scope: match exact scope + legacy sessions
            stmt = stmt.where(
                or_(
                    (ChatSessionModel.scope_type == scope_type) & (ChatSessionModel.scope_value == scope_value),
                    ChatSessionModel.scope_type.is_(None),
                )
            )
        elif scope_type == "global":
            # Global scope: show global + legacy sessions
            stmt = stmt.where(
                or_(
                    ChatSessionModel.scope_type == "global",
                    ChatSessionModel.scope_type.is_(None),
                )
            )
        # No filter params = return all (backward compat)

        result = await self._session.execute(stmt)
        sessions = []
        for s in result.scalars().all():
            # Get preview from first human message
            msg_result = await self._session.execute(
                select(ChatMessageModel)
                .where(
                    ChatMessageModel.session_id == s.session_id,
                    ChatMessageModel.role == "human",
                )
                .order_by(ChatMessageModel.created_at)
                .limit(1)
            )
            first_msg = msg_result.scalar_one_or_none()
            sessions.append({
                "session_id": s.session_id,
                "preview": first_msg.content[:100] if first_msg else "",
                "created_at": s.created_at.isoformat(),
                "last_access": s.last_access.isoformat(),
                "scope_type": s.scope_type,
                "scope_value": s.scope_value,
            })
        return sessions

    async def get_session_preview(self, session_id: str) -> str:
        """Return the first human message content (truncated) as session title."""
        stmt = (
            select(ChatMessageModel)
            .where(
                ChatMessageModel.session_id == session_id,
                ChatMessageModel.role == "human",
            )
            .order_by(ChatMessageModel.created_at)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        msg = result.scalar_one_or_none()
        return msg.content[:80] if msg else "New Chat"

    async def get_messages_for_display(self, session_id: str, user_id: str) -> list[dict] | None:
        """Return messages as frontend-friendly dicts. None if session not found or not owned."""
        result = await self._session.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id,
                ChatSessionModel.user_id == user_id,
            )
        )
        if not result.scalar_one_or_none():
            return None

        msg_result = await self._session.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at)
        )
        result_list = []
        for m in msg_result.scalars().all():
            entry = {"role": m.role, "content": m.content}
            if m.sources_json:
                entry["sources"] = m.sources_json
            result_list.append(entry)
        return result_list

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        """Delete a session only if it belongs to user_id."""
        result = await self._session.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id,
                ChatSessionModel.user_id == user_id,
            )
        )
        if not result.scalar_one_or_none():
            return False
        await self._session.execute(
            delete(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id
            )
        )
        await self._session.flush()
        return True

    async def add_exchange(
        self, session_id: str, question: str, answer: str,
        user_id: str | None = None, sources_json: str | None = None,
        scope_type: str | None = None, scope_value: str | None = None,
    ) -> None:
        # Ensure session exists
        result = await self._session.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id
            )
        )
        chat_session = result.scalar_one_or_none()
        if not chat_session:
            chat_session = ChatSessionModel(
                session_id=session_id,
                user_id=user_id,
                scope_type=scope_type,
                scope_value=scope_value,
            )
            self._session.add(chat_session)
            await self._session.flush()

        # Add the two messages
        now = datetime.now(timezone.utc)
        self._session.add(ChatMessageModel(
            session_id=session_id, role="human", content=question, created_at=now,
        ))
        self._session.add(ChatMessageModel(
            session_id=session_id, role="ai", content=answer,
            sources_json=sources_json, created_at=now,
        ))
        chat_session.last_access = now
        await self._session.flush()

        # Trim to max_messages (keep most recent)
        count_result = await self._session.execute(
            select(func.count()).select_from(ChatMessageModel).where(
                ChatMessageModel.session_id == session_id
            )
        )
        total = count_result.scalar_one()
        if total > self._max_messages:
            # Find the oldest messages to delete
            oldest = await self._session.execute(
                select(ChatMessageModel.id)
                .where(ChatMessageModel.session_id == session_id)
                .order_by(ChatMessageModel.created_at)
                .limit(total - self._max_messages)
            )
            ids_to_delete = [row[0] for row in oldest.all()]
            if ids_to_delete:
                await self._session.execute(
                    delete(ChatMessageModel).where(
                        ChatMessageModel.id.in_(ids_to_delete)
                    )
                )
                await self._session.flush()

    async def _cleanup_expired(self) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - self._session_ttl
        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
        await self._session.execute(
            delete(ChatSessionModel).where(
                ChatSessionModel.last_access < cutoff_dt
            )
        )


class EdgeRepository:
    """Async PostgreSQL-backed chunk edge (relationship) store."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def bulk_insert(self, edges: list[dict]) -> int:
        """Insert multiple edges at once. Returns count inserted."""
        if not edges:
            return 0
        objects = [ChunkEdgeModel(**e) for e in edges]
        self._db.add_all(objects)
        await self._db.flush()
        return len(objects)

    async def get_edges_from(
        self, doc_id: str, chunk_index: int, relations: list[str] | None = None,
    ) -> list[dict]:
        """Get all edges originating from a specific chunk."""
        stmt = select(ChunkEdgeModel).where(
            ChunkEdgeModel.source_doc_id == doc_id,
            ChunkEdgeModel.source_chunk_index == chunk_index,
        )
        if relations:
            stmt = stmt.where(ChunkEdgeModel.relation.in_(relations))
        result = await self._db.execute(stmt)
        return [
            {
                "source_doc_id": e.source_doc_id,
                "source_chunk_index": e.source_chunk_index,
                "target_doc_id": e.target_doc_id,
                "target_chunk_index": e.target_chunk_index,
                "relation": e.relation,
                "score": e.score,
            }
            for e in result.scalars().all()
        ]

    async def get_edges_in_doc(self, doc_id: str) -> list[dict]:
        """Return all intra-doc edges (source & target both in this doc).

        Used by the per-doc mindmap endpoint. Null scores normalized to 1.0
        so downstream consumers always get a numeric value.
        """
        stmt = select(ChunkEdgeModel).where(
            ChunkEdgeModel.source_doc_id == doc_id,
            ChunkEdgeModel.target_doc_id == doc_id,
        )
        result = await self._db.execute(stmt)
        return [
            {
                "source_chunk_index": e.source_chunk_index,
                "target_chunk_index": e.target_chunk_index,
                "relation": e.relation,
                "score": float(e.score) if e.score is not None else 1.0,
            }
            for e in result.scalars().all()
        ]

    async def get_edges_among_docs(
        self,
        doc_ids: list[str],
        relations: list[str] | None = None,
        include_intra_doc: bool = False,
    ) -> list[dict]:
        """Return every edge whose source AND target both fall within ``doc_ids``.

        Single SQL roundtrip — avoids the N+1 pattern from calling
        ``get_edges_from`` once per chunk. Used by the multi-doc chunk graph
        endpoint.

        - ``relations``: optional whitelist (e.g. ``["similar_to"]``)
        - ``include_intra_doc``: when False, drop edges where source_doc_id ==
          target_doc_id so callers see cross-doc relationships only
        """
        if not doc_ids:
            return []
        stmt = select(ChunkEdgeModel).where(
            ChunkEdgeModel.source_doc_id.in_(doc_ids),
            ChunkEdgeModel.target_doc_id.in_(doc_ids),
        )
        if relations:
            stmt = stmt.where(ChunkEdgeModel.relation.in_(relations))
        if not include_intra_doc:
            stmt = stmt.where(
                ChunkEdgeModel.source_doc_id != ChunkEdgeModel.target_doc_id,
            )
        result = await self._db.execute(stmt)
        return [
            {
                "source_doc_id": e.source_doc_id,
                "source_chunk_index": e.source_chunk_index,
                "target_doc_id": e.target_doc_id,
                "target_chunk_index": e.target_chunk_index,
                "relation": e.relation,
                "score": float(e.score) if e.score is not None else 1.0,
            }
            for e in result.scalars().all()
        ]

    async def get_edges_to(
        self, doc_id: str, chunk_index: int, relations: list[str] | None = None,
    ) -> list[dict]:
        """Get all edges pointing to a specific chunk."""
        stmt = select(ChunkEdgeModel).where(
            ChunkEdgeModel.target_doc_id == doc_id,
            ChunkEdgeModel.target_chunk_index == chunk_index,
        )
        if relations:
            stmt = stmt.where(ChunkEdgeModel.relation.in_(relations))
        result = await self._db.execute(stmt)
        return [
            {
                "source_doc_id": e.source_doc_id,
                "source_chunk_index": e.source_chunk_index,
                "target_doc_id": e.target_doc_id,
                "target_chunk_index": e.target_chunk_index,
                "relation": e.relation,
                "score": e.score,
            }
            for e in result.scalars().all()
        ]

    async def get_cross_doc_edges(
        self,
        relation: str = "similar_to",
        min_pairs: int = 1,
    ) -> list[dict]:
        """Get cross-document edges aggregated by unordered doc pair.

        Returns one entry per (doc_a, doc_b) pair containing:
          - source_doc_id, target_doc_id, relation
          - supporting_pairs: count of distinct chunk pairs in this group
          - mean_score: arithmetic mean of supporting pair scores
          - score: alias for mean_score (backward-compat for older clients)
        Pairs with fewer than ``min_pairs`` supporting chunk pairs are dropped —
        this is what stops the doc-level graph from collapsing into a hairball.
        """
        stmt = select(ChunkEdgeModel).where(
            ChunkEdgeModel.relation == relation,
            ChunkEdgeModel.source_doc_id != ChunkEdgeModel.target_doc_id,
        )
        result = await self._db.execute(stmt)

        groups: dict[tuple[str, str], dict] = {}
        for e in result.scalars().all():
            pair_key = tuple(sorted([e.source_doc_id, e.target_doc_id]))
            entry = groups.setdefault(pair_key, {
                "source_doc_id": e.source_doc_id,
                "target_doc_id": e.target_doc_id,
                "relation": e.relation,
                "scores": [],
            })
            if e.score is not None:
                entry["scores"].append(float(e.score))

        edges: list[dict] = []
        for entry in groups.values():
            scores = entry["scores"]
            if len(scores) < min_pairs:
                continue
            mean = sum(scores) / len(scores) if scores else None
            edges.append({
                "source_doc_id": entry["source_doc_id"],
                "target_doc_id": entry["target_doc_id"],
                "relation": entry["relation"],
                "supporting_pairs": len(scores),
                "mean_score": round(mean, 4) if mean is not None else None,
                "score": round(mean, 4) if mean is not None else None,
            })
        return edges

    async def get_edge_counts_batch(
        self, doc_id: str, chunk_indices: list[int],
    ) -> dict[int, int]:
        """Get edge count per chunk in a single query. Returns {chunk_index: count}."""
        from sqlalchemy import func
        if not chunk_indices:
            return {}
        stmt = (
            select(
                ChunkEdgeModel.source_chunk_index,
                func.count().label("cnt"),
            )
            .where(
                ChunkEdgeModel.source_doc_id == doc_id,
                ChunkEdgeModel.source_chunk_index.in_(chunk_indices),
            )
            .group_by(ChunkEdgeModel.source_chunk_index)
        )
        result = await self._db.execute(stmt)
        return {row[0]: row[1] for row in result.all()}

    async def get_edge_type_counts_batch(
        self, doc_id: str, chunk_indices: list[int],
    ) -> dict[int, dict[str, int]]:
        """Get edge counts per chunk grouped by relation type.

        Returns {chunk_index: {"follows": 2, "describes": 1, ...}}.
        """
        from sqlalchemy import func
        if not chunk_indices:
            return {}
        stmt = (
            select(
                ChunkEdgeModel.source_chunk_index,
                ChunkEdgeModel.relation,
                func.count().label("cnt"),
            )
            .where(
                ChunkEdgeModel.source_doc_id == doc_id,
                ChunkEdgeModel.source_chunk_index.in_(chunk_indices),
            )
            .group_by(ChunkEdgeModel.source_chunk_index, ChunkEdgeModel.relation)
        )
        result = await self._db.execute(stmt)
        counts: dict[int, dict[str, int]] = {}
        for cidx, relation, cnt in result.all():
            counts.setdefault(cidx, {})[relation] = cnt
        return counts

    async def delete_by_doc(self, doc_id: str) -> int:
        """Delete all edges involving a document (source or target)."""
        from sqlalchemy import or_
        stmt = delete(ChunkEdgeModel).where(
            or_(
                ChunkEdgeModel.source_doc_id == doc_id,
                ChunkEdgeModel.target_doc_id == doc_id,
            )
        )
        result = await self._db.execute(stmt)
        return result.rowcount

    async def count_all(self) -> int:
        """Total number of edges across the entire corpus."""
        result = await self._db.execute(
            select(func.count()).select_from(ChunkEdgeModel)
        )
        return int(result.scalar() or 0)
