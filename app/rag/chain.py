import logging
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
    for i, doc in enumerate(docs, 1):
        source = doc.metadata.get("source_file", "unknown")
        page = doc.metadata.get("page")
        page_str = f" (p.{page + 1})" if page is not None else ""
        formatted.append(f"[Source {i}: {source}{page_str}]\n{doc.page_content}")
    return "\n\n---\n\n".join(formatted)


def _build_filtered_retriever(
    vector_store: VectorStoreManager,
    doc_ids: list[str] | None,
    top_k: int,
) -> RunnableLambda:
    """Retriever that filters results by document IDs."""

    def _search(query: str) -> list[Document]:
        return vector_store.similarity_search_with_filter(query, k=top_k, doc_ids=doc_ids)

    return RunnableLambda(_search)


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

    bm25_retriever = BM25Retriever.from_documents(all_docs, k=top_k)

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


def _build_reranked_retriever(
    base_retriever,
    llm: BaseChatModel,
    top_n: int,
) -> RunnableLambda:
    """Wraps a retriever with LLM listwise re-ranking."""
    from langchain.retrievers import ContextualCompressionRetriever
    from langchain.retrievers.document_compressors import LLMListwiseRerank

    compressor = LLMListwiseRerank.from_llm(llm, top_n=top_n)
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=base_retriever,
    )

    def _search(query: str) -> list[Document]:
        return compression_retriever.invoke(query)

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

    fetch_k = top_k * 3 if rerank_enabled else top_k

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

    # Step 2: Wrap with re-ranker if enabled
    if rerank_enabled:
        retriever = _build_reranked_retriever(retriever, llm, rerank_top_n)

    # Step 3: Choose prompt based on chat history
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
