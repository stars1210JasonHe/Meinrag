"""Tests for the multi-doc mindmap service + endpoint."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from langchain_core.messages import AIMessage
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import LLMProvider, Settings, VectorStoreType
from app.db.models import Base, DocumentModel, UserModel
from app.dependencies import (
    get_db, get_edge_repository, get_embeddings, get_llm, get_settings,
    get_summary_store, get_vector_store,
)
from app.main import create_app


def _chunk(doc_id: str, idx: int, summary: str) -> Document:
    return Document(
        page_content=summary,
        metadata={
            "doc_id": doc_id, "chunk_index": idx,
            "summary": summary, "chunk_type": "text",
        },
    )


class TestParser:
    """Pin _parse_tree_response behaviour — validates chunks_by_doc, drops
    unknown doc_ids + out-of-range chunk indices, caps depth at 4."""

    def _valid(self):
        # docA has chunks 0..3; docB has chunks 0..2
        return {"docA": {0, 1, 2, 3}, "docB": {0, 1, 2}}

    def test_valid_payload_parses(self):
        from app.services.multi_mindmap import _parse_tree_response
        payload = json.dumps({
            "central": "Attention across papers",
            "branches": [
                {"name": "QKV", "children": [
                    {"name": "Self-attention",
                     "chunks_by_doc": {"docA": [0, 1], "docB": [2]}},
                ]},
            ],
        })
        central, branches = _parse_tree_response(payload, self._valid())
        assert central == "Attention across papers"
        assert len(branches) == 1
        leaf = branches[0].children[0]
        assert leaf.chunks_by_doc == {"docA": [0, 1], "docB": [2]}

    def test_unknown_doc_id_dropped(self):
        from app.services.multi_mindmap import _parse_tree_response
        payload = json.dumps({
            "central": "X",
            "branches": [
                {"name": "B", "children": [
                    {"name": "L",
                     "chunks_by_doc": {"docA": [0], "docHALLUCINATED": [99]}},
                ]},
            ],
        })
        _, branches = _parse_tree_response(payload, self._valid())
        leaf = branches[0].children[0]
        assert "docHALLUCINATED" not in leaf.chunks_by_doc
        assert leaf.chunks_by_doc == {"docA": [0]}

    def test_out_of_range_chunk_indices_dropped(self):
        from app.services.multi_mindmap import _parse_tree_response
        payload = json.dumps({
            "central": "X",
            "branches": [
                {"name": "B", "children": [
                    {"name": "L",
                     "chunks_by_doc": {"docA": [0, 99, 2, "bad"]}},
                ]},
            ],
        })
        _, branches = _parse_tree_response(payload, self._valid())
        leaf = branches[0].children[0]
        assert leaf.chunks_by_doc == {"docA": [0, 2]}

    def test_depth_cap_drops_layer_5(self):
        """A runaway 5-layer tree gets the deepest layer collapsed."""
        from app.services.multi_mindmap import (
            MULTI_MINDMAP_MAX_DEPTH, _parse_tree_response,
        )
        # 5 layers: central → branch → child → grandchild → great-grandchild
        payload = json.dumps({
            "central": "X",
            "branches": [{"name": "L1", "children": [
                {"name": "L2", "children": [
                    {"name": "L3", "children": [
                        {"name": "L4 (illegal)",
                         "chunks_by_doc": {"docA": [0]}},
                    ]},
                ]},
            ]}],
        })
        _, branches = _parse_tree_response(payload, self._valid())

        def max_depth(node, d=1):
            if not node.children:
                return d
            return max(max_depth(c, d + 1) for c in node.children)
        deepest = max(max_depth(b) for b in branches)
        assert deepest <= MULTI_MINDMAP_MAX_DEPTH

    def test_malformed_json_returns_empty(self):
        from app.services.multi_mindmap import _parse_tree_response
        central, branches = _parse_tree_response(
            "not json at all", self._valid(),
        )
        assert central == ""
        assert branches == []


class TestCacheRoundtrip:
    """Pin cache key stability + invalidation."""

    def test_cache_key_order_independent(self):
        from app.services.multi_mindmap import _cache_key
        # Same set of ids, different order → same key
        assert _cache_key(["A", "B", "C"]) == _cache_key(["C", "A", "B"])
        # Different set → different key
        assert _cache_key(["A", "B"]) != _cache_key(["A", "B", "C"])

    def test_invalidate_removes_matching_caches(self, tmp_path, monkeypatch):
        from app.services import multi_mindmap as mm
        from app.models.schemas import MultiMindmapTree, MultiMindmapNode
        monkeypatch.setattr(mm, "MULTI_MINDMAPS_CACHE_DIR", tmp_path)
        tree = MultiMindmapTree(
            central="x", branches=[
                MultiMindmapNode(name="b", chunks_by_doc={"A": [0]}),
            ],
            palette={"A": "#123456", "B": "#abcdef"},
        )
        mm._save_cached(["A", "B"], tree)
        mm._save_cached(["A", "C"], tree)
        mm._save_cached(["B", "C"], tree)
        assert len(list(tmp_path.glob("*.json"))) == 3

        # Delete doc A → caches AB and AC should go; BC stays.
        removed = mm.invalidate_caches_for_doc("A")
        assert removed == 2
        assert len(list(tmp_path.glob("*.json"))) == 1


@pytest.fixture
def mock_settings():
    return Settings(
        openai_api_key="fake",
        llm_provider=LLMProvider.OPENAI,
        vector_store=VectorStoreType.CHROMA,
    )


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_vector_store():
    store = MagicMock()
    store.get_chunks_by_doc.return_value = []
    return store


@pytest.fixture
def client(mock_settings, mock_vector_store, mock_llm, tmp_path, monkeypatch):
    """TestClient with two pre-seeded docs owned by admin."""
    from app.services import multi_mindmap as mm
    monkeypatch.setattr(mm, "MULTI_MINDMAPS_CACHE_DIR", tmp_path / "multi")
    monkeypatch.setattr(mm, "MINDMAPS_CACHE_DIR", tmp_path / "single")

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    @asynccontextmanager
    async def test_lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(UserModel(user_id="admin", display_name="Admin"))
            session.add(UserModel(user_id="alice", display_name="Alice"))
            session.add(DocumentModel(
                doc_id="docA", filename="A.pdf", file_type=".pdf",
                user_id="admin", chunk_count=5,
            ))
            session.add(DocumentModel(
                doc_id="docB", filename="B.pdf", file_type=".pdf",
                user_id="admin", chunk_count=4,
            ))
            session.add(DocumentModel(
                doc_id="docOther", filename="other.pdf", file_type=".pdf",
                user_id="alice", chunk_count=3,
            ))
            await session.commit()
        yield
        await engine.dispose()

    async def override_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.router.lifespan_context = test_lifespan
    app.dependency_overrides[get_settings] = lambda: mock_settings
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_vector_store] = lambda: mock_vector_store
    app.dependency_overrides[get_llm] = lambda: mock_llm
    app.dependency_overrides[get_embeddings] = lambda: MagicMock()
    app.dependency_overrides[get_edge_repository] = lambda: MagicMock()
    app.dependency_overrides[get_summary_store] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


class TestEndpoint:
    def test_empty_doc_ids_returns_400(self, client):
        r = client.get(
            "/graph/mindmap-multi?doc_ids=",
            headers={"X-User-Id": "admin"},
        )
        assert r.status_code == 400

    def test_single_doc_returns_400(self, client):
        r = client.get(
            "/graph/mindmap-multi?doc_ids=docA",
            headers={"X-User-Id": "admin"},
        )
        assert r.status_code == 400
        assert "at least 2" in r.json()["detail"]

    def test_over_cap_returns_400(self, client):
        ids = ",".join(f"doc{i}" for i in range(11))
        r = client.get(
            f"/graph/mindmap-multi?doc_ids={ids}",
            headers={"X-User-Id": "admin"},
        )
        assert r.status_code == 400

    def test_cross_user_docs_dropped(self, client):
        # admin owns docA, docB. docOther is alice's. With both A and Other
        # requested, alice's gets dropped → only 1 owned → 400.
        r = client.get(
            "/graph/mindmap-multi?doc_ids=docA,docOther",
            headers={"X-User-Id": "admin"},
        )
        assert r.status_code == 400

    def test_happy_path_with_mock_llm(self, client, mock_llm, mock_vector_store):
        chunks_a = [_chunk("docA", i, f"summary A {i}") for i in range(3)]
        chunks_b = [_chunk("docB", i, f"summary B {i}") for i in range(2)]
        mock_vector_store.get_chunks_by_doc.side_effect = lambda did: (
            chunks_a if did == "docA" else chunks_b if did == "docB" else []
        )
        mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content=json.dumps({
            "central": "Attention across papers",
            "branches": [
                {"name": "Encoder side", "children": [
                    {"name": "Self-attention",
                     "chunks_by_doc": {"docA": [0, 1], "docB": [0]}},
                ]},
            ],
        })))
        r = client.get(
            "/graph/mindmap-multi?doc_ids=docA,docB",
            headers={"X-User-Id": "admin"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["doc_ids"] == ["docA", "docB"]
        assert body["cached"] is False
        assert body["tree"]["central"] == "Attention across papers"
        leaf = body["tree"]["branches"][0]["children"][0]
        assert leaf["chunks_by_doc"] == {"docA": [0, 1], "docB": [0]}
        # Palette resolved (deterministic fallback since no single-doc cache).
        assert set(body["tree"]["palette"].keys()) == {"docA", "docB"}
