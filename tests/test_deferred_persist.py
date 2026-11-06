"""Deferred persist for bulk ingest (?defer_persist=true + POST /documents/persist).

WHY: every upload saved the FULL FAISS index three times (main store on add, main store again after the chunk
summaries, the summary store). Measured on the live NAS 2026-11-06 with a read-only observer on the atomic-save
temp dirs during one single-chunk upload: 10.0 s + 12.6 s + 7.7 s = 30.3 s of a 40 s document, on a 1.6 GB
index.faiss + 0.56 GB index.pkl main store and a 1.5 GB summary store. A 21k-document corpus = ~9.6 days and
~60k full rewrites of multi-GB files.

Guarantees under test:
- default path is unchanged: add_documents without the kwarg, persist on add, summaries persist as before
- deferred path: no save on add / after summaries, stores marked dirty, one flush saves both and clears dirty
- the flush refuses (409) while deferred summary tasks are still running, and is admin-only
"""
import asyncio
import io
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings, LLMProvider, VectorStoreType
from app.db.models import Base, UserModel
from app.dependencies import (
    get_settings, get_vector_store, get_db, get_llm, get_embeddings, get_edge_repository, get_summary_store,
)
from app.main import create_app
from app.services import task_dispatcher
from app.vectorstore.faiss_store import FAISSStoreManager
from tests.test_workorder_p3 import _HashEmbeddings


def _docs(doc_id, n):
    return [Document(page_content=f"{doc_id} chunk {i}", metadata={"chunk_index": i}) for i in range(n)]


def _live_files(root: Path):
    return sorted(p.name for p in (root / "faiss").glob("index.*"))


# --- store level: real FAISS on disk -------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    s = FAISSStoreManager(tmp_path)
    s.initialize(_HashEmbeddings())
    return s


def test_default_add_persists_and_is_clean(store, tmp_path):
    store.add_documents(_docs("d1", 2), doc_id="d1")
    assert _live_files(tmp_path) == ["index.faiss", "index.pkl"]
    assert store.dirty is False


def test_deferred_add_writes_nothing_until_persist(store, tmp_path):
    store.add_documents(_docs("d1", 2), doc_id="d1", persist=False)
    assert _live_files(tmp_path) == []          # nothing on disk yet
    assert store.dirty is True
    assert len(store.get_chunks_by_doc("d1", allowed_doc_ids=None)) == 2   # but searchable in memory
    store.persist()
    assert _live_files(tmp_path) == ["index.faiss", "index.pkl"]
    assert store.dirty is False
    # and the flushed index loads back with the deferred chunks in it
    again = FAISSStoreManager(tmp_path)
    again.initialize(_HashEmbeddings())
    assert len(again.get_chunks_by_doc("d1", allowed_doc_ids=None)) == 2


