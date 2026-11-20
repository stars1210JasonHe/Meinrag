"""Header-only docs: is_navigation_chunk + _expand_navigation_hits.

The failure these reproduce (2026-11-20): a question naming "2014年修正的《行政诉讼法》" pulled the
statute's header chunk (title, 【发布部门】, 目录) into the candidates but not the chunk with Art. 46
(六个月); the answer then used 1989-era commentary (三个月) under the 2014 label.
"""
from langchain_core.documents import Document

from app.config import Settings
from app.services.chunk_utils import is_navigation_chunk
from app.services.retrieval import _expand_navigation_hits

HEADER = (
    "中华人民共和国行政诉讼法(2014修正)\n【发布部门】 全国人民代表大会\n【发文字号】 主席令第15号\n"
    "【发布日期】 2014.11.01【实施日期】 1990.10.01\n【时效性】 现行有效\n"
    "目录\n第一章　总则\n第二章　受案范围\n第三章　管辖\n"
)
TOC_ONLY = "某某条例\n目录\n第一章 总则\n第二章 登记\n第三章 法律责任\n第四章 附则"
ART46 = "第四十六条　公民、法人或者其他组织直接向人民法院提起诉讼的，应当自知道或者应当知道作出行政行为之日起六个月内提出。"
ART44 = "第四十四条　对属于人民法院受案范围的行政案件，可以先向行政机关申请复议。"
ART2 = "第二条　公民、法人或者其他组织认为行政机关的行政行为侵犯其合法权益，有权提起诉讼。"


# ── detector ──────────────────────────────────────────────────────────────

def test_header_block_is_navigation():
    assert is_navigation_chunk(HEADER)


def test_toc_without_fields_is_navigation():
    assert is_navigation_chunk(TOC_ONLY)


def test_provision_is_not_navigation():
    assert not is_navigation_chunk(ART46)


def test_header_followed_by_a_provision_is_content():
    # a short law whose first chunk already contains Art. 1 has real content
    assert not is_navigation_chunk(HEADER + "第一条　为保证人民法院公正、及时审理行政案件，制定本法。")


def test_two_fields_or_two_chapters_are_not_enough():
    assert not is_navigation_chunk("【发布部门】 国务院\n【时效性】 现行有效\n正文说明")
    assert not is_navigation_chunk("目录\n第一章 总则\n第二章 附则")


def test_empty_and_plain_text():
    assert not is_navigation_chunk("")
    assert not is_navigation_chunk("起诉期限从知道或者应当知道行政行为之日起计算。")


# ── expansion ─────────────────────────────────────────────────────────────

def _doc(did, idx, text, **meta):
    return Document(page_content=text, metadata={"doc_id": did, "chunk_index": idx, **meta})


class _Store:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def get_chunks_by_doc(self, did, chunk_indices=None, **_):
        self.calls.append(did)
        return sorted([d for d in self.docs if d.metadata["doc_id"] == did], key=lambda d: d.metadata["chunk_index"])


class _Emb:
    """Two-dimensional toy embedding: axis 0 = mentions 六个月, axis 1 = mentions 复议."""

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def _v(self, t):
        return [1.0 if "六个月" in t else 0.05, 1.0 if "复议" in t else 0.05]

    def embed_query(self, t):
        if self.fail:
            raise RuntimeError("embedding service down")
        return [1.0, 0.1]

    def embed_documents(self, ts):
        self.calls += 1
        return [self._v(t) for t in ts]


def _statute(did="law2014"):
    return [_doc(did, 0, HEADER), _doc(did, 1, ART2), _doc(did, 19, ART44), _doc(did, 20, ART46)]


def _keys(pairs):
    return [(d.metadata["doc_id"], d.metadata["chunk_index"]) for d, _ in pairs]


def test_header_only_doc_gets_its_best_provision():
    store = _Store(_statute())
    retrieved = [(_doc("other", 3, "评论：修改前第三十九条规定三个月。"), 0.9), (store.docs[0], 0.8)]
    out = _expand_navigation_hits(retrieved, store, "2014行政诉讼法起诉期限", _Emb(), per_doc=1)
    assert _keys(out) == [("other", 3), ("law2014", 0), ("law2014", 20)]
    added = out[-1][0]
    assert added.metadata["_sim_source"] == "nav_expansion"
    assert added.metadata["_query_sim"] == out[-1][1] > 0.9


def test_per_doc_limits_and_order():
    store = _Store(_statute())
    out = _expand_navigation_hits([(store.docs[0], 0.8)], store, "q", _Emb(), per_doc=2)
    # toy cosines vs query (1, 0.1): Art.46 (1, .05) 0.999 > Art.2 (.05, .05) 0.77 > Art.44 (.05, 1) 0.15
    assert _keys(out)[1:] == [("law2014", 20), ("law2014", 1)]


def test_doc_with_a_content_chunk_already_retrieved_is_not_expanded():
    store = _Store(_statute())
    retrieved = [(store.docs[0], 0.8), (store.docs[2], 0.7)]
    out = _expand_navigation_hits(retrieved, store, "q", _Emb())
    assert out == retrieved
    assert store.calls == []


def test_navigation_chunks_and_already_retrieved_chunks_are_not_added():
    docs = _statute() + [_doc("law2014", 30, TOC_ONLY)]
    store = _Store(docs)
    out = _expand_navigation_hits([(docs[0], 0.8)], store, "q", _Emb(), per_doc=10)
    added = _keys(out)[1:]
    assert ("law2014", 0) not in added and ("law2014", 30) not in added
    assert sorted(added) == [("law2014", 1), ("law2014", 19), ("law2014", 20)]


def test_max_docs_takes_the_first_in_retrieval_order():
    docs = _statute("a") + _statute("b") + _statute("c")
    store = _Store(docs)
    retrieved = [(d, 0.5) for d in docs if d.metadata["chunk_index"] == 0]
    out = _expand_navigation_hits(retrieved, store, "q", _Emb(), max_docs=2, per_doc=1)
    assert {k[0] for k in _keys(out)[3:]} == {"a", "b"}


def test_long_doc_is_skipped():
    store = _Store(_statute())
    out = _expand_navigation_hits([(store.docs[0], 0.8)], store, "q", _Emb(), max_scan=3)
    assert len(out) == 1


def test_embedding_failure_leaves_the_pipeline_unchanged():
    store = _Store(_statute())
    retrieved = [(store.docs[0], 0.8)]
    assert _expand_navigation_hits(retrieved, store, "q", _Emb(fail=True)) == retrieved


def test_added_chunk_does_not_inherit_mandatory_from_the_shared_docstore_object():
    docs = _statute()
    docs[3].metadata["_mandatory"] = True  # left behind by an earlier query
    out = _expand_navigation_hits([(docs[0], 0.8)], _Store(docs), "q", _Emb(), per_doc=1)
    assert "_mandatory" not in out[-1][0].metadata


def test_no_header_in_candidates_means_no_work():
    store = _Store(_statute())
    emb = _Emb()
    retrieved = [(store.docs[3], 0.9)]
    assert _expand_navigation_hits(retrieved, store, "q", emb) == retrieved
    assert store.calls == [] and emb.calls == 0


def test_off_by_default():
    assert Settings.model_fields["nav_expansion_enabled"].default is False
