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

# Contextual variant: the document opening rides in the SYSTEM message, identical for every
# chunk of one document, so a provider that caches prompt prefixes bills it once. The chunk
# is the user message. Two wordings, chosen by the chunk's script: the Chinese one is the
# wording measured in the 2026-09-06 spike on a Chinese statute corpus.
CHUNK_SUMMARY_PROMPT_CONTEXTUAL_EN = (
    "Below is the opening of a document, for orientation. The user will give one passage "
    "from it. In ONE sentence, state where the passage sits in the document and what it says: "
    "name the document (title or number), the article or section it belongs to, and its key "
    "facts, numbers and conclusions. Output only that sentence.\n\nDocument opening:\n{head}"
)
CHUNK_SUMMARY_PROMPT_CONTEXTUAL_ZH = (
    "下面是一份文件的开头(用于定位)。之后用户会给出这份文件中的一段。"
    "用一句话说明这一段在整份文件中的位置和内容:它属于哪部文件(写出文件名称或文号)、"
    "是哪一条或哪一部分、讲了什么,含关键事实、数字和结论。只输出这一句,不要解释。\n\n文件开头:\n{head}"
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


def _cjk_share(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff") / len(text)


def chunk_summary_prompt(content: str, settings, doc_head: str | None) -> str:
    """The system prompt for one chunk: contextual when enabled and a head is available."""
    if doc_head and getattr(settings, "summary_contextual", False):
        template = CHUNK_SUMMARY_PROMPT_CONTEXTUAL_ZH if _cjk_share(content) >= 0.3 else CHUNK_SUMMARY_PROMPT_CONTEXTUAL_EN
        return template.format(head=doc_head)
    return CHUNK_SUMMARY_PROMPT


def build_doc_head(chunks, max_chars: int) -> str:
    """The document opening used as context: file name, then the first chunks in order
    until at least 300 characters are collected, capped at ``max_chars``."""
    ordered = sorted(chunks, key=lambda c: c.metadata.get("chunk_index", 0))
    name = ""
    for c in ordered:
        if c.metadata.get("source_file"):
            name = str(c.metadata["source_file"])
            break
    body = ""
    for c in ordered:
        body += (c.page_content or "") + "\n"
        if len(body) >= 300:
            break
    head = (name + "\n" + body) if name else body
    return head[:max_chars]


async def generate_chunk_summary(content: str, settings, llm=None, doc_head: str | None = None) -> str | None:
    """Generate a one-line summary for a chunk (contextual when ``doc_head`` is given and
    ``settings.summary_contextual`` is on)."""
    if not content or len(content) < settings.summary_min_chars:
        return None
    system_prompt = chunk_summary_prompt(content, settings, doc_head)
    if settings.summary_provider == "openrouter" and settings.openrouter_api_key:
        return await _call_openrouter(
            content, system_prompt,
            settings.summary_model, settings.openrouter_api_key,
        )
    elif llm:
        return await _call_openai_llm(content, system_prompt, llm)
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


async def generate_all_summaries(doc_id: str, settings, vector_store=None, summary_store=None,
                                 persist: bool = True) -> None:
    """Orchestrator: generate chunk + doc summaries for a document.

    This is a standalone async function — can be called from BackgroundTasks
    or ARQ worker without changes. ``persist=False`` lets a bulk backfill write the
    FAISS files once per batch instead of once per document.
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

    doc_head = None
    if getattr(settings, "summary_contextual", False):
        doc_head = build_doc_head(chunks, getattr(settings, "summary_context_head_chars", 1200))

    batch_size = 10
    generated = 0
    for i in range(0, len(eligible), batch_size):
        batch = eligible[i:i + batch_size]
        results = await asyncio.gather(
            *[generate_chunk_summary(c.page_content, settings, llm=llm, doc_head=doc_head) for c in batch],
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
                if persist:
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
                if persist:
                    summary_store.add_documents(summary_docs, doc_id=doc_id)
                else:
                    summary_store.add_documents(summary_docs, doc_id=doc_id, persist=False)
                logger.info("Added %d summary embeddings for %s", len(summary_docs), doc_id)
            except Exception as e:
                logger.warning("Failed to add summary embeddings: %s", e)

    # Generate document-level summary from ALL chunk summaries (capped for
    # prompt size). Previous logic grouped by section_type and kept only the
    # first summary per section — which collapsed to a single "body" entry
    # whenever docling didn't populate section_type (which is most of the time
    # on current corpora), making the doc-level overview useless.
    #
    # Stride-sample evenly across the document instead of head-only [:N], so
    # the overview covers intro + body + conclusion for long docs (books,
    # reports) rather than just the first N chunks.
    all_chunk_summaries = [
        c.metadata["summary"] for c in chunks if c.metadata.get("summary")
    ]
    cap = settings.summary_max_chunks_for_overview
    if len(all_chunk_summaries) <= cap:
        sampled = all_chunk_summaries
    else:
        stride = len(all_chunk_summaries) / cap
        sampled = [all_chunk_summaries[int(i * stride)] for i in range(cap)]
    section_sums = {f"part_{i}": s for i, s in enumerate(sampled)}

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
