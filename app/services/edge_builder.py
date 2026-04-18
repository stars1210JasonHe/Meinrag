"""Build edges between chunks for graph-based retrieval."""
import logging
import re
from collections import defaultdict

import numpy as np
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

_VISUAL_TYPES = {"image", "table", "formula"}
_LABEL_PATTERN = re.compile(
    r'(?:Table|Figure|Fig\.|Equation|Eq\.)\s+\d+(?:\.\d+)*',
    re.IGNORECASE,
)


def build_intra_doc_edges(
    chunks: list[Document],
    doc_id: str,
    embeddings: dict[int, np.ndarray] | None = None,
    describes_threshold: float = 0.5,
) -> list[dict]:
    """Build edges between chunks within a single document.

    Args:
        chunks: List of Document chunks (must have chunk_index, page, chunk_type in metadata).
        doc_id: Document ID.
        embeddings: Optional dict of chunk_index -> embedding vector for describes edges.
        describes_threshold: Cosine similarity threshold for describes edges.

    Returns:
        List of edge dicts with keys: source_doc_id, source_chunk_index,
        target_doc_id, target_chunk_index, relation, score.
    """
    if not chunks:
        return []

    edges = []

    # Sort by chunk_index
    sorted_chunks = sorted(chunks, key=lambda c: c.metadata.get("chunk_index", 0))

    # --- follows edges ---
    for i in range(len(sorted_chunks) - 1):
        curr = sorted_chunks[i].metadata
        nxt = sorted_chunks[i + 1].metadata
        edges.append({
            "source_doc_id": doc_id,
            "source_chunk_index": curr["chunk_index"],
            "target_doc_id": doc_id,
            "target_chunk_index": nxt["chunk_index"],
            "relation": "follows",
            "score": None,
        })

    # --- co_located edges (same page, different chunks) ---
    page_groups = defaultdict(list)
    for chunk in chunks:
        page = chunk.metadata.get("page")
        if page is not None:
            page_groups[page].append(chunk)

    for page, group in page_groups.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                ci = group[i].metadata["chunk_index"]
                cj = group[j].metadata["chunk_index"]
                edges.append({
                    "source_doc_id": doc_id,
                    "source_chunk_index": ci,
                    "target_doc_id": doc_id,
                    "target_chunk_index": cj,
                    "relation": "co_located",
                    "score": None,
                })

    # --- describes edges (visual <-> text on same/adjacent page) ---
    if embeddings:
        text_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "text"]
        visual_chunks = [c for c in chunks if c.metadata.get("chunk_type") in _VISUAL_TYPES]

        for vc in visual_chunks:
            vpage = vc.metadata.get("page")
            vidx = vc.metadata.get("chunk_index")
            if vpage is None or vidx not in embeddings:
                continue

            for tc in text_chunks:
                tpage = tc.metadata.get("page")
                tidx = tc.metadata.get("chunk_index")
                if tpage is None or tidx not in embeddings:
                    continue
                if abs(tpage - vpage) > 1:
                    continue

                # Cosine similarity
                v_emb = embeddings[vidx]
                t_emb = embeddings[tidx]
                cos = float(np.dot(v_emb, t_emb) / (np.linalg.norm(v_emb) * np.linalg.norm(t_emb) + 1e-10))

                if cos >= describes_threshold:
                    edges.append({
                        "source_doc_id": doc_id,
                        "source_chunk_index": tidx,
                        "target_doc_id": doc_id,
                        "target_chunk_index": vidx,
                        "relation": "describes",
                        "score": round(cos, 4),
                    })

    # --- references edges (text mentions label -> visual with that label) ---
    label_chunks = {}
    for chunk in chunks:
        label = chunk.metadata.get("label")
        if label:
            label_chunks[label.lower()] = chunk.metadata["chunk_index"]

    if label_chunks:
        for chunk in chunks:
            if chunk.metadata.get("chunk_type") != "text":
                continue
            for match in _LABEL_PATTERN.finditer(chunk.page_content):
                ref_label = match.group(0).lower()
                if ref_label in label_chunks:
                    target_idx = label_chunks[ref_label]
                    source_idx = chunk.metadata["chunk_index"]
                    if source_idx != target_idx:
                        edges.append({
                            "source_doc_id": doc_id,
                            "source_chunk_index": source_idx,
                            "target_doc_id": doc_id,
                            "target_chunk_index": target_idx,
                            "relation": "references",
                            "score": None,
                        })

    logger.info("Built %d intra-doc edges for %s (follows=%d, co_located=%d, describes=%d, references=%d)",
                len(edges), doc_id,
                sum(1 for e in edges if e["relation"] == "follows"),
                sum(1 for e in edges if e["relation"] == "co_located"),
                sum(1 for e in edges if e["relation"] == "describes"),
                sum(1 for e in edges if e["relation"] == "references"))
    return edges


def build_cross_doc_edges(
    doc_id: str,
    chunks: list[Document],
    vector_store,
    top_k: int = 5,
    min_score: float = 0.6,
) -> list[dict]:
    """Build similar_to edges between this document's chunks and other documents.

    Uses FAISS ANN to find top-K nearest neighbors for each chunk. Only edges
    with cosine similarity >= min_score are kept — lower scores are noise from
    top-K's greedy fill (embeddings naturally cluster in [0.2, 0.8] so even
    unrelated chunks show up in top-K).

    Affects downstream retrieval: edges feed into composite graph_score and
    graph expansion, so the threshold gates both visualization and signal.
    """
    edges = []
    seen = set()
    below_threshold = 0

    for chunk in chunks:
        cidx = chunk.metadata.get("chunk_index")
        try:
            results = vector_store.similarity_search_with_scores(
                chunk.page_content, k=top_k + 5,
            )
            count = 0
            for doc, score in results:
                target_doc_id = doc.metadata.get("doc_id")
                target_idx = doc.metadata.get("chunk_index")
                # Skip self
                if target_doc_id == doc_id and target_idx == cidx:
                    continue
                # Threshold — drop weak matches
                if score < min_score:
                    below_threshold += 1
                    continue
                # Dedup
                key = (doc_id, cidx, target_doc_id, target_idx)
                if key in seen:
                    continue
                seen.add(key)

                edges.append({
                    "source_doc_id": doc_id,
                    "source_chunk_index": cidx,
                    "target_doc_id": target_doc_id,
                    "target_chunk_index": target_idx,
                    "relation": "similar_to",
                    "score": round(float(score), 4),
                })
                count += 1
                if count >= top_k:
                    break
        except Exception as e:
            logger.warning("Cross-doc edge build failed for chunk %d: %s", cidx, e)

    logger.info(
        "Built %d cross-doc similar_to edges for %s (dropped %d below score %.2f)",
        len(edges), doc_id, below_threshold, min_score,
    )
    return edges
