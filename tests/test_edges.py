"""Tests for edge building between chunks."""
import pytest
import numpy as np
from langchain_core.documents import Document

from app.services.edge_builder import build_intra_doc_edges


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


class TestGraphExpansion:
    """Test _expand_via_edges() traverses edges to find related chunks."""

    @pytest.mark.asyncio
    async def test_expands_describes_edge(self):
        from app.routers.query import _expand_via_edges

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
        expanded = await _expand_via_edges(
            retrieved, MockEdgeRepo(), MockStore(),
            relations=["describes", "references"],
        )
        assert len(expanded) == 2
        assert expanded[1][0].page_content == "Figure 1: Architecture"
        assert expanded[1][1] == 0.8

    @pytest.mark.asyncio
    async def test_no_duplicates(self):
        from app.routers.query import _expand_via_edges

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
        expanded = await _expand_via_edges(retrieved, MockEdgeRepo(), MockStore())
        assert len(expanded) == 1

    @pytest.mark.asyncio
    async def test_empty_retrieved(self):
        from app.routers.query import _expand_via_edges

        class MockEdgeRepo:
            async def get_edges_from(self, doc_id, chunk_index, relations=None):
                return []

        class MockStore:
            def get_chunks_by_doc(self, doc_id):
                return []

        result = await _expand_via_edges([], MockEdgeRepo(), MockStore())
        assert result == []

    @pytest.mark.asyncio
    async def test_max_expansion_limit(self):
        from app.routers.query import _expand_via_edges

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
            retrieved, MockEdgeRepo(), MockStore(), max_expansion=3,
        )
        # 1 original + 3 expanded (capped at max_expansion)
        assert len(expanded) == 4
