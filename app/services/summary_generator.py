"""Generate chunk and document summaries via LLM (OpenRouter or OpenAI)."""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

CHUNK_SUMMARY_PROMPT = (
    "Summarize this text in one concise sentence. "
    "Focus on key facts, numbers, and conclusions. "
    "Return ONLY the summary sentence, nothing else."
)

DOC_SUMMARY_PROMPT = (
    "Based on these section summaries from a document, write a 2-3 sentence "
    "overview of the entire document. Include title if mentioned, key findings, "
    "and main contribution. Return ONLY the summary."
)


async def _call_openrouter(content: str, system_prompt: str, model: str, api_key: str) -> str | None:
    """Call OpenRouter API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content[:2000]},
                    ],
                    "max_tokens": 150,
                },
            )
            if resp.status_code != 200:
                logger.warning("OpenRouter %d: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning("OpenRouter call failed: %s", e)
        return None


async def _call_openai_llm(content: str, system_prompt: str, llm) -> str | None:
    """Call OpenAI-compatible LLM via LangChain."""
    try:
        from langchain_core.prompts import ChatPromptTemplate
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{content}"),
        ])
        messages = prompt.format_messages(content=content[:2000])
        response = await llm.ainvoke(messages)
        return (response.content if hasattr(response, "content") else str(response)).strip()
    except Exception as e:
        logger.warning("LLM summary failed: %s", e)
        return None


async def generate_chunk_summary(content: str, settings, llm=None) -> str | None:
    """Generate a one-line summary for a chunk."""
    if not content or len(content) < settings.summary_min_chars:
        return None
    if settings.summary_provider == "openrouter" and settings.openrouter_api_key:
        return await _call_openrouter(
            content, CHUNK_SUMMARY_PROMPT,
            settings.summary_model, settings.openrouter_api_key,
        )
    elif llm:
        return await _call_openai_llm(content, CHUNK_SUMMARY_PROMPT, llm)
    return None


async def generate_doc_summary(section_summaries: dict, settings, llm=None) -> str | None:
    """Generate a document-level summary from section summaries."""
    if not section_summaries:
        return None
    combined = "\n".join(f"{k}: {v}" for k, v in section_summaries.items())
    if settings.summary_provider == "openrouter" and settings.openrouter_api_key:
        return await _call_openrouter(
            combined, DOC_SUMMARY_PROMPT,
            settings.summary_model, settings.openrouter_api_key,
        )
    elif llm:
        return await _call_openai_llm(combined, DOC_SUMMARY_PROMPT, llm)
    return None


async def generate_all_summaries(doc_id: str, settings, vector_store=None, summary_store=None) -> None:
    """Orchestrator: generate chunk + doc summaries for a document.

    This is a standalone async function — can be called from BackgroundTasks
    or ARQ worker without changes.
    """
    if not vector_store:
        logger.warning("No vector store provided for summary generation")
        return

    # Create LLM instance for openai provider (BackgroundTasks can't receive Depends objects)
    llm = None
    if settings.summary_provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=settings.openai_model,
                api_key=settings.openai_api_key,
            )
        except Exception as e:
            logger.warning("Failed to create OpenAI LLM for summaries: %s", e)

    chunks = vector_store.get_chunks_by_doc(doc_id)
    if not chunks:
        logger.warning("No chunks found for doc %s", doc_id)
        return

    logger.info("Generating summaries for %s (%d chunks)", doc_id, len(chunks))

    # Generate chunk summaries in batches of 10
    eligible = [c for c in chunks
                if c.metadata.get("chunk_type") in ("text", "table")
                and len(c.page_content) >= settings.summary_min_chars]

    batch_size = 10
    generated = 0
    for i in range(0, len(eligible), batch_size):
        batch = eligible[i:i + batch_size]
        results = await asyncio.gather(
            *[generate_chunk_summary(c.page_content, settings, llm=llm) for c in batch],
            return_exceptions=True,
        )
        for chunk, result in zip(batch, results):
            if isinstance(result, str) and result:
                chunk.metadata["summary"] = result
                generated += 1
            elif isinstance(result, Exception):
                logger.warning("Summary failed for chunk %s: %s",
                               chunk.metadata.get("chunk_index"), result)

    logger.info("Generated %d/%d chunk summaries for %s", generated, len(eligible), doc_id)

    # Update FAISS docstore with summaries if using FAISS
    if generated > 0:
        try:
            store = getattr(vector_store, "_store", None)
            docstore = getattr(store, "docstore", None) if store else None
            dict_ = getattr(docstore, "_dict", None) if docstore else None
            if dict_ is not None:
                for store_id, doc in dict_.items():
                    if doc.metadata.get("doc_id") == doc_id:
                        for chunk in chunks:
                            if (chunk.metadata.get("chunk_index") == doc.metadata.get("chunk_index")
                                    and chunk.metadata.get("summary")):
                                doc.metadata["summary"] = chunk.metadata["summary"]
                                break
                vector_store.persist()
        except Exception as e:
            logger.warning("Failed to persist summaries to vector store: %s", e)

    # Add summaries to summary FAISS store for dual-index search
    if summary_store and generated > 0:
        from langchain_core.documents import Document as LCDocument
        summary_docs = []
        for chunk in chunks:
            if chunk.metadata.get("summary"):
                summary_docs.append(LCDocument(
                    page_content=chunk.metadata["summary"],
                    metadata=chunk.metadata,
                ))
        if summary_docs:
            try:
                summary_store.add_documents(summary_docs, doc_id=doc_id)
                logger.info("Added %d summary embeddings for %s", len(summary_docs), doc_id)
            except Exception as e:
                logger.warning("Failed to add summary embeddings: %s", e)

    # Generate document-level summary from section summaries
    section_sums = {}
    for chunk in chunks:
        st = chunk.metadata.get("section_type", "body")
        if chunk.metadata.get("summary") and st not in section_sums:
            section_sums[st] = chunk.metadata["summary"]

    doc_summary = await generate_doc_summary(section_sums, settings, llm=llm)

    # Update document status and summary in DB using a self-contained session
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import update
    from app.db.models import DocumentModel

    for attempt in range(5):
        try:
            engine = create_async_engine(
                settings.database_url,
                connect_args={"timeout": 30},  # wait up to 30s for SQLite lock
            )
            session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with session_factory() as session:
                await session.execute(
                    update(DocumentModel)
                    .where(DocumentModel.doc_id == doc_id)
                    .values(
                        status="ready",
                        summary=doc_summary,
                    )
                )
                await session.commit()
            await engine.dispose()
            logger.info("Document %s summary saved: %s", doc_id, (doc_summary or "")[:80])
            break
        except Exception as e:
            if attempt < 4 and "locked" in str(e).lower():
                logger.warning("DB locked, retry %d/5 for %s", attempt + 1, doc_id)
                await asyncio.sleep(5)
                continue
        logger.error("Failed to update document %s summary in DB: %s", doc_id, e)

    logger.info("Summary generation complete for %s", doc_id)
