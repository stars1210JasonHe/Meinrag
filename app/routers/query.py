import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.config import Settings
from app.dependencies import (
    get_settings, get_vector_store, get_llm, get_embeddings, get_memory_manager,
    get_registry, get_current_user,
)
from app.db.repositories import DocumentRepository, ChatSessionRepository
from app.models.schemas import QueryRequest, QueryResponse, SourceChunk, ChunkContextRequest, AskAIRequest, AskAIResponse
from langchain_core.output_parsers import StrOutputParser
from app.rag.chain import build_rag_chain, is_reference_entry
from app.services.chunk_utils import is_garbage_table
from app.rag.prompts import WEB_SEARCH_PROMPT, CHUNK_CONTEXT_PROMPT, QUERY_REWRITE_PROMPT, QUERY_EXPANSION_PROMPT, ASK_AI_PROMPT, QUESTION_CLASSIFY_PROMPT
from app.routers.stream_helpers import sse_event, stream_chain_response
from app.vectorstore.base import VectorStoreManager
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)
router = APIRouter()

_RETRYABLE_KEYWORDS = ("500", "503", "rate", "overloaded", "internal server error")
_REFERENCE_SCORE_PENALTY = 0.3


async def _maybe_expand_query(
    question: str,
    retrieved: list[tuple],
    llm: BaseChatModel,
    vector_store: VectorStoreManager,
    settings: Settings,
    doc_ids: list[str] | None,
    top_k: int,
) -> tuple[str, list[tuple]]:
    """If all retrieval scores are below threshold, expand the query via LLM and re-query."""
    if not settings.query_expansion_enabled or not retrieved:
        return question, retrieved

    max_score = max(score for _, score in retrieved) if retrieved else 0
    if max_score >= settings.query_expansion_score_threshold:
        return question, retrieved

    # Scores are all low — expand the query
    try:
        expansion_chain = QUERY_EXPANSION_PROMPT | llm | StrOutputParser()
        expanded = await expansion_chain.ainvoke({"question": question})
        expanded = expanded.strip()
        if not expanded or expanded == question:
            return question, retrieved

        logger.info("Query expanded: %r → %r", question, expanded)

        # Re-query with expanded query
        new_retrieved = vector_store.similarity_search_with_scores(
            expanded, k=int(top_k * 1.5), doc_ids=doc_ids,
        )
        new_max = max(score for _, score in new_retrieved) if new_retrieved else 0

        # Only use expanded results if they're actually better
        if new_max > max_score:
            return expanded, new_retrieved
    except Exception as e:
        logger.warning("Query expansion failed: %s", e)

    return question, retrieved


def _demote_reference_results(
    results: list[tuple], top_k: int
) -> list[tuple]:
    """Move reference-list results to the end so real content fills top_k first."""
    content, refs = [], []
    for r in results:
        (refs if is_reference_entry(r[0].page_content) else content).append(r)
    if refs:
        logger.info("Reference demotion: %d ref chunks demoted out of %d results", len(refs), len(results))
    return (content + refs)[:top_k]


def _apply_reference_penalty(results: list[tuple]) -> list[tuple]:
    """Multiply score by penalty factor for chunks tagged as reference section."""
    return [
        (doc, score * _REFERENCE_SCORE_PENALTY) if doc.metadata.get("section") == "references" else (doc, score)
        for doc, score in results
    ]


_SECTION_WEIGHTS = {
    "abstract": 1.0,
    "introduction": 1.0,
    "related_work": 0.9,
    "methods": 1.0,
    "training": 1.0,
    "results": 1.0,
    "discussion": 1.0,
    "references": 1.0,      # handled separately by _apply_reference_penalty
    "appendix": 0.7,
    "acknowledgment": 0.4,
    "body": 1.0,
}


def _apply_section_weights(results: list[tuple]) -> list[tuple]:
    """Apply section-based score weights.

    Penalizes low-value sections (acknowledgments, appendix).
    References NOT penalized here — they have their own penalty.
    """
    weighted = []
    for doc, score in results:
        section = doc.metadata.get("section_type", "body")
        if section == "references":
            weighted.append((doc, score))
            continue
        weight = _SECTION_WEIGHTS.get(section, 1.0)
        weighted.append((doc, score * weight))
    return weighted


