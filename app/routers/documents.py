import uuid
import hashlib
import logging
import re
import shutil
from pathlib import Path

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.classification import PRIMARY_CATEGORIES, TAXONOMY
from app.dependencies import (
    get_settings, get_vector_store, get_registry, get_llm, get_embeddings, get_current_user, get_db,
    get_summary_store, get_edge_repository,
)
from app.db.repositories import DocumentRepository
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from app.models.schemas import (
    UploadResponse,
    DocumentListResponse,
    DocumentInfo,
    DeleteResponse,
    DocumentUpdateRequest,
    DocumentUpdateResponse,
    TaxonomyResponse,
    SaveCollectionRequest,
    SaveCollectionResponse,
    ChunkDetail,
    ChunkListResponse,
    DocGraphResponse,
    MindmapTreeResponse,
    CorpusStatsResponse,
)
from app.services.document_processor import DocumentProcessor, SUPPORTED_EXTENSIONS
from app.services.mindmap import build_doc_graph, build_mindmap_tree
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
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    collections: str | None = Query(default=None, description="Comma-separated collection names"),
    auto_suggest: bool = True,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    embeddings: Embeddings = Depends(get_embeddings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    summary_store=Depends(get_summary_store),
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
        chunks = await processor.load_and_split(upload_path, doc_id=doc_id, llm=llm)

        # Parse user-curated collections from comma-separated form field
        parsed_collections: list[str] = []
        if collections:
            parsed_collections = [c.strip() for c in collections.split(",") if c.strip()]

        # Auto-classify into primary_category + subtags. The classifier never
        # invents new collections — it can only suggest existing user ones.
        primary_category: str | None = None
        subtags: list[str] = []
        suggested_collections: list[str] = []
        if auto_suggest:
            from app.services.collection_suggester import classify_document
            existing = await registry.get_all_collections()
            classification = classify_document(chunks, llm, existing, embeddings=embeddings)
            primary_category = classification.primary_category
            subtags = classification.subtags
            suggested_collections = classification.collection_suggestions

        # Bake user-curated collections into chunk metadata for retrieval filtering
        collections_csv = "|".join(parsed_collections)
        for chunk in chunks:
            chunk.metadata["collections_csv"] = collections_csv
            if primary_category:
                chunk.metadata["primary_category"] = primary_category

        vector_store.add_documents(chunks, doc_id=doc_id)
        from app.rag.chain import invalidate_bm25_cache
        invalidate_bm25_cache()

        # Build graph edges between chunks
        from app.services.edge_builder import build_intra_doc_edges, build_cross_doc_edges
        from app.db.repositories import EdgeRepository

        chunk_embeddings = {}
        try:
            texts = [c.page_content for c in chunks]
            emb_vectors = embeddings.embed_documents(texts)
            for i, chunk in enumerate(chunks):
                chunk_embeddings[chunk.metadata["chunk_index"]] = np.array(emb_vectors[i])
        except Exception as e:
            logger.warning("Failed to get embeddings for edge building: %s", e)

        intra_edges = build_intra_doc_edges(
            chunks, doc_id=doc_id,
            embeddings=chunk_embeddings if chunk_embeddings else None,
        )
        cross_edges = build_cross_doc_edges(
            doc_id, chunks, vector_store,
            top_k=5,
            min_score=settings.graph_similar_min_score,
        )

        edge_repo = EdgeRepository(db)
        await edge_repo.bulk_insert(intra_edges + cross_edges)

        # Enqueue background summary generation
        if settings.summary_enabled:
            from app.services.task_dispatcher import enqueue_summary_task
            await registry.update_status(doc_id, "summarizing")
            await enqueue_summary_task(
                doc_id, settings,
                background_tasks=background_tasks,
                vector_store=vector_store,
                summary_store=summary_store,
            )

        # Register metadata
        await registry.add(
            doc_id=doc_id,
            filename=filename,
            file_type=suffix,
            chunk_count=len(chunks),
            collections=parsed_collections,
            user_id=current_user,
            file_hash=file_hash,
            primary_category=primary_category,
            subtags=subtags,
        )

        message = "Document uploaded and indexed successfully"
        if primary_category:
            message += f". Classified as {primary_category}"

        return UploadResponse(
            doc_id=doc_id,
            filename=filename,
            chunk_count=len(chunks),
            primary_category=primary_category,
            subtags=subtags,
            collections=parsed_collections,
            suggested_collections=suggested_collections or None,
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


@router.get("/taxonomy", response_model=TaxonomyResponse)
async def get_taxonomy(
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    """Three-layer taxonomy:

    - ``primary_categories`` — fixed top-level types from ``data/taxonomy.json``.
    - ``domain_options`` — ``primary -> [domain, ...]`` for the Auto-Categorize UI.
    - ``user_collections`` — free-form, user-curated collection names from the DB.
    """
    user_filter = _get_user_filter(settings, current_user)
    user_collections = await registry.get_all_collections(user_id=user_filter)
    return TaxonomyResponse(
        primary_categories=PRIMARY_CATEGORIES,
        domain_options={cat: list(domains.keys()) for cat, domains in TAXONOMY.items()},
        user_collections=user_collections,
    )


@router.get("/stats", response_model=CorpusStatsResponse)
async def get_corpus_stats(
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    edge_repo=Depends(get_edge_repository),
    current_user: str = Depends(get_current_user),
):
    """Aggregate corpus stats for the chat empty state and similar surfaces.

    Returns total documents, total chunks (summed across docs), distinct
    collections in use, and total chunk_edges rows. Edge count is corpus-wide
    (no per-user scoping yet — chunk_edges has no user_id column).
    """
    user_filter = _get_user_filter(settings, current_user)
    docs = await registry.list_all(user_id=user_filter)
    collections = await registry.get_all_collections(user_id=user_filter)
    edges = await edge_repo.count_all()
    return CorpusStatsResponse(
        chunks=sum(d.get("chunk_count", 0) or 0 for d in docs),
        collections=len(collections),
        edges=edges,
        documents=len(docs),
    )


@router.post("/collections/save", response_model=SaveCollectionResponse)
async def save_collection(
    request: SaveCollectionRequest,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    """Save a selection as a named collection — atomic add of doc_ids to collection.

    If the collection already has docs, behavior depends on `mode`:
      - mode="new": return 409 so the frontend can prompt for rename OR merge.
      - mode="merge": add non-duplicate doc_ids to the existing collection.
    """
    # Normalize name (lowercase, hyphen-separated, matches classifier convention)
    name = request.name.strip().lower().replace(" ", "-")
    if not re.match(r"^[a-z0-9_-]+$", name):
        raise HTTPException(
            status_code=400,
            detail="Collection name must contain only letters, numbers, hyphens, underscores",
        )

    user_filter = _get_user_filter(settings, current_user)

    # Check if collection already has docs (user-scoped)
    existing_docs = await registry.list_by_collection(name, user_id=user_filter)

    if existing_docs and request.mode == "new":
        raise HTTPException(
            status_code=409,
            detail=f"Collection '{name}' already exists with {len(existing_docs)} documents. "
                   f"Pick a different name or retry with mode='merge'.",
        )

    added, skipped = await registry.add_docs_to_collection(
        collection=name,
        doc_ids=request.doc_ids,
        user_id=user_filter,
    )

    total = len(existing_docs) + added  # existing + newly added

    return SaveCollectionResponse(
        name=name,
        added=added,
        already_in_collection=skipped,
        total_docs_in_collection=total,
    )


@router.get("/images/{doc_id}/{filename}")
async def get_document_image(
    doc_id: str,
    filename: str,
    settings: Settings = Depends(get_settings),
    current_user: str = Depends(get_current_user),
):
    """Serve stored images extracted from documents."""
    # Sanitize both doc_id and filename to prevent path traversal
    for param_name, param_val in [("doc_id", doc_id), ("filename", filename)]:
        if ".." in param_val or "/" in param_val or "\\" in param_val:
            raise HTTPException(status_code=400, detail=f"Invalid {param_name}")
    # Resolve and verify path stays within upload directory
    image_path = (settings.upload_dir / doc_id / "images" / filename).resolve()
    upload_root = settings.upload_dir.resolve()
    if not str(image_path).startswith(str(upload_root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    # Determine media type from extension
    ext = image_path.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
    media_type = media_types.get(ext, "image/png")
    return FileResponse(path=str(image_path), media_type=media_type)


@router.get("/{doc_id}/page-highlight")
async def get_page_highlight(
    doc_id: str,
    page: int = Query(..., ge=0),
    bbox: str | None = Query(None, description="x0,y0,x1,y1"),
    text: str | None = Query(None, max_length=2000, description="Chunk text to search for and highlight"),
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    """Render a PDF page with highlighted region (bbox → red rect, text → yellow highlight)."""
    import fitz

    # Sanitize doc_id
    if ".." in doc_id or "/" in doc_id or "\\" in doc_id:
        raise HTTPException(status_code=400, detail="Invalid doc_id")

    # Ownership check
    doc_record = await registry.get(doc_id)
    if not doc_record:
        raise HTTPException(status_code=404, detail="Document not found")
    user_filter = _get_user_filter(settings, current_user)
    if user_filter and doc_record.get("user_id") != user_filter:
        raise HTTPException(status_code=404, detail="Document not found")

    # Parse bbox if provided
    coords = None
    if bbox:
        if not re.match(r'^[\d.,\s-]+$', bbox):
            raise HTTPException(status_code=400, detail="Invalid bbox format")
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) != 4:
                raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="bbox must be x0,y0,x1,y1")

    # Find the PDF file on disk
    pdf_path = None
    for f in settings.upload_dir.iterdir():
        if f.name.startswith(doc_id) and f.suffix.lower() == ".pdf" and f.is_file():
            pdf_path = f
            break

    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF not found for this document")

    try:
        doc = fitz.open(str(pdf_path))
        try:
            if page >= len(doc):
                raise HTTPException(status_code=400, detail=f"Page {page} out of range (max {len(doc) - 1})")

            pg = doc[page]

            if coords:
                # Draw red rectangle for bbox (tables/images)
                shape = pg.new_shape()
                shape.draw_rect(fitz.Rect(*coords))
                shape.finish(color=(1, 0, 0), width=2.5)
                shape.commit()
            elif text:
                # Text search: split into fragments and highlight matches
                _highlight_text_on_page(pg, text)

            # Render to PNG
            pixmap = pg.get_pixmap(dpi=150)
            png_bytes = pixmap.tobytes("png")
        finally:
            doc.close()

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Page highlight failed for {doc_id} page {page}")
        raise HTTPException(status_code=500, detail=f"Failed to render page: {str(e)}")


def _split_into_fragments(text: str, target_len: int = 60) -> list[str]:
    """Split text into fragments of roughly target_len characters at word boundaries."""
    words = text.split()
    fragments = []
    current = ""
    for w in words:
        candidate = f"{current} {w}" if current else w
        if len(candidate) >= target_len and current:
            fragments.append(current)
            current = w
        else:
            current = candidate
    if current:
        fragments.append(current)
    return fragments


def _highlight_text_on_page(pg, text: str) -> None:
    """Search for text fragments on a PDF page and add yellow highlight annotations."""
    # Clean up the text: collapse whitespace
    clean = " ".join(text.split())
    if not clean:
        return

    # Try progressively smaller fragments for better match coverage
    # Each size is tried fresh — smaller fragments match more flexibly
    all_rects = []
    for frag_size in (80, 50, 30):
        all_rects.clear()
        for frag in _split_into_fragments(clean, frag_size):
            rects = pg.search_for(frag, quads=False)
            all_rects.extend(rects)
        if len(all_rects) >= 2:
            break

    # If fragment search found nothing, try individual sentences
    if not all_rects:
        for line in clean.split(". "):
            line = line.strip()
            if len(line) > 15:
                rects = pg.search_for(line[:100], quads=False)
                all_rects.extend(rects)

    # Add yellow semi-transparent highlight annotations
    for rect in all_rects:
        annot = pg.add_highlight_annot(rect)
        annot.set_colors(stroke=(1, 0.9, 0))  # yellow
        annot.set_opacity(0.4)
        annot.update()


@router.get("/{doc_id}/pdf")
async def get_document_pdf(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    """Serve original PDF for in-browser viewing (PDF.js)."""
    doc = await registry.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    user_filter = _get_user_filter(settings, current_user)
    if user_filter and doc.get("user_id") != user_filter:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    for f in settings.upload_dir.iterdir():
        if f.name.startswith(doc_id) and f.suffix.lower() == ".pdf" and f.is_file():
            return FileResponse(
                path=str(f),
                media_type="application/pdf",
                headers={
                    "Cache-Control": "private, max-age=86400",
                    "Content-Disposition": "inline",
                    "Access-Control-Expose-Headers": "Content-Length",
                },
            )

    raise HTTPException(status_code=404, detail="PDF file not found on disk")


@router.get("/{doc_id}/info")
async def get_document_info(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    """Return document metadata including total page count."""
    doc = await registry.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    user_filter = _get_user_filter(settings, current_user)
    if user_filter and doc.get("user_id") != user_filter:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    total_pages = None
    for f in settings.upload_dir.iterdir():
        if f.name.startswith(doc_id) and f.suffix.lower() == ".pdf" and f.is_file():
            try:
                import fitz
                pdf = fitz.open(str(f))
                total_pages = pdf.page_count
                pdf.close()
            except Exception:
                pass
            break

    return {
        "doc_id": doc_id,
        "filename": doc.get("filename", ""),
        "total_pages": total_pages,
    }


@router.get("/{doc_id}/status")
async def get_document_status(
    doc_id: str,
    registry: DocumentRepository = Depends(get_registry),
    current_user: str = Depends(get_current_user),
):
    """Return processing status and summary availability for a document."""
    doc = await registry.get_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "doc_id": doc_id,
        "status": doc.get("status", "ready"),
        "has_summary": doc.get("summary") is not None,
    }


@router.get("/{doc_id}/chunks", response_model=ChunkListResponse)
async def get_document_chunks(
    doc_id: str,
    page: int | None = None,
    vector_store: VectorStoreManager = Depends(get_vector_store),
    current_user: str = Depends(get_current_user),
):
    """Get chunks for a document, optionally filtered by page."""
    chunks = vector_store.get_chunks_by_doc(doc_id)

    result = []
    for chunk in chunks:
        m = chunk.metadata
        if page is not None and m.get("page") != page:
            continue

        bbox_raw = m.get("bbox")
        bbox = None
        if bbox_raw:
            import json as json_mod
            try:
                bbox = json_mod.loads(bbox_raw) if isinstance(bbox_raw, str) else bbox_raw
            except (json_mod.JSONDecodeError, ValueError):
                pass

        result.append(ChunkDetail(
            doc_id=doc_id,
            chunk_index=m.get("chunk_index", 0),
            chunk_type=m.get("chunk_type"),
            label=m.get("label"),
            page=m.get("page"),
            content=chunk.page_content,
            source_file=m.get("source_file", ""),
            bbox=bbox,
        ))

    return ChunkListResponse(chunks=result, total=len(result))


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
        if f.is_file() and f.name.startswith(doc_id + "_"):
            return FileResponse(
                path=str(f),
                filename=doc["filename"],
                media_type="application/octet-stream",
            )

    raise HTTPException(status_code=404, detail="File not found on disk")


@router.get(
    "/{doc_id}/graph",
    response_model=DocGraphResponse,
)
async def get_document_graph(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    edge_repo = Depends(get_edge_repository),
    current_user: str = Depends(get_current_user),
) -> DocGraphResponse:
    """Return the doc-graph data (nodes + edges + stats) for one doc.
    Chunks become graph nodes; chunk_edges rows become graph edges.
    For a hierarchical mind map, see the /mindmap endpoint.
    """
    doc = await registry.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if (
        settings.user_isolation != "none"
        and doc.get("user_id") != current_user
    ):
        raise HTTPException(
            status_code=403, detail="Not authorized for this document",
        )

    return await build_doc_graph(doc_id, doc, vector_store, edge_repo)


@router.get(
    "/{doc_id}/mindmap",
    response_model=MindmapTreeResponse,
)
async def get_document_mindmap_tree(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    current_user: str = Depends(get_current_user),
) -> MindmapTreeResponse:
    """Return the hierarchical mind map (tree) for one doc.

    LLM-derived concept hierarchy, cached per-doc to disk. For the
    force-graph view of the same doc, see /documents/{id}/graph.
    """
    doc = await registry.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if (
        settings.user_isolation != "none"
        and doc.get("user_id") != current_user
    ):
        raise HTTPException(
            status_code=403, detail="Not authorized for this document",
        )

    return await build_mindmap_tree(doc_id, doc, vector_store, llm)


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

    # Distinguish "field omitted" from "field explicitly set to null" via
    # Pydantic's model_fields_set. An explicit null clears primary_category;
    # an omitted field leaves the existing value untouched.
    fields_set = request.model_fields_set

    if "primary_category" in fields_set or "subtags" in fields_set:
        new_primary = (
            request.primary_category
            if "primary_category" in fields_set
            else doc.get("primary_category")
        )
        new_subtags = (
            list(request.subtags or [])
            if "subtags" in fields_set
            else list(doc.get("subtags") or [])
        )
        await registry.update_classification(doc_id, new_primary, new_subtags)
        # Mirror primary_category onto chunk metadata for retrieval-time filtering
        if new_primary:
            vector_store.update_document_metadata(doc_id, {"primary_category": new_primary})

    if "collections" in fields_set:
        new_collections = list(request.collections or [])
        await registry.update_collections(doc_id, new_collections)
        vector_store.update_document_metadata(doc_id, {"collections_csv": "|".join(new_collections)})

    # Re-read so the response reflects every applied change
    updated = await registry.get(doc_id)
    return DocumentUpdateResponse(
        doc_id=doc_id,
        primary_category=updated.get("primary_category"),
        subtags=list(updated.get("subtags") or []),
        collections=list(updated.get("collections") or []),
        message="Document updated successfully",
    )


@router.post("/{doc_id}/reclassify", response_model=DocumentUpdateResponse)
async def reclassify_document(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    embeddings: Embeddings = Depends(get_embeddings),
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

    from app.services.collection_suggester import classify_document
    existing = await registry.get_all_collections()
    classification = classify_document(doc_chunks, llm, existing, embeddings=embeddings)

    await registry.update_classification(
        doc_id,
        classification.primary_category,
        classification.subtags,
    )

    # Update vector store chunk metadata so retrieval can filter by primary_category
    metadata: dict = {}
    if classification.primary_category:
        metadata["primary_category"] = classification.primary_category
    if metadata:
        vector_store.update_document_metadata(doc_id, metadata)

    return DocumentUpdateResponse(
        doc_id=doc_id,
        primary_category=classification.primary_category,
        subtags=classification.subtags,
        collections=doc.get("collections", []),
        message=(
            f"Reclassified to {classification.primary_category}"
            if classification.primary_category
            else "Reclassified (uncategorized)"
        ),
    )


@router.delete("/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    registry: DocumentRepository = Depends(get_registry),
    db: AsyncSession = Depends(get_db),
    summary_store=Depends(get_summary_store),
):
    if not await registry.get(doc_id):
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    try:
        vector_store.delete_document(doc_id)
        from app.rag.chain import invalidate_bm25_cache
        invalidate_bm25_cache()
    except Exception as e:
        logger.warning(f"Vector store delete failed for {doc_id} (continuing): {e}")

    if summary_store:
        try:
            summary_store.delete_document(doc_id)
        except Exception:
            pass

    # Remove all edges involving this document
    from app.db.repositories import EdgeRepository
    edge_repo = EdgeRepository(db)
    await edge_repo.delete_by_doc(doc_id)

    await registry.remove(doc_id)

    # Remove uploaded file/directory from disk
    for f in settings.upload_dir.iterdir():
        if f.name.startswith(doc_id):
            try:
                if f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
                else:
                    f.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Failed to remove {f}: {e}")

    # Invalidate cached mindmap tree so a future upload with the same
    # doc_id won't serve stale concept structure from a deleted doc.
    from app.services.mindmap import MINDMAPS_CACHE_DIR
    mindmap_cache = MINDMAPS_CACHE_DIR / f"{doc_id}.json"
    if mindmap_cache.exists():
        try:
            mindmap_cache.unlink()
        except Exception as e:
            logger.warning(f"Failed to remove mindmap cache for {doc_id}: {e}")

    return DeleteResponse(doc_id=doc_id, message="Document deleted successfully")
