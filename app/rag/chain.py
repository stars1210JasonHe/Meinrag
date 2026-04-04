import logging
import re
from typing import Sequence

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from app.config import Settings
from app.rag.prompts import RAG_PROMPT, RAG_CHAT_PROMPT
from app.vectorstore.base import VectorStoreManager

logger = logging.getLogger(__name__)


def format_docs(docs: list[Document]) -> str:
    """Format retrieved documents into a single context string."""
    formatted = []
    image_counter = 0
    table_counter = 0
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source_file", "unknown")
        page = doc.metadata.get("page")
        page_str = f" (p.{page + 1})" if page is not None else ""
        chunk_type = doc.metadata.get("chunk_type", "text")
        type_label = ""
        if chunk_type == "table":
            table_counter += 1
            type_label = f" [TABLE {table_counter}]"
        elif chunk_type == "image":
            image_counter += 1
            type_label = f" [FIGURE {image_counter}]"
        formatted.append(f"[Source {i}: {source}{page_str}{type_label}]\n{doc.page_content}")
    return "\n\n---\n\n".join(formatted)


_REF_LINE_RE = re.compile(r"^-?\s*\[\d+\]\s+[A-Z]")
_REF_HEADING_RE = re.compile(
    r"^[`\s]*#{1,3}\s*(?:References|Bibliography|Works\s+Cited)\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def is_reference_entry(text: str) -> bool:
    """Detect if text is a bibliography/reference list entry.

    Matches:
      - [1] Author, Title...          (numbered reference lines)
      - # References                   (heading, including markdown fenced)
      - ## Bibliography
    Returns True if heading matches or >= 50% of lines are reference entries.
    """
    stripped = text.strip().strip('`').strip()
    if not stripped:
        return False

    # Check for reference section heading
    if _REF_HEADING_RE.search(text):
        return True

    # Check for numbered reference lines
    lines = stripped.split("\n")
    ref_lines = sum(1 for line in lines if _REF_LINE_RE.match(line.strip()))
    return ref_lines > 0 and ref_lines >= len(lines) * 0.5


def _demote_reference_chunks(docs: list[Document], limit: int) -> list[Document]:
    """Move reference-list chunks to the end so real content fills top slots first."""
    content, refs = [], []
    for d in docs:
        (refs if is_reference_entry(d.page_content) else content).append(d)
    return (content + refs)[:limit]


def _build_filtered_retriever(
    vector_store: VectorStoreManager,
    doc_ids: list[str] | None,
    top_k: int,
) -> RunnableLambda:
    """Retriever that filters results by document IDs."""

    def _search(query: str) -> list[Document]:
        return vector_store.similarity_search_with_filter(query, k=top_k, doc_ids=doc_ids)

    return RunnableLambda(_search)


# BM25 index cache — invalidated on document add/delete
_bm25_cache: dict = {"doc_count": 0, "retriever": None, "doc_ids_key": None}


def invalidate_bm25_cache():
    """Call after document add/delete to rebuild BM25 on next query."""
    _bm25_cache["doc_count"] = 0
    _bm25_cache["retriever"] = None
    _bm25_cache["doc_ids_key"] = None


def _build_hybrid_retriever(
    vector_store: VectorStoreManager,
    top_k: int,
    bm25_weight: float,
    doc_ids: list[str] | None = None,
) -> RunnableLambda:
    """EnsembleRetriever combining vector similarity + BM25 via RRF."""
    from langchain.retrievers import EnsembleRetriever
    from langchain_community.retrievers import BM25Retriever

    all_docs = vector_store.get_all_documents()
    if doc_ids:
        all_docs = [d for d in all_docs if d.metadata.get("doc_id") in doc_ids]

    if not all_docs:
        return RunnableLambda(lambda query: [])

    # Use cached BM25 if doc set hasn't changed
    cache_key = tuple(sorted(doc_ids)) if doc_ids else None
    if (_bm25_cache["retriever"] is not None
            and _bm25_cache["doc_count"] == len(all_docs)
            and _bm25_cache["doc_ids_key"] == cache_key):
        bm25_retriever = _bm25_cache["retriever"]
        bm25_retriever.k = top_k
    else:
        bm25_retriever = BM25Retriever.from_documents(all_docs, k=top_k)
        _bm25_cache["retriever"] = bm25_retriever
        _bm25_cache["doc_count"] = len(all_docs)
        _bm25_cache["doc_ids_key"] = cache_key

    if doc_ids:
        vector_retriever = _build_filtered_retriever(vector_store, doc_ids, top_k)
    else:
        vector_retriever = vector_store.as_retriever(
            search_type="similarity", search_kwargs={"k": top_k}
        )

    vector_weight = 1.0 - bm25_weight
    ensemble = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[bm25_weight, vector_weight],
    )

    def _search(query: str) -> list[Document]:
        results = ensemble.invoke(query)
        return results[:top_k]

    return RunnableLambda(_search)


