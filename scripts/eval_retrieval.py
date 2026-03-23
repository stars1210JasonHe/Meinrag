"""Retrieval quality benchmark.

Usage:
    uv run python scripts/eval_retrieval.py --save baseline
    uv run python scripts/eval_retrieval.py --save post-fix
    uv run python scripts/eval_retrieval.py --compare baseline post-fix
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

API = "http://localhost:9999"
RESULTS_DIR = Path("data/eval_retrieval")
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

EVAL_QUERIES = [
    {
        "question": "What is the Transformer architecture?",
        "expected_keywords": ["transformer", "encoder", "decoder", "architecture", "attention"],
        "should_not_contain": ["et al.", "arxiv", "proceedings"],
    },
    {
        "question": "How does multi-head attention work?",
        "expected_keywords": ["multi-head", "attention", "queries", "keys", "values", "concatenat"],
        "should_not_contain": ["et al.", "arxiv"],
    },
    {
        "question": "What are the training details?",
        "expected_keywords": ["training", "optimizer", "adam", "gpu", "p100", "batch", "learning rate"],
        "should_not_contain": ["|Col1|", "|Col2|"],
    },
    {
        "question": "What BLEU scores did the model achieve?",
        "expected_keywords": ["bleu", "28.", "wmt", "english-to-german", "english-to-french"],
        "should_not_contain": ["|Col1|"],
    },
    {
        "question": "What are the references of this paper?",
        "expected_keywords": ["references", "[1]", "[2]", "et al."],
        "should_not_contain": [],
    },
    {
        "question": "What is positional encoding?",
        "expected_keywords": ["positional", "encoding", "sinusoid", "frequency", "position"],
        "should_not_contain": ["et al.", "arxiv"],
    },
    {
        "question": "How does the model compare to RNNs?",
        "expected_keywords": ["recurrent", "rnn", "sequential", "paralleliz"],
        "should_not_contain": ["|Col1|"],
    },
    {
        "question": "What is the complexity of self-attention?",
        "expected_keywords": ["complexity", "O(n", "self-attention", "layer"],
        "should_not_contain": ["|Col1|"],
    },
]


def _is_garbage(content: str) -> bool:
    lower = content.lower()
    if lower.count("|col") >= 3:
        return True
    cells = [c.strip() for c in content.split("|") if c.strip()]
    if cells and len(cells) > 10 and sum(1 for c in cells if len(c) <= 2) / len(cells) > 0.6:
        return True
    return False


def _is_reference(content: str) -> bool:
    lower = content.lower()
    ref_markers = ["et al.", "arxiv", "proceedings of", "journal of", "conference on",
                   "in proc.", "nips", "icml", "iclr", "emnlp", "naacl"]
    return sum(1 for m in ref_markers if m in lower) >= 2


def _is_duplicate(content: str, seen: set) -> bool:
    norm = content.strip().lower()[:200]
    if norm in seen:
        return True
    seen.add(norm)
    return False


async def run_eval(doc_id: str) -> dict:
    results = []
    async with httpx.AsyncClient(timeout=60) as client:
        for q in EVAL_QUERIES:
            resp = await client.post(
                f"{API}/query",
                json={"question": q["question"], "doc_ids": [doc_id]},
                headers={"X-User-Id": "admin"},
            )
            data = resp.json()
            sources = data.get("sources", [])

            total = len(sources)
            scored = [s for s in sources if s.get("score", 0) > 0]
            zero_score = total - len(scored)
            garbage = sum(1 for s in sources if _is_garbage(s.get("content", "")))
            refs = sum(1 for s in sources if _is_reference(s.get("content", "")))

            seen = set()
            dupes = sum(1 for s in sources if _is_duplicate(s.get("content", ""), seen))

            relevant = 0
            for s in scored:
                low = s.get("content", "").lower()
                if any(kw in low for kw in q["expected_keywords"]):
                    relevant += 1
            precision = relevant / len(scored) if scored else 0

            contaminated = 0
            for s in scored:
                low = s.get("content", "").lower()
                if any(bad in low for bad in q["should_not_contain"]):
                    contaminated += 1

            top1_score = scored[0]["score"] if scored else 0
            top1_relevant = False
            if scored:
                low = scored[0].get("content", "").lower()
                top1_relevant = any(kw in low for kw in q["expected_keywords"])

            results.append({
                "question": q["question"],
                "total_sources": total,
                "scored_sources": len(scored),
                "zero_score_sources": zero_score,
                "garbage_chunks": garbage,
                "reference_chunks": refs,
                "duplicate_chunks": dupes,
                "precision_at_k": round(precision, 3),
                "contaminated": contaminated,
                "top1_score": top1_score,
                "top1_relevant": top1_relevant,
                "sources": [
                    {"score": s.get("score", 0), "page": s.get("page"),
                     "chunk_type": s.get("chunk_type"), "content_preview": s.get("content", "")[:100]}
                    for s in sources
                ],
            })

    n = len(results)
    agg = {
        "avg_precision": round(sum(r["precision_at_k"] for r in results) / n, 3),
        "avg_scored_sources": round(sum(r["scored_sources"] for r in results) / n, 1),
        "avg_zero_score": round(sum(r["zero_score_sources"] for r in results) / n, 1),
        "total_garbage": sum(r["garbage_chunks"] for r in results),
        "total_references_in_non_ref_queries": sum(
            r["reference_chunks"] for r in results if "references" not in r["question"].lower()
        ),
        "total_duplicates": sum(r["duplicate_chunks"] for r in results),
        "total_contaminated": sum(r["contaminated"] for r in results),
        "avg_top1_score": round(sum(r["top1_score"] for r in results) / n, 3),
        "top1_relevant_rate": round(sum(1 for r in results if r["top1_relevant"]) / n, 3),
    }

    return {"aggregate": agg, "queries": results}


def compare(name_a: str, name_b: str):
    a = json.loads((RESULTS_DIR / f"{name_a}.json").read_text(encoding="utf-8"))
    b = json.loads((RESULTS_DIR / f"{name_b}.json").read_text(encoding="utf-8"))

    aa, ba = a["aggregate"], b["aggregate"]
    print(f"\n{'Metric':<45} {name_a:>12} {name_b:>12} {'Change':>10}")
    print("-" * 82)
    for key in aa:
        va, vb = aa[key], ba[key]
        if isinstance(va, float):
            delta = vb - va
            arrow = "+" if delta > 0 else ""
            better = delta < 0 if "garbage" in key or "contam" in key or "duplic" in key or "zero" in key or "reference" in key else delta > 0
            marker = " *" if better and abs(delta) > 0.01 else ""
            print(f"  {key:<43} {va:>12} {vb:>12} {arrow}{delta:>+9.3f}{marker}")
        else:
            delta = vb - va
            better = delta < 0 if "garbage" in key or "contam" in key or "duplic" in key or "zero" in key or "reference" in key else delta > 0
            marker = " *" if better and delta != 0 else ""
            print(f"  {key:<43} {va:>12} {vb:>12} {delta:>+9d}{marker}")

    print("\nPer-query breakdown:")
    for qa, qb in zip(a["queries"], b["queries"]):
        print(f"\n  Q: {qa['question']}")
        print(f"    Precision:    {qa['precision_at_k']:.3f} -> {qb['precision_at_k']:.3f}")
        print(f"    Scored:       {qa['scored_sources']} -> {qb['scored_sources']}")
        print(f"    Zero-score:   {qa['zero_score_sources']} -> {qb['zero_score_sources']}")
        print(f"    Garbage:      {qa['garbage_chunks']} -> {qb['garbage_chunks']}")
        print(f"    Contaminated: {qa['contaminated']} -> {qb['contaminated']}")


async def main():
    parser = argparse.ArgumentParser(description="Retrieval quality benchmark")
    parser.add_argument("--save", help="Run eval and save results with this name (e.g. 'baseline')")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"), help="Compare two saved runs")
    parser.add_argument("--doc-id", default="751dba9a1981", help="Document ID to evaluate against")
    args = parser.parse_args()

    if args.compare:
        compare(args.compare[0], args.compare[1])
    elif args.save:
        print(f"Running eval against doc_id={args.doc_id}...")
        results = await run_eval(args.doc_id)
        out_path = RESULTS_DIR / f"{args.save}.json"
        out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved to {out_path}")
        print(f"\nAggregate metrics:")
        for k, v in results["aggregate"].items():
            print(f"  {k}: {v}")
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
