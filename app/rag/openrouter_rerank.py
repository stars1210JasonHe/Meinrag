"""OpenRouter `/rerank` as a LangChain document compressor.

One provider covers every rerank model OpenRouter serves (voyageai/rerank-3, cohere/rerank-4-pro,
qwen/qwen3-reranker-8b, ...); the model is chosen by `rerank_model`. Contract (OpenRouter openapi.json, read
2026-10-27): POST {base}/rerank {model, query, documents[], top_n, provider} -> {results: [{index,
relevance_score}], provider, usage: {cost, total_tokens, search_units}}.

Failure is loud on purpose: an HTTP error, an empty result or an out-of-range / repeated index raises, so
`_rerank_results` falls back with ran=False and the trace shows the reranker did not run. Returning the input
order instead would look exactly like a reranker that agreed with retrieval.
"""
import logging
import time
from typing import Optional, Sequence

import httpx
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from pydantic import ConfigDict

logger = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER = 5.0


class OpenRouterRerank(BaseDocumentCompressor):
    model: str
    api_key: str
    top_n: int = 4
    base_url: str = "https://openrouter.ai/api/v1"
    timeout: float = 30.0
    # Each document is cut to this many characters before it is sent (0 = no cut). Chunks are short (median
    # 224 chars, measured 2026-10-27) but a few are >100k, which exceeds every provider's per-document limit.
    max_chars: int = 8000
    allow_fallbacks: bool = False
    zdr: bool = False
    retries: int = 2
    retry_backoff: float = 1.0
    retry_budget: float = 8.0   # seconds; no retry starts if elapsed + next wait would exceed it
    sleep: Optional[object] = None  # injected by tests; defaults to time.sleep
    clock: Optional[object] = None  # injected by tests; defaults to time.monotonic
    transport: Optional[httpx.BaseTransport] = None  # injected by tests

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def payload(self, documents: Sequence[Document], query: str) -> dict:
        texts = [d.page_content or "" for d in documents]
        if self.max_chars > 0:
            texts = [t[: self.max_chars] for t in texts]
        provider = {"allow_fallbacks": self.allow_fallbacks}
        if self.zdr:
            provider["zdr"] = True
        return {"model": self.model, "query": query, "documents": texts,
                "top_n": min(self.top_n, len(texts)), "provider": provider}

    def _wait(self, attempt: int, resp: Optional[httpx.Response]) -> float:
        wait = self.retry_backoff * (2 ** attempt)
        ra = resp.headers.get("retry-after") if resp is not None else None
        if ra:
            try:
                wait = max(wait, min(float(ra), MAX_RETRY_AFTER))
            except ValueError:
                pass
        return wait

    def _over_budget(self, elapsed: float, wait: float) -> bool:
        if elapsed + wait <= self.retry_budget:
            return False
        logger.warning("openrouter rerank retry budget %.1fs used up (elapsed %.1fs, next wait %.1fs); giving up",
                       self.retry_budget, elapsed, wait)
        return True

    def _post(self, payload: dict) -> httpx.Response:
        """POST with retries on 429 / 5xx / connection errors, within retry_budget seconds in total. Returns the
        last response; a final error status is left for the caller's raise_for_status, a final connection error
        is raised. Timeouts (connect, read, write, pool) are never retried."""
        url = self.base_url.rstrip("/") + "/rerank"
        headers = {"Authorization": "Bearer " + self.api_key}
        sleep = self.sleep or time.sleep
        clock = self.clock or time.monotonic
        t0 = clock()
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            for attempt in range(self.retries + 1):
                last = attempt == self.retries
                try:
                    resp = client.post(url, json=payload, headers=headers)
                except httpx.TimeoutException:
                    raise  # a timeout already cost `timeout` seconds; do not multiply it
                except httpx.TransportError as e:
                    wait = self._wait(attempt, None)
                    if last or self._over_budget(clock() - t0, wait):
                        raise
                    logger.warning("openrouter rerank retry %d/%d after %s, waiting %.1fs", attempt + 1, self.retries,
                                   type(e).__name__, wait)
                    sleep(wait)
                    continue
                if resp.status_code not in RETRY_STATUS or last:
                    return resp
                wait = self._wait(attempt, resp)
                if self._over_budget(clock() - t0, wait):
                    return resp
                logger.warning("openrouter rerank retry %d/%d after HTTP %d, waiting %.1fs", attempt + 1, self.retries,
                               resp.status_code, wait)
                sleep(wait)
        raise AssertionError("unreachable")

    def compress_documents(self, documents: Sequence[Document], query: str,
                           callbacks: Optional[Callbacks] = None) -> Sequence[Document]:
        docs = list(documents)
        if not docs:
            return []
        resp = self._post(self.payload(docs, query))
        resp.raise_for_status()
        body = resp.json()
        results = body.get("results")
        if not isinstance(results, list) or not results:
            raise ValueError("OpenRouter rerank returned no results")
        out, seen = [], set()
        for item in results:
            i = item.get("index") if isinstance(item, dict) else None
            if not isinstance(i, int) or not 0 <= i < len(docs) or i in seen:
                raise ValueError("OpenRouter rerank returned an invalid index: %r" % (i,))
            seen.add(i)
            d = docs[i]
            out.append(Document(page_content=d.page_content,
                                metadata={**d.metadata, "relevance_score": item.get("relevance_score")}))
        usage = body.get("usage") or {}
        cut = sum(len(d.page_content or "") > self.max_chars for d in docs) if self.max_chars > 0 else 0
        logger.info("openrouter rerank model=%s served_by=%s in=%d out=%d cut=%d cost=%s total_tokens=%s "
                    "search_units=%s", body.get("model"), body.get("provider"), len(docs), len(out), cut,
                    usage.get("cost"), usage.get("total_tokens"), usage.get("search_units"))
        return out
