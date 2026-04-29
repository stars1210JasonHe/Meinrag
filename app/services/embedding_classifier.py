"""Embedding-based document classification.

Embeds taxonomy category/domain descriptions once (cached), then classifies
documents by cosine similarity against those embeddings.  Much faster and
cheaper than the LLM-based path, with deterministic results.
"""

import logging
import re
import threading
from dataclasses import dataclass

import numpy as np
from langchain_core.embeddings import Embeddings

from app.classification import TAXONOMY

logger = logging.getLogger(__name__)

# ── thresholds ───────────────────────────────────────────────────────────
CATEGORY_THRESHOLD = 0.18  # min raw cosine for primary category match
DOMAIN_THRESHOLD = 0.15    # min raw cosine for domain selection
MAX_DOMAINS = 2

# ── taxonomy embedding cache ─────────────────────────────────────────────

@dataclass
class TaxonomyEmbeddings:
    """Pre-computed embeddings for every category and domain."""
    category_names: list[str]
    category_vectors: np.ndarray   # (n_categories, dim)
    domain_names: list[str]        # flat list across all categories
    domain_categories: list[str]   # parallel list: which category each domain belongs to
    domain_vectors: np.ndarray     # (n_domains, dim)


_cache: dict[str, TaxonomyEmbeddings] = {}
_lock = threading.Lock()


def _build_category_description(category: str, domains: dict[str, list[str]]) -> str:
    """Rich text describing a primary category for embedding."""
    domain_names = " ".join(d.replace("-", " ") for d in domains)
    examples = []
    for subs in domains.values():
        examples.extend(s.replace("-", " ") for s in subs[:2])
    example_text = ", ".join(examples[:6])
    return f"{category.replace('-', ' ')}: {domain_names}. Examples: {example_text}"


def _build_domain_description(category: str, domain: str, sub_domains: list[str]) -> str:
    """Rich text describing a domain for embedding."""
    subs = ", ".join(s.replace("-", " ") for s in sub_domains)
    return f"{category.replace('-', ' ')} > {domain.replace('-', ' ')}: {subs}"


def _get_taxonomy_embeddings(embeddings: Embeddings) -> TaxonomyEmbeddings:
    """Return cached taxonomy embeddings, computing on first call."""
    key = type(embeddings).__name__
    if key in _cache:
        return _cache[key]

    with _lock:
        if key in _cache:
            return _cache[key]

        cat_names: list[str] = []
        cat_texts: list[str] = []
        dom_names: list[str] = []
        dom_cats: list[str] = []
        dom_texts: list[str] = []

        for category, domains in TAXONOMY.items():
            if category == "other":
                continue
            cat_names.append(category)
            cat_texts.append(_build_category_description(category, domains))
            for domain, subs in domains.items():
                dom_names.append(domain)
                dom_cats.append(category)
                dom_texts.append(_build_domain_description(category, domain, subs))

        cat_vecs = np.array(embeddings.embed_documents(cat_texts), dtype=np.float32)
        dom_vecs = np.array(embeddings.embed_documents(dom_texts), dtype=np.float32)

        result = TaxonomyEmbeddings(
            category_names=cat_names,
            category_vectors=cat_vecs,
            domain_names=dom_names,
            domain_categories=dom_cats,
            domain_vectors=dom_vecs,
        )
        _cache[key] = result
        logger.info("Taxonomy embeddings cached (%d categories, %d domains)", len(cat_names), len(dom_names))
        return result


