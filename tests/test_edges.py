"""Tests for edge building between chunks."""
import pytest
import numpy as np
from langchain_core.documents import Document

from app.services.edge_builder import build_intra_doc_edges, build_cross_doc_edges


class TestFollowsEdges:
    def test_sequential_chunks(self):
        chunks = [
            Document(page_content="A", metadata={"doc_id": "d1", "chunk_index": 0, "chunk_type": "text"}),
            Document(page_content="B", metadata={"doc_id": "d1", "chunk_index": 1, "chunk_type": "text"}),
            Document(page_content="C", metadata={"doc_id": "d1", "chunk_index": 2, "chunk_type": "text"}),
        ]
        edges = build_intra_doc_edges(chunks, doc_id="d1")
        follows = [e for e in edges if e["relation"] == "follows"]
        assert len(follows) == 2
        assert follows[0]["source_chunk_index"] == 0
        assert follows[0]["target_chunk_index"] == 1
        assert follows[1]["source_chunk_index"] == 1
        assert follows[1]["target_chunk_index"] == 2

    def test_empty_chunks(self):
        edges = build_intra_doc_edges([], doc_id="d1")
        assert edges == []

    def test_single_chunk(self):
        chunks = [Document(page_content="A", metadata={"doc_id": "d1", "chunk_index": 0, "chunk_type": "text"})]
        edges = build_intra_doc_edges(chunks, doc_id="d1")
        follows = [e for e in edges if e["relation"] == "follows"]
        assert len(follows) == 0


class TestCoLocatedEdges:
    def test_same_page(self):
        chunks = [
            Document(page_content="Text", metadata={"doc_id": "d1", "chunk_index": 0, "chunk_type": "text", "page": 5}),
            Document(page_content="|A|B|", metadata={"doc_id": "d1", "chunk_index": 1, "chunk_type": "table", "page": 5}),
            Document(page_content="Other", metadata={"doc_id": "d1", "chunk_index": 2, "chunk_type": "text", "page": 10}),
        ]
        edges = build_intra_doc_edges(chunks, doc_id="d1")
        co_located = [e for e in edges if e["relation"] == "co_located"]
        pairs = {(e["source_chunk_index"], e["target_chunk_index"]) for e in co_located}
        assert (0, 1) in pairs
        assert (0, 2) not in pairs

    def test_no_page_metadata(self):
        chunks = [
            Document(page_content="A", metadata={"doc_id": "d1", "chunk_index": 0, "chunk_type": "text"}),
            Document(page_content="B", metadata={"doc_id": "d1", "chunk_index": 1, "chunk_type": "text"}),
        ]
        edges = build_intra_doc_edges(chunks, doc_id="d1")
        co_located = [e for e in edges if e["relation"] == "co_located"]
        assert len(co_located) == 0


class TestDescribesEdges:
    def test_visual_text_same_page_high_similarity(self):
        chunks = [
            Document(page_content="The model architecture is shown", metadata={
                "doc_id": "d1", "chunk_index": 0, "chunk_type": "text", "page": 2}),
            Document(page_content="Figure 1: The Transformer architecture", metadata={
                "doc_id": "d1", "chunk_index": 1, "chunk_type": "image", "page": 2}),
        ]
        embeddings = {0: np.array([1.0, 0.0, 0.0]), 1: np.array([0.9, 0.1, 0.0])}
        edges = build_intra_doc_edges(chunks, doc_id="d1", embeddings=embeddings, describes_threshold=0.5)
        describes = [e for e in edges if e["relation"] == "describes"]
        assert len(describes) >= 1
        assert describes[0]["source_chunk_index"] == 0  # text describes visual
        assert describes[0]["target_chunk_index"] == 1

    def test_visual_text_low_similarity_no_edge(self):
        chunks = [
            Document(page_content="Unrelated text", metadata={
                "doc_id": "d1", "chunk_index": 0, "chunk_type": "text", "page": 2}),
            Document(page_content="Figure 1: Architecture", metadata={
                "doc_id": "d1", "chunk_index": 1, "chunk_type": "image", "page": 2}),
        ]
        embeddings = {0: np.array([1.0, 0.0, 0.0]), 1: np.array([0.0, 1.0, 0.0])}
        edges = build_intra_doc_edges(chunks, doc_id="d1", embeddings=embeddings, describes_threshold=0.5)
        describes = [e for e in edges if e["relation"] == "describes"]
        assert len(describes) == 0

    def test_distant_pages_no_edge(self):
        chunks = [
            Document(page_content="Text", metadata={
                "doc_id": "d1", "chunk_index": 0, "chunk_type": "text", "page": 1}),
            Document(page_content="Figure", metadata={
                "doc_id": "d1", "chunk_index": 1, "chunk_type": "image", "page": 10}),
        ]
        embeddings = {0: np.array([1.0, 0.0, 0.0]), 1: np.array([1.0, 0.0, 0.0])}
        edges = build_intra_doc_edges(chunks, doc_id="d1", embeddings=embeddings, describes_threshold=0.5)
        describes = [e for e in edges if e["relation"] == "describes"]
        assert len(describes) == 0


