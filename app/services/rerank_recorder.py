"""Opt-in record of what the LLM listwise reranker was given and what it answered.

Why: in the 2026-10-26 target-trace run every rerank loss was a target that WAS in the
reranker's input and was missing from its output, and on article queries the LLM returned
exactly 5 ids in 143 of 237 calls although top_n is far larger. The response only shows the
documents LangChain kept, so it cannot say whether the model chose few ids, was cut off, or
returned ids LangChain could not map. This records the model's own answer.

Only ids, lengths, finish reasons and token counts are recorded -- never document or query
text -- so the record can leave a deployment that holds client material.

Variants (debug_target.rerank_variants) send the SAME candidates again; their answers are
recorded and never used:
  repeat    the unchanged prompt again: run-to-run variation of one prompt
  all_ids   a prompt that asks for every id exactly once
  shuffled  the unchanged prompt, input order permuted with a fixed seed: separates "late in
            the list" from "scored low upstream", which the score-sorted input confounds
"""
import json
import logging
import random

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

SHUFFLE_SEED = 20261026

ALL_IDS_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "{context}\n\nSort the Documents by their relevance to the Query. "
               "Return the IDs of ALL the documents, every ID exactly once, from most to least relevant."),
    ("human", "{query}"),
])


def _int_list(value) -> list[int] | None:
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, int) and not isinstance(v, bool)]


def _ids_from_message(msg) -> tuple[list[int] | None, str]:
    """The ranked ids as the model wrote them, before LangChain maps them to documents."""
    for call in getattr(msg, "tool_calls", None) or []:
        ids = _int_list((call.get("args") or {}).get("ranked_document_ids"))
        if ids is not None:
            return ids, "tool_call"
    parsed = (getattr(msg, "additional_kwargs", None) or {}).get("parsed")
    if parsed is not None:
        raw = parsed.get("ranked_document_ids") if isinstance(parsed, dict) else getattr(parsed, "ranked_document_ids", None)
        ids = _int_list(raw)
        if ids is not None:
            return ids, "parsed"
    content = getattr(msg, "content", None)
    if isinstance(content, str) and content.strip():
        try:
            ids = _int_list(json.loads(content).get("ranked_document_ids"))
        except (ValueError, AttributeError):
            ids = None
        if ids is not None:
            return ids, "content_json"
    return None, "not_found"


class RerankCapture(BaseCallbackHandler):
    """Captures the chat model's answer inside LLMListwiseRerank via LangChain callbacks."""

    def __init__(self):
        self.raw_ids = None
        self.raw_kind = "no_llm_end"
        self.finish_reason = None
        self.usage = None
        self.llm_error = None

    def on_llm_end(self, response, **kwargs):
        try:
            gen = response.generations[0][0]
            msg = getattr(gen, "message", None)
            self.raw_ids, self.raw_kind = _ids_from_message(msg)
            meta = getattr(msg, "response_metadata", None) or {}
            self.finish_reason = (gen.generation_info or {}).get("finish_reason") or meta.get("finish_reason")
            um = getattr(msg, "usage_metadata", None) or {}
            self.usage = {"input_tokens": um.get("input_tokens"), "output_tokens": um.get("output_tokens")}
        except Exception as e:  # a recorder must never break the call it observes
            self.raw_kind = "capture_failed:%s" % type(e).__name__

    def on_llm_error(self, error, **kwargs):
        self.llm_error = type(error).__name__


def input_record(docs) -> list:
    """[doc_id, chunk_index, characters] per candidate, in the order the model saw them."""
    return [[d.metadata.get("doc_id"), d.metadata.get("chunk_index"), len(d.page_content or "")] for d in docs]


def call_record(docs, compressed, cap: RerankCapture, error: Exception | None = None) -> dict:
    """One reranker call. out_idx = input positions of the documents LangChain returned."""
    pos = {id(d): i for i, d in enumerate(docs)}
    return {
        "out_idx": None if compressed is None else [pos.get(id(d)) for d in compressed],
        "raw_ids": cap.raw_ids,
        "raw_kind": cap.raw_kind,
        "finish_reason": cap.finish_reason,
        "usage": cap.usage,
        "llm_error": cap.llm_error,
        "error": None if error is None else type(error).__name__,
    }


def _one_variant(llm, docs, question, top_n, prompt=None) -> dict:
    from langchain_classic.retrievers.document_compressors.listwise_rerank import LLMListwiseRerank
    cap = RerankCapture()
    try:
        comp = LLMListwiseRerank.from_llm(llm, top_n=top_n, prompt=prompt)
        return call_record(docs, comp.compress_documents(docs, question, callbacks=[cap]), cap)
    except Exception as e:
        return call_record(docs, None, cap, error=e)


def run_variants(llm, docs, question, top_n) -> dict:
    out = {
        "repeat": _one_variant(llm, docs, question, top_n),
        "all_ids": _one_variant(llm, docs, question, top_n, prompt=ALL_IDS_PROMPT),
    }
    perm = list(range(len(docs)))
    random.Random(SHUFFLE_SEED).shuffle(perm)
    shuffled = _one_variant(llm, [docs[i] for i in perm], question, top_n)
    # Map back to ORIGINAL input positions so all variants are read on one index; keep the
    # permutation so the target's position in the shuffled list can be recovered.
    if shuffled["out_idx"] is not None:
        shuffled["out_idx"] = [None if j is None else perm[j] for j in shuffled["out_idx"]]
    shuffled["perm"] = perm
    out["shuffled"] = shuffled
    return out


def recorded_compress(compressor, docs, question, *, provider, llm, top_n, recorder: dict):
    """compressor.compress_documents with the call recorded into `recorder` (mutated in place)."""
    provider_name = str(getattr(provider, "value", provider))
    recorder.update(provider=provider_name, top_n=top_n, input=input_record(docs))
    cap = RerankCapture()
    try:
        compressed = compressor.compress_documents(docs, question, callbacks=[cap])
        recorder["primary"] = call_record(docs, compressed, cap)
        return compressed
    except Exception as e:
        recorder["primary"] = call_record(docs, None, cap, error=e)
        raise
    finally:
        if recorder.get("want_variants"):
            if provider_name != "llm" or llm is None:
                recorder["variants"] = {"skipped": "rerank_provider is not llm"}
            else:
                try:
                    recorder["variants"] = run_variants(llm, docs, question, top_n)
                except Exception as e:
                    logger.warning("rerank variants failed: %s", type(e).__name__)
                    recorder["variants"] = {"error": type(e).__name__}
