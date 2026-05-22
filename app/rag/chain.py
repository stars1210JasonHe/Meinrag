import logging
import re
from collections import Counter
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


def _should_use_bm25(settings: Settings) -> bool:
    """BM25 over anonymized text silently fails on PII-named queries
    (chunk has `[PERSON_1]`, query has the raw name — zero token overlap).
    Disable BM25 outright when anonymization is on. Vector + reranker
    still run normally.

    Callers must guard `settings is None` themselves (see build_rag_chain).
    """
    if settings.anonymization_enabled:
        return False
    return settings.hybrid_search_enabled


def _strip_ext(filename: str) -> str:
    """Strip file extension from filename."""
    dot = filename.rfind(".")
    return filename[:dot] if dot > 0 else filename


def _build_header(doc: Document, idx: int, filename_counts: Counter) -> str:
    """Build a contextual header like [name | p.5 | 3.2 Attention]."""
    meta = doc.metadata
    source = meta.get("source_file", "unknown")
    name = _strip_ext(source)

    # Disambiguate duplicate filenames with short doc_id suffix
    if filename_counts.get(source, 0) > 1:
        doc_id = meta.get("doc_id", "")
        if doc_id:
            name = f"{name}#{doc_id[:4]}"

    parts = [name]

    page = meta.get("page")
    if page is not None:
        parts.append(f"p.{page + 1}")

    # Prefer label (e.g. "Table 4"), else last heading segment
    label = meta.get("label")
    if label:
        parts.append(label)
    else:
        headings = meta.get("headings")
        if headings:
            last_heading = headings.split(" > ")[-1].strip()
            if last_heading:
                parts.append(last_heading)
        else:
            # Fallback: chunk_type badge for non-text
            chunk_type = meta.get("chunk_type", "text")
            if chunk_type == "table":
                parts.append("Table")
            elif chunk_type == "image":
                parts.append("Image")

    return f"[{idx}] {' | '.join(parts)}"


def format_docs(
    docs: list[Document],
    doc_summaries: dict[str, str] | None = None,
) -> str:
    """Format retrieved documents into a single context string.

    If doc_summaries is provided (doc_id -> documents.summary from DB), an
    upfront "Document overviews" block is prepended so the LLM has doc-level
    context for multi-doc queries. Chunk order is preserved; per-chunk
    summaries (chunk.metadata["summary"]) continue to appear inline.
    """
    # Count distinct doc_ids per filename — only disambiguate when
    # the same filename maps to different documents
    _file_docids: dict[str, set[str]] = {}
    for doc in docs:
        sf = doc.metadata.get("source_file", "unknown")
        did = doc.metadata.get("doc_id", "")
        _file_docids.setdefault(sf, set()).add(did)
    filename_counts = Counter({sf: len(ids) for sf, ids in _file_docids.items()})

    # Upfront doc overviews (first appearance per doc_id, only if summary exists)
    overview_block = ""
    if doc_summaries:
        seen: list[str] = []
        overview_lines: list[str] = []
        for doc in docs:
            did = doc.metadata.get("doc_id", "")
            if did and did not in seen and doc_summaries.get(did):
                seen.append(did)
                fname = doc.metadata.get("source_file", did)
                overview_lines.append(f"[{_strip_ext(fname)}]: {doc_summaries[did]}")
        if overview_lines:
            overview_block = (
                "=== Document overviews ===\n"
                + "\n".join(overview_lines)
                + "\n\n=== Retrieved chunks ===\n\n"
            )

    formatted = []
    for i, doc in enumerate(docs, 1):
        header = _build_header(doc, i, filename_counts)
        summary = doc.metadata.get("summary")
        if summary:
            formatted.append(f"{header}\nSummary: {summary}\n---\n{doc.page_content}")
        else:
            formatted.append(f"{header}\n{doc.page_content}")
    return overview_block + "\n\n---\n\n".join(formatted)


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


def _get_reranker(settings: Settings, llm: BaseChatModel | None = None, top_n_override: int | None = None):
    """Create a document compressor based on the configured rerank provider.

    Supported providers: flashrank (default, local CPU), cross-encoder (local GPU),
    jina (API), cohere (API), llm (uses chat model).

    Args:
        top_n_override: If set, overrides settings.rerank_top_n. Used when the
            caller (retrieval pipeline) knows how many chunks the LLM should see,
            so the rerank step doesn't throttle multi-doc queries.
    """
    provider = settings.rerank_provider
    top_n = top_n_override if top_n_override is not None else settings.rerank_top_n
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
    hybrid_enabled = _should_use_bm25(settings) if settings else False
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
