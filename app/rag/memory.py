import threading
import time

from langchain_core.messages import AIMessage, HumanMessage, BaseMessage


class SessionMemoryManager:
    """Thread-safe in-memory chat session store with TTL expiry."""

    def __init__(self, max_messages: int = 20, session_ttl: int = 3600):
        self._max_messages = max_messages
        self._session_ttl = session_ttl
        self._sessions: dict[str, list[BaseMessage]] = {}
        self._last_access: dict[str, float] = {}
        self._lock = threading.Lock()

    def get_history(self, session_id: str) -> list[BaseMessage]:
        """Return the message history for a session (empty list if new/expired)."""
        with self._lock:
            self._cleanup_expired()
            if session_id not in self._sessions:
                return []
            self._last_access[session_id] = time.time()
            return list(self._sessions[session_id])

    def add_exchange(self, session_id: str, question: str, answer: str) -> None:
        """Store a Q&A pair in the session history, trimming to max_messages."""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = []
            self._sessions[session_id].append(HumanMessage(content=question))
            self._sessions[session_id].append(AIMessage(content=answer))

            # Trim to max_messages (each exchange = 2 messages)
            if len(self._sessions[session_id]) > self._max_messages:
                self._sessions[session_id] = self._sessions[session_id][
                    -self._max_messages :
                ]

            self._last_access[session_id] = time.time()

    def _cleanup_expired(self) -> None:
        """Remove sessions that have been idle longer than session_ttl."""
        now = time.time()
        expired = [
            sid
            for sid, last in self._last_access.items()
            if now - last > self._session_ttl
        ]
        for sid in expired:
            del self._sessions[sid]
            del self._last_access[sid]