def test_failed_save_leaves_store_dirty(store, monkeypatch):
    store.add_documents(_docs("d1", 1), doc_id="d1", persist=False)
    monkeypatch.setattr(store, "_atomic_save", MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        store.persist()
    assert store.dirty is True    # a failed flush must not report clean


# --- summary generator ---------------------------------------------------------------------------------------

class _CountingStore:
    def __init__(self):
        self.persist_calls = 0
        self.add_kwargs = []
        self.marked = 0
        chunk = Document(page_content="x" * 400, metadata={"chunk_index": 0, "chunk_type": "text", "doc_id": "d1"})
        self._store = MagicMock()
        self._store.docstore._dict = {"s0": chunk}
        self._chunks = [chunk]

    def get_chunks_by_doc(self, doc_id, allowed_doc_ids=None):
        return self._chunks

    def persist(self):
        self.persist_calls += 1

    def mark_dirty(self):
        self.marked += 1

    def add_documents(self, docs, doc_id, **kw):
        self.add_kwargs.append(kw)
        return []


def _run_summaries(monkeypatch, defer):
    from app.services import summary_generator as sg

    async def fake_chunk_summary(text, settings, llm=None):
        return "a summary"

    async def fake_doc_summary(*a, **k):
        return None
    monkeypatch.setattr(sg, "generate_chunk_summary", fake_chunk_summary)
    for name in ("generate_doc_summary",):
        if hasattr(sg, name):
            monkeypatch.setattr(sg, name, fake_doc_summary)
    settings = Settings(openai_api_key="fake", summary_provider="openrouter", summary_min_chars=10)
    main, summ = _CountingStore(), _CountingStore()
    try:
        asyncio.run(sg.generate_all_summaries("d1", settings, vector_store=main, summary_store=summ,
                                              **({"defer_persist": True} if defer else {})))
    except Exception:
        pass  # the document-level summary step needs a DB; the store calls under test happen before it
    return main, summ


def test_summaries_default_persist_as_before(monkeypatch):
    main, summ = _run_summaries(monkeypatch, defer=False)
    assert main.persist_calls == 1 and main.marked == 0
    assert summ.add_kwargs == [{}]           # called exactly as before: no persist kwarg


def test_summaries_deferred_mark_dirty_and_skip_save(monkeypatch):
    main, summ = _run_summaries(monkeypatch, defer=True)
    assert main.persist_calls == 0 and main.marked == 1
    assert summ.add_kwargs == [{"persist": False}]


# --- dispatcher ----------------------------------------------------------------------------------------------

def test_deferred_task_is_pending_until_it_finishes_even_on_error(monkeypatch):
    from app.services import summary_generator as sg

    async def boom(*a, **k):
        assert task_dispatcher.deferred_pending() == ["d9"]
        raise RuntimeError("llm down")
    monkeypatch.setattr(sg, "generate_all_summaries", boom)
    bt = MagicMock()
    settings = Settings(openai_api_key="fake")
    asyncio.run(task_dispatcher.enqueue_summary_task("d9", settings, background_tasks=bt, defer_persist=True))
    assert task_dispatcher.deferred_pending() == ["d9"]
    fn, *args = bt.add_task.call_args.args
    with pytest.raises(RuntimeError):
        asyncio.run(fn(*args))
    assert task_dispatcher.deferred_pending() == []


def test_default_enqueue_unchanged(monkeypatch):
    bt = MagicMock()
    asyncio.run(task_dispatcher.enqueue_summary_task("d8", Settings(openai_api_key="fake"), background_tasks=bt))
    fn = bt.add_task.call_args.args[0]
    assert fn.__name__ == "generate_all_summaries"
    assert "defer_persist" not in bt.add_task.call_args.kwargs
    assert task_dispatcher.deferred_pending() == []


# --- API -----------------------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path):
    settings = Settings(openai_api_key="fake-key-for-testing", llm_provider=LLMProvider.OPENAI,
                        vector_store=VectorStoreType.CHROMA, upload_dir=tmp_path, summary_enabled=False,
                        classification_enabled=False)
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def test_lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(UserModel(user_id="admin", display_name="Admin"))
            await session.commit()
        yield
        await engine.dispose()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    vs, summ = MagicMock(), MagicMock()
    vs.dirty, summ.dirty = True, True
    app = create_app()
    app.router.lifespan_context = test_lifespan
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: vs
    app.dependency_overrides[get_llm] = lambda: MagicMock()
    app.dependency_overrides[get_embeddings] = lambda: MagicMock()
    app.dependency_overrides[get_edge_repository] = lambda: MagicMock()
    app.dependency_overrides[get_summary_store] = lambda: summ
    with TestClient(app) as c:
        yield c, vs, summ, settings
    app.dependency_overrides.clear()


def _upload(c, name, **params):
    return c.post("/documents/upload", params=params,
                  files={"file": (name, io.BytesIO(("Section 1 text " * 40).encode()), "text/markdown")},
                  headers={"X-User-Id": "admin"})


def _add_calls(vs):
    return [call for call in vs.add_documents.call_args_list]


def test_upload_default_calls_add_documents_exactly_as_before(api):
    c, vs, _, _ = api
    _upload(c, "a.md")
    calls = _add_calls(vs)
    assert calls, "upload never reached the vector store"
    assert all("persist" not in k.kwargs for k in calls)


def test_upload_deferred_passes_persist_false(api):
    c, vs, _, _ = api
    _upload(c, "b.md", defer_persist="true")
    calls = _add_calls(vs)
    assert calls and calls[-1].kwargs.get("persist") is False


def test_upload_deferred_ignored_when_disabled(api):
    c, vs, _, settings = api
    settings.deferred_persist_enabled = False
    _upload(c, "c.md", defer_persist="true")
    assert all("persist" not in k.kwargs for k in _add_calls(vs))


def test_flush_admin_only(api):
    c, vs, summ, _ = api
    r = c.post("/documents/persist", headers={"X-User-Id": "someone"})
    assert r.status_code == 403
    assert vs.persist.call_count == 0


def test_flush_refuses_while_tasks_pending_then_saves_both(api):
    c, vs, summ, _ = api
    task_dispatcher._DEFERRED_PENDING.add("dX")
    try:
        r = c.post("/documents/persist", headers={"X-User-Id": "admin"})
        assert r.status_code == 409 and vs.persist.call_count == 0
    finally:
        task_dispatcher._DEFERRED_PENDING.discard("dX")
    r = c.post("/documents/persist", headers={"X-User-Id": "admin"})
    assert r.status_code == 200, r.text
    assert vs.persist.call_count == 1 and summ.persist.call_count == 1


def test_persist_status_route_not_captured_by_doc_id_routes(api):
    c, _, _, _ = api
    r = c.get("/documents/persist-status")
    assert r.status_code == 200 and set(r.json()) == {"main_dirty", "summary_dirty", "pending_summary_tasks"}
