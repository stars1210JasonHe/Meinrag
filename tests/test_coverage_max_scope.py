"""per_doc_coverage_max_scope: above the limit, coverage does nothing (no mandatory marks, no
backfill); at or below it, and with the limit at 0, behaviour is today's.

Case behind it: the 3388-doc legal collection, 2026-11-19 - 30 of 31 context chunks were
mandatory and unrelated statutes filled the tail, because the backfill takes missing docs in
scope-list order (neo outputs/meinrag-version-error-20261119/FINDINGS.md)."""
import inspect

from langchain_core.documents import Document

from app.config import Settings
from app.services import retrieval
from app.services.retrieval import _ensure_per_doc_coverage


def _doc(did, idx=0):
    return Document(page_content=f"text {did}", metadata={"doc_id": did, "chunk_index": idx})


class _FakeStore:
    def __init__(self):
        self.calls = 0

    def get_chunks_by_doc(self, did, **_):
        self.calls += 1
        return [_doc(did)]


def _mandatory(out):
    return [d.metadata["doc_id"] for d, _ in out if d.metadata.get("_mandatory")]


def _run(n_scope, max_scope, n_retrieved=3, pool_docs=10):
    scope = [f"d{i}" for i in range(n_scope)]
    retrieved = [(_doc(f"d{i}"), 0.9 - i * 0.01) for i in range(n_retrieved)]
    pool = [(_doc(f"d{i}", 5), 0.5) for i in range(n_retrieved, n_retrieved + pool_docs)]
    store = _FakeStore()
    out = _ensure_per_doc_coverage(
        retrieved, all_candidates=pool, scope_doc_ids=scope,
        vector_store=store, max_backfill=30, max_scope=max_scope,
    )
    return out, store


def test_large_scope_above_limit_is_untouched():
    out, store = _run(n_scope=3388, max_scope=30)
    assert _mandatory(out) == []             # nothing pinned
    assert len(out) == 3                      # nothing backfilled
    assert store.calls == 0                   # no per-doc store reads


def test_large_scope_without_limit_keeps_todays_behaviour():
    # The failing state the limit exists for: surfaced docs pinned + pool backfill.
    out, _ = _run(n_scope=3388, max_scope=0)
    assert len(_mandatory(out)) == 3 + 10 + 20   # 3 surfaced, 10 from pool, 20 via store (cap 30)


def test_scope_at_limit_is_still_covered():
    out, _ = _run(n_scope=30, max_scope=30)
    assert sorted(_mandatory(out)) == sorted(f"d{i}" for i in range(30))


def test_small_multiselect_unaffected_by_limit():
    out, _ = _run(n_scope=8, max_scope=30, n_retrieved=1, pool_docs=0)
    assert sorted(_mandatory(out)) == sorted(f"d{i}" for i in range(8))


def test_default_setting_is_no_limit():
    assert Settings.model_fields["per_doc_coverage_max_scope"].default == 0


def test_call_site_passes_the_setting():
    # Guards the wiring: a function that accepts max_scope is useless if retrieve() never passes it.
    src = inspect.getsource(retrieval)
    call = src[src.index("retrieved = _ensure_per_doc_coverage("):]
    call = call[:call.index(")\n")]
    assert "max_scope=_coverage_max_scope(settings)" in call


def test_setting_reader():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    assert retrieval._coverage_max_scope(SimpleNamespace(per_doc_coverage_max_scope=30)) == 30
    assert retrieval._coverage_max_scope(SimpleNamespace()) == 0          # attribute absent
    assert retrieval._coverage_max_scope(MagicMock()) == 0                # test doubles elsewhere in the suite
    assert retrieval._coverage_max_scope(SimpleNamespace(per_doc_coverage_max_scope=True)) == 0
