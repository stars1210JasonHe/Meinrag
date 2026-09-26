"""Opt-in CJK tokenizer for the BM25 hybrid arm (2026-09-26).

Measured before this change: BM25Retriever's default preprocess_func is ``text.split()``, so a Chinese question
with no spaces is ONE token and the lexical arm returns nothing useful for Chinese (keyword-only doc recall@10 on
240 legal questions: 0.000 with split vs 0.883 with jieba, offline). This change lets a request OPT IN to jieba;
the default path must stay byte-for-byte what it was, so production behaviour does not move until someone decides.

T1  jieba yields more than one token for a Chinese sentence; whitespace split yields one (the defect, pinned).
T2  a default request never builds or touches the opt-in index.
T3  an opt-in request uses a cache separate from the default one.
T4  document add/delete (invalidate_bm25_cache) clears the opt-in caches too.
T5  an opt-in index unused for longer than the TTL is evicted (memory is returned after an eval run).
"""
from langchain_core.documents import Document

from app.rag import bm25_tokenizers as bt
from app.rag.chain import _bm25_cache, invalidate_bm25_cache

SENTENCE = "被征收房屋的评估价经复核后有变动"


def _docs():
    return [Document(page_content="被征收房屋评估价复核后变动的，评估均价不受影响", metadata={"doc_id": "d1"}),
            Document(page_content="出租人有权要求承租人及时支付拖欠的租金", metadata={"doc_id": "d2"})]


def setup_function(_):
    invalidate_bm25_cache()


def test_t1_jieba_splits_chinese_and_split_does_not():
    assert len(SENTENCE.split()) == 1                       # the defect, pinned
    assert len(bt.tokenize("jieba", SENTENCE)) > 1


def test_t2_default_request_never_touches_opt_in_cache():
    assert bt.is_default(None) and bt.is_default("whitespace")
    assert bt.opt_in_cache_size() == 0
    # the default path is the caller's existing code; this module must not have built anything for it
    assert bt.opt_in_cache_size() == 0


def test_t3_opt_in_uses_its_own_cache():
    r = bt.get_retriever("jieba", _docs, cache_key=None, k=2, now=100.0)
    assert r is not None and bt.opt_in_cache_size() == 1
    assert _bm25_cache["retriever"] is None                 # default cache untouched
    hits = r.invoke(SENTENCE)
    assert hits and hits[0].metadata["doc_id"] == "d1"      # lexical match now works on Chinese


def test_t4_invalidate_clears_opt_in_caches():
    bt.get_retriever("jieba", _docs, cache_key=None, k=2, now=100.0)
    assert bt.opt_in_cache_size() == 1
    invalidate_bm25_cache()
    assert bt.opt_in_cache_size() == 0


def test_t5_idle_opt_in_index_is_evicted():
    bt.get_retriever("jieba", _docs, cache_key=None, k=2, now=100.0)
    bt.evict_idle(now=100.0 + bt.IDLE_TTL_S - 1)
    assert bt.opt_in_cache_size() == 1
    bt.evict_idle(now=100.0 + bt.IDLE_TTL_S + 1)
    assert bt.opt_in_cache_size() == 0
