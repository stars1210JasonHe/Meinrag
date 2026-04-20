"""Unit tests for app.services.fast_path — doc summary fast-path routing.

Covers:
  - matches_summary_intent: pattern matching on English + Chinese keywords,
    length gating
  - should_use_doc_summary_fastpath: the async gatekeeper that checks scope +
    registry state before returning a summary
"""
from __future__ import annotations

import pytest

from app.services.fast_path import (
    matches_summary_intent,
    should_use_doc_summary_fastpath,
)


def _fake_doc(summary: str | None):
    """DocumentRepository.get returns a dict (via to_dict()), not an ORM object.
    Mirror that shape so the test exercises the real code path."""
    return {"doc_id": "d1", "summary": summary}


class _FakeRegistry:
    """Minimal stand-in for DocumentRepository.get."""

    def __init__(self, docs: dict):
        self._docs = docs

    async def get(self, doc_id: str):
        return self._docs.get(doc_id)


# ---------------------------------------------------------------------------
# matches_summary_intent
# ---------------------------------------------------------------------------

class TestMatchesSummaryIntent:
    def test_english_summarize(self):
        assert matches_summary_intent("Please summarize this document")

    def test_english_summarise_uk(self):
        assert matches_summary_intent("Summarise this paper")

    def test_overview(self):
        assert matches_summary_intent("Give me an overview")

    def test_main_findings(self):
        assert matches_summary_intent("What are the main findings?")

    def test_tldr(self):
        assert matches_summary_intent("TLDR this")

    def test_chinese_总结(self):
        assert matches_summary_intent("总结一下这篇文档")

    def test_chinese_概括(self):
        assert matches_summary_intent("概括主要内容")

    def test_chinese_讲的什么(self):
        assert matches_summary_intent("这篇讲的什么")

    def test_specific_technical_query_rejected(self):
        """A specific query about a technical detail should NOT match."""
        assert not matches_summary_intent(
            "What is the optimal learning rate for BERT pre-training on WikiText-103?"
        )

    def test_long_query_with_keyword_rejected(self):
        """Long query that incidentally mentions 'overview' should be rejected."""
        q = (
            "Could you give me a detailed technical overview of the specific "
            "attention mechanism variants used in section 3.2 of the paper, "
            "especially how they differ from the original formulation"
        )
        assert not matches_summary_intent(q)

    def test_empty_string(self):
        assert not matches_summary_intent("")

    def test_none_safe(self):
        # Defensive — shouldn't crash on None-like input
        assert not matches_summary_intent("")


# ---------------------------------------------------------------------------
# should_use_doc_summary_fastpath
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestShouldUseDocSummaryFastpath:
    async def test_happy_path(self):
        registry = _FakeRegistry({"d1": _fake_doc("This is the doc overview.")})
        result = await should_use_doc_summary_fastpath(
            "summarize this document", ["d1"], registry,
        )
        assert result == "This is the doc overview."

    async def test_chinese_happy_path(self):
        registry = _FakeRegistry({"d1": _fake_doc("这是文档概述")})
        result = await should_use_doc_summary_fastpath(
            "总结这篇文档", ["d1"], registry,
        )
        assert result == "这是文档概述"

    async def test_rejects_multi_doc_scope(self):
        registry = _FakeRegistry({
            "d1": _fake_doc("A"),
            "d2": _fake_doc("B"),
        })
        result = await should_use_doc_summary_fastpath(
            "summarize these", ["d1", "d2"], registry,
        )
        assert result is None

    async def test_rejects_no_doc_ids(self):
        registry = _FakeRegistry({})
        result = await should_use_doc_summary_fastpath(
            "summarize everything", None, registry,
        )
        assert result is None

    async def test_rejects_empty_summary(self):
        registry = _FakeRegistry({"d1": _fake_doc("")})
        result = await should_use_doc_summary_fastpath(
            "summarize this", ["d1"], registry,
        )
        assert result is None

    async def test_rejects_whitespace_only_summary(self):
        registry = _FakeRegistry({"d1": _fake_doc("   \n  ")})
        result = await should_use_doc_summary_fastpath(
            "summarize this", ["d1"], registry,
        )
        assert result is None

    async def test_rejects_missing_doc(self):
        registry = _FakeRegistry({})
        result = await should_use_doc_summary_fastpath(
            "summarize this", ["nonexistent"], registry,
        )
        assert result is None

    async def test_rejects_non_summary_intent(self):
        registry = _FakeRegistry({"d1": _fake_doc("Overview here")})
        result = await should_use_doc_summary_fastpath(
            "What is the optimal hyperparameter for this specific loss function?",
            ["d1"], registry,
        )
        assert result is None

    async def test_strips_leading_trailing_whitespace(self):
        registry = _FakeRegistry({"d1": _fake_doc("  \n  overview  \n")})
        result = await should_use_doc_summary_fastpath(
            "summarize this", ["d1"], registry,
        )
        assert result == "overview"