async def _classify_question(
    question: str, llm: BaseChatModel,
) -> str:
    """Classify a question as 'open' or 'closed' using LLM.

    Open questions need broad section coverage (summaries, overviews).
    Closed questions need specific top-K retrieval (facts, scores).
    Returns 'closed' on any failure.
    """
    try:
        messages = QUESTION_CLASSIFY_PROMPT.format_messages(question=question)
        response = await llm.ainvoke(messages)
        result = response.content if hasattr(response, "content") else str(response)
        classification = result.strip().lower()
        if classification in ("open", "closed"):
            logger.info("Question classified as: %s — %r", classification, question)
            return classification
        logger.warning("Unexpected classification %r, defaulting to closed", result)
        return "closed"
    except Exception as e:
        logger.warning("Question classification failed: %s, defaulting to closed", e)
        return "closed"


def _section_aware_sample(
    results: list[tuple],
) -> list[tuple]:
    """Pick the highest-scoring chunk from each section type.

    For open questions that need broad coverage across a document,
    this ensures the LLM sees content from every section instead of
    multiple chunks from the same section.
    """
    if not results:
        return []

    best_per_section: dict[str, tuple] = {}
    for doc, score in results:
        section = doc.metadata.get("section_type", "body")
        if section not in best_per_section or score > best_per_section[section][1]:
            best_per_section[section] = (doc, score)

    sampled = list(best_per_section.values())
    sampled.sort(key=lambda x: x[1], reverse=True)
    return sampled


def _link_nearby_visuals(
    retrieved: list,
    vector_store: VectorStoreManager,
    doc_ids: list[str] | None,
    question: str | None = None,
    embeddings=None,
    proximity_pages: int = 1,
) -> list:
    """Link visual chunks (image/table/formula) from pages near retrieved text chunks.

    For each retrieved text chunk, finds visual chunks on the same or
    adjacent pages (within proximity_pages range) from the same document.
    Computes real cosine similarity scores when embeddings are available.
    """
    if not doc_ids or not retrieved:
        return retrieved

    # Collect pages referenced by retrieved text chunks, per doc
    doc_pages: dict[str, set[int]] = {}
    retrieved_keys = set()
    for doc, _ in retrieved:
        meta = doc.metadata
        key = (meta.get("doc_id"), meta.get("chunk_index"))
        retrieved_keys.add(key)
        did = meta.get("doc_id")
        page = meta.get("page")
        if did and page is not None:
            doc_pages.setdefault(did, set())
            for p in range(page - proximity_pages, page + proximity_pages + 1):
                doc_pages[did].add(p)

    # Find visual chunks on those pages
    extra_docs = []
    for did, pages in doc_pages.items():
        chunks = vector_store.get_chunks_by_doc(did)
        for chunk in chunks:
            meta = chunk.metadata
            ct = meta.get("chunk_type")
            if ct not in ("image", "table", "formula"):
                continue
            if ct == "image" and not meta.get("image_path"):
                continue
            if ct == "table" and is_garbage_table(chunk.page_content):
                continue
            chunk_page = meta.get("page")
            if chunk_page not in pages:
                continue
            key = (meta.get("doc_id"), meta.get("chunk_index"))
            if key in retrieved_keys:
                continue
            extra_docs.append(chunk)
            retrieved_keys.add(key)

    if not extra_docs:
        return retrieved

    # Compute real similarity scores if embeddings and question available
    extra_with_scores = []
    if question and embeddings:
        try:
            import numpy as np
            query_emb = embeddings.embed_query(question)
            doc_texts = [d.page_content for d in extra_docs]
            doc_embs = embeddings.embed_documents(doc_texts)
            query_vec = np.array(query_emb)
            for doc, emb in zip(extra_docs, doc_embs):
                doc_vec = np.array(emb)
                cosine = float(np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-10))
                extra_with_scores.append((doc, max(0.0, cosine)))
        except Exception as e:
            logger.warning(f"Failed to compute proximity scores: {e}")
            extra_with_scores = [(doc, 0.0) for doc in extra_docs]
    else:
        extra_with_scores = [(doc, 0.0) for doc in extra_docs]

    if extra_with_scores:
        logger.info(f"Linked {len(extra_with_scores)} visual chunks from nearby pages")
    return retrieved + extra_with_scores


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


