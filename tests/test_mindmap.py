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


class TestDocGraphSchemas:
    def test_mindmap_node_basic(self):
        from app.models.schemas import DocGraphNode

        node = DocGraphNode(
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
        from app.models.schemas import DocGraphNode

        node = DocGraphNode(
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
        from app.models.schemas import DocGraphEdge

        edge = DocGraphEdge(
            source="d1:0", target="d1:1",
            relation="follows", score=1.0,
        )
        assert edge.relation == "follows"

    def test_mindmap_stats(self):
        from app.models.schemas import DocGraphStats

        stats = DocGraphStats(
            node_count=42,
            edge_count=89,
            edges_by_type={"follows": 41, "describes": 8},
            chunks_by_type={"text": 35, "table": 5},
        )
        assert stats.node_count == 42
        assert stats.edges_by_type["follows"] == 41

    def test_mindmap_response(self):
        from app.models.schemas import DocGraphResponse

        resp = DocGraphResponse(
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


class TestBuildDocGraph:
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


from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


def _build_test_app():
    """Build a FastAPI app with stubbed dependencies for integration tests.

    Returns (app, stubs_dict) where stubs_dict lets the test configure
    what the mocked dependencies return.
    """
    from fastapi import FastAPI
    from app.routers.documents import router
    from app.dependencies import (
        get_settings, get_vector_store, get_registry,
        get_edge_repository, get_current_user,
    )

    app = FastAPI()
    # Match production mount: app.include_router(documents.router, prefix="/documents")
    app.include_router(router, prefix="/documents")

    stubs = {
        "settings": MagicMock(user_isolation="all"),
        "vector_store": MagicMock(),
        "registry": MagicMock(),
        "edge_repo": MagicMock(),
        "current_user": "admin",
    }
    stubs["registry"].get = AsyncMock()
    stubs["edge_repo"].get_edges_in_doc = AsyncMock()

    app.dependency_overrides[get_settings] = lambda: stubs["settings"]
    app.dependency_overrides[get_vector_store] = lambda: stubs["vector_store"]
    app.dependency_overrides[get_registry] = lambda: stubs["registry"]
    app.dependency_overrides[get_edge_repository] = lambda: stubs["edge_repo"]
    app.dependency_overrides[get_current_user] = lambda: stubs["current_user"]

    return app, stubs


class TestDocGraphRoute:
    def test_happy_path(self):
        app, stubs = _build_test_app()
        stubs["registry"].get.return_value = {
            "doc_id": "d1", "filename": "paper.pdf",
            "summary": "A paper about X", "user_id": "admin",
        }
        stubs["vector_store"].get_chunks_by_doc = MagicMock(return_value=[
            Document(page_content="content 0", metadata={
                "doc_id": "d1", "chunk_index": 0, "chunk_type": "text",
                "summary": "chunk 0 summary",
            }),
            Document(page_content="content 1", metadata={
                "doc_id": "d1", "chunk_index": 1, "chunk_type": "table",
                "summary": "chunk 1 summary",
            }),
        ])
        stubs["edge_repo"].get_edges_in_doc.return_value = [
            {"source_chunk_index": 0, "target_chunk_index": 1,
             "relation": "follows", "score": 1.0},
        ]

        with TestClient(app) as client:
            resp = client.get(
                "/documents/d1/graph",
                headers={"X-User-Id": "admin"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == "d1"
        assert data["filename"] == "paper.pdf"
        assert len(data["nodes"]) == 2
        assert len(data["edges"]) == 1
        assert data["edges"][0]["source"] == "d1:0"
        assert data["edges"][0]["target"] == "d1:1"
        assert data["stats"]["node_count"] == 2
        assert data["stats"]["chunks_by_type"] == {"text": 1, "table": 1}

    def test_404_for_missing_doc(self):
        app, stubs = _build_test_app()
        stubs["registry"].get.return_value = None

        with TestClient(app) as client:
            resp = client.get(
                "/documents/nonexistent/graph",
                headers={"X-User-Id": "admin"},
            )
        assert resp.status_code == 404

    def test_403_for_wrong_user(self):
        app, stubs = _build_test_app()
        stubs["settings"].user_isolation = "all"
        stubs["registry"].get.return_value = {
            "doc_id": "d1", "filename": "paper.pdf",
            "summary": "...", "user_id": "alice",
        }
        # Re-override current_user to bob
        from app.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: "bob"

        with TestClient(app) as client:
            resp = client.get(
                "/documents/d1/graph",
                headers={"X-User-Id": "bob"},
            )
        assert resp.status_code == 403

    def test_empty_doc_returns_empty_arrays(self):
        app, stubs = _build_test_app()
        stubs["registry"].get.return_value = {
            "doc_id": "d1", "filename": "empty.pdf",
            "summary": None, "user_id": "admin",
        }
        stubs["vector_store"].get_chunks_by_doc = MagicMock(return_value=[])
        stubs["edge_repo"].get_edges_in_doc.return_value = []

        with TestClient(app) as client:
            resp = client.get(
                "/documents/d1/graph",
                headers={"X-User-Id": "admin"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["stats"]["node_count"] == 0


class TestMindmapTreeSchemas:
    def test_mindmap_leaf(self):
        from app.models.schemas import MindmapLeaf

        leaf = MindmapLeaf(name="Attention mechanism", chunk_indices=[3, 5, 7])
        assert leaf.name == "Attention mechanism"
        assert leaf.chunk_indices == [3, 5, 7]

    def test_mindmap_branch(self):
        from app.models.schemas import MindmapBranch, MindmapLeaf

        branch = MindmapBranch(
            name="Architecture",
            children=[
                MindmapLeaf(name="Attention", chunk_indices=[3]),
                MindmapLeaf(name="Feed-forward", chunk_indices=[4, 6]),
            ],
        )
        assert branch.name == "Architecture"
        assert len(branch.children) == 2
        assert branch.children[0].name == "Attention"

    def test_mindmap_tree(self):
        from app.models.schemas import MindmapTree, MindmapBranch, MindmapLeaf

        tree = MindmapTree(
            central="A paper on attention in transformers",
            branches=[
                MindmapBranch(
                    name="Architecture",
                    children=[MindmapLeaf(name="QKV", chunk_indices=[3])],
                ),
            ],
        )
        assert tree.central == "A paper on attention in transformers"
        assert len(tree.branches) == 1

    def test_mindmap_tree_response(self):
        from app.models.schemas import MindmapTreeResponse

        resp = MindmapTreeResponse(
            doc_id="d1",
            filename="paper.pdf",
            cached=False,
            tree={
                "central": "test",
                "branches": [],
            },
        )
        assert resp.doc_id == "d1"
        assert resp.cached is False
        assert resp.tree.central == "test"
