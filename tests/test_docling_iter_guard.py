"""Bug 1: 25 files (17 PDF + 8 .docx, both via the docling path) crashed with
'not enough values to unpack (expected 2, got 1)'. In docling mode every file
type goes through docling_process(), so both reach `for element, _level in
doc.iterate_items()` — the only shared per-element 2-unpack. We can't reproduce
(no docling locally, files on NAS), so we guard the unpack so a malformed yield
degrades instead of 500ing. Validated by re-running a failing file in deployment."""
from app.services.docling_processor import _iter_doc_items


class _FakeDoc:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        return iter(self._items)


def test_handles_mixed_yield_shapes():
    doc = _FakeDoc([("a", 1), ("b",), "c"])      # 2-tuple, 1-tuple, bare
    out = list(_iter_doc_items(doc))
    assert out == [("a", 1), ("b", None), ("c", None)]
