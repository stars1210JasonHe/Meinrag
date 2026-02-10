import uuid
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.config import Settings
from app.dependencies import get_settings, get_vector_store, get_registry, get_llm
from app.models.document import DocumentRegistry
from langchain_core.language_models import BaseChatModel
from app.models.schemas import (
    UploadResponse,
    DocumentListResponse,
    DocumentInfo,
    DeleteResponse,
)
from app.services.document_processor import DocumentProcessor, SUPPORTED_EXTENSIONS
from app.vectorstore.base import VectorStoreManager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    collection: str | None = None,
    auto_suggest: bool = False,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    registry: DocumentRegistry = Depends(get_registry),
):
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    # Save file to disk
    doc_id = uuid.uuid4().hex[:12]
    upload_path = settings.upload_dir / f"{doc_id}_{filename}"
    content = await file.read()
    upload_path.write_bytes(content)

    try:
        # Process and index
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(upload_path)

        # AI suggests collection if requested and not manually specified
        suggested_collection = None
        if auto_suggest and not collection:
            from app.services.collection_suggester import suggest_collection
            suggested_collection = suggest_collection(chunks, llm)
            collection = suggested_collection  # Auto-assign

        # Add collection to chunk metadata
        for chunk in chunks:
            chunk.metadata["collection"] = collection

        vector_store.add_documents(chunks, doc_id=doc_id)

        # Register metadata
        registry.add(
            doc_id=doc_id,
            filename=filename,
            file_type=suffix,
            chunk_count=len(chunks),
            collection=collection,
        )

        message = "Document uploaded and indexed successfully"
        if suggested_collection:
            message += f". Suggested collection: {suggested_collection}"

        return UploadResponse(
            doc_id=doc_id,
            filename=filename,
            chunk_count=len(chunks),
            collection=collection,
            suggested_collection=suggested_collection,
            message=message,
        )
    except Exception as e:
        upload_path.unlink(missing_ok=True)
        logger.exception(f"Failed to process {filename}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    collection: str | None = None,
    registry: DocumentRegistry = Depends(get_registry),
):
    if collection:
        docs = registry.list_by_collection(collection)
    else:
        docs = registry.list_all()
    return DocumentListResponse(
        documents=[DocumentInfo(**d) for d in docs],
        total=len(docs),
    )


@router.delete("/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    registry: DocumentRegistry = Depends(get_registry),
):
    if not registry.get(doc_id):
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    vector_store.delete_document(doc_id)
    registry.remove(doc_id)

    # Remove uploaded file from disk
    for f in settings.upload_dir.iterdir():
        if f.name.startswith(doc_id):
            f.unlink(missing_ok=True)

    return DeleteResponse(doc_id=doc_id, message="Document deleted successfully")
