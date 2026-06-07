"""Bug 3a: a collection-scoped query expands to ALL member doc_ids, and
_ensure_per_doc_coverage force-backfills 1 chunk per missing doc. For a 1456-doc
collection that's ~1453 mandatory chunks → reranker OOM + context blow-up. The
backfill must be capped; small multi-select scopes stay fully covered."""
from langchain_core.documents import Document
from app.services.retrieval import _ensure_per_doc_coverage


def _doc(did, idx=0):
    return Document(page_content=f"text {did}", metadata={"doc_id": did, "chunk_index": idx})


class _FakeStore:
    def get_chunks_by_doc(self, did):
        return [_doc(did)]


def _mandatory_count(retrieved):
    return sum(1 for d, _ in retrieved if d.metadata.get("_mandatory"))


def test_backfill_capped_for_large_scope():
    scope = [f"d{i}" for i in range(200)]          # 200 docs in scope
    retrieved = [(_doc("d0"), 0.9)]                # only 1 surfaced
    out = _ensure_per_doc_coverage(
        retrieved, all_candidates=[], scope_doc_ids=scope,
        vector_store=_FakeStore(), max_backfill=30,
    )
    # 1 surfaced mandatory + at most 30 backfilled = <= 31
    assert _mandatory_count(out) <= 31


def test_small_multiselect_fully_covered():
    scope = [f"d{i}" for i in range(8)]            # multi-select of 8
    retrieved = [(_doc("d0"), 0.9)]
    out = _ensure_per_doc_coverage(
        retrieved, all_candidates=[], scope_doc_ids=scope,
        vector_store=_FakeStore(), max_backfill=30,
    )
    covered = {d.metadata["doc_id"] for d, _ in out if d.metadata.get("_mandatory")}
    assert covered == set(scope)                   # all 8 covered