class TestReferencesEdges:
    def test_label_match(self):
        chunks = [
            Document(page_content="As shown in Table 1, the results improve", metadata={
                "doc_id": "d1", "chunk_index": 0, "chunk_type": "text", "page": 3}),
            Document(page_content="Table 1: Results", metadata={
                "doc_id": "d1", "chunk_index": 1, "chunk_type": "table", "page": 5, "label": "Table 1"}),
        ]
        edges = build_intra_doc_edges(chunks, doc_id="d1")
        refs = [e for e in edges if e["relation"] == "references"]
        assert len(refs) >= 1
        assert refs[0]["source_chunk_index"] == 0
        assert refs[0]["target_chunk_index"] == 1

    def test_no_label_no_edge(self):
        chunks = [
            Document(page_content="As shown in Table 1", metadata={
                "doc_id": "d1", "chunk_index": 0, "chunk_type": "text", "page": 3}),
            Document(page_content="|A|B|", metadata={
                "doc_id": "d1", "chunk_index": 1, "chunk_type": "table", "page": 5}),
        ]
        edges = build_intra_doc_edges(chunks, doc_id="d1")
        refs = [e for e in edges if e["relation"] == "references"]
        assert len(refs) == 0

    def test_multiple_references(self):
        chunks = [
            Document(page_content="Table 1 and Figure 2 show the results", metadata={
                "doc_id": "d1", "chunk_index": 0, "chunk_type": "text", "page": 3}),
            Document(page_content="Table 1: data", metadata={
                "doc_id": "d1", "chunk_index": 1, "chunk_type": "table", "page": 5, "label": "Table 1"}),
            Document(page_content="Figure 2: graph", metadata={
                "doc_id": "d1", "chunk_index": 2, "chunk_type": "image", "page": 5, "label": "Figure 2"}),
        ]
        edges = build_intra_doc_edges(chunks, doc_id="d1")
        refs = [e for e in edges if e["relation"] == "references"]
        assert len(refs) == 2


class TestCrossDocSimilarityThreshold:
    """build_cross_doc_edges filters by min_score to drop noise."""

    class _FakeVectorStore:
        """Returns canned (doc, score) pairs for similarity_search_with_scores."""
        def __init__(self, results):
            self._results = results
        def similarity_search_with_scores(self, _query, k):
            return self._results[:k]

    def test_filters_below_threshold(self):
        src_chunks = [
            Document(page_content="q", metadata={"doc_id": "s1", "chunk_index": 0, "chunk_type": "text"}),
        ]
        # Neighbors: 2 above 0.6, 3 below
        neighbor_results = [
            (Document(page_content="a", metadata={"doc_id": "t1", "chunk_index": 0}), 0.85),
            (Document(page_content="b", metadata={"doc_id": "t2", "chunk_index": 0}), 0.70),
            (Document(page_content="c", metadata={"doc_id": "t3", "chunk_index": 0}), 0.55),
            (Document(page_content="d", metadata={"doc_id": "t4", "chunk_index": 0}), 0.40),
            (Document(page_content="e", metadata={"doc_id": "t5", "chunk_index": 0}), 0.25),
        ]
        vs = self._FakeVectorStore(neighbor_results)
        edges = build_cross_doc_edges("s1", src_chunks, vs, top_k=5, min_score=0.6)
        assert len(edges) == 2
        for e in edges:
            assert e["score"] >= 0.6

    def test_threshold_default_is_0_6(self):
        import inspect
        sig = inspect.signature(build_cross_doc_edges)
        assert sig.parameters["min_score"].default == 0.6

    def test_skips_self(self):
        src_chunks = [
            Document(page_content="q", metadata={"doc_id": "s1", "chunk_index": 0, "chunk_type": "text"}),
        ]
        neighbor_results = [
            (Document(page_content="self", metadata={"doc_id": "s1", "chunk_index": 0}), 1.0),
            (Document(page_content="other", metadata={"doc_id": "t1", "chunk_index": 0}), 0.85),
        ]
        vs = self._FakeVectorStore(neighbor_results)
        edges = build_cross_doc_edges("s1", src_chunks, vs, top_k=5, min_score=0.5)
        # Self edge should NOT appear; only the cross-doc edge
        assert len(edges) == 1
        assert edges[0]["target_doc_id"] == "t1"

    def test_dedup_across_multiple_source_chunks(self):
        src_chunks = [
            Document(page_content="a", metadata={"doc_id": "s1", "chunk_index": 0, "chunk_type": "text"}),
            Document(page_content="b", metadata={"doc_id": "s1", "chunk_index": 1, "chunk_type": "text"}),
        ]
        # Same target for both source chunks — should produce 2 edges (different source indices, same target)
        neighbor_results = [
            (Document(page_content="same", metadata={"doc_id": "t1", "chunk_index": 0}), 0.85),
        ]
        vs = self._FakeVectorStore(neighbor_results)
        edges = build_cross_doc_edges("s1", src_chunks, vs, top_k=5, min_score=0.5)
        # Two distinct source chunks → two edges allowed
        assert len(edges) == 2
        keys = {(e["source_chunk_index"], e["target_doc_id"], e["target_chunk_index"]) for e in edges}
        assert keys == {(0, "t1", 0), (1, "t1", 0)}


