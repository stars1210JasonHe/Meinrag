from fastapi import APIRouter, Depends

from app.config import Settings
from app.dependencies import get_settings, get_registry
from app.db.repositories import DocumentRepository
from app.models.schemas import HealthResponse

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
