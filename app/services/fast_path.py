"""Fast-path routing for queries answerable from pre-computed doc-level
summaries.

When a user asks a clear summarization question about a single document that
has a populated `documents.summary` column, we can skip full retrieval and
feed the doc summary + a handful of supporting chunks to the LLM directly.

Value: faster, cheaper, and usually more coherent than top-K chunk synthesis
for overview-type questions.

Trigger conditions (ALL required):
    1. Exactly one doc_id in scope
    2. The doc exists and has a non-empty `summary` field
    3. Question matches summarization intent (English + Chinese keywords)
    4. Question is short (< 20 words) — filters out complex multi-hop queries
       that only incidentally mention "overview"
"""
from __future__ import annotations

import re

# Case-insensitive. Catches English and Chinese summarization intent.
# Not exhaustive — stays strict to avoid misrouting semantic queries.
_SUMMARY_INTENT_RE = re.compile(
    r"\b(summari[sz]e|overview|brief(?:ly)?|main\s+(?:idea|point|finding)s?|"
    r"what\s+is\s+this|what.s\s+this\s+(?:doc|paper|book|about)|about\s+what|"
    r"tl;?dr|gist)\b"
    r"|总结|概括|简介|摘要|大意|讲的什么|讲了什么|主要内容|主旨",
    re.IGNORECASE,
)

_MAX_WORDS = 20


def matches_summary_intent(question: str) -> bool:
    """True if the question looks like a summarization request."""
    if not question:
        return False
    # Length gate — chunk-count heuristic for CJK + word count for Latin.
    # A "short" CJK query is < ~60 chars; short English query is < 20 words.
    words = question.split()
    if len(words) >= _MAX_WORDS and len(question) >= 60:
        return False
    return bool(_SUMMARY_INTENT_RE.search(question))


async def should_use_doc_summary_fastpath(
    question: str,
    doc_ids: list[str] | None,
    registry,
) -> str | None:
    """Return the doc summary if all fast-path conditions hold, else None.

    Conditions:
        - Exactly one doc_id in scope
        - Doc exists in registry
        - Doc has a non-empty `summary` field
        - Question matches summarization intent + length gate

    Returns:
        doc.summary string if fast-path should fire, else None.
    """
    if not doc_ids or len(doc_ids) != 1:
        return None
    if not matches_summary_intent(question):
        return None

    doc = await registry.get(doc_ids[0])
    if not doc:
        return None
    # registry.get() returns a dict (via to_dict()), not an ORM object
    summary = doc.get("summary") if isinstance(doc, dict) else getattr(doc, "summary", None)
    if not summary or not summary.strip():
        return None

    return summary.strip()
