from fastapi import APIRouter, Depends, Request

from app.config import Settings
from app.dependencies import get_settings, get_registry, get_vector_store
from app.db.repositories import DocumentRepository
from app.models.schemas import HealthResponse
from app.vectorstore.base import VectorStoreManager

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
):
    return HealthResponse(
        status="ok",
        llm_provider=settings.llm_provider.value,
        vector_store=settings.vector_store.value,
        document_count=await registry.count(),
    )


@router.get("/health/deep")
async def deep_health_check(
    request: Request,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    vector_store: VectorStoreManager = Depends(get_vector_store),
):
    """Deep health check — tests DB, vector store, and LLM connectivity."""
    checks = {}
    overall_ok = True

    # 1. Database check
    try:
        count = await registry.count()
        checks["database"] = {"status": "ok", "document_count": count}
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}
        overall_ok = False

    # 2. Vector store check
    try:
        all_docs = vector_store.get_all_documents()
        checks["vector_store"] = {"status": "ok", "chunk_count": len(all_docs)}
    except Exception as e:
        checks["vector_store"] = {"status": "error", "detail": str(e)}
        overall_ok = False

    # 3. LLM check (lightweight ping)
    try:
        llm = request.app.state.llm
        result = await llm.ainvoke("ping")
        model = settings.openai_model if settings.llm_provider.value == "openai" else settings.openrouter_model
        checks["llm"] = {"status": "ok", "model": model}
    except Exception as e:
        checks["llm"] = {"status": "error", "detail": str(e)}
        overall_ok = False

    return {
        "status": "ok" if overall_ok else "degraded",
        "checks": checks,
    }
