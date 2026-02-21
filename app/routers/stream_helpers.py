"""SSE streaming helpers for query endpoints."""

import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


def sse_event(event: str, data: dict) -> dict:
    """Format an SSE event for sse-starlette's EventSourceResponse."""
    return {"event": event, "data": json.dumps(data)}


async def stream_chain_response(
    chain,
    question: str | dict,
    sources: list[dict],
    session_id: str | None = None,
    web_search_used: bool = False,
) -> AsyncGenerator[dict, None]:
    """Yield SSE events: sources -> tokens -> done.

    The chain must be an LCEL chain that supports .astream().
    """
    # 1. Send sources immediately
    yield sse_event("sources", {
        "sources": sources,
        "web_search_used": web_search_used,
        "session_id": session_id,
    })

    # 2. Stream tokens
    full_answer = []
    try:
        async for chunk in chain.astream(question):
            token = chunk if isinstance(chunk, str) else str(chunk)
            if token:
                full_answer.append(token)
                yield sse_event("token", {"token": token})
    except Exception as e:
        logger.exception("Error during streaming")
        yield sse_event("error", {"detail": str(e)})
        return

    # 3. Send done event with full answer for memory persistence
    yield sse_event("done", {
        "answer": "".join(full_answer),
        "session_id": session_id,
    })
