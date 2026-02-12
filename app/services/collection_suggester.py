import json
import logging

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel

from app.classification import TAXONOMY, PRIMARY_CATEGORIES

logger = logging.getLogger(__name__)

SUGGESTION_PROMPT = """\
You are a document classifier. Analyze the document excerpt below and classify it using the provided taxonomy.

## Taxonomy (Primary Category → Domains)
{taxonomy_text}

## Existing custom collections in the system
{existing_collections}

## Rules
1. Pick exactly 1 primary category from the taxonomy above.
2. Pick 1-2 domains from that category (or from a second category if the document spans topics).
3. Return ONLY a JSON array of collection names, e.g. ["legal-compliance", "contracts-agreements"]
4. Use only lowercase, hyphen-separated names.
5. You may include ONE custom collection name if the document clearly doesn't fit the taxonomy.

## Document excerpt
{content}

JSON array:"""


def _build_taxonomy_text() -> str:
    """Format taxonomy as compact text for the prompt."""
    lines = []
    for category, domains in TAXONOMY.items():
        domain_names = ", ".join(domains.keys())
        lines.append(f"- {category}: [{domain_names}]")
    return "\n".join(lines)


def suggest_collections(
    chunks: list[Document],
    llm: BaseChatModel,
    existing_collections: list[str] | None = None,
) -> list[str]:
    """Analyze document content and suggest collection names from the taxonomy."""
    # Take first 3 chunks or ~1500 chars
    content = "\n\n".join([c.page_content for c in chunks[:3]])
    content = content[:1500]

    existing = ", ".join(existing_collections) if existing_collections else "(none)"

    try:
        response = llm.invoke(
            SUGGESTION_PROMPT.format(
                taxonomy_text=_build_taxonomy_text(),
                existing_collections=existing,
                content=content,
            )
        )
        raw = response.content.strip()
    except Exception as e:
        logger.error(f"LLM classification failed: {e}")
        return ["other"]

    # Parse JSON array from response
    try:
        # Handle cases where LLM wraps in markdown code block
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        suggestions = json.loads(raw)
        if isinstance(suggestions, list):
            # Clean and validate
            cleaned = []
            for s in suggestions:
                s = str(s).strip().lower().replace(" ", "-").replace('"', "").replace("'", "")
                if s and len(s) <= 50:
                    cleaned.append(s)
            if cleaned:
                return cleaned
    except (json.JSONDecodeError, IndexError):
        pass

    # Fallback: try to extract from raw text
    raw_clean = raw.replace('"', '').replace("'", '').replace('.', '').replace(' ', '-').lower()
    # Check if it matches a primary category
    for cat in PRIMARY_CATEGORIES:
        if cat in raw_clean:
            return [cat]

    return ["other"]
