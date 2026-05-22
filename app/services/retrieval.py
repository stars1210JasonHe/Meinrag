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
    FACT_KEYWORD_EXPANSION_PROMPT,
)
from app.services.chunk_utils import is_garbage_table
from app.services.scoring_profile import ResolvedScoring, load_scoring_profile
from app.vectorstore.base import VectorStoreManager

logger = logging.getLogger(__name__)


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
    confidence_tier: str | None = None
    # Context budget telemetry
    context_used_tokens: int | None = None
    context_budget_tokens: int | None = None
    context_mode: str | None = None  # "chunks" (v1); "summary" (phase 3, future)
    chunks_included: int | None = None
    chunks_available: int | None = None


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


async def _fact_keyword_expand(
    question: str,
    retrieved: list[tuple],
    llm: BaseChatModel,
    vector_store: VectorStoreManager,
    doc_ids: list[str] | None,
    fetch_k: int,
) -> list[tuple]:
    """For fact queries, LLM predicts likely answer tokens; we re-retrieve
    using the keyword-augmented query. Result is the UNION, deduplicated,
    with augmented-retrieval chunks preferred (they contain the concrete
    answer tokens the query was too abstract to express).

    Bridges the abstract-query ↔ concrete-answer lexical gap that dense
    embeddings + BM25 both struggle with. E.g., "parameter counts" should
    find chunks with "7B", "175 billion" — this adds those tokens to the
    query so the retriever can find them.

    NB: we do NOT RRF-merge because RRF rewards consensus (both retrievers
    found it) over novel signal (only augmented found it). For fact
    expansion, the novel augmented hits ARE the goal — they're the chunks
    with the concrete answer tokens. Consensus-based ranking demotes them.

    No-op on errors — falls back to original retrieval.
    """
    try:
        chain = FACT_KEYWORD_EXPANSION_PROMPT | llm | StrOutputParser()
        keywords = (await chain.ainvoke({"question": question})).strip()
        # Reject runaway / sentence-length responses: must be a short token list.
        if not keywords or len(keywords.split()) > 20 or len(keywords) > 200:
            return retrieved
        augmented = f"{question} {keywords}"
        logger.info("Fact query keyword-expanded: +%r", keywords[:80])

        aug_results = vector_store.similarity_search_with_scores(
            augmented, k=fetch_k, doc_ids=doc_ids,
        )
        if not aug_results:
            return retrieved

        # Union preserving augmented-first order, dedupe by (doc_id, chunk_index).
        seen = set()
        merged: list[tuple] = []
        for doc, score in aug_results:
            key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
            if key not in seen:
                seen.add(key)
                merged.append((doc, score))
        for doc, score in retrieved:
            key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
            if key not in seen:
                seen.add(key)
                merged.append((doc, score))
        return merged
    except Exception as e:
        logger.warning("Fact keyword expansion failed: %s", e)
        return retrieved


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


def _apply_reference_penalty(results: list[tuple], profile: ResolvedScoring) -> list[tuple]:
    """Multiply score by penalty factor for chunks tagged as reference section."""
    penalty = profile.reference_penalty
    return [
        (doc, score * penalty) if doc.metadata.get("section") == "references" else (doc, score)
        for doc, score in results
    ]


def _apply_section_weights(results: list[tuple], profile: ResolvedScoring) -> list[tuple]:
    """Apply section-based score weights from the scoring profile.

    Penalizes low-value sections (acknowledgments, appendix).
    References NOT penalized here — they have their own penalty.
    """
    section_weights = profile.section_weights
    weighted = []
    for doc, score in results:
        section = doc.metadata.get("section_type", "body")
        if section == "references":
            weighted.append((doc, score))
            continue
        weight = section_weights.get(section, 1.0)
        weighted.append((doc, score * weight))
    return weighted


