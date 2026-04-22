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
