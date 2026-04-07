"""Configurable background task dispatcher.

Supports two backends:
- "background": FastAPI BackgroundTasks (default, no extra deps)
- "arq": ARQ + Redis (persistent, retries, monitoring)

Switch via TASK_BACKEND env var. Task functions are identical for both.
"""
import logging

logger = logging.getLogger(__name__)


async def enqueue_summary_task(
    doc_id: str,
    settings,
    background_tasks=None,
    vector_store=None,
    summary_store=None,
):
    """Dispatch summary generation to the configured backend."""
    if settings.task_backend == "arq":
        try:
            from arq import create_pool
            from arq.connections import RedisSettings
            redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            await redis.enqueue_job("generate_summaries_task", doc_id)
            logger.info("Summary task enqueued via ARQ for %s", doc_id)
            return
        except Exception as e:
            logger.warning("ARQ enqueue failed, falling back to BackgroundTasks: %s", e)

    # Fallback: FastAPI BackgroundTasks
    if background_tasks is not None:
        from app.services.summary_generator import generate_all_summaries
        background_tasks.add_task(
            generate_all_summaries,
            doc_id, settings,
            vector_store=vector_store,
            summary_store=summary_store,
        )
        logger.info("Summary task enqueued via BackgroundTasks for %s", doc_id)
    else:
        logger.warning("No task backend available for summary generation of %s", doc_id)
