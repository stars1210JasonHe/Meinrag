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
    """Chat history is persistent — get_history must never delete data."""

    async def test_history_persists_past_ttl(self, db_session):
        """get_history must NOT side-effect-delete stale sessions.

        Chat history is user data, not an LRU cache. A prior bug made
        get_history invoke _cleanup_expired, which cascade-deleted any
        session whose last_access was older than session_ttl — destroying
        the user's chat data on the next query that loaded context.
        """
        mgr = ChatSessionRepository(db_session, max_messages=20, session_ttl=1)
        await mgr.add_exchange("s1", "Q1", "A1")
        history = await mgr.get_history("s1")
        assert len(history) == 2

        await asyncio.sleep(1.5)

        history = await mgr.get_history("s1")
        assert len(history) == 2
        assert history[0].content == "Q1"
        assert history[1].content == "A1"


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


class TestSessionListing:
    """A4.7: Session listing and management."""

    async def test_list_sessions_empty(self, memory_manager):
        """No sessions for a user returns empty list."""
        sessions = await memory_manager.list_sessions("admin")
        assert sessions == []

    async def test_list_sessions_after_exchange(self, memory_manager):
        """Sessions appear after adding exchanges with user_id."""
        await memory_manager.add_exchange("s1", "Hello", "Hi there", user_id="admin")
        await memory_manager.add_exchange("s2", "Bye", "Goodbye", user_id="admin")
        sessions = await memory_manager.list_sessions("admin")
        assert len(sessions) == 2
        session_ids = {s["session_id"] for s in sessions}
        assert "s1" in session_ids
        assert "s2" in session_ids

    async def test_list_sessions_user_isolation(self, db_session):
        """Sessions from different users are isolated."""
        from app.db.models import UserModel
        db_session.add(UserModel(user_id="bob", display_name="Bob"))
        await db_session.flush()

        mgr = ChatSessionRepository(db_session, max_messages=20, session_ttl=300)
        await mgr.add_exchange("s_admin", "Q1", "A1", user_id="admin")
        await mgr.add_exchange("s_bob", "Q2", "A2", user_id="bob")

        admin_sessions = await mgr.list_sessions("admin")
        bob_sessions = await mgr.list_sessions("bob")
        assert len(admin_sessions) == 1
        assert admin_sessions[0]["session_id"] == "s_admin"
        assert len(bob_sessions) == 1
        assert bob_sessions[0]["session_id"] == "s_bob"

    async def test_session_preview(self, memory_manager):
        """Preview returns first human message content."""
        await memory_manager.add_exchange("s1", "What is quantum computing?", "It is...", user_id="admin")
        preview = await memory_manager.get_session_preview("s1")
        assert "quantum computing" in preview

    async def test_session_preview_empty(self, memory_manager):
        """Preview for nonexistent session returns 'New Chat'."""
        preview = await memory_manager.get_session_preview("nonexistent")
        assert preview == "New Chat"


class TestSessionDeletion:
    """A4.8: Session deletion with ownership."""

    async def test_delete_session(self, memory_manager):
        """Delete session owned by user succeeds."""
        await memory_manager.add_exchange("s1", "Q1", "A1", user_id="admin")
        deleted = await memory_manager.delete_session("s1", "admin")
        assert deleted is True
        history = await memory_manager.get_history("s1")
        assert history == []

    async def test_delete_session_wrong_user(self, db_session):
        """Delete session not owned by user fails."""
        from app.db.models import UserModel
        db_session.add(UserModel(user_id="charlie", display_name="Charlie"))
        await db_session.flush()

        mgr = ChatSessionRepository(db_session, max_messages=20, session_ttl=300)
        await mgr.add_exchange("s1", "Q1", "A1", user_id="admin")
        deleted = await mgr.delete_session("s1", "charlie")
        assert deleted is False
        # Session should still exist
        history = await mgr.get_history("s1")
        assert len(history) == 2


class TestSessionMessages:
    """A4.9: Get messages for display."""

    async def test_get_messages_for_display(self, memory_manager):
        """Get messages returns frontend-friendly dicts."""
        await memory_manager.add_exchange("s1", "Hello", "Hi", user_id="admin")
        messages = await memory_manager.get_messages_for_display("s1", "admin")
        assert messages is not None
        assert len(messages) == 2
        assert messages[0] == {"role": "human", "content": "Hello"}
        assert messages[1] == {"role": "ai", "content": "Hi"}

    async def test_get_messages_wrong_user(self, db_session):
        """Get messages for session not owned by user returns None."""
        from app.db.models import UserModel
        db_session.add(UserModel(user_id="dave", display_name="Dave"))
        await db_session.flush()

        mgr = ChatSessionRepository(db_session, max_messages=20, session_ttl=300)
        await mgr.add_exchange("s1", "Q1", "A1", user_id="admin")
        messages = await mgr.get_messages_for_display("s1", "dave")
        assert messages is None

    async def test_get_messages_nonexistent(self, memory_manager):
        """Get messages for nonexistent session returns None."""
        messages = await memory_manager.get_messages_for_display("nonexistent", "admin")
        assert messages is None