def _general_scoring():
    from app.services.scoring_profile import load_scoring_profile
    return load_scoring_profile("general").for_query_type()


class TestGraphExpansion:
    """Test _expand_via_edges() traverses edges to find related chunks."""

    @pytest.mark.asyncio
    async def test_expands_describes_edge(self):
        from app.services.retrieval import _expand_via_edges

        text_chunk = Document(
            page_content="The model architecture",
            metadata={"doc_id": "d1", "chunk_index": 0, "chunk_type": "text", "page": 2},
        )
        image_chunk = Document(
            page_content="Figure 1: Architecture",
            metadata={"doc_id": "d1", "chunk_index": 1, "chunk_type": "image", "page": 2},
        )

        class MockEdgeRepo:
            async def get_edges_from(self, doc_id, chunk_index, relations=None):
                if chunk_index == 0:
                    return [{"target_doc_id": "d1", "target_chunk_index": 1,
                             "relation": "describes", "score": 0.8}]
                return []

        class MockStore:
            def get_chunks_by_doc(self, doc_id):
                return [text_chunk, image_chunk]

        retrieved = [(text_chunk, 0.7)]
        profile = _general_scoring()
        expanded = await _expand_via_edges(
            retrieved, MockEdgeRepo(), MockStore(), profile,
            relations=["describes", "references"],
        )
        assert len(expanded) == 2
        assert expanded[1][0].page_content == "Figure 1: Architecture"
        # Expanded score is query-linked: parent x decay x edge — never the raw
        # static edge score (that was the constant-top-3 bug, P1 2026-07-10).
        decay = profile.graph_expansion_score_decay
        assert expanded[1][1] == pytest.approx(0.7 * decay * 0.8)
        assert expanded[1][1] < 0.7  # always below the parent chunk

    @pytest.mark.asyncio
    async def test_no_duplicates(self):
        from app.services.retrieval import _expand_via_edges

        chunk = Document(
            page_content="Text",
            metadata={"doc_id": "d1", "chunk_index": 0, "chunk_type": "text"},
        )

        class MockEdgeRepo:
            async def get_edges_from(self, doc_id, chunk_index, relations=None):
                return []

        class MockStore:
            def get_chunks_by_doc(self, doc_id):
                return [chunk]

        retrieved = [(chunk, 0.7)]
        expanded = await _expand_via_edges(retrieved, MockEdgeRepo(), MockStore(), _general_scoring())
        assert len(expanded) == 1

    @pytest.mark.asyncio
    async def test_empty_retrieved(self):
        from app.services.retrieval import _expand_via_edges

        class MockEdgeRepo:
            async def get_edges_from(self, doc_id, chunk_index, relations=None):
                return []

        class MockStore:
            def get_chunks_by_doc(self, doc_id):
                return []

        result = await _expand_via_edges([], MockEdgeRepo(), MockStore(), _general_scoring())
        assert result == []

    @pytest.mark.asyncio
    async def test_max_expansion_limit(self):
        from app.services.retrieval import _expand_via_edges

        text_chunk = Document(
            page_content="Text",
            metadata={"doc_id": "d1", "chunk_index": 0, "chunk_type": "text"},
        )
        targets = [
            Document(page_content=f"Target {i}", metadata={"doc_id": "d1", "chunk_index": i + 1, "chunk_type": "text"})
            for i in range(10)
        ]

        class MockEdgeRepo:
            async def get_edges_from(self, doc_id, chunk_index, relations=None):
                if chunk_index == 0:
                    return [{"target_doc_id": "d1", "target_chunk_index": i + 1,
                             "relation": "describes", "score": 0.5} for i in range(10)]
                return []

        class MockStore:
            def get_chunks_by_doc(self, doc_id):
                return [text_chunk] + targets

        retrieved = [(text_chunk, 0.7)]
        expanded = await _expand_via_edges(
            retrieved, MockEdgeRepo(), MockStore(), _general_scoring(), max_expansion=3,
        )
        # 1 original + 3 expanded (capped at max_expansion)
        assert len(expanded) == 4
