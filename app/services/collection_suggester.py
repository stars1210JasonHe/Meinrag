"""Document classification — structured 3-layer output.

Returns a ``ClassificationResult`` with:
- ``primary_category``: one of ``PRIMARY_CATEGORIES`` (or ``None`` when uncertain)
- ``subtags``: validated against ``ALL_TAGS`` (taxonomy domains + sub-domains)
- ``collection_suggestions``: subset of existing user-curated collections only
  (the classifier never invents new collection names — that's the user's job)
"""
import json
import logging
from dataclasses import dataclass, field

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from app.classification import TAXONOMY, PRIMARY_CATEGORIES, ALL_TAGS

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    primary_category: str | None = None
    subtags: list[str] = field(default_factory=list)
    collection_suggestions: list[str] = field(default_factory=list)


SUGGESTION_PROMPT = """\
You are a document classifier. Analyze the document filename and excerpt below and return a structured JSON classification.

## Taxonomy (Primary Category → Domains → Sub-domains)
{taxonomy_text}

## Existing user-curated collections (you may suggest these; never invent new ones)
{existing_collections}

## Output schema (return ONLY this JSON, no prose)
{{
  "primary_category": "<one of the primary categories above, or null if none fits>",
  "subtags": ["<domain or sub-domain>", "..."],
  "collection_suggestions": ["<existing user collection that clearly fits>", "..."]
}}

## Rules
1. ``primary_category`` is the single best top-level fit. Use ``null`` rather than guessing.
2. ``subtags`` is 1-4 domain or sub-domain names from the taxonomy. Lowercase, hyphen-separated.
3. ``collection_suggestions`` MUST be a subset of the existing user collections listed above. If none fits, return ``[]``.
4. The filename often signals the field — pay attention.

## Filename
{filename}

## Document excerpt
{content}

JSON:"""


def _build_taxonomy_text() -> str:
    """Format taxonomy with primary → domains → sub-domains for the prompt."""
    lines = []
    for category, domains in TAXONOMY.items():
        domain_lines = []
        for domain, subs in domains.items():
            sub_text = ", ".join(subs) if subs else ""
            domain_lines.append(f"  - {domain}: [{sub_text}]")
        lines.append(f"- {category}:\n" + "\n".join(domain_lines))
    return "\n".join(lines)


def _validate(
    raw: dict, existing_collections: list[str] | None,
) -> ClassificationResult:
    """Coerce LLM output into a clean ``ClassificationResult``."""
    primary = raw.get("primary_category")
    if not isinstance(primary, str) or primary not in PRIMARY_CATEGORIES:
        primary = None

    subtags_raw = raw.get("subtags") or []
    subtags: list[str] = []
    if isinstance(subtags_raw, list):
        for s in subtags_raw:
            if not isinstance(s, str):
                continue
            s = s.strip().lower()
            if s in ALL_TAGS and s not in subtags:
                subtags.append(s)

    suggestions_raw = raw.get("collection_suggestions") or []
    existing_set = {c.lower() for c in (existing_collections or [])}
    suggestions: list[str] = []
    if isinstance(suggestions_raw, list):
        for s in suggestions_raw:
            if isinstance(s, str) and s.lower() in existing_set and s not in suggestions:
                suggestions.append(s)

    return ClassificationResult(
        primary_category=primary,
        subtags=subtags,
        collection_suggestions=suggestions,
    )


def classify_document(
    chunks: list[Document],
    llm: BaseChatModel,
    existing_collections: list[str] | None = None,
    embeddings: Embeddings | None = None,
) -> ClassificationResult:
    """Classify a document into primary category + sub-tags + collection suggestions.

    Tries the embedding-based classifier first (fast, deterministic). Falls back
    to the LLM path on low confidence or error. The LLM never invents new
    collection names — only existing ones from *existing_collections* are valid
    suggestions.
    """
    # ── fast path: embedding cosine similarity ───────────────────────
    if embeddings is not None:
        try:
            from app.services.embedding_classifier import classify_by_embedding
            result = classify_by_embedding(chunks, embeddings)
            if result is not None and result.primary_category is not None:
                logger.info(
                    "Embedding classifier: primary=%s subtags=%s",
                    result.primary_category, result.subtags,
                )
                return result
            logger.debug("Embedding classifier returned no primary, falling back to LLM")
        except Exception:
            logger.warning("Embedding classifier failed, falling back to LLM", exc_info=True)

    # ── LLM path ────────────────────────────────────────────────────
    content = "\n\n".join(c.page_content for c in chunks[:3])[:1500]
    filename = chunks[0].metadata.get("source_file", "unknown") if chunks else "unknown"
    existing = ", ".join(existing_collections) if existing_collections else "(none)"

    try:
        response = llm.invoke(
            SUGGESTION_PROMPT.format(
                taxonomy_text=_build_taxonomy_text(),
                existing_collections=existing,
                filename=filename,
                content=content,
            )
        )
        raw_text = response.content.strip()
    except Exception as e:
        logger.error("LLM classification failed: %s", e)
        return ClassificationResult()

    # Strip markdown code fences if present
    if "```" in raw_text:
        parts = raw_text.split("```")
        if len(parts) >= 2:
            raw_text = parts[1]
            if raw_text.lstrip().lower().startswith("json"):
                raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[4:]
            raw_text = raw_text.strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Could not parse LLM classification JSON: %s", raw_text[:200])
        return ClassificationResult()

    if not isinstance(parsed, dict):
        return ClassificationResult()

    return _validate(parsed, existing_collections)