def _apply_boilerplate_penalty(results: list[tuple], profile: ResolvedScoring) -> list[tuple]:
    """Penalize boilerplate chunks (author footnotes, copyright, disclaimers)."""
    from app.services.chunk_utils import is_boilerplate_chunk

    penalty = profile.boilerplate_penalty
    return [
        (doc, score * penalty)
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
        return (0.7, 0.3, 0.0, 0.0)
    if len(parts) != 4:
        return (0.7, 0.3, 0.0, 0.0)
    return tuple(parts)


def _composite_score(
    similarity: float,
    graph_score: float = 0.0,
    recency: float = 1.0,
    authority: float = 1.0,
    weights: tuple[float, float, float, float] = (0.7, 0.3, 0.0, 0.0),
) -> float:
    """Compute weighted composite score from multiple signals."""
    w_sim, w_graph, w_rec, w_auth = weights
    return w_sim * similarity + w_graph * graph_score + w_rec * recency + w_auth * authority


async def _apply_composite_scoring(
    retrieved: list[tuple],
    edge_repo,
    query_type: str,
    settings,
    profile: ResolvedScoring,
) -> list[tuple]:
    """Replace raw similarity scores with composite scores.

    Uses per-query-type weights from query_types.json config.
    Graph scoring uses edge-type weights from the scoring profile.
    """
    from app.services.query_types import load_query_types, get_type_config
    qt_config = load_query_types(settings.query_types_file)
    type_cfg = get_type_config(qt_config, query_type)
    if type_cfg and type_cfg.get("weights"):
        weights = tuple(type_cfg["weights"])
    else:
        weights = (0.7, 0.3, 0.0, 0.0)

    edge_type_weights = profile.edge_type_weights
    norm_factor = profile.graph_normalization_factor

    # Batch fetch edge counts by type for graph score
    edge_type_counts: dict[tuple, dict[str, int]] = {}
    if edge_repo:
        doc_chunks: dict[str, list[int]] = {}
        for doc, _ in retrieved:
            did = doc.metadata.get("doc_id")
            cidx = doc.metadata.get("chunk_index")
            if did is not None and cidx is not None:
                doc_chunks.setdefault(did, []).append(cidx)
        for did, indices in doc_chunks.items():
            try:
                type_counts = await edge_repo.get_edge_type_counts_batch(did, indices)
                for cidx, rel_counts in type_counts.items():
                    edge_type_counts[(did, cidx)] = rel_counts
            except Exception:
                pass

    rescored = []
    # Breakdown capture for Score-B diagnostics — enabled via DEBUG logging.
    # When active, we log per-chunk signal contributions so we can see which
    # signal drives high composite on nonsense queries.
    debug_enabled = logger.isEnabledFor(logging.DEBUG)
    breakdown_rows: list[dict] = []

    for doc, similarity in retrieved:
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        rel_counts = edge_type_counts.get(key, {})
        weighted_edge_sum = sum(
            edge_type_weights.get(rel, 1.0) * count
            for rel, count in rel_counts.items()
        )
        # Michaelis-Menten saturation: never hits 1.0, always differentiates.
        # norm_factor is the "half-saturation point" — at norm_factor edges, score=0.5
        graph_score = weighted_edge_sum / (weighted_edge_sum + norm_factor) if weighted_edge_sum > 0 else 0.0
        # placeholder: recency/authority weights are 0.0 in query_types.json until signals are implemented
        recency = 1.0
        authority = 1.0
        new_score = _composite_score(similarity, graph_score, recency, authority, weights)
        rescored.append((doc, new_score))

        if debug_enabled:
            w_sim, w_graph, w_rec, w_auth = weights
            breakdown_rows.append({
                "doc_id": key[0],
                "chunk_idx": key[1],
                "similarity": round(similarity, 4),
                "graph_score": round(graph_score, 4),
                "edge_sum": round(weighted_edge_sum, 2),
                "w_sim": w_sim,
                "w_graph": w_graph,
                "sim_contrib": round(w_sim * similarity, 4),
                "graph_contrib": round(w_graph * graph_score, 4),
                "recency_contrib": round(w_rec * recency, 4),
                "authority_contrib": round(w_auth * authority, 4),
                "composite": round(new_score, 4),
            })

    if debug_enabled and breakdown_rows:
        # Sort by composite desc and log top 5 — most interesting for false-high cases
        top = sorted(breakdown_rows, key=lambda r: r["composite"], reverse=True)[:5]
        logger.debug(
            "[SCORE-B BREAKDOWN] query_type=%s weights=(sim=%s graph=%s rec=%s auth=%s) top-5:",
            query_type, *weights,
        )
        for r in top:
            logger.debug(
                "  [%s:%s] sim=%.3f(x%.2f=%.3f) graph=%.3f(x%.2f=%.3f) | composite=%.3f",
                r["doc_id"], r["chunk_idx"],
                r["similarity"], r["w_sim"], r["sim_contrib"],
                r["graph_score"], r["w_graph"], r["graph_contrib"],
                r["composite"],
            )

    return rescored


def _normalize_scores(retrieved: list[tuple], profile=None) -> list[tuple]:
    """Normalize composite scores to 0-100 range for frontend display.

    Three modes via profile.normalization:
      - "absolute" (default): score * 100, clamped to [0, 100]. Honest: a weak
        query shows low percentages; top is not artificially pinned to 100.
      - "tanh": tanh(k*p) / tanh(k) * 100. Smooth S-curve with steepness k.
      - "max_scale": legacy. Top score divided by max → always 100 at top.
    """
    if not retrieved:
        return retrieved

    mode = getattr(profile, "normalization", "absolute") if profile else "absolute"

    if mode == "tanh":
        import math
        k = getattr(profile, "normalization_k", 1.5)
        denom = math.tanh(k)
        if denom <= 0:
            return retrieved
        return [
            (doc, round(math.tanh(k * max(0.0, score)) / denom * 100, 1))
            for doc, score in retrieved
        ]

    if mode == "max_scale":
        max_score = max(score for _, score in retrieved)
        if max_score <= 0:
            return retrieved
        return [(doc, round(score / max_score * 100, 1)) for doc, score in retrieved]

    # Default: absolute — just score * 100, no hidden rescaling
    return [(doc, round(max(0.0, min(1.0, score)) * 100, 1)) for doc, score in retrieved]


def _compute_confidence_tier(retrieved: list[tuple], profile) -> str:
    """Map best raw composite score to confidence tier. Informational only."""
    if not retrieved:
        return "low"
    best = max(score for _, score in retrieved)
    if best >= profile.confidence_high:
        return "high"
    if best >= profile.confidence_moderate:
        return "moderate"
    return "low"


# ---------------------------------------------------------------------------
# Graph expansion
# ---------------------------------------------------------------------------

async def _expand_via_edges(
    retrieved: list[tuple],
    edge_repo,
    vector_store: VectorStoreManager,
    profile: ResolvedScoring,
    relations: list[str] | None = None,
    max_expansion: int = 5,
) -> list[tuple]:
    """Expand retrieved results by traversing graph edges.

    For each retrieved chunk, find connected chunks via edges
    and add them to the result set.
    """
    if not retrieved:
        return retrieved

    decay = profile.graph_expansion_score_decay

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

            target_chunks = vector_store.get_chunks_by_doc(edge["target_doc_id"])
            for tc in target_chunks:
                if tc.metadata.get("chunk_index") == edge["target_chunk_index"]:
                    edge_score = edge.get("score") or score * decay
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
    top_n: int | None = None,
) -> list[tuple]:
    """Apply cross-encoder reranking to retrieved results.

    top_n: how many to keep after reranking. Defaults to settings.rerank_top_n
    (currently 4), which is fine for single-doc but starves multi-doc queries.
    Callers should pass the effective top_k so per-doc distribution works.
    """
    if not retrieved:
        return retrieved
    try:
        from app.rag.chain import _get_reranker
        # Use max of setting and caller's request so a small setting doesn't cap large queries
        effective_top_n = max(settings.rerank_top_n, top_n) if top_n else settings.rerank_top_n
        compressor = _get_reranker(settings, llm, top_n_override=effective_top_n)
        docs = [doc for doc, _ in retrieved]
        compressed = compressor.compress_documents(docs, question)

        # Build score map from original results
        score_map = {}
        for doc, score in retrieved:
            key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
            score_map[key] = score

        # Use reranker output for ORDERING only; preserve original FAISS similarity
        # as the score value. Reranker scores (e.g. FlashRank) cluster near 1.0 for
        # any query, which would destroy the signal that separates good from weak
        # matches in the final composite display.
        reranked = []
        for cdoc in compressed:
            key = (cdoc.metadata.get("doc_id"), cdoc.metadata.get("chunk_index"))
            original_score = score_map.get(key, 0.0)
            reranked.append((cdoc, original_score))

        logger.info("Reranked %d → %d results (reordered, original scores preserved)", len(retrieved), len(reranked))
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
# RRF fusion
# ---------------------------------------------------------------------------

