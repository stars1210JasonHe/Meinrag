"""A4: Chat Memory tests - No API key required."""
import asyncio

from langchain_core.messages import HumanMessage, AIMessage

from app.db.repositories import ChatSessionRepository


class TestMemoryBasic:
    """A4.1 - A4.3: Basic history operations."""

    async def test_new_session_empty(self, memory_manager):
        """A4.1: New session returns empty history."""
        history = await memory_manager.get_history("new_session")
        assert history == []

    async def test_add_exchange_stored(self, memory_manager):
        """A4.2: Add exchange, verify history contains HumanMessage + AIMessage."""
        await memory_manager.add_exchange("s1", "What is RAG?", "RAG is retrieval-augmented generation.")
        history = await memory_manager.get_history("s1")
        assert len(history) == 2
        assert isinstance(history[0], HumanMessage)
        assert isinstance(history[1], AIMessage)
        assert history[0].content == "What is RAG?"
        assert history[1].content == "RAG is retrieval-augmented generation."

    async def test_multiple_exchanges_ordered(self, memory_manager):
        """A4.3: Multiple exchanges stored in chronological order."""
        await memory_manager.add_exchange("s1", "Q1", "A1")
        await memory_manager.add_exchange("s1", "Q2", "A2")
        history = await memory_manager.get_history("s1")
        assert len(history) == 4
        assert history[0].content == "Q1"
        assert history[1].content == "A1"
        assert history[2].content == "Q2"
        assert history[3].content == "A2"


class TestMemoryTrimming:
    """A4.4: Trimming at max_messages limit."""

    async def test_trimming(self, db_session):
        """Oldest messages removed when limit exceeded (max_messages=4)."""
        mgr = ChatSessionRepository(db_session, max_messages=4, session_ttl=300)
        await mgr.add_exchange("s1", "Q1", "A1")  # 2 messages
        await mgr.add_exchange("s1", "Q2", "A2")  # 4 messages (at limit)
        await mgr.add_exchange("s1", "Q3", "A3")  # 6 -> trimmed to 4

        history = await mgr.get_history("s1")
        assert len(history) == 4
        # Q1/A1 should be trimmed, Q2/A2 and Q3/A3 remain
        assert history[0].content == "Q2"
        assert history[1].content == "A2"
        assert history[2].content == "Q3"
        assert history[3].content == "A3"


class TestMemoryTTL:
    """A4.5: TTL expiry."""

    async def test_ttl_expiry(self, db_session):
        """Session data cleared after TTL seconds."""
        mgr = ChatSessionRepository(db_session, max_messages=20, session_ttl=1)
        await mgr.add_exchange("s1", "Q1", "A1")
        history = await mgr.get_history("s1")
        assert len(history) == 2

        await asyncio.sleep(1.5)

        history = await mgr.get_history("s1")
        assert history == []


class TestMemoryIsolation:
    """A4.6: Independent sessions."""

    async def test_sessions_independent(self, memory_manager):
        """Session s1 and s2 don't share history."""
        await memory_manager.add_exchange("s1", "Q1", "A1")
        await memory_manager.add_exchange("s2", "Q2", "A2")

        h1 = await memory_manager.get_history("s1")
        h2 = await memory_manager.get_history("s2")

        assert len(h1) == 2
        assert len(h2) == 2
        assert h1[0].content == "Q1"
        assert h2[0].content == "Q2"
