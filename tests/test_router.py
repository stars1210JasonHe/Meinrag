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
