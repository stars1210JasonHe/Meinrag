"""Configurable background task dispatcher.

Supports two backends:
- "background": FastAPI BackgroundTasks (default, no extra deps)
- "arq": ARQ + Redis (persistent, retries, monitoring)

Switch via TASK_BACKEND env var. Task functions are identical for both.
"""
import logging

logger = logging.getLogger(__name__)

# doc_ids whose summary task runs with defer_persist=True and has not finished yet. POST /documents/persist
# refuses (409) while this is non-empty: a flush taken now would miss the summaries those tasks add afterwards.
# In-process only, which is exactly the scope of the stores it protects (BackgroundTasks share them).
_DEFERRED_PENDING: set[str] = set()


def deferred_pending() -> list[str]:
    return sorted(_DEFERRED_PENDING)


async def _run_deferred(doc_id, settings, vector_store, summary_store):
    from app.services.summary_generator import generate_all_summaries
    try:
        await generate_all_summaries(doc_id, settings, vector_store=vector_store, summary_store=summary_store,
                                     defer_persist=True)
    finally:
        _DEFERRED_PENDING.discard(doc_id)


async def enqueue_summary_task(
    doc_id: str,
    settings,
    background_tasks=None,
    vector_store=None,
    summary_store=None,
    defer_persist: bool = False,
):
    """Dispatch summary generation to the configured backend.

    defer_persist=True only takes effect on the "background" backend, where the task shares this process's
    stores. An ARQ worker is a separate process with its own stores and persists as before."""
    if settings.task_backend == "arq":
        try:
            from arq import create_pool
            from arq.connections import RedisSettings
            redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            await redis.enqueue_job("generate_summaries_task", doc_id)
            if defer_persist:
                logger.warning("defer_persist ignored for %s: the ARQ worker persists its own stores", doc_id)
            logger.info("Summary task enqueued via ARQ for %s", doc_id)
            return
        except Exception as e:
            logger.warning("ARQ enqueue failed, falling back to BackgroundTasks: %s", e)

    # Fallback: FastAPI BackgroundTasks
    if background_tasks is not None:
        if defer_persist:
            _DEFERRED_PENDING.add(doc_id)
            background_tasks.add_task(_run_deferred, doc_id, settings, vector_store, summary_store)
            logger.info("Summary task enqueued via BackgroundTasks for %s (persist deferred)", doc_id)
            return
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
