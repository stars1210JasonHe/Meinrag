"""Opt-in tokenizers for the BM25 hybrid arm.

WHY. BM25Retriever's default ``preprocess_func`` is ``text.split()``. Chinese text has no spaces, so a Chinese
question is ONE token and a Chinese chunk is one or a few: the lexical arm matches nothing and hybrid search is
effectively dense-only on this corpus. Measured 2026-09-26 on the 55,234 ``legal`` chunks with 240 generated
questions, keyword-only doc recall@10: split 0.000, jieba 0.883 (offline; not a live-pipeline number).

WHY OPT-IN. The live pipeline effect is unmeasured, and a jieba index for ``legal`` costs ~0.75 GB RSS. So a request
must ask for it (``SearchRequest.bm25_tokenizer``); without that, the caller keeps its existing default path and
this module is never touched. The opt-in index lives in its OWN cache and is evicted after ``IDLE_TTL_S`` unused,
so an evaluation run hands its memory back.
"""
from __future__ import annotations

import re
import time
from typing import Callable

DEFAULT = "whitespace"
IDLE_TTL_S = 15 * 60
_PUNCT = re.compile(r"[\W_]+")

# tokenizer name -> {"retriever", "doc_ids_key", "last_used"}
_opt_in_caches: dict[str, dict] = {}


def _jieba(text: str) -> list[str]:
    import jieba  # lazy: only an opt-in request pays the import and dictionary load

    jieba.setLogLevel(60)
    return [w for w in jieba.lcut(text) if w.strip() and not _PUNCT.fullmatch(w)]


_TOKENIZERS: dict[str, Callable[[str], list[str]]] = {"jieba": _jieba}
SUPPORTED = (DEFAULT, *_TOKENIZERS)


def is_default(name: str | None) -> bool:
    return name in (None, DEFAULT)


def tokenize(name: str, text: str) -> list[str]:
    if is_default(name):
        return text.split()
    return _TOKENIZERS[name](text)


def opt_in_cache_size() -> int:
    return len(_opt_in_caches)


def invalidate_opt_in_caches() -> None:
    _opt_in_caches.clear()


def evict_idle(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    for name in [n for n, c in _opt_in_caches.items() if now - c["last_used"] > IDLE_TTL_S]:
        del _opt_in_caches[name]


def get_retriever(name: str, load_docs: Callable[[], list], cache_key, k: int, now: float | None = None):
    """BM25 retriever for an opt-in tokenizer, cached per tokenizer and scope. Returns None if no docs."""
    from langchain_community.retrievers import BM25Retriever

    if name not in _TOKENIZERS:
        raise ValueError("unsupported bm25 tokenizer %r (supported: %s)" % (name, ", ".join(SUPPORTED)))
    now = time.monotonic() if now is None else now
    c = _opt_in_caches.get(name)
    if c is not None and c["doc_ids_key"] == cache_key:
        c["retriever"].k = k
        c["last_used"] = now
        return c["retriever"]
    docs = load_docs()
    if not docs:
        return None
    r = BM25Retriever.from_documents(docs, k=k, preprocess_func=_TOKENIZERS[name])
    _opt_in_caches[name] = {"retriever": r, "doc_ids_key": cache_key, "last_used": now}
    return r