def _rrf_merge_bm25(
    vector_results: list[tuple],
    bm25_docs: list,
    k: int = 60,
) -> list[tuple]:
    """Merge vector (with cosine scores) and BM25 (ranked docs) via Reciprocal Rank Fusion.

    RRF_score(d) = sum 1/(k + rank) for each retriever that found d.
    Output is re-normalized to 0-1 for downstream threshold compatibility.
    """
    rrf: dict[tuple, list] = {}

    for rank, (doc, _cosine) in enumerate(vector_results, 1):
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        rrf[key] = [doc, 1.0 / (k + rank)]

    for rank, doc in enumerate(bm25_docs, 1):
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        bm25_rrf = 1.0 / (k + rank)
        if key in rrf:
            rrf[key][1] += bm25_rrf
        else:
            rrf[key] = [doc, bm25_rrf]

    merged = [(doc, score) for doc, score in rrf.values()]

    if merged:
        max_s = max(s for _, s in merged)
        if max_s > 0:
            merged = [(d, s / max_s) for d, s in merged]

    # Sort desc — downstream pipeline (_section_aware_sample, _reorder_for_attention)
    # assumes this invariant on entry.
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged


# ---------------------------------------------------------------------------
# Main pipeline orchestrator
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Token budget management
# ---------------------------------------------------------------------------

_TIKTOKEN_ENC = None  # cached encoding

