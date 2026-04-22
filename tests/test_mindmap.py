"""Tests for mindmap endpoint, service, and repository method."""
from __future__ import annotations

import pytest

from app.db.repositories import EdgeRepository


@pytest.mark.asyncio
class TestEdgeRepositoryGetEdgesInDoc:
    async def test_returns_only_intra_doc_edges(self, db_session):
        repo = EdgeRepository(db_session)
        await repo.bulk_insert([
            # Intra-doc: d1 -> d1
            {"source_doc_id": "d1", "source_chunk_index": 0,
             "target_doc_id": "d1", "target_chunk_index": 1,
             "relation": "follows", "score": 1.0},
            {"source_doc_id": "d1", "source_chunk_index": 2,
             "target_doc_id": "d1", "target_chunk_index": 5,
             "relation": "describes", "score": 0.85},
            # Cross-doc: d1 -> d2 (should NOT be returned)
            {"source_doc_id": "d1", "source_chunk_index": 3,
             "target_doc_id": "d2", "target_chunk_index": 0,
             "relation": "similar_to", "score": 0.7},
            # Other doc entirely: d2 -> d2 (should NOT be returned)
            {"source_doc_id": "d2", "source_chunk_index": 0,
             "target_doc_id": "d2", "target_chunk_index": 1,
             "relation": "follows", "score": 1.0},
        ])

        rows = await repo.get_edges_in_doc("d1")

        assert len(rows) == 2
        relations = sorted(r["relation"] for r in rows)
        assert relations == ["describes", "follows"]
        # Shape check
        for r in rows:
            assert set(r.keys()) == {
                "source_chunk_index", "target_chunk_index",
                "relation", "score",
            }

    async def test_returns_empty_for_unknown_doc(self, db_session):
        repo = EdgeRepository(db_session)
        rows = await repo.get_edges_in_doc("nonexistent")
        assert rows == []

    async def test_null_score_becomes_1_0(self, db_session):
        repo = EdgeRepository(db_session)
        await repo.bulk_insert([
            {"source_doc_id": "d1", "source_chunk_index": 0,
             "target_doc_id": "d1", "target_chunk_index": 1,
             "relation": "follows", "score": None},
        ])
        rows = await repo.get_edges_in_doc("d1")
        assert len(rows) == 1
        assert rows[0]["score"] == 1.0


class TestMindmapSchemas:
    def test_mindmap_node_basic(self):
        from app.models.schemas import MindmapNode

        node = MindmapNode(
            id="d1:5",
            chunk_index=5,
            chunk_type="text",
            section_type="body",
            page=3,
            label="Summary preview",
            full_summary="Full summary text here",
            content_length=1240,
            has_image=False,
            bbox=[10, 20, 30, 40],
        )
        assert node.id == "d1:5"
        assert node.bbox == [10, 20, 30, 40]

    def test_mindmap_node_optional_fields(self):
        from app.models.schemas import MindmapNode

        node = MindmapNode(
            id="d1:0",
            chunk_index=0,
            chunk_type="image",
            label="Image chunk",
            content_length=0,
            has_image=True,
        )
        assert node.section_type is None
        assert node.page is None
        assert node.full_summary is None
        assert node.bbox is None

    def test_mindmap_edge(self):
        from app.models.schemas import MindmapEdge

        edge = MindmapEdge(
            source="d1:0", target="d1:1",
            relation="follows", score=1.0,
        )
        assert edge.relation == "follows"

    def test_mindmap_stats(self):
        from app.models.schemas import MindmapStats

        stats = MindmapStats(
            node_count=42,
            edge_count=89,
            edges_by_type={"follows": 41, "describes": 8},
            chunks_by_type={"text": 35, "table": 5},
        )
        assert stats.node_count == 42
        assert stats.edges_by_type["follows"] == 41

    def test_mindmap_response(self):
        from app.models.schemas import MindmapResponse

        resp = MindmapResponse(
            doc_id="d1",
            filename="paper.pdf",
            doc_summary="A paper about X",
            nodes=[],
            edges=[],
            stats={
                "node_count": 0,
                "edge_count": 0,
                "edges_by_type": {},
                "chunks_by_type": {},
            },
        )
        assert resp.doc_id == "d1"
        assert resp.nodes == []


from langchain_core.documents import Document


class TestBuildMindmap:
    def _chunk(self, doc_id="d1", chunk_index=0, chunk_type="text",
               content="hello world", summary="summary text",
               section_type="body", page=1, **extra_meta):
        meta = {
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "chunk_type": chunk_type,
            "summary": summary,
            "section_type": section_type,
            "page": page,
            "bbox": [10.0, 20.0, 30.0, 40.0],
        }
        meta.update(extra_meta)
        return Document(page_content=content, metadata=meta)

    def test_chunk_to_node_happy_path(self):
        from app.services.mindmap import _chunk_to_node

        chunk = self._chunk(content="x" * 100, summary="short summary")
        node = _chunk_to_node(chunk)
        assert node.id == "d1:0"
        assert node.chunk_index == 0
        assert node.chunk_type == "text"
        assert node.page == 1
        assert node.content_length == 100
        assert node.has_image is False
        assert node.full_summary == "short summary"
        assert node.label == "short summary"  # under 60 chars, no truncation
        assert node.bbox == [10.0, 20.0, 30.0, 40.0]

    def test_chunk_to_node_summary_truncated(self):
        from app.services.mindmap import _chunk_to_node

        long = "a" * 100
        chunk = self._chunk(summary=long)
        node = _chunk_to_node(chunk)
        assert node.label.endswith("...")
        assert len(node.label) <= 63  # 60 + "..."
        assert node.full_summary == long

    def test_chunk_to_node_falls_back_when_no_summary(self):
        from app.services.mindmap import _chunk_to_node

        chunk = self._chunk(content="fallback content", summary=None)
        node = _chunk_to_node(chunk)
        assert node.label == "fallback content"
        assert node.full_summary is None

    def test_chunk_to_node_image_detection(self):
        from app.services.mindmap import _chunk_to_node

        chunk = self._chunk(chunk_type="image", image_path="/path/to.png")
        node = _chunk_to_node(chunk)
        assert node.has_image is True

    def test_chunk_to_node_parses_json_bbox(self):
        from app.services.mindmap import _chunk_to_node

        chunk = self._chunk(bbox='[1.0, 2.0, 3.0, 4.0]')
        node = _chunk_to_node(chunk)
        assert node.bbox == [1.0, 2.0, 3.0, 4.0]

    def test_build_edges_and_stats(self):
        from app.services.mindmap import _build_edges_and_stats

        chunks = [
            self._chunk(chunk_index=0, chunk_type="text"),
            self._chunk(chunk_index=1, chunk_type="table"),
            self._chunk(chunk_index=2, chunk_type="text"),
        ]
        edge_rows = [
            {"source_chunk_index": 0, "target_chunk_index": 1,
             "relation": "follows", "score": 1.0},
            {"source_chunk_index": 1, "target_chunk_index": 2,
             "relation": "follows", "score": 1.0},
            {"source_chunk_index": 0, "target_chunk_index": 2,
             "relation": "similar_to", "score": 0.7},
        ]

        edges, stats = _build_edges_and_stats("d1", chunks, edge_rows)

        assert len(edges) == 3
        assert edges[0].source == "d1:0"
        assert edges[0].target == "d1:1"
        assert stats.node_count == 3
        assert stats.edge_count == 3
        assert stats.edges_by_type == {"follows": 2, "similar_to": 1}
        assert stats.chunks_by_type == {"text": 2, "table": 1}