def _cosine_similarity(query: np.ndarray, targets: np.ndarray) -> np.ndarray:
    """Cosine similarity between a single query vector and a matrix of targets."""
    # Normalise
    q_norm = query / (np.linalg.norm(query) + 1e-10)
    t_norms = targets / (np.linalg.norm(targets, axis=1, keepdims=True) + 1e-10)
    return t_norms @ q_norm


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting noise that dilutes semantic signal."""
    # Remove code fences
    text = re.sub(r"```\w*\n?", "", text)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}|_{1,3}", "", text)
    # Remove markdown headings markers (keep the text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Remove LaTeX commands like \textsuperscript{...}, \textbf{...}
    text = re.sub(r"\\(?:textsuperscript|textbf|textit|mathrm|mathbf)\{([^}]*)\}", r"\1", text)
    # Remove <sup>...</sup>, <sub>...</sub> tags
    text = re.sub(r"</?(?:sup|sub|br|em|strong|b|i)>", "", text)
    # Remove image references ![...](...) and links [...](...) — keep link text
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_smart_sample(chunks) -> str:
    """Build a classification-friendly text sample from document chunks.

    Uses filename + first chunk + second chunk + last chunk, capped at 2000 chars.
    Strips markdown formatting to boost semantic signal for embeddings.
    """
    if not chunks:
        return ""

    parts: list[str] = []

    # Filename — often the strongest signal
    filename = chunks[0].metadata.get("source_file", "")
    if filename:
        clean_name = re.sub(r"[_\-.]", " ", filename)
        clean_name = re.sub(r"\s+", " ", clean_name).strip()
        parts.append(clean_name)

    # First chunk (title / abstract area)
    if len(chunks) >= 1:
        parts.append(_strip_markdown(chunks[0].page_content[:800])[:600])

    # Second chunk (intro / methodology)
    if len(chunks) >= 2:
        parts.append(_strip_markdown(chunks[1].page_content[:600])[:400])

    # Last chunk (conclusion / references area)
    if len(chunks) >= 3:
        parts.append(_strip_markdown(chunks[-1].page_content[:600])[:400])

    sample = "\n\n".join(parts)
    return sample[:2000]


def classify_by_embedding(
    chunks,
    embeddings: Embeddings,
    category_threshold: float = CATEGORY_THRESHOLD,
    domain_threshold: float = DOMAIN_THRESHOLD,
):
    """Classify document chunks using embedding cosine similarity.

    Returns a ``ClassificationResult`` (primary_category + subtags), or ``None``
    if confidence is below *category_threshold* (caller should fall back to LLM).
    The embedding path never proposes user collections.
    """
    from app.services.collection_suggester import ClassificationResult

    sample = _extract_smart_sample(chunks)
    if not sample.strip():
        return None

    tax = _get_taxonomy_embeddings(embeddings)

    query_vec = np.array(embeddings.embed_query(sample), dtype=np.float32)

    # ── category match ───────────────────────────────────────────────
    cat_scores = _cosine_similarity(query_vec, tax.category_vectors)
    best_cat_idx = int(np.argmax(cat_scores))
    best_cat_score = float(cat_scores[best_cat_idx])

    if best_cat_score < category_threshold:
        logger.debug("Embedding classifier: best category score %.3f < threshold %.3f",
                      best_cat_score, category_threshold)
        return None

    best_category = tax.category_names[best_cat_idx]

    # ── domain match (within winning category) ───────────────────────
    subtags: list[str] = []
    domain_indices = [i for i, c in enumerate(tax.domain_categories) if c == best_category]
    if domain_indices:
        dom_vecs = tax.domain_vectors[domain_indices]
        dom_scores = _cosine_similarity(query_vec, dom_vecs)

        ranked = sorted(enumerate(dom_scores), key=lambda x: x[1], reverse=True)
        for local_idx, score in ranked[:MAX_DOMAINS]:
            if score >= domain_threshold:
                global_idx = domain_indices[local_idx]
                subtags.append(tax.domain_names[global_idx])

    logger.info(
        "Embedding classifier: primary=%s subtags=%s (score=%.3f)",
        best_category, subtags, best_cat_score,
    )
    return ClassificationResult(
        primary_category=best_category,
        subtags=subtags,
    )


def clear_cache() -> None:
    """Clear cached taxonomy embeddings (for tests)."""
    with _lock:
        _cache.clear()
