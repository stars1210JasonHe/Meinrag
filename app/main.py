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

    # Store in app.state for dependency injection
    app.state.settings = settings
    app.state.db_engine = engine
    app.state.db_session_factory = session_factory
    app.state.vector_store = vector_store
    app.state.llm = llm
    app.state.embeddings = embeddings

    logger.info(
        f"MEINRAG started | LLM={settings.llm_provider.value} "
        f"| VectorStore={settings.vector_store.value} "
        f"| DB=PostgreSQL "
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

    from app.routers import documents, query, health, users
    app.include_router(health.router, tags=["Health"])
    app.include_router(users.router, prefix="/users", tags=["Users"])
    app.include_router(documents.router, prefix="/documents", tags=["Documents"])
    app.include_router(query.router, tags=["Query"])

    return app


app = create_app()
