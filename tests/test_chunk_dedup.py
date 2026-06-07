"""DUP-PARA: some PDFs extract a paragraph twice (e.g. 第148条 ×2) → duplicate
chunks. Opt-in (legal only) because the same text at different positions can be
legitimate context in general corpora. Dedup is by normalized text within a doc."""
from langchain_core.documents import Document
from app.services.chunk_dedup import dedup_chunks


def _c(text, idx):
    return Document(page_content=text, metadata={"chunk_index": idx})


def test_drops_exact_duplicate_keeping_first():
    chunks = [_c("第148条 内容", 0), _c("别的内容", 1), _c("第148条 内容", 2)]
    out = dedup_chunks(chunks)
    assert [d.page_content for d in out] == ["第148条 内容", "别的内容"]


def test_whitespace_normalized():
    chunks = [_c("第148条  内容", 0), _c("第148条 内容", 1)]
    assert len(dedup_chunks(chunks)) == 1


def test_distinct_text_kept():
    chunks = [_c("a", 0), _c("b", 1), _c("c", 2)]
    assert len(dedup_chunks(chunks)) == 3
