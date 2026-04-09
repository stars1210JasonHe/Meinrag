"""Retrieval pipeline — single source of truth for query ranking and scoring.

All retrieval-related helpers and the main `retrieve_and_rank()` orchestrator
live here so that both /query and /query/stream use identical logic.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from app.config import Settings
from app.models.schemas import SourceChunk
from app.rag.chain import is_reference_entry
from app.rag.prompts import (
    QUERY_ANALYZE_PROMPT,
    QUERY_EXPANSION_PROMPT,
)
from app.services.chunk_utils import is_garbage_table
from app.vectorstore.base import VectorStoreManager

logger = logging.getLogger(__name__)

_REFERENCE_SCORE_PENALTY = 0.3

_SECTION_WEIGHTS = {
    "abstract": 1.0,
    "introduction": 1.0,
    "related_work": 0.9,
    "methods": 1.0,
    "training": 1.0,
    "results": 1.0,
    "discussion": 1.0,
    "references": 1.0,      # handled separately by _apply_reference_penalty
    "appendix": 0.7,
    "acknowledgment": 0.4,
    "body": 1.0,
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class RetrievalResult:
    sources: list  # list of SourceChunk
    retrieved: list  # list of (doc, score) tuples for chain context
    query_types: list[str] = field(default_factory=list)
    query_label: str | None = None
    web_search_needed: bool = False
    chat_history: list | None = None


# ---------------------------------------------------------------------------
# Query analysis
# ---------------------------------------------------------------------------

async def _analyze_query(
    question: str, llm: BaseChatModel,
) -> dict:
    """Analyze query to determine types and optional label in a single LLM call.

    Returns {"types": ["fact"|"overview"|"reference"|"exploratory"], "label": str|None}
    """
    try:
        messages = QUERY_ANALYZE_PROMPT.format_messages(question=question)
        response = await llm.ainvoke(messages)
        result = response.content if hasattr(response, "content") else str(response)
        # Try to extract JSON from response (handle markdown code blocks)
        text = result.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(text)

        types = parsed.get("types", [])
        from app.services.query_types import load_query_types, get_type_names
        valid_types = set(get_type_names(load_query_types()))
        types = [t for t in types if t in valid_types]
        if not types:
            types = [get_type_names(load_query_types())[-1]]  # last type as default

        label = parsed.get("label")
        if label and len(label) > 30:
            label = None

        return {"types": types, "label": label}
    except Exception as e:
        logger.warning("Query analysis failed: %s, defaulting to exploratory", e)
        return {"types": ["exploratory"], "label": None}


# ---------------------------------------------------------------------------
# Query expansion
# ---------------------------------------------------------------------------

async def _maybe_expand_query(
    question: str,
    retrieved: list[tuple],
    llm: BaseChatModel,
    vector_store: VectorStoreManager,
    settings: Settings,
    doc_ids: list[str] | None,
    top_k: int,
    fetch_k: int | None = None,
) -> tuple[str, list[tuple]]:
    """If all retrieval scores are below threshold, expand the query via LLM and re-query."""
    if not settings.query_expansion_enabled or not retrieved:
        return question, retrieved

    max_score = max(score for _, score in retrieved) if retrieved else 0
    if max_score >= settings.query_expansion_score_threshold:
        return question, retrieved

    # Scores are all low — expand the query
    try:
        expansion_chain = QUERY_EXPANSION_PROMPT | llm | StrOutputParser()
        expanded = await expansion_chain.ainvoke({"question": question})
        expanded = expanded.strip()
        if not expanded or expanded == question:
            return question, retrieved

        logger.info("Query expanded: %r → %r", question, expanded)

        # Re-query with expanded query (use caller's fetch_k if provided)
        k = fetch_k if fetch_k is not None else int(top_k * 1.5)
        new_retrieved = vector_store.similarity_search_with_scores(
            expanded, k=k, doc_ids=doc_ids,
        )
        new_max = max(score for _, score in new_retrieved) if new_retrieved else 0

        # Only use expanded results if they're actually better
        if new_max > max_score:
            return expanded, new_retrieved
    except Exception as e:
        logger.warning("Query expansion failed: %s", e)

    return question, retrieved


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _demote_reference_results(
    results: list[tuple], top_k: int
) -> list[tuple]:
    """Move reference-list results to the end so real content fills top_k first."""
    content, refs = [], []
    for r in results:
        (refs if is_reference_entry(r[0].page_content) else content).append(r)
    if refs:
        logger.info("Reference demotion: %d ref chunks demoted out of %d results", len(refs), len(results))
    return (content + refs)[:top_k]


def _apply_reference_penalty(results: list[tuple]) -> list[tuple]:
    """Multiply score by penalty factor for chunks tagged as reference section."""
    return [
        (doc, score * _REFERENCE_SCORE_PENALTY) if doc.metadata.get("section") == "references" else (doc, score)
        for doc, score in results
    ]


def _apply_section_weights(results: list[tuple]) -> list[tuple]:
    """Apply section-based score weights.

    Penalizes low-value sections (acknowledgments, appendix).
    References NOT penalized here — they have their own penalty.
    """
    weighted = []
    for doc, score in results:
        section = doc.metadata.get("section_type", "body")
        if section == "references":
            weighted.append((doc, score))
            continue
        weight = _SECTION_WEIGHTS.get(section, 1.0)
        weighted.append((doc, score * weight))
    return weighted


_BOILERPLATE_SCORE_PENALTY = 0.2


def _apply_boilerplate_penalty(results: list[tuple]) -> list[tuple]:
    """Penalize boilerplate chunks (author footnotes, copyright, disclaimers)."""
    from app.services.chunk_utils import is_boilerplate_chunk

    return [
        (doc, score * _BOILERPLATE_SCORE_PENALTY)
        if is_boilerplate_chunk(doc.page_content)
        else (doc, score)
        for doc, score in results
    ]


def _section_aware_sample(
    results: list[tuple],
    top_k: int = 8,
) -> list[tuple]:
    """Round-robin sample across section types for broad coverage.

    For open/overview questions, ensures the LLM sees content from
    diverse sections rather than clustering from one section.
    Picks the best chunk from each section first, then fills up
    to top_k with remaining chunks by score.
    """
    if not results:
        return []

    # Group by section, each list sorted by score desc
    from collections import defaultdict
    by_section: dict[str, list[tuple]] = defaultdict(list)
    for doc, score in results:
        section = doc.metadata.get("section_type", "body")
        by_section[section].append((doc, score))
    for sec in by_section:
        by_section[sec].sort(key=lambda x: x[1], reverse=True)

    # Round-robin: pick best from each section, then second-best, etc.
    sampled = []
    seen_keys = set()
    round_idx = 0
    while len(sampled) < top_k:
        added_this_round = False
        for sec in sorted(by_section, key=lambda s: by_section[s][0][1] if by_section[s] else 0, reverse=True):
            items = by_section[sec]
            if round_idx < len(items):
                doc, score = items[round_idx]
                did = doc.metadata.get("doc_id")
                cidx = doc.metadata.get("chunk_index")
                key = (did, cidx) if did is not None and cidx is not None else id(doc)
                if key not in seen_keys:
                    seen_keys.add(key)
                    sampled.append((doc, score))
                    added_this_round = True
                    if len(sampled) >= top_k:
                        break
        if not added_this_round:
            break
        round_idx += 1

    sampled.sort(key=lambda x: x[1], reverse=True)
    return sampled


def _parse_weights(weights_str: str) -> tuple[float, float, float, float]:
    """Parse comma-separated weights string into tuple."""
    try:
        parts = [float(x.strip()) for x in weights_str.split(",")]
    except (ValueError, AttributeError):
        return (0.7, 0.15, 0.05, 0.1)
    if len(parts) != 4:
        return (0.7, 0.15, 0.05, 0.1)
    return tuple(parts)


def _composite_score(
    similarity: float,
    graph_score: float = 0.0,
    recency: float = 1.0,
    authority: float = 1.0,
    weights: tuple[float, float, float, float] = (0.7, 0.15, 0.05, 0.1),
) -> float:
    """Compute weighted composite score from multiple signals."""
    w_sim, w_graph, w_rec, w_auth = weights
    return w_sim * similarity + w_graph * graph_score + w_rec * recency + w_auth * authority


async def _apply_composite_scoring(
    retrieved: list[tuple],
    edge_repo,
    query_type: str,
    settings,
) -> list[tuple]:
    """Replace raw similarity scores with composite scores.

    Uses per-query-type weights from query_types.json config.
    """
    from app.services.query_types import load_query_types, get_type_config
    qt_config = load_query_types(settings.query_types_file)
    type_cfg = get_type_config(qt_config, query_type)
    if type_cfg and type_cfg.get("weights"):
        weights = tuple(type_cfg["weights"])
    else:
        weights = (0.7, 0.15, 0.05, 0.1)

    # Batch fetch edge counts for graph score
    edge_counts = {}
    if edge_repo:
        # Group chunks by doc_id
        doc_chunks = {}
        for doc, _ in retrieved:
            did = doc.metadata.get("doc_id")
            cidx = doc.metadata.get("chunk_index")
            if did is not None and cidx is not None:
                doc_chunks.setdefault(did, []).append(cidx)
        # Single query per doc
        for did, indices in doc_chunks.items():
            try:
                counts = await edge_repo.get_edge_counts_batch(did, indices)
                for cidx, count in counts.items():
                    edge_counts[(did, cidx)] = count
            except Exception:
                pass

    rescored = []
    for doc, similarity in retrieved:
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        graph_score = min(edge_counts.get(key, 0) / 10.0, 1.0)
        recency = 1.0
        authority = 1.0
        new_score = _composite_score(similarity, graph_score, recency, authority, weights)
        rescored.append((doc, new_score))

    return rescored


def _normalize_scores(retrieved: list[tuple]) -> list[tuple]:
    """Normalize scores to 0-100 range for frontend display."""
    if not retrieved:
        return retrieved
    max_score = max(score for _, score in retrieved)
    if max_score <= 0:
        return retrieved
    return [(doc, round(score / max_score * 100, 1)) for doc, score in retrieved]


# ---------------------------------------------------------------------------
# Graph expansion
# ---------------------------------------------------------------------------

async def _expand_via_edges(
    retrieved: list[tuple],
    edge_repo,
    vector_store: VectorStoreManager,
    relations: list[str] | None = None,
    max_expansion: int = 5,
) -> list[tuple]:
    """Expand retrieved results by traversing graph edges.

    For each retrieved chunk, find connected chunks via edges
    and add them to the result set.
    """
    if not retrieved:
        return retrieved

    # Track what we already have
    seen_keys = set()
    for doc, _ in retrieved:
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        seen_keys.add(key)

    expanded = []
    for doc, score in retrieved:
        doc_id = doc.metadata.get("doc_id")
        chunk_index = doc.metadata.get("chunk_index")
        if doc_id is None or chunk_index is None:
            continue

        edges = await edge_repo.get_edges_from(doc_id, chunk_index, relations=relations)
        for edge in edges:
            target_key = (edge["target_doc_id"], edge["target_chunk_index"])
            if target_key in seen_keys:
                continue
            seen_keys.add(target_key)

            # Fetch the target chunk
            target_chunks = vector_store.get_chunks_by_doc(edge["target_doc_id"])
            for tc in target_chunks:
                if tc.metadata.get("chunk_index") == edge["target_chunk_index"]:
                    edge_score = edge.get("score") or score * 0.8
                    expanded.append((tc, edge_score))
                    break

            if len(expanded) >= max_expansion:
                break
        if len(expanded) >= max_expansion:
            break

    if expanded:
        logger.info("Graph expansion: added %d chunks via edges", len(expanded))

    return retrieved + expanded


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------

async def _rerank_results(
    retrieved: list[tuple],
    question: str,
    settings,
    llm=None,
) -> list[tuple]:
    """Apply cross-encoder reranking to retrieved results."""
    if not retrieved:
        return retrieved
    try:
        from app.rag.chain import _get_reranker
        compressor = _get_reranker(settings, llm)
        docs = [doc for doc, _ in retrieved]
        compressed = compressor.compress_documents(docs, question)

        # Build score map from original results
        score_map = {}
        for doc, score in retrieved:
            key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
            score_map[key] = score

        reranked = []
        for cdoc in compressed:
            key = (cdoc.metadata.get("doc_id"), cdoc.metadata.get("chunk_index"))
            rerank_score = cdoc.metadata.get("relevance_score", score_map.get(key, 0.0))
            reranked.append((cdoc, rerank_score))

        logger.info("Reranked %d → %d results", len(retrieved), len(reranked))
        return reranked if reranked else retrieved
    except Exception as e:
        logger.warning("Reranking failed, using original order: %s", e)
        return retrieved


# ---------------------------------------------------------------------------
# Visual proximity linking
# ---------------------------------------------------------------------------

def _link_nearby_visuals(
    retrieved: list,
    vector_store: VectorStoreManager,
    doc_ids: list[str] | None,
    question: str | None = None,
    embeddings=None,
    proximity_pages: int = 1,
) -> list:
    """Link visual chunks (image/table/formula) from pages near retrieved text chunks.

    For each retrieved text chunk, finds visual chunks on the same or
    adjacent pages (within proximity_pages range) from the same document.
    Computes real cosine similarity scores when embeddings are available.
    """
    if not doc_ids or not retrieved:
        return retrieved

    # Collect pages referenced by retrieved text chunks, per doc
    doc_pages: dict[str, set[int]] = {}
    retrieved_keys = set()
    for doc, _ in retrieved:
        meta = doc.metadata
        key = (meta.get("doc_id"), meta.get("chunk_index"))
        retrieved_keys.add(key)
        did = meta.get("doc_id")
        page = meta.get("page")
        if did and page is not None:
            doc_pages.setdefault(did, set())
            for p in range(page - proximity_pages, page + proximity_pages + 1):
                doc_pages[did].add(p)

    # Find visual chunks on those pages
    extra_docs = []
    for did, pages in doc_pages.items():
        chunks = vector_store.get_chunks_by_doc(did)
        for chunk in chunks:
            meta = chunk.metadata
            ct = meta.get("chunk_type")
            if ct not in ("image", "table", "formula"):
                continue
            if ct == "image" and not meta.get("image_path"):
                continue
            if ct == "table" and is_garbage_table(chunk.page_content):
                continue
            chunk_page = meta.get("page")
            if chunk_page not in pages:
                continue
            key = (meta.get("doc_id"), meta.get("chunk_index"))
            if key in retrieved_keys:
                continue
            extra_docs.append(chunk)
            retrieved_keys.add(key)

    if not extra_docs:
        return retrieved

    # Compute real similarity scores if embeddings and question available
    extra_with_scores = []
    if question and embeddings:
        try:
            import numpy as np
            query_emb = embeddings.embed_query(question)
            doc_texts = [d.page_content for d in extra_docs]
            doc_embs = embeddings.embed_documents(doc_texts)
            query_vec = np.array(query_emb)
            for doc, emb in zip(extra_docs, doc_embs):
                doc_vec = np.array(emb)
                cosine = float(np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-10))
                extra_with_scores.append((doc, max(0.0, cosine)))
        except Exception as e:
            logger.warning(f"Failed to compute proximity scores: {e}")
            extra_with_scores = [(doc, 0.0) for doc in extra_docs]
    else:
        extra_with_scores = [(doc, 0.0) for doc in extra_docs]

    if extra_with_scores:
        logger.info(f"Linked {len(extra_with_scores)} visual chunks from nearby pages")
    return retrieved + extra_with_scores


# ---------------------------------------------------------------------------
# Source chunk building
# ---------------------------------------------------------------------------

def _parse_bbox(raw) -> list[float] | None:
    """Parse bbox from metadata — may be a JSON string or already a list."""
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
    if isinstance(raw, list):
        return raw
    return None


def _smart_truncate(text: str, max_len: int = 500) -> str:
    """Truncate text at a sentence or word boundary instead of mid-word."""
    if len(text) <= max_len:
        return text
    # Try to break at last sentence end (. ! ?) within limit
    for sep in (". ", ".\n", "! ", "? "):
        idx = text.rfind(sep, 0, max_len)
        if idx > max_len * 0.5:  # only if at least half the content is kept
            return text[: idx + 1]
    # Fallback: break at last space
    idx = text.rfind(" ", 0, max_len)
    if idx > max_len * 0.5:
        return text[:idx] + "..."
    # Last resort: hard cut
    return text[:max_len] + "..."


def _build_source_chunks(retrieved: list) -> list[SourceChunk]:
    """Build SourceChunk list from retrieved (doc, score) pairs."""
    return [
        SourceChunk(
            content=_smart_truncate(doc.page_content, 500),
            source_file=doc.metadata.get("source_file", "unknown"),
            chunk_index=doc.metadata.get("chunk_index"),
            doc_id=doc.metadata.get("doc_id"),
            page=doc.metadata.get("page"),
            score=round(score, 4),
            chunk_type=doc.metadata.get("chunk_type"),
            image_path=doc.metadata.get("image_path"),
            bbox=_parse_bbox(doc.metadata.get("bbox")),
            label=doc.metadata.get("label"),
            headings=doc.metadata.get("headings"),
            summary=doc.metadata.get("summary"),
        )
        for doc, score in retrieved
    ]


# ---------------------------------------------------------------------------
# Label lookup
# ---------------------------------------------------------------------------

def _lookup_by_label(
    label: str,
    vector_store: VectorStoreManager,
    doc_ids: list[str] | None,
) -> list:
    """Find chunks with a matching label in metadata.

    If no exact label match, falls back to Nth chunk of that type by document order.
    E.g., "Table 1" → first table chunk, "Figure 3" → third image chunk.

    Returns list of Documents with matching label.
    """
    if not doc_ids or not label:
        return []

    label_lower = label.lower()
    matches = []
    for did in doc_ids:
        chunks = vector_store.get_chunks_by_doc(did)
        for chunk in chunks:
            chunk_label = chunk.metadata.get("label", "")
            if chunk_label and chunk_label.lower() == label_lower:
                matches.append(chunk)

    if matches:
        return matches

    # Fallback: parse type + number from label, find Nth chunk of that type
    m = re.match(r'(table|figure|equation)\s+(\d+)', label_lower)
    if not m:
        return []

    label_type = m.group(1)
    label_num = int(m.group(2))

    # Map label type to chunk_type
    type_map = {"table": "table", "figure": "image", "equation": "formula"}
    chunk_type = type_map.get(label_type)
    if not chunk_type:
        return []

    for did in doc_ids:
        chunks = vector_store.get_chunks_by_doc(did)
        typed = sorted(
            [c for c in chunks if c.metadata.get("chunk_type") == chunk_type],
            key=lambda c: c.metadata.get("chunk_index", 0),
        )
        if 1 <= label_num <= len(typed):
            logger.info("Label fallback: %s → %dth %s chunk", label, label_num, chunk_type)
            return [typed[label_num - 1]]

    return []


# ---------------------------------------------------------------------------
# Main pipeline orchestrator
# ---------------------------------------------------------------------------

def _merge_dual_results(raw_results: list[tuple], summary_results: list[tuple]) -> list[tuple]:
    """Merge raw and summary search results, keeping best score per chunk."""
    best: dict = {}  # (doc_id, chunk_index) -> (doc, score)
    for doc, score in raw_results:
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        if key not in best or score > best[key][1]:
            best[key] = (doc, score)
    for doc, score in summary_results:
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        if key not in best or score > best[key][1]:
            # Keep raw doc object if available (has full content), use higher score
            if key in best:
                best[key] = (best[key][0], score)
            else:
                best[key] = (doc, score)
    return list(best.values())


async def retrieve_and_rank(
    question: str,
    top_k: int,
    doc_ids: list[str] | None,
    user_scoped: bool,
    llm: BaseChatModel,
    vector_store: VectorStoreManager,
    embeddings: Embeddings,
    edge_repo,
    settings: Settings,
    force_web_search: bool = False,
    summary_store=None,
    chat_history=None,
) -> RetrievalResult:
    """Full retrieval pipeline — single source of truth.

    Returns a RetrievalResult with web_search_needed=True when the caller
    should fall back to web search (no retrieval results are populated in
    that case).
    """
    # 1. Analyze query
    analysis = await _analyze_query(question, llm)
    query_types = analysis["types"]
    query_label = analysis["label"]
    logger.info("Query analysis: types=%s label=%s — %r", query_types, query_label, question)
    primary_type = query_types[0]

    # 2. Label lookup
    label_chunks = []
    if query_label and doc_ids:
        label_chunks = _lookup_by_label(query_label, vector_store, doc_ids)
        if label_chunks:
            logger.info("Label lookup: found %d chunks for %r", len(label_chunks), query_label)

    # 3. Determine strategy from config
    from app.services.query_types import load_query_types, get_type_config, get_strategy
    qt_config = load_query_types(settings.query_types_file)
    primary_cfg = get_type_config(qt_config, primary_type) or {}
    strategy_name = primary_cfg.get("strategy", "top_k")
    strategy = get_strategy(qt_config, strategy_name)
    fetch_k = int(top_k * strategy.get("fetch_multiplier", 1.5))

    # 4. Vector search
    retrieved = vector_store.similarity_search_with_scores(
        question, k=fetch_k, doc_ids=doc_ids,
    )

    # 4b. Summary index search (dual-index)
    if summary_store:
        try:
            summary_results = summary_store.similarity_search_with_scores(
                question, k=fetch_k, doc_ids=doc_ids,
            )
            if summary_results:
                before = len(retrieved)
                retrieved = _merge_dual_results(retrieved, summary_results)
                logger.info("Dual-index: merged %d raw + %d summary -> %d results",
                           before, len(summary_results), len(retrieved))
        except Exception as e:
            logger.warning("Summary search failed: %s", e)

    # 4c. BM25 hybrid search (if enabled)
    if settings.hybrid_search_enabled:
        try:
            from langchain_community.retrievers import BM25Retriever
            from app.rag.chain import _bm25_cache
            all_docs = vector_store.get_all_documents()
            if doc_ids:
                all_docs = [d for d in all_docs if d.metadata.get("doc_id") in doc_ids]
            if all_docs:
                cache_key = tuple(sorted(doc_ids)) if doc_ids else None
                if (_bm25_cache["retriever"] is not None
                        and _bm25_cache["doc_count"] == len(all_docs)
                        and _bm25_cache["doc_ids_key"] == cache_key):
                    bm25 = _bm25_cache["retriever"]
                    bm25.k = fetch_k
                else:
                    bm25 = BM25Retriever.from_documents(all_docs, k=fetch_k)
                    _bm25_cache["retriever"] = bm25
                    _bm25_cache["doc_count"] = len(all_docs)
                    _bm25_cache["doc_ids_key"] = cache_key
                bm25_results = [(doc, 0.5) for doc in bm25.invoke(question)]
                retrieved = _merge_dual_results(retrieved, bm25_results)
        except Exception as e:
            logger.warning("BM25 hybrid search failed: %s", e)

    # 5. Query expansion
    _, retrieved = await _maybe_expand_query(
        question, retrieved, llm, vector_store, settings, doc_ids, top_k,
        fetch_k=fetch_k,
    )

    # 6. Type-specific strategies
    if strategy.get("text_only"):
        text_only = [(doc, score) for doc, score in retrieved
                     if doc.metadata.get("chunk_type") == "text"]
        retrieved = _section_aware_sample(text_only, top_k=top_k)
    elif strategy.get("demote_references"):
        retrieved = _demote_reference_results(retrieved, top_k)

    retrieved = _apply_reference_penalty(retrieved)
    retrieved = _apply_section_weights(retrieved)
    retrieved = _apply_boilerplate_penalty(retrieved)

    # 6b. Reranking (if enabled)
    if settings.rerank_enabled:
        retrieved = await _rerank_results(retrieved, question, settings, llm)

    # 7. Check web search
    if force_web_search or _needs_web_search(user_scoped, retrieved, settings):
        return RetrievalResult(
            sources=[], retrieved=[], query_types=query_types,
            query_label=query_label, web_search_needed=True,
            chat_history=chat_history,
        )

    # 8. Visual proximity linking
    if settings.visual_proximity_enabled:
        retrieved = _link_nearby_visuals(
            retrieved, vector_store, doc_ids,
            question=question, embeddings=embeddings,
            proximity_pages=settings.visual_proximity_pages,
        )

    # 9. Graph expansion
    retrieved = await _expand_via_edges(
        retrieved, edge_repo, vector_store,
        relations=["describes", "references"],
    )

    # 10. Composite scoring
    retrieved = await _apply_composite_scoring(retrieved, edge_repo, primary_type, settings)

    # 11. Sort + normalize
    retrieved.sort(key=lambda x: x[1], reverse=True)
    retrieved = _normalize_scores(retrieved)

    # 12. Prepend label chunks
    if label_chunks:
        label_keys = set()
        label_results = []
        for chunk in label_chunks:
            key = (chunk.metadata.get("doc_id"), chunk.metadata.get("chunk_index"))
            label_keys.add(key)
            label_results.append((chunk, 100.0))
        retrieved = [(doc, score) for doc, score in retrieved
                     if (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index")) not in label_keys]
        retrieved = label_results + retrieved

    sources = _build_source_chunks(retrieved)

    return RetrievalResult(
        sources=sources,
        retrieved=retrieved,
        query_types=query_types,
        query_label=query_label,
        chat_history=chat_history,
    )


def _needs_web_search(
    user_scoped: bool,
    retrieved: list,
    settings: Settings,
) -> bool:
    """Determine if web search is needed based on retrieval results.

    Note: force_web_search and settings.web_search_enabled checks are
    handled by the caller before reaching retrieve_and_rank().
    """
    if not settings.web_search_enabled:
        return False
    if user_scoped:
        return False
    if not retrieved:
        return True
    best_score = max(score for _, score in retrieved)
    return best_score < settings.web_search_score_threshold