def _get_reranker(settings: Settings, llm: BaseChatModel | None = None):
    """Create a document compressor based on the configured rerank provider.

    Supported providers: flashrank (default, local CPU), cross-encoder (local GPU),
    jina (API), cohere (API), llm (uses chat model).
    """
    provider = settings.rerank_provider
    top_n = settings.rerank_top_n
    model = settings.rerank_model

    try:
        if provider == "flashrank":
            from langchain_community.document_compressors.flashrank_rerank import FlashrankRerank
            return FlashrankRerank(
                model=model or "ms-marco-MiniLM-L-12-v2",
                top_n=top_n,
            )

        elif provider == "cross-encoder":
            from langchain_community.cross_encoders import HuggingFaceCrossEncoder
            from langchain_classic.retrievers.document_compressors.cross_encoder_rerank import CrossEncoderReranker
            encoder = HuggingFaceCrossEncoder(
                model_name=model or "BAAI/bge-reranker-v2-m3",
            )
            return CrossEncoderReranker(model=encoder, top_n=top_n)

        elif provider == "jina":
            from langchain_community.document_compressors.jina_rerank import JinaRerank
            return JinaRerank(
                model=model or "jina-reranker-v2-base-multilingual",
                top_n=top_n,
            )

        elif provider == "cohere":
            from langchain_cohere import CohereRerank
            return CohereRerank(
                model=model or "rerank-english-v3.0",
                top_n=top_n,
            )

        elif provider == "llm":
            from langchain_classic.retrievers.document_compressors.listwise_rerank import LLMListwiseRerank
            if llm is None:
                raise ValueError("LLM reranker requires an LLM instance")
            return LLMListwiseRerank.from_llm(llm, top_n=top_n)

        else:
            raise ValueError(f"Unknown rerank_provider: {provider}")

    except (ImportError, ModuleNotFoundError) as e:
        raise ImportError(
            f"Rerank provider '{provider}' requires a package that is not installed. "
            f"Install with: uv pip install <package>. Original error: {e}"
        ) from e


def _build_reranked_retriever(
    base_retriever,
    settings: Settings,
    llm: BaseChatModel | None = None,
) -> RunnableLambda:
    """Wraps a retriever with a configurable re-ranker."""
    from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever

    compressor = _get_reranker(settings, llm)
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever,
    )

    def _search(query: str) -> list[Document]:
        try:
            return compression_retriever.invoke(query)
        except Exception as e:
            logger.warning("Reranker failed, returning unranked results: %s", e)
            return base_retriever.invoke(query)

    return RunnableLambda(_search)


def build_rag_chain(
    vector_store: VectorStoreManager,
    llm: BaseChatModel,
    top_k: int = 4,
    doc_ids: list[str] | None = None,
    chat_history: list[BaseMessage] | None = None,
    settings: Settings | None = None,
):
    """Build a LangChain RAG chain using LCEL.

    Supports optional document filtering, hybrid search, re-ranking,
    and chat-aware prompting. All features are backwards-compatible.
    """
    # Determine effective fetch count (over-fetch if re-ranking)
    rerank_enabled = settings.rerank_enabled if settings else False
    rerank_top_n = settings.rerank_top_n if settings else 4
    hybrid_enabled = settings.hybrid_search_enabled if settings else False
    bm25_weight = settings.hybrid_bm25_weight if settings else 0.5

    # Over-fetch to allow reference demotion (fetch extra, then filter down)
    fetch_k = top_k * 3 if rerank_enabled else int(top_k * 1.5)

    # Step 1: Build base retriever
    if hybrid_enabled:
        retriever = _build_hybrid_retriever(
            vector_store, fetch_k, bm25_weight, doc_ids
        )
    elif doc_ids:
        retriever = _build_filtered_retriever(vector_store, doc_ids, fetch_k)
    else:
        retriever = vector_store.as_retriever(
            search_type="similarity", search_kwargs={"k": fetch_k}
        )

    # Step 2: Demote reference-section chunks (push to end)
    # When reranking, keep full fetch_k so reranker has enough candidates
    demote_limit = fetch_k if rerank_enabled else top_k
    base_retriever = retriever
    retriever = RunnableLambda(
        lambda query, lim=demote_limit: _demote_reference_chunks(
            base_retriever.invoke(query), lim
        )
    )

    # Step 3: Wrap with re-ranker if enabled
    if rerank_enabled:
        retriever = _build_reranked_retriever(retriever, settings, llm)

    # Step 4: Choose prompt based on chat history
    if chat_history:
        prompt = RAG_CHAT_PROMPT
        chain = (
            {
                "context": retriever | format_docs,
                "chat_history": lambda _: chat_history,
                "question": RunnablePassthrough(),
            }
            | prompt
            | llm
            | StrOutputParser()
        )
    else:
        prompt = RAG_PROMPT
        chain = (
            {
                "context": retriever | format_docs,
                "question": RunnablePassthrough(),
            }
            | prompt
            | llm
            | StrOutputParser()
        )

    return chain, retriever
