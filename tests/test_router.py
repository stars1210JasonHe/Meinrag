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
