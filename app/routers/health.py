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


RETRIEVAL_SETTINGS = (
    "retrieval_top_k", "rerank_enabled", "rerank_provider", "rerank_model", "rerank_max_candidates",
    "hybrid_search_enabled", "anonymization_enabled", "summary_enabled", "summary_contextual",
    "summary_min_chars", "chunk_size", "chunk_overlap", "rrf_k", "router_enabled",
    "context_budget_ratio", "reserved_output_tokens", "max_context_tokens",
    "openai_model", "openai_embedding_model", "llm_provider", "vector_store",
)


def config_snapshot(settings: Settings) -> dict:
    """The retrieval-side settings, by name. Only the names above are read, so no key,
    token or URL can leak through this route; a name a deployment does not have is
    reported as null rather than skipped, so two snapshots always line up."""
    out = {}
    for name in RETRIEVAL_SETTINGS:
        v = getattr(settings, name, None)
        out[name] = getattr(v, "value", v)
    return out


@router.get("/health/config")
async def config_check(settings: Settings = Depends(get_settings)):
    """Which retrieval knobs this server actually runs with. An evaluation report that
    does not record these cannot be compared with another run: the same script under a
    different .env is a different experiment."""
    return config_snapshot(settings)


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
