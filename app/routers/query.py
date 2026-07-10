import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.config import Settings
from app.dependencies import (
    get_settings, get_vector_store, get_llm, get_embeddings, get_memory_manager,
    get_registry, get_current_user, get_edge_repository, get_summary_store,
    get_anonymization_mapping_repo, get_anonymization_audit_repo,
)
from app.db.repositories import DocumentRepository, ChatSessionRepository, EdgeRepository
from app.models.schemas import (
    QueryRequest, QueryResponse, SourceChunk, ChunkContextRequest,
    AskAIRequest, AskAIResponse, SearchRequest, SearchResponse,
)
from langchain_core.output_parsers import StrOutputParser
from app.rag.chain import format_docs
from app.rag.prompts import (
    RAG_PROMPT, RAG_CHAT_PROMPT, WEB_SEARCH_PROMPT, CHUNK_CONTEXT_PROMPT,
    QUERY_REWRITE_PROMPT, ASK_AI_PROMPT,
    DOC_SUMMARY_FASTPATH_PROMPT, DOC_SUMMARY_FASTPATH_CHAT_PROMPT,
)
from app.routers.stream_helpers import sse_event, stream_chain_response
from app.services.retrieval import (
    retrieve_and_rank,
    _build_source_chunks,
)
from app.services.fast_path import should_use_doc_summary_fastpath
from app.vectorstore.base import VectorStoreManager
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)
router = APIRouter()

_RETRYABLE_KEYWORDS = ("500", "503", "rate", "overloaded", "internal server error")


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
    request: "QueryRequest | SearchRequest",
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
                collection_set = set(collection_doc_ids)  # collections reach thousands of ids
                doc_ids = [d for d in doc_ids if d in collection_set and d in user_doc_ids]
            else:
                doc_ids = collection_doc_ids
        elif doc_ids:
            doc_ids = [d for d in doc_ids if d in user_doc_ids]
        else:
            doc_ids = list(user_doc_ids) if user_doc_ids else []
    elif request.collection:
        collection_docs = await registry.list_by_collection(request.collection)
        doc_ids = [d["doc_id"] for d in collection_docs]

    return doc_ids, user_scoped



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


