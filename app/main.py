import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db.models import Base
from app.db.session import create_engine_and_session
from app.db.repositories import UserRepository
from app.llm.provider import create_chat_model, create_embeddings
from app.vectorstore.factory import create_vector_store_manager
from app.vectorstore.faiss_store import FAISSStoreManager

logger = logging.getLogger("meinrag")


def setup_logging(log_level: str = "info") -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared resources on startup."""
    settings = get_settings()
    setup_logging(settings.log_level)

    # Ensure directories exist (for uploaded files and vectorstore)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.vectorstore_dir.mkdir(parents=True, exist_ok=True)
    (settings.vectorstore_dir.parent / "vectorstore_summary").mkdir(parents=True, exist_ok=True)

    # Database setup
    engine, session_factory = create_engine_and_session(
        settings.database_url,
        echo=(settings.log_level == "debug"),
    )

    # Auto-create tables for fresh installs
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Ensure default user exists
    async with session_factory() as session:
        user_repo = UserRepository(session)
        if not await user_repo.exists(settings.default_user):
            await user_repo.add(settings.default_user, settings.default_user.capitalize())
        await session.commit()

    # Initialize non-DB components
    embeddings = create_embeddings(settings)
    vector_store = create_vector_store_manager(settings)
    vector_store.initialize(embeddings)
    llm = create_chat_model(settings)

    # Summary vector store (dual-index for compiled layer)
    from pathlib import Path
    summary_store = FAISSStoreManager(Path(settings.vectorstore_dir) / ".." / "vectorstore_summary")
    summary_store.initialize(embeddings)

    # Store in app.state for dependency injection
    app.state.settings = settings
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    app.state.vector_store = vector_store
    app.state.summary_store = summary_store
    app.state.llm = llm
    app.state.embeddings = embeddings

    # ─── Anonymization plugin (optional, default off) ─────────────
    if settings.anonymization_enabled:
        # Key presence is enforced by Settings._validate_anonymization_key
        # (see app/config.py). Reaching here guarantees the key is set —
        # MappingCrypto's job here is to catch *malformed* keys (e.g.,
        # right length but bad base64) via the verify() round-trip.
        from app.anonymization import AnonymizationEngine, MappingCrypto, EncryptionError

        try:
            mapping_crypto = MappingCrypto(settings.anonymization_encryption_key)
            if not mapping_crypto.verify():
                raise EncryptionError(
                    "MappingCrypto.verify() self-test failed — key may be truncated or corrupted."
                )
        except EncryptionError as e:
            raise RuntimeError(f"Anonymization encryption setup failed: {e}") from e

        app.state.mapping_crypto = mapping_crypto
        # AnonymizationEngine.__init__ is intentionally trivial — no heavy
        # imports, no IO. Presidio + spaCy load lazily on first call.
        app.state.anonymization_engine = AnonymizationEngine(settings)
        logger.info(
            "Anonymization plugin loaded | languages=%s | confidence>=%.2f",
            settings.anonymization_languages, settings.anonymization_confidence_threshold,
        )
    else:
        app.state.mapping_crypto = None
        app.state.anonymization_engine = None

        # Flag is off — but if there are anonymized docs from a previous
        # session, surfacing [PERSON_N] in chat answers is a bad UX.
        # Warn loudly so the operator notices.
        from sqlalchemy import select, func
        from app.db.models import AnonymizationMappingModel

        async with session_factory() as s:
            count = (await s.execute(
                select(func.count()).select_from(AnonymizationMappingModel)
            )).scalar_one()
        if count > 0:
            logger.warning(
                "ANONYMIZATION_ENABLED=false but %d row(s) in "
                "anonymization_mappings exist — chat answers for those "
                "documents will display [PERSON_N] placeholders. "
                "Use scripts/reanonymize_doc.py --disable <doc_id> to revert.",
                count,
            )

    logger.info(
        f"MEINRAG started | LLM={settings.llm_provider.value} "
        f"| VectorStore={settings.vector_store.value} "
        f"| DB={'SQLite' if 'sqlite' in settings.database_url else 'PostgreSQL'} "
        f"| Isolation={settings.user_isolation}"
    )
    yield
    # Cleanup
    vector_store.persist()
    await engine.dispose()
    logger.info("MEINRAG shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="MEINRAG",
        description="RAG backend API — upload documents and ask questions",
        version="0.3.0",
        lifespan=lifespan,
    )

    # Parse CORS origins from env (comma-separated)
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled error on {request.method} {request.url.path}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Check server logs."},
        )

    from app.routers import documents, query, health, users, sessions, graph
    app.include_router(health.router, tags=["Health"])
    app.include_router(users.router, prefix="/users", tags=["Users"])
    app.include_router(documents.router, prefix="/documents", tags=["Documents"])
    app.include_router(query.router, tags=["Query"])
    app.include_router(sessions.router, tags=["Sessions"])
    app.include_router(graph.router)

    return app


app = create_app()
