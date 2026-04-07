"""Chat session management endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import get_memory_manager, get_current_user
from app.db.repositories import ChatSessionRepository
from app.models.schemas import SessionInfo

router = APIRouter()


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    scope_type: str | None = Query(default=None),
    scope_value: str | None = Query(default=None),
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    current_user: str = Depends(get_current_user),
):
    """List chat sessions for the current user, most recent first.

    Optional query params:
    - scope_type: "doc" | "collection" | "global"
    - scope_value: doc_id or collection name (required when scope_type is doc/collection)

    Omit both to return all sessions (backward compat).
    """
    sessions = await memory_manager.list_sessions(
        current_user,
        scope_type=scope_type,
        scope_value=scope_value,
    )
    return [
        SessionInfo(
            session_id=s["session_id"],
            preview=s["preview"],
            created_at=s["created_at"],
            last_access=s["last_access"],
            scope_type=s["scope_type"],
            scope_value=s["scope_value"],
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    current_user: str = Depends(get_current_user),
):
    """Load all messages from a session (for resuming a conversation)."""
    messages = await memory_manager.get_messages_for_display(session_id, current_user)
    if messages is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return messages


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    current_user: str = Depends(get_current_user),
):
    """Delete a chat session (only if owned by current user)."""
    deleted = await memory_manager.delete_session(session_id, current_user)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"message": "Session deleted", "session_id": session_id}