async def _rewrite_search_queries(question: str, llm: BaseChatModel) -> list[str]:
    """Use LLM to rewrite user question into optimized search queries."""
    try:
        rewrite_chain = QUERY_REWRITE_PROMPT | llm | StrOutputParser()
        result = await rewrite_chain.ainvoke({"question": question})
        queries = [q.strip() for q in result.strip().split("\n") if q.strip()]
        return queries[:3] if queries else [question]
    except Exception:
        logger.warning("Query rewriting failed, using original question")
        return [question]


async def _resolve_doc_ids(
    request: QueryRequest,
    settings: Settings,
    registry: DocumentRepository,
    current_user: str,
) -> tuple[list[str] | None, bool]:
    """Resolve doc_ids from request, applying collection filters and user isolation.

    Returns (doc_ids, user_scoped) where user_scoped is True if the query
    is explicitly scoped to a collection or doc_ids.
    """
    doc_ids = request.doc_ids
    user_scoped = request.collection is not None or request.doc_ids is not None

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

    return doc_ids, user_scoped


def _parse_bbox(raw) -> list[float] | None:
    """Parse bbox from metadata — may be a JSON string or already a list."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
    if isinstance(raw, list):
        return raw
    return None


def _build_source_chunks(retrieved: list) -> list[SourceChunk]:
    """Build SourceChunk list from retrieved (doc, score) pairs."""
    return [
        SourceChunk(
            content=_smart_truncate(doc.page_content, 500),
            source_file=doc.metadata.get("source_file", "unknown"),
            chunk_index=doc.metadata.get("chunk_index"),
            doc_id=doc.metadata.get("doc_id"),
            page=doc.metadata.get("page"),
            score=round(score, 4),
            chunk_type=doc.metadata.get("chunk_type"),
            image_path=doc.metadata.get("image_path"),
            bbox=_parse_bbox(doc.metadata.get("bbox")),
        )
        for doc, score in retrieved
    ]


async def _fetch_page(url: str) -> str:
    """Fetch a web page and extract plain text content."""
    import httpx
    import re

    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
            text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:3000]
    except Exception:
        return ""


async def _build_web_search_context(
    question: str, llm: BaseChatModel, settings: Settings,
) -> tuple[str, list]:
    """Run web search, fetch pages, and return (context_str, top_results).

    Returns ("", []) if no results found.
    """
    from app.services.web_search import create_web_search_provider

    provider = create_web_search_provider(settings.web_search_provider)
    search_queries = await _rewrite_search_queries(question, llm)
    logger.info(f"Web search queries: {search_queries}")

    all_results = []
    seen_urls = set()
    per_query_limit = max(3, settings.web_search_max_results // len(search_queries))
    for query in search_queries:
        try:
            results = await provider.search(query, max_results=per_query_limit)
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)
        except Exception as e:
            logger.warning(f"Web search failed for query '{query}': {e}")

    if not all_results:
        return "", []

    top_results = all_results[:min(6, len(all_results))]
    page_texts = await asyncio.gather(*[_fetch_page(r.url) for r in top_results[:3]])

    web_context_parts = []
    for i, r in enumerate(top_results):
        part = f"[{_sanitize(r.title, 200)}]\n"
        if i < len(page_texts) and page_texts[i]:
            part += f"{_sanitize(page_texts[i], 2000)}\n"
        else:
            part += f"{_sanitize(r.body, 800)}\n"
        part += f"URL: {_sanitize(r.url, 300)}"
        web_context_parts.append(part)

    return "\n\n---\n\n".join(web_context_parts), top_results


def _web_source_chunks(top_results: list) -> list[SourceChunk]:
    """Build SourceChunk list from web search results."""
    return [
        SourceChunk(
            content=_sanitize(r.body, 500),
            source_file=_sanitize(r.title, 200),
            source_type="web",
            url=_sanitize(r.url, 300),
        )
        for r in top_results
    ]


def _should_web_search(
    request: QueryRequest,
    settings: Settings,
    user_scoped: bool,
    retrieved: list,
) -> bool:
    """Determine if we should fall back to web search."""
    if not settings.web_search_enabled:
        return False
    if request.force_web_search:
        return True
    if user_scoped:
        return False
    if not retrieved:
        return True
    best_score = max(score for _, score in retrieved)
    return best_score < settings.web_search_score_threshold


async def _web_search_fallback(
    request: QueryRequest,
    llm: BaseChatModel,
    memory_manager: ChatSessionRepository,
    settings: Settings,
    current_user: str | None = None,
) -> QueryResponse:
    """Fall back to web search when no relevant documents are found."""
    web_context, top_results = await _build_web_search_context(
        request.question, llm, settings,
    )

    if not top_results:
        return QueryResponse(
            answer="I couldn't find relevant information in your documents or on the web.",
            sources=[],
            question=request.question,
            session_id=request.session_id,
            web_search_used=False,
        )

    web_chain = WEB_SEARCH_PROMPT | llm | StrOutputParser()
    answer = await _invoke_with_retry(web_chain, {
        "context": web_context,
        "question": request.question,
    })

    if request.session_id:
        await memory_manager.add_exchange(request.session_id, request.question, answer, user_id=current_user)

    return QueryResponse(
        answer=answer,
        sources=_web_source_chunks(top_results),
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
    embeddings: Embeddings = Depends(get_embeddings),
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    doc_ids, user_scoped = await _resolve_doc_ids(request, settings, registry, current_user)

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
        # Force web search — skip vector search entirely
        if request.force_web_search and settings.web_search_enabled:
            return await _web_search_fallback(
                request, llm, memory_manager, settings, current_user=current_user,
            )

        # Determine fetch size based on question type
        is_open = False
        if settings.open_question_detection:
            question_type = await _classify_question(request.question, llm)
            is_open = question_type == "open"

        fetch_k = int(request.top_k * 3) if is_open else int(request.top_k * 1.5)

        # Get source docs with similarity scores
        retrieved = vector_store.similarity_search_with_scores(
            request.question, k=fetch_k, doc_ids=doc_ids,
        )

        # Expand vague queries (low scores → LLM rewrites → re-query)
        search_query, retrieved = await _maybe_expand_query(
            request.question, retrieved, llm, vector_store, settings, doc_ids, request.top_k,
        )

        # Apply section-aware sampling for open questions
        if is_open:
            retrieved = _section_aware_sample(retrieved)
        else:
            # Demote reference-list entries so real content fills top_k
            retrieved = _demote_reference_results(retrieved, request.top_k)

        retrieved = _apply_reference_penalty(retrieved)
        retrieved = _apply_section_weights(retrieved)

        # Web search fallback if needed
        if _should_web_search(request, settings, user_scoped, retrieved):
            return await _web_search_fallback(
                request, llm, memory_manager, settings, current_user=current_user,
            )

        # Link visual chunks from pages near retrieved text chunks
        if settings.visual_proximity_enabled:
            retrieved = _link_nearby_visuals(
                retrieved, vector_store, doc_ids,
                question=request.question, embeddings=embeddings,
                proximity_pages=settings.visual_proximity_pages,
            )

        # Sort by score descending so highest-relevance sources appear first
        retrieved.sort(key=lambda x: x[1], reverse=True)

        answer = await _invoke_with_retry(chain, request.question)

        # Store exchange in session memory
        if request.session_id:
            await memory_manager.add_exchange(request.session_id, request.question, answer, user_id=current_user)

        return QueryResponse(
            answer=answer,
            sources=_build_source_chunks(retrieved),
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


@router.post("/query/chunk-context", response_model=QueryResponse)
async def query_chunk_context(
    request: ChunkContextRequest,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    current_user: str = Depends(get_current_user),
):
    """Ask a question about a specific source chunk (document or web)."""
    if request.source_type == "web":
        # Fetch the full web page and use as context
        if not request.url:
            raise HTTPException(status_code=400, detail="URL required for web source")
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(request.url)
                resp.raise_for_status()
                page_text = resp.text
            # Strip HTML tags for a rough text extraction
            import re
            page_text = re.sub(r"<script[^>]*>.*?</script>", "", page_text, flags=re.DOTALL)
            page_text = re.sub(r"<style[^>]*>.*?</style>", "", page_text, flags=re.DOTALL)
            page_text = re.sub(r"<[^>]+>", " ", page_text)
            page_text = re.sub(r"\s+", " ", page_text).strip()
            # Truncate to ~4000 chars
            context = page_text[:4000]
        except Exception as e:
            logger.warning(f"Failed to fetch web page {request.url}: {e}")
            context = f"(Could not fetch page content from {request.url})"
    else:
        # Fetch surrounding chunks from vector store
        if not request.doc_id:
            raise HTTPException(status_code=400, detail="doc_id required for document source")
        center = request.chunk_index or 0
        neighbor_indices = list(range(max(0, center - 2), center + 3))
        chunks = vector_store.get_chunks_by_doc(request.doc_id, chunk_indices=neighbor_indices)
        if not chunks:
            raise HTTPException(status_code=404, detail="No chunks found for this document")
        context = "\n\n---\n\n".join(
            f"[Chunk {c.metadata.get('chunk_index', '?')}]\n{c.page_content}"
            for c in chunks
        )

    chain = CHUNK_CONTEXT_PROMPT | llm | StrOutputParser()
    try:
        answer = await _invoke_with_retry(chain, {
            "context": context,
            "question": request.question,
        })
    except Exception as e:
        logger.exception("Chunk context query failed")
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")

    if request.session_id:
        await memory_manager.add_exchange(
            request.session_id, request.question, answer, user_id=current_user,
        )

    return QueryResponse(
        answer=answer,
        sources=[],
        question=request.question,
        session_id=request.session_id,
    )


@router.post("/query/ask-ai", response_model=AskAIResponse)
async def ask_ai(
    request: AskAIRequest,
    llm: BaseChatModel = Depends(get_llm),
):
    """Answer a question using only the LLM's general knowledge (no documents)."""
    chain = ASK_AI_PROMPT | llm | StrOutputParser()
    try:
        answer = await _invoke_with_retry(chain, {"question": request.question})
    except Exception as e:
        logger.exception("Ask AI failed")
        err_msg = str(e).lower()
        if any(k in err_msg for k in ("api_error", "internal server error", "overloaded", "rate")):
            raise HTTPException(
                status_code=502,
                detail="The AI provider returned an error. Please try again in a moment.",
            )
        raise HTTPException(status_code=500, detail=f"Ask AI failed: {str(e)}")

    return AskAIResponse(answer=answer, question=request.question)


