"""ARQ background worker for async tasks.

Run with: uv run arq app.worker.WorkerSettings
"""
import logging

from arq.connections import RedisSettings

from app.config import Settings

logger = logging.getLogger(__name__)
settings = Settings()


async def generate_summaries_task(ctx, doc_id: str):
    """Background task: generate chunk + document summaries."""
    from app.services.summary_generator import generate_all_summaries
    from app.vectorstore.faiss_store import FAISSStoreManager
    from langchain_openai import OpenAIEmbeddings
    from pathlib import Path

    # Initialize vector stores (worker runs in separate process)
    embeddings = OpenAIEmbeddings(model=settings.openai_embedding_model)

    vector_store = FAISSStoreManager(Path(settings.vectorstore_dir))
    vector_store.initialize(embeddings)

    summary_store = FAISSStoreManager(Path(settings.vectorstore_dir) / ".." / "vectorstore_summary")
    summary_store.initialize(embeddings)

    logger.info("ARQ: starting summary generation for %s", doc_id)
    await generate_all_summaries(doc_id, settings, vector_store=vector_store, summary_store=summary_store)
    logger.info("ARQ: summary generation complete for %s", doc_id)


async def startup(ctx):
    logger.info("ARQ worker started")


async def shutdown(ctx):
    logger.info("ARQ worker stopped")


class WorkerSettings:
    functions = [generate_summaries_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 5
    job_timeout = 300
