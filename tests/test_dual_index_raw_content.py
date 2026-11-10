"""Dual-index (summary store) hits must return the SOURCE text, never the generated summary.

Defect measured 2026-11-10 on the deployed MCP channels (top-10, 4 queries each): content == the
hit's generated summary on legal 4/38, legal-au 2/40, caselaw 10/37. A legal client quoted the
"law text" it got back, and two of those summaries were factually wrong (an outdated monetary
threshold, a compilation date presented as a commencement date) -- confirmed against the primary
sources by a separate fact-check.

Mechanism: `_rrf_merge_dual` keeps the summary-store Document for a chunk that only the summary
retriever found, and that Document's page_content IS the summary
(summary_generator: `LCDocument(page_content=chunk.metadata["summary"], ...)`).

These tests drive the whole `retrieve_and_rank` pipeline (not the merge helper alone), so they
pin the observable contract -- what a caller receives -- rather than one implementation of it.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.documents import Document

from tests.test_hyde import _llm, _settings

RAW = {
    ("d1", 0): "RAW d1#0: s 3(1) a person is a consumer if the amount does not exceed $100,000",
    ("d1", 1): "RAW d1#1: s 3(2) the amount is the price of the goods",
    ("d2", 4): "RAW d2#4: cl 124 this item commences after the commencement of this Act",
}
SUMMARY = {k: f"SUMMARY of {k[0]}#{k[1]} (model-written, may be wrong)" for k in RAW}


def _raw_doc(doc_id, idx):
    return Document(page_content=RAW[(doc_id, idx)],
                    metadata={"doc_id": doc_id, "chunk_index": idx, "source_file": f"{doc_id}.txt",
                              "summary": SUMMARY[(doc_id, idx)]})


def _summary_doc(doc_id, idx):
    # exactly what summary_generator writes into the summary store
    raw = _raw_doc(doc_id, idx)
    return Document(page_content=raw.metadata["summary"], metadata=dict(raw.metadata))


def _stores(raw_hits, summary_hits, store_has=None):
    """vector_store returns raw_hits for the query and serves get_chunks_by_doc from `store_has`
    (default: every chunk in RAW); summary_store returns summary_hits."""
    store_has = set(RAW) if store_has is None else set(store_has)
    vs = MagicMock()
    vs.similarity_search_with_scores = MagicMock(return_value=list(raw_hits))
    vs.get_all_documents = MagicMock(return_value=[])

    def _chunks(doc_id, chunk_indices=None, *, allowed_doc_ids):
        if allowed_doc_ids is not None and doc_id not in allowed_doc_ids:
            return []
        return [_raw_doc(d, i) for (d, i) in sorted(store_has)
                if d == doc_id and (chunk_indices is None or i in chunk_indices)]

    vs.get_chunks_by_doc = MagicMock(side_effect=_chunks)
    ss = MagicMock()
    ss.similarity_search_with_scores = MagicMock(return_value=list(summary_hits))
    return vs, ss


async def _run(vs, ss, doc_ids=None):
    from app.services import retrieval as retrieval_mod
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    return await retrieval_mod.retrieve_and_rank(
        question="what is a consumer", top_k=5, doc_ids=doc_ids, user_scoped=False,
        llm=_llm(), vector_store=vs, embeddings=MagicMock(), edge_repo=edge_repo,
        settings=_settings(hyde_enabled=False), force_corpus_only=True,
        summary_store=ss, reorder_for_attention=False, ensure_coverage=False,
        source_truncate_chars=None,
    )


def _by_key(result):
    return {(s.doc_id, s.chunk_index): s.content for s in result.sources}


@pytest.mark.asyncio
class TestSummaryOnlyHitsReturnSourceText:
    async def test_summary_only_hit_returns_raw_chunk_text(self):
        """THE defect: d1#1 and d2#4 are found only by the summary retriever."""
        vs, ss = _stores(raw_hits=[(_raw_doc("d1", 0), 0.8)],
                         summary_hits=[(_summary_doc("d1", 1), 0.9), (_summary_doc("d2", 4), 0.7)])
        got = _by_key(await _run(vs, ss))
        # positive control: the summary-only chunks DID make it into the result -- otherwise the
        # assertions below would pass vacuously on a result that simply dropped them
        assert {("d1", 1), ("d2", 4)} <= set(got), got
        for key, content in got.items():
            assert content == RAW[key], f"{key} returned {content!r}, not its source text"
            assert content != SUMMARY[key]

    async def test_consensus_hit_still_returns_raw(self):
        """Found by both retrievers -- already correct before the fix; must stay correct."""
        vs, ss = _stores(raw_hits=[(_raw_doc("d1", 0), 0.8)],
                         summary_hits=[(_summary_doc("d1", 0), 0.9)])
        assert _by_key(await _run(vs, ss)) == {("d1", 0): RAW[("d1", 0)]}

    async def test_entrant_carries_summary_cosine(self):
        """The swapped-in raw chunk keeps the summary retriever's cosine as its query similarity
        (the magnitude the summary match earned), labelled as such."""
        vs, ss = _stores(raw_hits=[(_raw_doc("d1", 0), 0.8)],
                         summary_hits=[(_summary_doc("d2", 4), 0.77)])
        res = await _run(vs, ss)
        doc = next(d for d, _ in res.retrieved if d.metadata["doc_id"] == "d2")
        assert doc.page_content == RAW[("d2", 4)]
        assert doc.metadata["_sim_source"] == "summary"
        assert doc.metadata["_query_sim"] == pytest.approx(0.77)

    async def test_raw_chunk_missing_drops_the_hit_not_returns_summary(self):
        """If the source chunk cannot be fetched (summary store out of sync with the raw store),
        the hit is DROPPED. Returning the summary as if it were source text is the defect itself,
        so it is not an acceptable fallback."""
        vs, ss = _stores(raw_hits=[(_raw_doc("d1", 0), 0.8)],
                         summary_hits=[(_summary_doc("d2", 4), 0.9)],
                         store_has=[("d1", 0)])  # d2#4 absent from the raw store
        got = _by_key(await _run(vs, ss))
        assert ("d2", 4) not in got
        assert got == {("d1", 0): RAW[("d1", 0)]}

    async def test_lookup_respects_doc_scope(self):
        """The raw-chunk fetch is scoped to the request's doc_ids like every other content path."""
        vs, ss = _stores(raw_hits=[(_raw_doc("d1", 0), 0.8)],
                         summary_hits=[(_summary_doc("d1", 1), 0.9)])
        await _run(vs, ss, doc_ids=["d1"])
        # only the calls that fetch the entrant chunk (other pipeline stages may call it too)
        scopes = [c.kwargs.get("allowed_doc_ids") for c in vs.get_chunks_by_doc.call_args_list
                  if c.args and c.args[0] == "d1" and len(c.args) > 1 and c.args[1] and 1 in c.args[1]]
        assert scopes, "raw-chunk lookup for the entrant was never called"
        assert all(s == {"d1"} for s in scopes), scopes
