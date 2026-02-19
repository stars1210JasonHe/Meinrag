"""Chat session management endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from app.dependencies import get_memory_manager, get_current_user
from app.db.repositories import ChatSessionRepository
from app.models.schemas import SessionInfo

router = APIRouter()


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    current_user: str = Depends(get_current_user),
):
    """List all chat sessions for the current user, most recent first."""
    sessions = await memory_manager.list_sessions(current_user)
    result = []
    for s in sessions:
        preview = await memory_manager.get_session_preview(s["session_id"])
        result.append(SessionInfo(
            session_id=s["session_id"],
            preview=preview,
            created_at=s["created_at"],
            last_access=s["last_access"],
        ))
    return result


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
