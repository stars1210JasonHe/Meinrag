"""Where #24 (target trace) meets #25 (section_sampling pool): the strategy-cut note must name the
cut that was actually made. Before this the note printed top_k while the branch kept the pool."""
import pytest
from unittest.mock import AsyncMock

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from tests.test_stage_counts_reported import _StubLLM, _settings, _vector_store


class _OverviewLLM(_StubLLM):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content='{"types": ["overview"], "label": null}'))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages)


async def _note(flag):
    from app.services import retrieval
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    s = _settings()
    s.rerank_enabled = True
    s.rerank_pool_size = 30
    s.rerank_pool_section_sampling = flag
    r = await retrieval.retrieve_and_rank(
        question="what is this about", top_k=4, doc_ids=None, user_scoped=False, llm=_OverviewLLM(),
        vector_store=_vector_store(6), embeddings=AsyncMock(), edge_repo=edge_repo, settings=s,
        force_corpus_only=True, reorder_for_attention=False, enforce_token_budget=False,
        debug_target={"doc_id": "doc-0", "chunk_index": None},
    )
    return {e["stage"]: e for e in r.target_trace}["after_strategy_cut"]["note"]


@pytest.mark.asyncio
async def test_note_names_pool_when_on():
    note = await _note(True)
    assert "section_sampling" in note and "top_k=30" in note


@pytest.mark.asyncio
async def test_note_names_top_k_when_off():
    assert "top_k=4" in await _note(False)
