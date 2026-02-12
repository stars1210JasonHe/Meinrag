import uuid
import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse

from app.config import Settings
from app.classification import PRIMARY_CATEGORIES
from app.dependencies import (
    get_settings, get_vector_store, get_registry, get_llm, get_current_user,
)
from app.db.repositories import DocumentRepository
from langchain_core.language_models import BaseChatModel
from app.models.schemas import (
    UploadResponse,
    DocumentListResponse,
    DocumentInfo,
    DeleteResponse,
    DocumentUpdateRequest,
    DocumentUpdateResponse,
    CollectionsResponse,
)
from app.services.document_processor import DocumentProcessor, SUPPORTED_EXTENSIONS
from app.vectorstore.base import VectorStoreManager

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_user_filter(settings: Settings, user_id: str) -> str | None:
    """Return user_id for filtering if isolation is enabled, else None."""
    if settings.user_isolation in ("all", "documents"):
        return user_id
    return None


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    collections: str | None = Query(default=None, description="Comma-separated collection names"),
    auto_suggest: bool = False,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    filename = file.filename or "unknown"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Supported: {sorted(SUPPORTED_EXTENSIONS)}",
        )

    # Read file content and check size
    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) // 1024 // 1024}MB). Maximum: {settings.max_upload_size_mb}MB.",
        )
    file_hash = hashlib.sha256(content).hexdigest()

    # Check for duplicate: same content already uploaded by this user
    user_filter = _get_user_filter(settings, current_user)
    existing_docs = await registry.list_all(user_id=user_filter)
    for doc in existing_docs:
        if doc.get("file_hash") == file_hash:
            raise HTTPException(
                status_code=409,
                detail=f"This file has already been uploaded as '{doc['filename']}'. Delete it first if you want to re-upload.",
            )

    # Save file to disk
    doc_id = uuid.uuid4().hex[:12]
    upload_path = settings.upload_dir / f"{doc_id}_{filename}"
    upload_path.write_bytes(content)

    try:
        # Process and index
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(upload_path)

        # Parse collections from comma-separated string
        parsed_collections: list[str] | None = None
        if collections:
            parsed_collections = [c.strip() for c in collections.split(",") if c.strip()]

        # AI suggests collections if requested and not manually specified
        suggested_collections = None
        if auto_suggest and not parsed_collections:
            from app.services.collection_suggester import suggest_collections
            existing = await registry.get_all_collections()
            suggested_collections = suggest_collections(chunks, llm, existing)
            parsed_collections = suggested_collections

        # Default to ["other"] if nothing specified
        if not parsed_collections:
            parsed_collections = ["other"]

        # Add collections_csv to chunk metadata (pipe-delimited for informational use)
        collections_csv = "|".join(parsed_collections)
        for chunk in chunks:
            chunk.metadata["collections_csv"] = collections_csv

        vector_store.add_documents(chunks, doc_id=doc_id)

        # Register metadata
        await registry.add(
            doc_id=doc_id,
            filename=filename,
            file_type=suffix,
            chunk_count=len(chunks),
            collections=parsed_collections,
            user_id=current_user,
            file_hash=file_hash,
        )

        message = "Document uploaded and indexed successfully"
        if suggested_collections:
            message += f". AI suggested: {', '.join(suggested_collections)}"

        return UploadResponse(
            doc_id=doc_id,
            filename=filename,
            chunk_count=len(chunks),
            collections=parsed_collections,
            suggested_collections=suggested_collections,
            user_id=current_user,
            message=message,
        )
    except Exception as e:
        upload_path.unlink(missing_ok=True)
        logger.exception(f"Failed to process {filename}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    collection: str | None = None,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    user_filter = _get_user_filter(settings, current_user)
    if collection:
        docs = await registry.list_by_collection(collection, user_id=user_filter)
    else:
        docs = await registry.list_all(user_id=user_filter)
    return DocumentListResponse(
        documents=[DocumentInfo(**d) for d in docs],
        total=len(docs),
    )


@router.get("/collections", response_model=CollectionsResponse)
async def list_collections(
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    user_filter = _get_user_filter(settings, current_user)
    existing = await registry.get_all_collections(user_id=user_filter)
    return CollectionsResponse(
        taxonomy_categories=PRIMARY_CATEGORIES,
        existing_collections=existing,
    )


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    doc = await registry.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # User isolation check
    user_filter = _get_user_filter(settings, current_user)
    if user_filter and doc.get("user_id") != user_filter:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # Find the uploaded file on disk
    for f in settings.upload_dir.iterdir():
        if f.name.startswith(doc_id):
            return FileResponse(
                path=str(f),
                filename=doc["filename"],
                media_type="application/octet-stream",
            )

    raise HTTPException(status_code=404, detail="File not found on disk")


@router.patch("/{doc_id}", response_model=DocumentUpdateResponse)
async def update_document_collections(
    doc_id: str,
    request: DocumentUpdateRequest,
    vector_store: VectorStoreManager = Depends(get_vector_store),
    registry: DocumentRepository = Depends(get_registry),
):
    doc = await registry.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # Update registry
    await registry.update_collections(doc_id, request.collections)

    # Update vector store chunk metadata
    collections_csv = "|".join(request.collections)
    vector_store.update_document_metadata(doc_id, {"collections_csv": collections_csv})

    return DocumentUpdateResponse(
        doc_id=doc_id,
        collections=request.collections,
        message="Collections updated successfully",
    )


@router.post("/{doc_id}/reclassify", response_model=DocumentUpdateResponse)
async def reclassify_document(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    registry: DocumentRepository = Depends(get_registry),
):
    doc = await registry.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    # Get chunks for this document from vector store
    all_docs = vector_store.get_all_documents()
    doc_chunks = [d for d in all_docs if d.metadata.get("doc_id") == doc_id]

    if not doc_chunks:
        raise HTTPException(status_code=404, detail="No chunks found for this document")

    from app.services.collection_suggester import suggest_collections
    existing = await registry.get_all_collections()
    new_collections = suggest_collections(doc_chunks, llm, existing)

    # Update registry
    await registry.update_collections(doc_id, new_collections)

    # Update vector store chunk metadata
    collections_csv = "|".join(new_collections)
    vector_store.update_document_metadata(doc_id, {"collections_csv": collections_csv})

    return DocumentUpdateResponse(
        doc_id=doc_id,
        collections=new_collections,
        message=f"Document reclassified to: {', '.join(new_collections)}",
    )


@router.delete("/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    registry: DocumentRepository = Depends(get_registry),
):
    if not await registry.get(doc_id):
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    vector_store.delete_document(doc_id)
    await registry.remove(doc_id)

    # Remove uploaded file from disk
    for f in settings.upload_dir.iterdir():
        if f.name.startswith(doc_id):
            f.unlink(missing_ok=True)

    return DeleteResponse(doc_id=doc_id, message="Document deleted successfully")
