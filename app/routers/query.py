import logging

from fastapi import APIRouter, Depends, HTTPException

from app.config import Settings
from app.dependencies import get_settings, get_vector_store, get_llm, get_memory_manager
from app.models.schemas import QueryRequest, QueryResponse, SourceChunk
from app.rag.chain import build_rag_chain
from app.rag.memory import SessionMemoryManager
from app.vectorstore.base import VectorStoreManager
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query_documents(
    request: QueryRequest,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    memory_manager: SessionMemoryManager = Depends(get_memory_manager),
):
    # Load chat history if session_id provided
    chat_history = None
    if request.session_id:
        chat_history = memory_manager.get_history(request.session_id) or None

    try:
        chain, retriever = build_rag_chain(
            vector_store=vector_store,
            llm=llm,
            top_k=request.top_k,
            doc_ids=request.doc_ids,
            collection=request.collection,
            chat_history=chat_history,
            settings=settings,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        # Get source docs for the response
        if request.doc_ids or request.collection:
            retrieved_docs = vector_store.similarity_search_with_filter(
                request.question, k=request.top_k, doc_ids=request.doc_ids, collection=request.collection
            )
        else:
            retrieved_docs = vector_store.similarity_search(
                request.question, k=request.top_k
            )

        answer = await chain.ainvoke(request.question)

        # Store exchange in session memory
        if request.session_id:
            memory_manager.add_exchange(request.session_id, request.question, answer)

        sources = [
            SourceChunk(
                content=doc.page_content[:500],
                source_file=doc.metadata.get("source_file", "unknown"),
                chunk_index=doc.metadata.get("chunk_index"),
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
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")
