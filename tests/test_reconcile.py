from app.services.reconcile import find_orphans


def test_find_orphans_both_directions():
    faiss_ids = {"a", "b", "c", "x"}      # x = FAISS-only orphan
    registry_ids = {"a", "b", "c", "y"}   # y = registry-only orphan
    faiss_only, registry_only = find_orphans(faiss_ids, registry_ids)
    assert faiss_only == {"x"}
    assert registry_only == {"y"}


def test_find_orphans_clean():
    assert find_orphans({"a", "b"}, {"a", "b"}) == (set(), set())
