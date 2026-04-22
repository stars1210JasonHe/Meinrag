"""Unit tests for app/services/router.py."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.rag.prompts import ROUTER_PROMPT


class TestRouterPrompt:
    def test_prompt_renders_with_question_and_menu(self):
        rendered = ROUTER_PROMPT.format_messages(
            question="What is the parameter count of Llama?",
            doc_menu="[d1] Llama paper — Meta's open foundation model family\n"
                     "[d2] GPT-3 paper — Few-shot learners",
            top_k=2,
        )
        # System + human message
        assert len(rendered) == 2
        combined = rendered[0].content + rendered[1].content
        assert "Llama" in combined
        assert "[d1]" in combined
        assert "2" in combined


class _FakeRegistry:
    """Minimal stub that mimics DocumentRepository.get(doc_id) -> dict|None."""
    def __init__(self, docs: dict[str, dict]):
        self._docs = docs

    async def get(self, doc_id: str) -> dict | None:
        return self._docs.get(doc_id)


@pytest.mark.asyncio
class TestRouteDocsHappyPath:
    async def test_llm_picks_subset_of_scope(self):
        from app.services.router import route_docs

        registry = _FakeRegistry({
            "d1": {"doc_id": "d1", "source_file": "llama.pdf",
                   "summary": "Llama foundation model"},
            "d2": {"doc_id": "d2", "source_file": "gpt3.pdf",
                   "summary": "GPT-3 few-shot"},
            "d3": {"doc_id": "d3", "source_file": "bert.pdf",
                   "summary": "BERT pretraining"},
        })
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"doc_ids": ["d1", "d2"]}'),
        )

        result = await route_docs(
            question="What are Llama and GPT-3 parameter counts?",
            doc_ids=["d1", "d2", "d3"],
            top_k=2,
            llm=llm,
            registry=registry,
        )
        assert result == ["d1", "d2"]
        # Only one LLM call
        assert llm.ainvoke.await_count == 1

    async def test_filename_key_renders_in_menu(self):
        """Real DocumentRepository.get() returns 'filename', not 'source_file'.
        Verify the menu still shows the filename for either key.
        """
        from app.services.router import route_docs, _format_doc_menu

        docs = [
            {"doc_id": "d1", "filename": "llama.pdf", "summary": "Llama"},
            {"doc_id": "d2", "source_file": "gpt3.pdf", "summary": "GPT-3"},
        ]
        menu = _format_doc_menu(docs)
        assert "llama.pdf" in menu
        assert "gpt3.pdf" in menu


class TestFormatDocMenu:
    """Pure-function tests for _format_doc_menu."""

    def test_long_summary_is_truncated(self):
        """Summaries >180 chars truncate with an ellipsis."""
        from app.services.router import _format_doc_menu

        docs = [
            {"doc_id": "d1", "filename": "big.pdf",
             "summary": "x" * 300},
        ]
        menu = _format_doc_menu(docs)
        assert "..." in menu
        # Line should be: [d1] big.pdf — <truncated summary>...
        # Truncated summary = 177 chars + "..."
        # Total line length is bounded ~205 chars
        assert len(menu) < 220


@pytest.mark.asyncio
class TestRouteDocsFailureModes:
    async def _registry(self):
        return _FakeRegistry({
            "d1": {"doc_id": "d1", "source_file": "a.pdf", "summary": "A"},
            "d2": {"doc_id": "d2", "source_file": "b.pdf", "summary": "B"},
        })

    async def test_malformed_json_falls_back(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="not json at all"),
        )
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1", "d2"]

    async def test_empty_doc_ids_list_falls_back(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"doc_ids": []}'),
        )
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1", "d2"]

    async def test_ids_not_in_scope_falls_back(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"doc_ids": ["fake1", "fake2"]}'),
        )
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1", "d2"]

    async def test_mixed_valid_invalid_keeps_valid(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"doc_ids": ["d1", "fake"]}'),
        )
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=2,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1"]

    async def test_llm_exception_falls_back(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("network down"))
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1", "d2"]

    async def test_markdown_fenced_json_is_parsed(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        fenced = '```json\n{"doc_ids": ["d1"]}\n```'
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=fenced))
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1"]

    async def test_empty_registry_falls_back(self):
        from app.services.router import route_docs

        empty_registry = _FakeRegistry({})
        llm = AsyncMock()  # should never be called
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=empty_registry,
        )
        assert result == ["d1", "d2"]
        assert llm.ainvoke.await_count == 0