async def _doc_summary_fastpath(
    request: QueryRequest,
    doc_summary: str,
    doc_ids: list[str],
    llm: BaseChatModel,
    vector_store: VectorStoreManager,
    memory_manager: ChatSessionRepository,
    chat_history,
    current_user: str | None,
    settings: Settings,
    mapping_repo=None,
    audit_repo=None,
) -> QueryResponse:
    """Answer using pre-computed doc.summary + a handful of supporting chunks.

    Skips the full retrieval pipeline. Fetches top-3 chunks for citations
    only — the doc summary is the primary content.

    Deanonymization note: this path bypasses retrieve_and_rank, so it
    must run deanonymize_chunks itself before format_docs + sources are
    built. Without this, anonymized docs surface [PERSON_N] tokens in
    both the LLM context and the user-facing citations.
    """
    top_chunks = vector_store.similarity_search_with_scores(
        request.question, k=3, doc_ids=doc_ids,
    )
    if top_chunks and settings.anonymization_enabled and mapping_repo is not None:
        from app.services.deanonymize import deanonymize_chunks
        raw_docs = [doc for doc, _ in top_chunks]
        chunk_doc_ids = list({d.metadata.get("doc_id") for d in raw_docs if d.metadata.get("doc_id")})
        if chunk_doc_ids:
            mappings = await mapping_repo.get_by_docs(chunk_doc_ids)
            if mappings:
                deanon_docs = deanonymize_chunks(raw_docs, mappings)
                top_chunks = list(zip(deanon_docs, (s for _, s in top_chunks)))
                if audit_repo is not None:
                    # See retrieval.py step 17 for entity_count semantics +
                    # fail-safe rationale. Same pattern here for the
                    # doc-summary fast-path bypass.
                    for did, mapping in mappings.items():
                        if mapping:  # skip docs with no entities
                            try:
                                await audit_repo.log(
                                    did, current_user, "deanonymize",
                                    entity_count=len(mapping),
                                )
                            except Exception:
                                logger.error(
                                    "AUDIT WRITE FAILED for doc=%s user=%s — "
                                    "deanonymize event NOT recorded (fast-path)",
                                    did, current_user, exc_info=True,
                                )

    context = format_docs([doc for doc, _ in top_chunks]) if top_chunks else "(no supporting excerpts available)"
    sources = _build_source_chunks(top_chunks) if top_chunks else []

    if chat_history:
        chain = DOC_SUMMARY_FASTPATH_CHAT_PROMPT | llm | StrOutputParser()
        answer = await _invoke_with_retry(chain, {
            "overview": doc_summary,
            "context": context,
            "chat_history": chat_history,
            "question": request.question,
        })
    else:
        chain = DOC_SUMMARY_FASTPATH_PROMPT | llm | StrOutputParser()
        answer = await _invoke_with_retry(chain, {
            "overview": doc_summary,
            "context": context,
            "question": request.question,
        })

    if request.session_id:
        sources_data = [s.model_dump() for s in sources]
        # Match the non-fast-path scope convention: use request.doc_ids (not
        # the resolved list) so session history stays under one scope_value.
        scope_value = (
            request.doc_ids[0] if request.doc_ids and len(request.doc_ids) == 1
            else doc_ids[0]
        )
        await memory_manager.add_exchange(
            request.session_id, request.question, answer,
            user_id=current_user,
            sources_json=json.dumps(sources_data),
            scope_type="doc",
            scope_value=scope_value,
        )

    return QueryResponse(
        answer=answer,
        sources=sources,
        question=request.question,
        session_id=request.session_id,
        fast_path=True,
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
    edge_repo: EdgeRepository = Depends(get_edge_repository),
    summary_store=Depends(get_summary_store),
    mapping_repo=Depends(get_anonymization_mapping_repo),
    audit_repo=Depends(get_anonymization_audit_repo),
):
    doc_ids, user_scoped = await _resolve_doc_ids(request, settings, registry, current_user)

    # Load chat history if session_id provided
    chat_history = None
    if request.session_id:
        chat_history = await memory_manager.get_history(request.session_id) or None

    try:
        # Force web search — skip vector search entirely
        if request.force_web_search and settings.web_search_enabled:
            return await _web_search_fallback(
                request, llm, memory_manager, settings, current_user=current_user,
            )

        # Fast-path: single-doc summarization with pre-computed doc.summary
        doc_summary = await should_use_doc_summary_fastpath(
            request.question, doc_ids, registry,
        )
        if doc_summary:
            return await _doc_summary_fastpath(
                request, doc_summary, doc_ids, llm, vector_store,
                memory_manager, chat_history, current_user,
                settings=settings, mapping_repo=mapping_repo,
                audit_repo=audit_repo,
            )

        # Single retrieval — one source of truth for both LLM context and frontend sources
        result = await retrieve_and_rank(
            question=request.question,
            top_k=request.top_k,
            doc_ids=doc_ids,
            user_scoped=user_scoped,
            llm=llm,
            vector_store=vector_store,
            embeddings=embeddings,
            edge_repo=edge_repo,
            settings=settings,
            force_web_search=False,
            summary_store=summary_store,
            chat_history=chat_history,
            registry=registry,
            mapping_repo=mapping_repo,
            audit_repo=audit_repo,
            user_id=current_user,
        )

        if result.web_search_needed:
            return await _web_search_fallback(
                request, llm, memory_manager, settings, current_user=current_user,
            )

        # Fetch doc-level summaries for all scoped docs (for format_docs overview block).
        # Covers multi-doc queries where per-doc coverage matters.
        doc_summaries: dict[str, str] = {}
        for did in (doc_ids or []):
            d = await registry.get(did)
            if d and isinstance(d, dict) and d.get("summary"):
                doc_summaries[did] = d["summary"]

        # Format retrieved docs as context for LLM
        context = format_docs(
            [doc for doc, _ in result.retrieved],
            doc_summaries=doc_summaries or None,
        )

        # Build simple chain (no retriever — just prompt + LLM)
        if chat_history:
            chain = RAG_CHAT_PROMPT | llm | StrOutputParser()
            answer = await _invoke_with_retry(chain, {
                "context": context,
                "chat_history": chat_history,
                "question": request.question,
            })
        else:
            chain = RAG_PROMPT | llm | StrOutputParser()
            answer = await _invoke_with_retry(chain, {
                "context": context,
                "question": request.question,
            })

        # Store exchange in session memory
        if request.session_id:
            sources_data = [s.model_dump() for s in result.sources]
            # Determine session scope from request
            _scope_type = "global"
            _scope_value = None
            if request.doc_ids and len(request.doc_ids) == 1:
                _scope_type = "doc"
                _scope_value = request.doc_ids[0]
            elif request.collection:
                _scope_type = "collection"
                _scope_value = request.collection
            await memory_manager.add_exchange(
                request.session_id, request.question, answer,
                user_id=current_user,
                sources_json=json.dumps(sources_data),
                scope_type=_scope_type,
                scope_value=_scope_value,
            )

        return QueryResponse(
            answer=answer,
            sources=result.sources,
            question=request.question,
            session_id=request.session_id,
            query_types=result.query_types,
            confidence_tier=result.confidence_tier,
            context_used_tokens=result.context_used_tokens,
            context_budget_tokens=result.context_budget_tokens,
            context_mode=result.context_mode,
            chunks_included=result.chunks_included,
            chunks_available=result.chunks_available,
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


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    embeddings: Embeddings = Depends(get_embeddings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
    edge_repo: EdgeRepository = Depends(get_edge_repository),
    summary_store=Depends(get_summary_store),
    mapping_repo=Depends(get_anonymization_mapping_repo),
    audit_repo=Depends(get_anonymization_audit_repo),
):
    """Retrieve-only search: ranked corpus chunks, no LLM-synthesized answer.

    For MCP / agent consumers that reason over raw results themselves. Unlike
    /query this: never synthesizes an answer, never falls back to web search
    (force_corpus_only=True), and returns FULL chunk text (source_truncate_chars
    =None, not the 500-char preview). Deanonymization still happens inside
    retrieve_and_rank, so results are deanonymized.
    """
    doc_ids, user_scoped = await _resolve_doc_ids(request, settings, registry, current_user)
    effective_top_k = request.top_k if request.top_k is not None else settings.retrieval_top_k

    try:
        result = await retrieve_and_rank(
            question=request.query,
            top_k=effective_top_k,
            doc_ids=doc_ids,
            user_scoped=user_scoped,
            llm=llm,
            vector_store=vector_store,
            embeddings=embeddings,
            edge_repo=edge_repo,
            settings=settings,
            force_web_search=False,
            force_corpus_only=True,
            source_truncate_chars=None,
            summary_store=summary_store,
            chat_history=None,
            registry=registry,
            mapping_repo=mapping_repo,
            audit_repo=audit_repo,
            user_id=current_user,
            ensure_coverage=settings.search_coverage_enabled,
            # retrieve-only: response order must be ranking order, not the
            # LLM-context U-shape placement (which buries #2 at the end)
            reorder_for_attention=False,
        )
        return SearchResponse(
            results=result.sources,
            confidence_tier=result.confidence_tier,
            total_available=result.chunks_available,
            query_types=result.query_types,
        )
    except Exception as e:
        logger.exception("Search failed")
        err_msg = str(e).lower()
        if any(k in err_msg for k in ("api_error", "internal server error", "overloaded", "rate")):
            raise HTTPException(
                status_code=502,
                detail="The AI provider returned an error. Please try again in a moment.",
            )
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


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
    raw_request: Request,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    embeddings: Embeddings = Depends(get_embeddings),
    memory_manager: ChatSessionRepository = Depends(get_memory_manager),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
    edge_repo: EdgeRepository = Depends(get_edge_repository),
    summary_store=Depends(get_summary_store),
    mapping_repo=Depends(get_anonymization_mapping_repo),
    audit_repo=Depends(get_anonymization_audit_repo),
):
    """Streaming version of /query. Returns SSE events."""
    doc_ids, user_scoped = await _resolve_doc_ids(request, settings, registry, current_user)

    chat_history = None
    if request.session_id:
        chat_history = await memory_manager.get_history(request.session_id) or None

    # --- Fast-path check (before retrieval): single-doc doc.summary path ---
    fast_path_summary: str | None = None
    fast_path_sources_data: list[dict] = []
    fast_path_overview: str | None = None
    if not (request.force_web_search and settings.web_search_enabled):
        fast_path_summary = await should_use_doc_summary_fastpath(
            request.question, doc_ids, registry,
        )
    if fast_path_summary:
        fast_path_overview = fast_path_summary
        # Fetch a small set of supporting chunks for citations
        supporting = vector_store.similarity_search_with_scores(
            request.question, k=3, doc_ids=doc_ids,
        )
        # Deanonymize before sources + context (this path bypasses
        # retrieve_and_rank, so the Task 11 hook does not fire here).
        if supporting and settings.anonymization_enabled and mapping_repo is not None:
            from app.services.deanonymize import deanonymize_chunks
            raw_docs = [doc for doc, _ in supporting]
            chunk_doc_ids = list({d.metadata.get("doc_id") for d in raw_docs if d.metadata.get("doc_id")})
            if chunk_doc_ids:
                mappings = await mapping_repo.get_by_docs(chunk_doc_ids)
                if mappings:
                    deanon_docs = deanonymize_chunks(raw_docs, mappings)
                    supporting = list(zip(deanon_docs, (s for _, s in supporting)))
                    if audit_repo is not None:
                        # See retrieval.py step 17 for entity_count semantics
                        # + fail-safe rationale. Same pattern here for the
                        # streaming doc-summary fast-path bypass.
                        for did, mapping in mappings.items():
                            if mapping:  # skip docs with no entities
                                try:
                                    await audit_repo.log(
                                        did, current_user, "deanonymize",
                                        entity_count=len(mapping),
                                    )
                                except Exception:
                                    logger.error(
                                        "AUDIT WRITE FAILED for doc=%s user=%s — "
                                        "deanonymize event NOT recorded (stream fast-path)",
                                        did, current_user, exc_info=True,
                                    )
        fast_path_sources_data = [s.model_dump() for s in _build_source_chunks(supporting)]
        result = None
        needs_web_search = False
        query_types = ["overview"]
        query_label = None
        # Don't hardcode "high" — we bypassed the composite scoring that
        # normally feeds confidence. Gate on doc summary length: a substantive
        # summary (>200 chars) signals real content; anything shorter might
        # be a degenerate one-liner and should read as moderate.
        confidence_tier = "high" if len(fast_path_overview) > 200 else "moderate"
        context = format_docs([doc for doc, _ in supporting]) if supporting else "(no supporting excerpts available)"
    elif request.force_web_search and settings.web_search_enabled:
        result = None
        needs_web_search = True
        query_types: list[str] = []
        query_label = None
        confidence_tier = None
        context = ""
    else:
        result = await retrieve_and_rank(
            question=request.question,
            top_k=request.top_k,
            doc_ids=doc_ids,
            user_scoped=user_scoped,
            llm=llm,
            vector_store=vector_store,
            embeddings=embeddings,
            edge_repo=edge_repo,
            settings=settings,
            force_web_search=False,
            summary_store=summary_store,
            chat_history=chat_history,
            registry=registry,
            mapping_repo=mapping_repo,
            audit_repo=audit_repo,
            user_id=current_user,
        )
        needs_web_search = result.web_search_needed
        query_types = result.query_types
        query_label = result.query_label
        confidence_tier = result.confidence_tier

        # Fetch doc-level summaries for multi-doc overview block
        doc_summaries: dict[str, str] = {}
        if not needs_web_search:
            for did in (doc_ids or []):
                d = await registry.get(did)
                if d and isinstance(d, dict) and d.get("summary"):
                    doc_summaries[did] = d["summary"]
        context = format_docs(
            [doc for doc, _ in result.retrieved],
            doc_summaries=doc_summaries or None,
        ) if not needs_web_search else ""

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
            elif fast_path_overview:
                # Fast-path: answer from pre-computed doc summary + supporting chunks
                yield sse_event("query_analysis", {
                    "types": query_types,
                    "label": query_label,
                    "confidence_tier": confidence_tier,
                    "fast_path": True,
                })

                if chat_history:
                    fp_chain = DOC_SUMMARY_FASTPATH_CHAT_PROMPT | llm | StrOutputParser()
                    input_data = {
                        "overview": fast_path_overview,
                        "context": context,
                        "chat_history": chat_history,
                        "question": request.question,
                    }
                else:
                    fp_chain = DOC_SUMMARY_FASTPATH_PROMPT | llm | StrOutputParser()
                    input_data = {
                        "overview": fast_path_overview,
                        "context": context,
                        "question": request.question,
                    }

                async for event in stream_chain_response(
                    fp_chain, input_data, fast_path_sources_data, request.session_id,
                ):
                    yield event
            else:
                # Normal RAG path — build prompt+LLM chain with pre-computed context
                yield sse_event("query_analysis", {
                    "types": query_types,
                    "label": query_label,
                    "confidence_tier": confidence_tier,
                    "context_used_tokens": result.context_used_tokens,
                    "context_budget_tokens": result.context_budget_tokens,
                    "context_mode": result.context_mode,
                    "chunks_included": result.chunks_included,
                    "chunks_available": result.chunks_available,
                })

                sources_data = [s.model_dump() for s in result.sources]

                if chat_history:
                    rag_chain = RAG_CHAT_PROMPT | llm | StrOutputParser()
                    input_data = {
                        "context": context,
                        "chat_history": chat_history,
                        "question": request.question,
                    }
                else:
                    rag_chain = RAG_PROMPT | llm | StrOutputParser()
                    input_data = {"context": context, "question": request.question}

                async for event in stream_chain_response(
                    rag_chain, input_data, sources_data, request.session_id,
                ):
                    yield event
        except Exception as e:
            logger.exception("Streaming query failed")
            yield sse_event("error", {"detail": str(e)})

    # Shared mutable to capture the full answer during streaming.
    # Post-yield code in SSE generators is unreliable (cancelled on
    # client disconnect), so we persist inside the generator itself
    # as soon as the "done" event is emitted.
    async def _persist_exchange(full_answer: str, sources_override: list[dict] | None = None):
        """Save exchange using a fresh DB session (request-scoped one may be closed)."""
        sources_data = sources_override if sources_override is not None else (
            [s.model_dump() for s in result.sources] if result else []
        )
        _scope_type = "global"
        _scope_value = None
        if request.doc_ids and len(request.doc_ids) == 1:
            _scope_type = "doc"
            _scope_value = request.doc_ids[0]
        elif request.collection:
            _scope_type = "collection"
            _scope_value = request.collection

        session_factory = raw_request.app.state.db_session_factory
        async with session_factory() as db:
            try:
                mem = ChatSessionRepository(
                    db,
                    max_messages=settings.memory_max_messages,
                    session_ttl=settings.memory_session_ttl,
                )
                await mem.add_exchange(
                    request.session_id, request.question, full_answer,
                    user_id=current_user,
                    sources_json=json.dumps(sources_data),
                    scope_type=_scope_type,
                    scope_value=_scope_value,
                )
                await db.commit()
                logger.info("Persisted streaming exchange for session %s", request.session_id)
            except Exception:
                await db.rollback()
                raise

    async def event_generator_with_memory():
        full_answer_parts = []
        async for event in event_generator():
            evt_type = event.get("event")
            # Capture tokens
            if evt_type == "token":
                import json as _json
                data = _json.loads(event["data"])
                full_answer_parts.append(data.get("token", ""))

            # Fire-and-forget persist on done event — use asyncio.create_task
            # so it survives the SSE task group cancellation on client disconnect
            if evt_type == "done" and request.session_id:
                full_answer = "".join(full_answer_parts)
                if full_answer:
                    # Pass web_sources for web-search path (result is None there),
                    # fast_path_sources_data for fast-path, default otherwise.
                    if needs_web_search:
                        override = web_sources
                    elif fast_path_overview:
                        override = fast_path_sources_data
                    else:
                        override = None
                    asyncio.create_task(_persist_exchange(full_answer, sources_override=override))

            yield event

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
