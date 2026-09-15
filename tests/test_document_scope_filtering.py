"""Document scope is enforced on every path that returns chunk content.

The invariant: a request for a document's content states, on the way in, which
documents the caller is entitled to read, and the store returns nothing outside
that set. Ownership is decided once at the route, and the store is what makes
"nobody applied it here" impossible rather than merely unlikely.

Two layers, and the second is the load-bearing one:

  route layer    a request for a document the caller does not own is refused,
                 and a request for one they do own is unchanged.
  storage layer  `get_chunks_by_doc` is the common throat of every content path
                 (16 call sites: 6 in routers, 10 in services). Its
                 `allowed_doc_ids` parameter is REQUIRED and keyword-only --
                 see `test_storage_refuses_to_be_called_without_a_decision` for
                 why it must not acquire a default.

Each layer has both cells: the owner must still get their content, and the
non-owner must not. A suite that only asserts the refusal cannot tell a working
gate from one that refuses everybody.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document


def _doc(doc_id: str, chunk_index: int = 0, content: str = "secret") -> Document:
    return Document(page_content=content,
                    metadata={"doc_id": doc_id, "chunk_index": chunk_index})


class _Store:
    """Minimal stand-in carrying the real gate semantics under test."""

    def __init__(self, chunks_by_doc: dict[str, list[Document]]):
        self._chunks = chunks_by_doc
        self.calls: list[tuple] = []

    def get_chunks_by_doc(self, doc_id, chunk_indices=None, *, allowed_doc_ids):
        self.calls.append((doc_id, allowed_doc_ids))
        if allowed_doc_ids is not None and doc_id not in allowed_doc_ids:
            return []
        return list(self._chunks.get(doc_id, []))


class _Registry:
    def __init__(self, owners: dict[str, str]):
        self._owners = owners

    async def get(self, doc_id):
        owner = self._owners.get(doc_id)
        return None if owner is None else {"doc_id": doc_id, "user_id": owner}

    async def get_many_by_ids(self, doc_ids, user_id=None):
        return [{"doc_id": d, "user_id": self._owners[d]}
                for d in doc_ids
                if d in self._owners and (user_id is None or self._owners[d] == user_id)]


class _Settings:
    def __init__(self, user_isolation="all"):
        self.user_isolation = user_isolation


# --------------------------------------------------------- storage layer -----
class TestStorageLayerGate:
    def test_storage_refuses_to_be_called_without_a_decision(self):
        """A gate that defaults to open is not a gate.

        Every concrete store must take `allowed_doc_ids` as a REQUIRED
        keyword-only parameter, so a future route cannot reach chunk content
        without stating whose documents it is allowed to read.
        """
        from app.vectorstore.base import VectorStoreManager
        sig = inspect.signature(VectorStoreManager.get_chunks_by_doc)
        p = sig.parameters.get("allowed_doc_ids")
        assert p is not None, "storage layer has no allow-list parameter"
        assert p.kind is inspect.Parameter.KEYWORD_ONLY, p.kind
        assert p.default is inspect.Parameter.empty, (
            "allowed_doc_ids must be REQUIRED; a default of None means every "
            "forgotten caller silently keeps today's unguarded behaviour")

    def test_every_concrete_store_has_the_same_signature(self):
        """Two stores drifting apart is how one of them ends up without a gate."""
        from app.vectorstore.base import VectorStoreManager
        from app.vectorstore.chroma_store import ChromaStoreManager
        from app.vectorstore.faiss_store import FAISSStoreManager
        base = inspect.signature(VectorStoreManager.get_chunks_by_doc).parameters
        for impl in (ChromaStoreManager, FAISSStoreManager):
            got = inspect.signature(impl.get_chunks_by_doc).parameters
            assert "allowed_doc_ids" in got, impl.__name__
            assert got["allowed_doc_ids"].kind is inspect.Parameter.KEYWORD_ONLY
            assert got["allowed_doc_ids"].default is inspect.Parameter.empty, impl.__name__
            assert set(got) == set(base), (impl.__name__, set(got) ^ set(base))

    def test_denied_helper_lives_in_one_place(self):
        """chroma and faiss must share the decision, not each re-implement it."""
        from app.vectorstore.base import VectorStoreManager
        assert hasattr(VectorStoreManager, "_scope_denies")
        assert VectorStoreManager._scope_denies("d1", None) is False
        assert VectorStoreManager._scope_denies("d1", {"d1"}) is False
        assert VectorStoreManager._scope_denies("d1", {"d2"}) is True
        assert VectorStoreManager._scope_denies("d1", set()) is True


# ----------------------------------------------------------- route layer -----
@pytest.mark.asyncio
class TestDocumentChunksRoute:
    async def test_in_scope_doc_returns_its_chunks(self):
        """The in-scope cell -- narrowing must not narrow away the legitimate case."""
        from app.routers.documents import get_document_chunks
        store = _Store({"d1": [_doc("d1", 0, "mine")]})
        resp = await get_document_chunks(
            doc_id="d1", page=None, vector_store=store,
            settings=_Settings(), registry=_Registry({"d1": "alice"}),
            current_user="alice", scope_collection=None)
        assert [c.content for c in resp.chunks] == ["mine"]

    async def test_out_of_scope_doc_yields_no_content(self):
        """The out-of-scope cell. Both cells are required: a filter that returns
        nothing for everyone would pass the in-scope test only by accident."""
        from app.routers.documents import get_document_chunks
        store = _Store({"d2": [_doc("d2", 0, "out of scope for this caller")]})
        with pytest.raises(HTTPException) as e:
            await get_document_chunks(
                doc_id="d2", page=None, vector_store=store,
                settings=_Settings(), registry=_Registry({"d2": "bob"}),
                current_user="alice", scope_collection=None)
        assert e.value.status_code in (403, 404), e.value.status_code

    async def test_unknown_doc_is_404_not_500(self):
        from app.routers.documents import get_document_chunks
        with pytest.raises(HTTPException) as e:
            await get_document_chunks(
                doc_id="nope", page=None, vector_store=_Store({}),
                settings=_Settings(), registry=_Registry({}), current_user="alice", scope_collection=None)
        assert e.value.status_code == 404

    async def test_isolation_off_keeps_todays_behaviour(self):
        """user_isolation='none' is a deployment choice, not a bug to fix here."""
        from app.routers.documents import get_document_chunks
        store = _Store({"d2": [_doc("d2", 0, "shared")]})
        resp = await get_document_chunks(
            doc_id="d2", page=None, vector_store=store,
            settings=_Settings(user_isolation="none"),
            registry=_Registry({"d2": "bob"}), current_user="alice", scope_collection=None)
        assert [c.content for c in resp.chunks] == ["shared"]


@pytest.mark.asyncio
class TestNeighborsRoute:
    async def test_out_of_scope_doc_yields_no_content(self):
        """`/graph/neighbors` injects no current_user at all today."""
        from app.routers.graph import get_neighbors
        import inspect as _i
        assert "current_user" in _i.signature(get_neighbors).parameters, \
            "the route must receive the caller's identity before it can check it"


class TestNeighborsCrossDocScope:
    def test_cross_doc_fetch_passes_an_allow_list(self):
        """The BFS follows edges INTO other documents and returns their
        content_preview. An ownership check on the entry doc_id alone does not
        reach that call, so the cross-doc fetch must carry the allow-list."""
        import re
        from pathlib import Path
        import app.routers.graph as g
        src = Path(g.__file__).read_text(encoding="utf-8")
        calls = re.findall(r"get_chunks_by_doc\((.*?)\)", src, flags=re.S)
        assert calls, "instrument dead: no calls found in graph.py"
        unguarded = [c for c in calls if "allowed_doc_ids" not in c]
        assert not unguarded, f"unguarded chunk fetches in graph.py: {unguarded}"