# ================================
# STREAMING ENDPOINTS
# ================================

@router.post("/query/stream")
async def query_documents_stream(
    request: QueryRequest,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    embeddings: Embeddings = Depends(get_embeddings),
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    """Streaming version of /query. Returns SSE events."""
    doc_ids, user_scoped = await _resolve_doc_ids(request, settings, registry, current_user)

    chat_history = None
    if request.session_id:
        chat_history = await memory_manager.get_history(request.session_id) or None

    try:
        chain, retriever = build_rag_chain(
            vector_store=vector_store, llm=llm, top_k=request.top_k,
            doc_ids=doc_ids, chat_history=chat_history, settings=settings,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # --- Retrieval (done before streaming starts) ---
    retrieved = []
    needs_web_search = False

    if request.force_web_search and settings.web_search_enabled:
        needs_web_search = True
    else:
        # Determine fetch size based on question type
        is_open = False
        if settings.open_question_detection:
            question_type = await _classify_question(request.question, llm)
            is_open = question_type == "open"

        fetch_k = int(request.top_k * 3) if is_open else int(request.top_k * 1.5)

        retrieved = vector_store.similarity_search_with_scores(
            request.question, k=fetch_k, doc_ids=doc_ids,
        )

        # Expand vague queries
        _, retrieved = await _maybe_expand_query(
            request.question, retrieved, llm, vector_store, settings, doc_ids, request.top_k,
        )

        if is_open:
            retrieved = _section_aware_sample(retrieved)
        else:
            retrieved = _demote_reference_results(retrieved, request.top_k)

        retrieved = _apply_reference_penalty(retrieved)
        retrieved = _apply_section_weights(retrieved)
        needs_web_search = _should_web_search(request, settings, user_scoped, retrieved)
        if not needs_web_search:
            if settings.visual_proximity_enabled:
                retrieved = _link_nearby_visuals(
                    retrieved, vector_store, doc_ids,
                    question=request.question, embeddings=embeddings,
                    proximity_pages=settings.visual_proximity_pages,
                )
            # Sort by score descending
            retrieved.sort(key=lambda x: x[1], reverse=True)

    # Pre-compute web search context if needed
    web_context = ""
    web_sources = []
    if needs_web_search:
        web_context, top_results = await _build_web_search_context(
            request.question, llm, settings,
        )
        web_sources = [s.model_dump() for s in _web_source_chunks(top_results)]

    async def event_generator():
        try:
            if needs_web_search:
                if not web_context:
                    yield sse_event("sources", {"sources": [], "web_search_used": False, "session_id": request.session_id})
                    yield sse_event("done", {"answer": "I couldn't find relevant information in your documents or on the web.", "session_id": request.session_id})
                    return

                web_chain = WEB_SEARCH_PROMPT | llm | StrOutputParser()
                async for event in stream_chain_response(
                    web_chain,
                    {"context": web_context, "question": request.question},
                    web_sources, request.session_id, web_search_used=True,
                ):
                    yield event
            else:
                # Normal RAG path
                sources_data = [s.model_dump() for s in _build_source_chunks(retrieved)]

                async for event in stream_chain_response(
                    chain, request.question, sources_data, request.session_id,
                ):
                    yield event
        except Exception as e:
            logger.exception("Streaming query failed")
            yield sse_event("error", {"detail": str(e)})

    # Wrap generator to also handle memory persistence
    async def event_generator_with_memory():
        full_answer_parts = []
        async for event in event_generator():
            yield event
            # Capture tokens for memory
            if event.get("event") == "token":
                import json as _json
                data = _json.loads(event["data"])
                full_answer_parts.append(data.get("token", ""))

        # Persist to memory after all events sent
        if request.session_id and full_answer_parts:
            try:
                full_answer = "".join(full_answer_parts)
                await memory_manager.add_exchange(
                    request.session_id, request.question, full_answer, user_id=current_user,
                )
            except Exception:
                logger.warning("Failed to persist streaming exchange to memory")

    return EventSourceResponse(event_generator_with_memory())


@router.post("/query/ask-ai/stream")
async def ask_ai_stream(
    request: AskAIRequest,
    llm: BaseChatModel = Depends(get_llm),
):
    """Streaming version of /query/ask-ai. Returns SSE events."""
    chain = ASK_AI_PROMPT | llm | StrOutputParser()

    async def event_generator():
        yield sse_event("sources", {"sources": []})
        full_answer = []
        try:
            async for chunk in chain.astream({"question": request.question}):
                if chunk:
                    full_answer.append(chunk)
                    yield sse_event("token", {"token": chunk})
        except Exception as e:
            logger.exception("Ask AI streaming failed")
            yield sse_event("error", {"detail": str(e)})
            return
        yield sse_event("done", {"answer": "".join(full_answer)})

    return EventSourceResponse(event_generator())