def _get_tiktoken_enc():
    """Load tiktoken encoding once and cache. cl100k_base covers OpenAI models;
    produces ±10% estimates for Claude/Gemini which is fine for a conservative budget."""
    global _TIKTOKEN_ENC
    if _TIKTOKEN_ENC is None:
        import tiktoken
        try:
            _TIKTOKEN_ENC = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _TIKTOKEN_ENC = tiktoken.get_encoding("gpt2")
    return _TIKTOKEN_ENC


def _count_tokens(text: str) -> int:
    """Count tokens in text. Uses cl100k_base (OpenAI GPT-4 family tokenizer)."""
    if not text:
        return 0
    try:
        return len(_get_tiktoken_enc().encode(text))
    except Exception:
        # Fallback: 1 token per 4 chars
        return max(1, len(text) // 4)


def _resolve_model_name(settings: Settings) -> str:
    """Pick the correct model name based on llm_provider setting."""
    if settings.llm_provider.value == "openrouter":
        return settings.openrouter_model
    return settings.openai_model


def _compute_context_budget(
    question: str,
    chat_history,
    query_type: str,
    settings: Settings,
) -> tuple[int, int, int]:
    """Return (chunk_budget_tokens, history_budget_tokens, total_input_budget).

    Layout of the input budget:
      total = model_window * context_budget_ratio  - reserved_output  - reserved_prompt_overhead
      history_budget = clamp(history_tokens,
                             history_min_reserve * total,
                             history_max_budget * total)
      chunk_budget = total - history_budget - query_tokens
      Then chunk_budget is multiplied by QUERY_BUDGET_RATIOS[query_type].
    """
    from app.config import lookup_model_window, QUERY_BUDGET_RATIOS, DEFAULT_QUERY_BUDGET_RATIO

    model_name = _resolve_model_name(settings)
    window = lookup_model_window(model_name)

    total = int(window * settings.context_budget_ratio) \
            - settings.reserved_output_tokens \
            - settings.reserved_prompt_overhead_tokens

    if settings.max_context_tokens is not None:
        total = min(total, settings.max_context_tokens)

    total = max(total, 1024)  # floor to prevent pathological cases

    # History budget
    history_min = int(total * settings.history_min_reserve_ratio)
    history_max = int(total * settings.history_max_budget_ratio)
    history_tokens = 0
    if chat_history:
        for msg in chat_history:
            content = getattr(msg, "content", None) or str(msg)
            history_tokens += _count_tokens(content)
    history_budget = max(history_min, min(history_tokens, history_max))

    # Query tokens
    query_tokens = _count_tokens(question)

    chunk_budget = total - history_budget - query_tokens
    chunk_budget = max(chunk_budget, 512)  # floor

    # Apply query-type multiplier
    qt_ratio = QUERY_BUDGET_RATIOS.get(query_type, DEFAULT_QUERY_BUDGET_RATIO)
    chunk_budget = int(chunk_budget * qt_ratio)

    return chunk_budget, history_budget, total


def _ensure_per_doc_coverage(
    retrieved: list[tuple],
    all_candidates: list[tuple],
    scope_doc_ids: list[str] | None,
    question: str = "",
    vector_store=None,
) -> list[tuple]:
    """Guarantee at least 1 chunk from every doc the user explicitly selected.

    For each scope_doc_id, mark the highest-scored existing chunk as _mandatory
    in metadata. If a scope doc is entirely missing from retrieved, backfill via
    (a) the pre-narrow candidate pool then (b) per-doc vector search, and mark
    the backfilled chunk _mandatory too.

    The _mandatory flag is honored by _rerank_results' reinsertion step and by
    _apply_token_budget's Pass 1 so selected docs always surface at least one
    chunk in the final LLM context, regardless of score or budget pressure.
    """
    if not scope_doc_ids or len(scope_doc_ids) <= 1:
        return retrieved

    # Find the highest-scored existing chunk per scope doc and mark it mandatory.
    best_index_per_doc: dict[str, int] = {}
    for i, (doc, score) in enumerate(retrieved):
        did = doc.metadata.get("doc_id")
        if did not in scope_doc_ids:
            continue
        if did not in best_index_per_doc or score > retrieved[best_index_per_doc[did]][1]:
            best_index_per_doc[did] = i
    for did, i in best_index_per_doc.items():
        retrieved[i][0].metadata["_mandatory"] = True

    missing = [did for did in scope_doc_ids if did not in best_index_per_doc]
    if not missing:
        return retrieved

    result = list(retrieved)
    appended_from_pool = 0
    still_missing: list[str] = []

    # Step 1: try pre-narrow pool
    for did in missing:
        best = None
        for doc, score in all_candidates:
            if doc.metadata.get("doc_id") == did:
                if best is None or score > best[1]:
                    best = (doc, score)
        if best is not None:
            best[0].metadata["_mandatory"] = True
            result.append(best)
            appended_from_pool += 1
        else:
            still_missing.append(did)

    # Step 2: get_chunks_by_doc for docs not found in pool.
    # NB: we bypass similarity_search_with_scores here because the FAISS
    # implementation uses an over-fetch-then-filter pattern — with a narrow
    # per-doc filter, the target doc's chunks often don't appear in the
    # global top-K*5, so the filter produces zero hits. get_chunks_by_doc
    # reads directly from the docstore and always returns what's there.
    # First chunk is usually the doc's intro/abstract — good enough as a
    # mandatory representative when retrieval missed the doc entirely.
    appended_from_search = 0
    if still_missing and vector_store is not None:
        for did in still_missing:
            try:
                chunks = vector_store.get_chunks_by_doc(did)
                if chunks:
                    representative = chunks[0]
                    representative.metadata["_mandatory"] = True
                    result.append((representative, 0.0))
                    appended_from_search += 1
            except Exception as e:
                logger.debug("Per-doc backfill for %s failed: %s", did, e)

    total_appended = appended_from_pool + appended_from_search
    if total_appended:
        logger.info(
            "Per-doc coverage: added %d chunks (%d from pool + %d via search) for missing docs",
            total_appended, appended_from_pool, appended_from_search,
        )
    return result


def _apply_per_doc_cap(
    retrieved: list[tuple], n_docs_in_scope: int, top_k: int,
) -> list[tuple]:
    """When scope is multiple docs, cap chunks per doc to prevent one doc from
    dominating. Preserves rank order within each doc."""
    if n_docs_in_scope <= 1:
        return retrieved
    cap = max(1, top_k // n_docs_in_scope)
    # Count per doc, keep top-cap from each
    from collections import defaultdict
    per_doc_count: dict[str, int] = defaultdict(int)
    kept = []
    for doc, score in retrieved:
        did = doc.metadata.get("doc_id")
        if per_doc_count[did] < cap:
            kept.append((doc, score))
            per_doc_count[did] += 1
    if len(kept) < len(retrieved):
        logger.info("Per-doc cap (%d/doc for %d docs): %d -> %d chunks",
                    cap, n_docs_in_scope, len(retrieved), len(kept))
    return kept


def _apply_token_budget(
    retrieved: list[tuple], chunk_budget: int,
) -> tuple[list[tuple], int]:
    """Three-pass greedy fill — mandatory-aware, doc-diversity aware.

    Pass 0: Mandatory chunks (marked by _ensure_per_doc_coverage) — ALWAYS
    included, even if they exceed budget. Selected docs must have a voice.
    Pass 1: Reserve budget for the highest-score chunk of each remaining doc,
    so multi-doc queries always have representation.
    Pass 2: Fill remaining budget with the next-best chunks by rank.

    Returns (truncated_list, actual_tokens_used). Skips chunks that
    individually exceed 25% of budget (outliers) — but mandatory chunks are
    kept regardless of size.
    """
    if chunk_budget <= 0:
        return [], 0
    max_single_chunk = chunk_budget // 4

    # Pass 0: mandatory chunks (bypass size cap, bypass budget cap)
    mandatory_indices: list[int] = []
    used = 0
    for i, (doc, _score) in enumerate(retrieved):
        if doc.metadata.get("_mandatory"):
            tokens = _count_tokens(doc.page_content or "")
            mandatory_indices.append(i)
            used += tokens
    if used > chunk_budget:
        logger.warning(
            "Mandatory chunks (%d tokens) exceed budget (%d); including anyway to preserve per-doc coverage",
            used, chunk_budget,
        )

    # Identify the best (highest-scoring) chunk per doc_id among NON-mandatory
    # (mandatory already covers those docs). Preserve retrieval order for ties.
    covered_docs = {
        retrieved[i][0].metadata.get("doc_id") for i in mandatory_indices
    }
    first_seen_index: dict[str, int] = {}
    for i, (doc, _score) in enumerate(retrieved):
        if i in mandatory_indices:
            continue
        did = doc.metadata.get("doc_id")
        if did in covered_docs:
            continue
        if did not in first_seen_index:
            first_seen_index[did] = i
    priority_indices = set(first_seen_index.values())

    kept_order_indices: list[int] = list(mandatory_indices)
    skipped_oversize = 0

    # Pass 1: priority chunks (top chunk per doc, excluding already-covered)
    for i, (doc, _score) in enumerate(retrieved):
        if i not in priority_indices:
            continue
        tokens = _count_tokens(doc.page_content or "")
        if tokens > max_single_chunk and kept_order_indices:
            skipped_oversize += 1
            continue
        if used + tokens > chunk_budget:
            # Budget exhausted even for priority pass — stop
            break
        kept_order_indices.append(i)
        used += tokens

    # Pass 2: fill remaining budget with non-priority, non-mandatory chunks by rank
    excluded = priority_indices | set(mandatory_indices)
    for i, (doc, _score) in enumerate(retrieved):
        if i in excluded:
            continue
        tokens = _count_tokens(doc.page_content or "")
        if tokens > max_single_chunk and kept_order_indices:
            skipped_oversize += 1
            continue
        if used + tokens > chunk_budget:
            break
        kept_order_indices.append(i)
        used += tokens

    # Preserve rank order among kept chunks
    kept_order_indices.sort()
    kept = [retrieved[i] for i in kept_order_indices]

    if skipped_oversize:
        logger.info("Budget: skipped %d oversize chunks (>%d tokens)",
                    skipped_oversize, max_single_chunk)
    if len(kept) < len(retrieved):
        logger.info("Budget truncation (mandatory-aware): %d -> %d chunks (%d tokens / %d budget, %d mandatory)",
                    len(retrieved), len(kept), used, chunk_budget, len(mandatory_indices))
    return kept, used


def _reorder_for_attention(retrieved: list[tuple]) -> list[tuple]:
    """'Lost in the middle' mitigation: place best chunk at start, second-best
    at end, middle-ranked chunks in between. Research shows U-shape attention
    in LLMs — positions 0 and N get the most weight."""
    if len(retrieved) <= 2:
        return retrieved
    sorted_items = retrieved  # already sorted by score desc on entry
    best = sorted_items[0]
    second = sorted_items[1]
    middle = sorted_items[2:]
    return [best] + middle + [second]


def _rrf_merge_dual(
    raw_results: list[tuple],
    summary_results: list[tuple],
    k: int = 60,
) -> list[tuple]:
    """Merge raw-chunk and summary-chunk vector search results via Reciprocal Rank Fusion.

    Both retrievers produce cosine scores, but on different distributions:
    summary text is 5-8x shorter than raw chunks, so summary cosines skew high
    by compression — taking max(raw_cosine, summary_cosine) systematically
    favors summary matches even when the raw match is the better signal.

    RRF is scale-agnostic: each chunk's score is the sum of 1/(k+rank) from
    each retriever that found it. Chunks found by both retrievers get consensus
    credit. Same primitive as _rrf_merge_bm25 (SIGIR 2009, Cormack et al.).

    When a chunk is found by both retrievers, the raw Document object is kept
    (has full content); the score is the RRF sum.
    """
    rrf: dict[tuple, list] = {}  # (doc_id, chunk_index) -> [doc, rrf_score]

    for rank, (doc, _cosine) in enumerate(raw_results, 1):
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        rrf[key] = [doc, 1.0 / (k + rank)]

    for rank, (doc, _cosine) in enumerate(summary_results, 1):
        key = (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
        contribution = 1.0 / (k + rank)
        if key in rrf:
            rrf[key][1] += contribution  # consensus — keep raw doc object
        else:
            rrf[key] = [doc, contribution]

    merged = [(doc, score) for doc, score in rrf.values()]

    if merged:
        max_s = max(s for _, s in merged)
        if max_s > 0:
            merged = [(d, s / max_s) for d, s in merged]

    # Sort desc — downstream pipeline assumes this invariant.
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged


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
    registry=None,
    mapping_repo=None,
) -> RetrievalResult:
    """Full retrieval pipeline — single source of truth.

    Scoring constants come from the scoring profile (data/scoring_profiles/).
    Composite weights come from query_types.json.
    Feature flags come from .env / Settings.

    Returns a RetrievalResult with web_search_needed=True when the caller
    should fall back to web search (no retrieval results are populated in
    that case).
    """
    # Load scoring profile (cached), resolve after query analysis
    profile = load_scoring_profile(settings.scoring_profile)

    # 1. Analyze query
    analysis = await _analyze_query(question, llm)
    query_types = analysis["types"]
    query_label = analysis["label"]
    logger.info("Query analysis: types=%s label=%s — %r", query_types, query_label, question)
    primary_type = query_types[0]

    # Resolve scoring constants for this query type
    scoring = profile.for_query_type(primary_type)
    logger.info("Scoring profile: %s (query_type=%s)", profile.name, primary_type)

    # 1b. Router prefix — narrow broad scope before retrieval when enabled.
    # Fail-safe: router internally falls back to full scope on any error.
    if (
        settings.router_enabled
        and registry is not None
        and doc_ids
        and len(doc_ids) >= settings.router_min_scope
    ):
        from app.services.router import route_docs
        before = len(doc_ids)
        doc_ids = await route_docs(
            question=question,
            doc_ids=doc_ids,
            top_k=settings.router_top_k,
            llm=llm,
            registry=registry,
        )
        logger.info("Router prefix: %d -> %d docs", before, len(doc_ids))

    # 2. Label lookup
    label_chunks = []
    if query_label and doc_ids:
        label_chunks = _lookup_by_label(query_label, vector_store, doc_ids)
        if label_chunks:
            logger.info("Label lookup: found %d chunks for %r", len(label_chunks), query_label)

    # 3. Determine strategy from config (query_types.json)
    from app.services.query_types import load_query_types, get_type_config, get_strategy
    qt_config = load_query_types(settings.query_types_file)
    primary_cfg = get_type_config(qt_config, primary_type) or {}
    strategy_name = primary_cfg.get("strategy", "top_k")
    strategy = get_strategy(qt_config, strategy_name)
    fetch_k = int(top_k * strategy.get("fetch_multiplier", 1.5))
    logger.debug("[TRACE] top_k=%d fetch_k=%d strategy=%s doc_ids=%d",
                top_k, fetch_k, strategy_name,
                len(doc_ids) if doc_ids else 0)

    # 4. Vector search
    retrieved = vector_store.similarity_search_with_scores(
        question, k=fetch_k, doc_ids=doc_ids,
    )
    logger.debug("[TRACE] after vector_search: %d chunks", len(retrieved))

    # 4b. Summary index search (dual-index)
    if summary_store:
        try:
            summary_results = summary_store.similarity_search_with_scores(
                question, k=fetch_k, doc_ids=doc_ids,
            )
            if summary_results:
                before = len(retrieved)
                retrieved = _rrf_merge_dual(retrieved, summary_results,
                                            k=settings.rrf_k)
                logger.info("Dual-index: merged %d raw + %d summary -> %d results",
                           before, len(summary_results), len(retrieved))
        except Exception as e:
            logger.warning("Summary search failed: %s", e)

    # 4c. BM25 hybrid search (if enabled — Settings flag)
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
                bm25_docs = bm25.invoke(question)
                retrieved = _rrf_merge_bm25(retrieved, bm25_docs, k=settings.rrf_k)
        except Exception as e:
            logger.warning("BM25 hybrid search failed: %s", e)

    # 5. Query expansion
    _, retrieved = await _maybe_expand_query(
        question, retrieved, llm, vector_store, settings, doc_ids, top_k,
        fetch_k=fetch_k,
    )
    logger.debug("[TRACE] after query_expansion: %d chunks", len(retrieved))

    # 5b. Fact-query keyword expansion — bridges abstract query ↔ concrete
    # answer lexical gap (e.g., "parameter counts" → surface "7B"/"175B").
    if primary_type == "fact":
        retrieved = await _fact_keyword_expand(
            question, retrieved, llm, vector_store, doc_ids, fetch_k,
        )
        logger.debug("[TRACE] after fact_keyword_expand: %d chunks", len(retrieved))

    # Save pre-narrowing candidates for per-doc coverage backfill
    pre_narrow_candidates = list(retrieved)

    # 6. Type-specific strategies
    if strategy.get("text_only"):
        text_only = [(doc, score) for doc, score in retrieved
                     if doc.metadata.get("chunk_type") == "text"]
        retrieved = _section_aware_sample(text_only, top_k=top_k)
        logger.debug("[TRACE] after text_only+section_aware_sample: %d chunks", len(retrieved))
    elif strategy.get("demote_references"):
        retrieved = _demote_reference_results(retrieved, top_k)
        logger.debug("[TRACE] after demote_references: %d chunks", len(retrieved))

    # 6a. Multi-doc coverage guarantee — ONLY when the user EXPLICITLY scoped
    # to specific docs (request.doc_ids or collection). When user_isolation
    # auto-fills doc_ids from the user's entire corpus, we must not force
    # coverage for every doc — that would flood the context with chunks from
    # unrelated docs and break single-topic queries.
    if user_scoped:
        retrieved = _ensure_per_doc_coverage(
            retrieved, pre_narrow_candidates, doc_ids,
            question=question, vector_store=vector_store,
        )
        logger.debug("[TRACE] after per_doc_coverage: %d chunks", len(retrieved))

    # Scoring stage — constants from scoring profile, resolved for query type
    retrieved = _apply_reference_penalty(retrieved, scoring)
    retrieved = _apply_section_weights(retrieved, scoring)
    retrieved = _apply_boilerplate_penalty(retrieved, scoring)
    logger.debug("[TRACE] after scoring penalties: %d chunks", len(retrieved))

    # 6b. Reranking (if enabled — Settings flag)
    if settings.rerank_enabled:
        # Pass top_k so rerank doesn't throttle multi-doc queries.
        # For multi-doc scope: ensure at least ~3 chunks per selected doc so the
        # per-doc cap has material to work with.
        n_docs = len(doc_ids) if doc_ids else 0
        effective_top_n = max(top_k, n_docs * 3) if n_docs > 1 else top_k

        # Snapshot mandatory chunks before rerank — the reranker may drop low-
        # relevance backfills, but we must preserve per-doc coverage.
        pre_rerank_mandatory = {
            (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index")): (doc, score)
            for doc, score in retrieved
            if doc.metadata.get("_mandatory")
        }

        retrieved = await _rerank_results(
            retrieved, question, settings, llm, top_n=effective_top_n,
        )

        # Re-insert any mandatory chunks the reranker dropped.
        post_keys = {
            (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
            for doc, _ in retrieved
        }
        restored = 0
        for key, pair in pre_rerank_mandatory.items():
            if key not in post_keys:
                retrieved.append(pair)
                restored += 1
        if restored:
            logger.info("Restored %d mandatory chunks dropped by reranker", restored)
        logger.debug("[TRACE] after rerank (top_n=%d): %d chunks", effective_top_n, len(retrieved))

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
        logger.debug("[TRACE] after visual_proximity: %d chunks", len(retrieved))

    # 9. Graph expansion (decay from scoring profile)
    retrieved = await _expand_via_edges(
        retrieved, edge_repo, vector_store, scoring,
        relations=["describes", "references"],
    )
    logger.debug("[TRACE] after graph_expansion: %d chunks", len(retrieved))

    # 10. Composite scoring (weights from query_types.json, graph math from profile)
    retrieved = await _apply_composite_scoring(
        retrieved, edge_repo, primary_type, settings, scoring,
    )
    logger.debug("[TRACE] after composite_scoring: %d chunks", len(retrieved))

    # 11. Confidence tier (from raw scores, before normalization)
    confidence_tier = _compute_confidence_tier(retrieved, profile)

    # 12. Sort + normalize
    retrieved.sort(key=lambda x: x[1], reverse=True)
    retrieved = _normalize_scores(retrieved, profile)

    # 13. Prepend label chunks
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

    chunks_available = len(retrieved)

    # 14. Per-doc cap (multi-doc scope only)
    # Count unique docs in retrieved set
    unique_docs = len({doc.metadata.get("doc_id") for doc, _ in retrieved})
    retrieved = _apply_per_doc_cap(retrieved, unique_docs, top_k)

    # 15. Token budget enforcement — greedy fill until budget reached
    chunk_budget, history_budget, total_input_budget = _compute_context_budget(
        question, chat_history, primary_type, settings,
    )
    retrieved, tokens_used = _apply_token_budget(retrieved, chunk_budget)

    # 16. Strategic placement — mitigate "lost in the middle"
    # (Apply only to non-label chunks; labels stay at front for priority)
    if label_chunks and retrieved:
        # Keep label chunks at front, reorder the rest
        n_label = sum(1 for doc, _ in retrieved
                      if (doc.metadata.get("doc_id"), doc.metadata.get("chunk_index"))
                      in {(c.metadata.get("doc_id"), c.metadata.get("chunk_index")) for c in label_chunks})
        if len(retrieved) > n_label + 2:
            retrieved = retrieved[:n_label] + _reorder_for_attention(retrieved[n_label:])
    else:
        retrieved = _reorder_for_attention(retrieved)

    # 17. Deanonymize at retrieval boundary (Phase 5).
    # Replaces pseudonyms with original PII in both the LLM context and the
    # API response (sources). The vector store retains pseudonymized text.
    # mapping_repo is None when anonymization is disabled or unavailable.
    if settings.anonymization_enabled and mapping_repo is not None:
        from app.services.deanonymize import deanonymize_chunks

        chunk_doc_ids = list({
            c.metadata.get("doc_id")
            for c, _ in retrieved
            if c.metadata.get("doc_id")
        })
        if chunk_doc_ids:
            mappings_by_doc = await mapping_repo.get_by_docs(chunk_doc_ids)
            if mappings_by_doc:
                deanon_docs = deanonymize_chunks(
                    [c for c, _ in retrieved], mappings_by_doc
                )
                retrieved = list(zip(deanon_docs, (s for _, s in retrieved)))
                # Only log when at least one doc actually had mappings to apply —
                # get_by_docs pre-populates empty dicts for legacy/PII-free docs.
                if any(mappings_by_doc.get(d) for d in chunk_doc_ids):
                    logger.info("Deanonymized %d chunks at retrieval boundary", len(retrieved))

    sources = _build_source_chunks(retrieved)

    logger.info(
        "Context budget: %d chunks (%d tokens / %d budget), query=%s",
        len(retrieved), tokens_used, chunk_budget, primary_type,
    )

    return RetrievalResult(
        sources=sources,
        retrieved=retrieved,
        query_types=query_types,
        query_label=query_label,
        chat_history=chat_history,
        confidence_tier=confidence_tier,
        context_used_tokens=tokens_used,
        context_budget_tokens=chunk_budget,
        context_mode="chunks",  # phase 3 will add "summary" fallback
        chunks_included=len(retrieved),
        chunks_available=chunks_available,
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
