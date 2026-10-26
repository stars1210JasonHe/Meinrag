"""Per-stage rank of ONE known target through retrieve_and_rank (opt-in debug).

Why this exists: stage_counts says how many results survived each stage, and the
[SCORE-TRACE] log shows each stage's top 10, but neither says what happened to a
SPECIFIC answer. So a missed answer can only be filed as one undifferentiated
recall_miss, which hides four different facts:

    no arm found it at all;
    an arm found it and a later stage removed it (which one?);
    it was outside the query's scope;
    the arm that would have found it never ran (e.g. BM25 skipped by its scope gate).

Contract (spec: Gauss 2026-10-26, "target trace"):
  * Observation only. Nothing here writes to doc.metadata -- FAISS hands back SHARED
    Document objects, and a flag written on one query leaks into the next (that is how
    `_mandatory` leaked before retrieval.py cleared it on every vector search).
  * Never reorders or edits a pipeline list. Ranks are computed on sorted COPIES.
  * Exactly five statuses: present / absent / not_run:<reason> / out_of_scope / replaced.
  * Every stage in STAGES appears exactly once in the output. A stage the pipeline never
    reached is reported as not_run with the reason, never silently omitted -- an omitted
    stage reads as "nothing happened there", which is the conflation this exists to remove.
"""

from __future__ import annotations

# Execution order. Index = the step number used in the spec's section 4 table.
STAGES = (
    "scope",
    "arm_vector",
    "arm_summary",
    "arm_hyde",
    "arm_bm25",
    "after_merges",
    "after_query_expansion",
    "after_fact_keyword_expand",
    "after_strategy_cut",
    "after_coverage",
    "after_penalties",
    "web_search_gate",
    "after_visual",
    "after_graph",
    "after_composite",
    "rerank_input",
    "rerank_output",
    "after_mandatory_restore",
    "after_labels",
    "after_per_doc_cap",
    "after_top_k_cap",
    "after_token_budget",
    "returned",
)


def _doc_of(item):
    """Pipeline lists hold (Document, score) tuples; the BM25 arm returns bare Documents."""
    return item[0] if isinstance(item, tuple) else item


class TargetTracer:
    """Collects one entry per stage for a single target (doc_id, optional chunk_index).

    chunk_index None = document-level: the rank is that of the document's best-placed chunk,
    and target_chunks counts how many of its chunks are in the list.
    """

    def __init__(self, doc_id: str, chunk_index: int | None = None):
        self.doc_id = doc_id
        self.chunk_index = chunk_index
        self._entries: dict[str, dict] = {}
        self._out_of_scope = False

    # -- scope ------------------------------------------------------------

    def check_scope(self, doc_ids: list[str] | None, note: str | None = None) -> bool:
        """Stage 0. doc_ids None = unscoped (whole corpus): the target is in scope by definition.

        Returns True when the target is out of scope. From then on every stage reports
        out_of_scope, so 'absent' can never be produced for a target the query could not
        have returned -- that keeps "outside the scope" apart from "found and dropped".
        """
        if doc_ids is not None and self.doc_id not in set(doc_ids):
            self._out_of_scope = True
            self._entries.clear()
            self._entries["scope"] = self._entry("scope", "out_of_scope", None, len(doc_ids), None,
                                                 note or "target doc_id not in this query's doc_ids")
            return True
        self._entries["scope"] = self._entry(
            "scope", "present", None, len(doc_ids) if doc_ids is not None else None, None,
            note or ("unscoped query (doc_ids is None)" if doc_ids is None else "target in scope"))
        return False

    def annotate(self, stage: str, note: str) -> None:
        """Append to an already-recorded stage's note (e.g. what the router did to the scope)."""
        entry = self._entries.get(stage)
        if entry is not None:
            entry["note"] = "; ".join(n for n in (entry["note"], note) if n)

    @property
    def out_of_scope(self) -> bool:
        return self._out_of_scope

    # -- recording --------------------------------------------------------

    def record(self, stage: str, items: list, *, by_score: bool = True,
               note: str | None = None, replaced: bool = False) -> None:
        """Record the target's rank in `items` at `stage`.

        by_score=True ranks by tuple score, high to low (same ordering as _trace), for the stages
        before reranking where list order is not guaranteed. by_score=False takes list order as
        the rank, for the reranker's output and every stage after it, and for the bare-Document
        BM25 arm (BM25Retriever returns best first).
        """
        if self._out_of_scope:
            return
        ordered = sorted(items, key=lambda x: x[1], reverse=True) if by_score else list(items)
        rank = None
        hits = 0
        mandatory = False
        for pos, item in enumerate(ordered, start=1):
            meta = getattr(_doc_of(item), "metadata", None) or {}
            if meta.get("doc_id") != self.doc_id:
                continue
            if self.chunk_index is not None and meta.get("chunk_index") != self.chunk_index:
                continue
            hits += 1
            if rank is None:
                rank = pos
                mandatory = bool(meta.get("_mandatory"))
        status = "replaced" if replaced else ("present" if rank is not None else "absent")
        notes = [n for n in (note, "list replaced by the expanded-query results" if replaced else None,
                             "mandatory" if mandatory else None) if n]
        self._entries[stage] = self._entry(stage, status, rank, len(items), hits,
                                           "; ".join(notes) or None)

    def skip(self, stage: str, reason: str, note: str | None = None) -> None:
        """The stage did not execute. reason is mandatory: a bare 'not_run' would hide why."""
        if self._out_of_scope:
            return
        self._entries[stage] = self._entry(stage, f"not_run:{reason}", None, None, None, note)

    def finish(self, reason: str) -> None:
        """An early return: every stage not yet recorded is not_run:<reason>."""
        for stage in STAGES:
            if stage not in self._entries:
                self.skip(stage, reason)

    # -- output -----------------------------------------------------------

    def result(self) -> list[dict]:
        if self._out_of_scope:
            scope = self._entries["scope"]
            return [scope] + [self._entry(s, "out_of_scope", None, None, None, None)
                              for s in STAGES[1:]]
        # A stage nobody recorded is a tracer bug, and it must be visible as one rather than
        # disappear from the list; the reconciliation control (cell E) then fails loudly.
        return [self._entries.get(s) or self._entry(s, "not_run:untraced", None, None, None,
                                                    "tracer bug: stage was never recorded")
                for s in STAGES]

    @staticmethod
    def _entry(stage, status, rank, list_len, target_chunks, note) -> dict:
        return {"stage": stage, "status": status, "rank": rank, "list_len": list_len,
                "target_chunks": target_chunks, "note": note}
