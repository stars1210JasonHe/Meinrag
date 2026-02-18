import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings
from app.dependencies import (
    get_settings, get_vector_store, get_llm, get_memory_manager,
    get_registry, get_current_user,
)
from app.db.repositories import DocumentRepository, ChatSessionRepository
from app.models.schemas import QueryRequest, QueryResponse, SourceChunk
from langchain_core.output_parsers import StrOutputParser
from app.rag.chain import build_rag_chain
from app.rag.prompts import WEB_SEARCH_PROMPT
from app.vectorstore.base import VectorStoreManager
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)
router = APIRouter()

_RETRYABLE_KEYWORDS = ("500", "503", "rate", "overloaded", "internal server error")


def _smart_truncate(text: str, max_len: int = 500) -> str:
    """Truncate text at a sentence or word boundary instead of mid-word."""
    if len(text) <= max_len:
        return text
    # Try to break at last sentence end (. ! ?) within limit
    for sep in (". ", ".\n", "! ", "? "):
        idx = text.rfind(sep, 0, max_len)
        if idx > max_len * 0.5:  # only if at least half the content is kept
            return text[: idx + 1]
    # Fallback: break at last space
    idx = text.rfind(" ", 0, max_len)
    if idx > max_len * 0.5:
        return text[:idx] + "..."
    # Last resort: hard cut
    return text[:max_len] + "..."


def _sanitize(value: str, max_len: int) -> str:
    """Strip and cap length for untrusted web content."""
    return value.strip()[:max_len]


async def _invoke_with_retry(chain, inputs, max_attempts: int = 3):
    """Invoke a LangChain chain with exponential backoff on transient errors."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            if isinstance(inputs, str):
                return await chain.ainvoke(inputs)
            return await chain.ainvoke(inputs)
        except Exception as err:
            last_err = err
            if any(k in str(err).lower() for k in _RETRYABLE_KEYWORDS):
                logger.warning(f"LLM transient error (attempt {attempt + 1}/{max_attempts}): {err}")
                await asyncio.sleep(2 ** attempt)
            else:
                raise
    raise last_err


async def _web_search_fallback(
    request: QueryRequest,
    llm: BaseChatModel,
    memory_manager: ChatSessionRepository,
    settings: Settings,
) -> QueryResponse:
    """Fall back to web search when no relevant documents are found."""
    from duckduckgo_search import DDGS

    loop = asyncio.get_event_loop()
    try:
        web_results = await loop.run_in_executor(
            None,
            lambda: DDGS().text(
                request.question, max_results=settings.web_search_max_results
            ),
        )
    except Exception as e:
        logger.warning(f"Web search failed: {e}")
        web_results = []

    if not web_results:
        return QueryResponse(
            answer="I couldn't find relevant information in your documents or on the web.",
            sources=[],
            question=request.question,
            session_id=request.session_id,
            web_search_used=False,
        )

    # Sanitize web content before injecting into LLM context
    web_context = "\n\n---\n\n".join(
        f"[{_sanitize(r['title'], 200)}]\n"
        f"{_sanitize(r['body'], 800)}\n"
        f"URL: {_sanitize(r['href'], 300)}"
        for r in web_results
    )

    web_chain = WEB_SEARCH_PROMPT | llm | StrOutputParser()
    answer = await _invoke_with_retry(web_chain, {
        "context": web_context,
        "question": request.question,
    })

    if request.session_id:
        await memory_manager.add_exchange(request.session_id, request.question, answer)

    sources = [
        SourceChunk(
            content=_sanitize(r["body"], 500),
            source_file=_sanitize(r["title"], 200),
            source_type="web",
        )
        for r in web_results
    ]

    return QueryResponse(
        answer=answer,
        sources=sources,
        question=request.question,
        session_id=request.session_id,
        web_search_used=True,
    )


@router.post("/query", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    # Resolve collection to doc_ids via registry
    doc_ids = request.doc_ids
    user_scoped = request.collection is not None or request.doc_ids is not None

    # User isolation: restrict to user's documents
    if settings.user_isolation in ("all", "documents"):
        user_docs = await registry.list_all(user_id=current_user)
        user_doc_ids = {d["doc_id"] for d in user_docs}

        if request.collection:
            collection_docs = await registry.list_by_collection(request.collection, user_id=current_user)
            collection_doc_ids = [d["doc_id"] for d in collection_docs]
            if doc_ids:
                doc_ids = [d for d in doc_ids if d in collection_doc_ids and d in user_doc_ids]
            else:
                doc_ids = collection_doc_ids
        elif doc_ids:
            doc_ids = [d for d in doc_ids if d in user_doc_ids]
        else:
            doc_ids = list(user_doc_ids) if user_doc_ids else None
    elif request.collection:
        collection_docs = await registry.list_by_collection(request.collection)
        doc_ids = [d["doc_id"] for d in collection_docs]

    # Load chat history if session_id provided
    chat_history = None
    if request.session_id:
        chat_history = await memory_manager.get_history(request.session_id) or None

    try:
        chain, retriever = build_rag_chain(
            vector_store=vector_store,
            llm=llm,
            top_k=request.top_k,
            doc_ids=doc_ids,
            chat_history=chat_history,
            settings=settings,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        # Get source docs for the response
        if doc_ids:
            retrieved_docs = vector_store.similarity_search_with_filter(
                request.question, k=request.top_k, doc_ids=doc_ids,
            )
        else:
            retrieved_docs = vector_store.similarity_search(
                request.question, k=request.top_k
            )

        # Web search fallback when no relevant documents found
        # Only fall back for unscoped queries (not when user chose a specific collection/docs)
        if not retrieved_docs and settings.web_search_enabled and not user_scoped:
            return await _web_search_fallback(
                request, llm, memory_manager, settings,
            )

        answer = await _invoke_with_retry(chain, request.question)

        # Store exchange in session memory
        if request.session_id:
            await memory_manager.add_exchange(request.session_id, request.question, answer)

        sources = [
            SourceChunk(
                content=_smart_truncate(doc.page_content, 500),
                source_file=doc.metadata.get("source_file", "unknown"),
                chunk_index=doc.metadata.get("chunk_index"),
                doc_id=doc.metadata.get("doc_id"),
                page=doc.metadata.get("page"),
            )
            for doc in retrieved_docs
        ]

        return QueryResponse(
            answer=answer,
            sources=sources,
            question=request.question,
            session_id=request.session_id,
        )
    except Exception as e:
        logger.exception("Query failed")
        err_msg = str(e).lower()
        if any(k in err_msg for k in ("api_error", "internal server error", "overloaded", "rate")):
            raise HTTPException(
                status_code=502,
                detail="The AI provider returned an error. Please try again in a moment.",
            )
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
