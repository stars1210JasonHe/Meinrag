"""Pre-demo smoke test — verifies every scene from the demo script
will land before you start recording or presenting live.

Hits the live backend at http://localhost:8000 and prints PASS/FAIL per
scene with the evidence (sample answer text, retrieved doc names, etc.)
so you can eyeball whether the demo will deliver each promised wow.

Run:
    uv run python scripts/demo_smoke.py

Pre-reqs:
    - backend up and serving today's code (mean_score in /graph/documents)
    - dev corpus indexed (16 docs incl. Transformer paper, CRS reports,
      shell-model papers)
    - OPENAI_API_KEY set (semantic search + answer generation need it)
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Any

BASE = "http://localhost:8000"
USER = "admin"


# ─── HTTP helpers ────────────────────────────────────────────────────────


def http_get(path: str, params: dict | None = None) -> dict:
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        path = f"{path}?{qs}"
    req = urllib.request.Request(f"{BASE}{path}", headers={"X-User-Id": USER})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def http_post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={"X-User-Id": USER, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


# ─── Pretty-print helpers ────────────────────────────────────────────────


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def header(scene: str, title: str) -> None:
    print(f"\n{'=' * 70}\n  {scene}: {title}\n{'=' * 70}")


def report(name: str, passed: bool, evidence: str = "") -> None:
    badge = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    print(f"  [{badge}] {name}")
    if evidence:
        for line in evidence.splitlines():
            print(f"         {line}")


def warn(message: str) -> None:
    print(f"  [{YELLOW}WARN{RESET}] {message}")


# ─── Corpus probe ────────────────────────────────────────────────────────


def fetch_corpus() -> dict[str, str]:
    """Return {filename_lower_substring: doc_id} for filename lookups."""
    docs = http_get("/documents", params={"limit": 200})["documents"]
    return {d["filename"].lower(): d["doc_id"] for d in docs}


def find_doc(corpus: dict[str, str], substring: str) -> str | None:
    sub = substring.lower()
    for fn, did in corpus.items():
        if sub in fn:
            return did
    return None


# ─── Scene checks ────────────────────────────────────────────────────────


def scene_1_smart_search(corpus: dict[str, str]) -> None:
    header("Scene 1", "Smart search returns the right doc by content")
    query = "幻数与氧同位素"
    expected_substr = "otsuka"  # otsuka_oxygen_drip_2010.pdf

    try:
        resp = http_get("/documents", params={"search": query, "limit": 5})
        docs = resp["documents"]
        first = docs[0] if docs else None
    except Exception as e:
        report("query succeeds", False, f"error: {e}")
        return

    report("query returns ≥1 doc", bool(docs),
           f"got {len(docs)} docs; first: {first['filename'] if first else '—'}")

    if first:
        hit = expected_substr in first["filename"].lower()
        report(f"top hit contains '{expected_substr}'", hit,
               f"top hit: {first['filename']}")
        if not hit:
            warn("system may have routed via short-query ILIKE instead of "
                 "semantic. The query is short, so ILIKE looks at filename "
                 "(misses 'magic numbers' which isn't in any filename). "
                 "Consider rephrasing as longer query: "
                 "'magic numbers in oxygen-24 isotopes nuclear physics'")


def scene_3_multimodal_citations(corpus: dict[str, str]) -> None:
    header("Scene 3", "Multi-modal citations on Transformer paper")
    doc_id = find_doc(corpus, "attention_is_all_you_need")
    if not doc_id:
        report("Transformer paper in corpus", False, "filename not found")
        return
    report("Transformer paper in corpus", True, f"doc_id: {doc_id[:8]}…")

    question = "Transformer 架构相比 RNN 有哪些核心优势？请结合论文中的图表说明。"
    try:
        resp = http_post("/query", {
            "question": question,
            "doc_ids": [doc_id],
            "top_k": 10,
        })
    except Exception as e:
        report("query succeeds", False, f"error: {e}")
        return

    answer = resp.get("answer", "")
    sources = resp.get("sources", [])

    report("non-empty answer", len(answer) > 50,
           f"{len(answer)} chars: {answer[:120].strip()}…")
    report("≥3 sources", len(sources) >= 3, f"{len(sources)} sources")

    # Check chunk-type diversity (the wow moment is multi-modal citations).
    chunk_types = {s.get("chunk_type") for s in sources if s.get("chunk_type")}
    if not chunk_types:
        warn("sources don't carry chunk_type metadata — can't verify "
             "multi-modal coverage. Check via UI by clicking citations.")
    else:
        report("≥2 distinct chunk_types in sources",
               len(chunk_types) >= 2,
               f"types: {sorted(chunk_types)}")

    pages = {s.get("page") for s in sources if s.get("page") is not None}
    report("citations span ≥2 pages", len(pages) >= 2,
           f"pages: {sorted(pages)}")


def scene_4_cross_language(corpus: dict[str, str]) -> None:
    header("Scene 4", "Cross-language: 中文 question, English sources, 中文 answer")
    question = ("请用中文解释 Section 230 的平台责任框架与 "
                "2023 年 AI 行政命令的治理思路有什么不同。")

    try:
        resp = http_post("/query", {
            "question": question,
            "top_k": 10,
        })
    except Exception as e:
        report("query succeeds", False, f"error: {e}")
        return

    answer = resp.get("answer", "")
    sources = resp.get("sources", [])

    # Heuristic: count CJK characters in the answer. Decent signal of
    # "Chinese-language answer."
    cjk_chars = len(re.findall(r"[一-鿿]", answer))
    cjk_ratio = cjk_chars / max(len(answer), 1)
    report("answer is mostly Chinese (≥30% CJK chars)",
           cjk_ratio >= 0.30,
           f"CJK ratio: {cjk_ratio:.0%} ({cjk_chars} of {len(answer)} chars)")

    # Source docs should be the English CRS PDFs.
    source_files = {s.get("source_file", "") for s in sources}
    has_section230 = any("section230" in f.lower() for f in source_files)
    has_eo2023 = any("eo2023" in f.lower() or "executive" in f.lower()
                     for f in source_files)
    report("cites Section 230 doc", has_section230,
           f"sources: {sorted(source_files)}")
    report("cites AI Executive Order doc", has_eo2023,
           f"({len(source_files)} unique source docs)")
    report("≥2 distinct source docs (multi-doc synthesis)",
           len(source_files) >= 2)

    print(f"  [...]  answer preview: {answer[:200].strip()}…")


def scene_5_refusal(corpus: dict[str, str]) -> None:
    header("Scene 5", "Honest refusal on out-of-corpus question")
    question = "中国 2024 年的 GDP 是多少？"

    try:
        resp = http_post("/query", {
            "question": question,
            "top_k": 10,
            "force_web_search": False,
        })
    except Exception as e:
        report("query succeeds", False, f"error: {e}")
        return

    answer = resp.get("answer", "")
    refusal_signals = [
        "不包含", "没有相关", "无法回答", "不知道",
        "do not contain", "not contain", "no information",
        "cannot answer", "i don't have",
    ]
    refused = any(s in answer.lower() for s in refusal_signals) or \
              any(s in answer for s in refusal_signals)
    report("system refuses honestly (no fabrication)", refused,
           f"answer: {answer[:200].strip()}…")

    # Confidence should NOT be high when the system is refusing.
    conf = (resp.get("confidence_tier") or "").lower()
    report("confidence is moderate or low (calibration)",
           conf in ("moderate", "low"),
           f"confidence_tier: {conf!r}")


def scene_6_graph_view(corpus: dict[str, str]) -> None:
    header("Scene 6", "Graph view + chunk-type diversity on Transformer paper")
    doc_id = find_doc(corpus, "attention_is_all_you_need")
    if not doc_id:
        report("Transformer paper in corpus", False, "filename not found")
        return

    try:
        graph = http_get(f"/graph/nodes", params={
            "doc_id": doc_id,
            "edge_types": "follows,co_located,describes,references,similar_to",
        })
    except Exception as e:
        report("graph endpoint responds", False, f"error: {e}")
        return

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    chunk_types = {n.get("chunk_type") for n in nodes if n.get("chunk_type")}

    report("graph has nodes", len(nodes) > 0, f"{len(nodes)} nodes")
    report("graph has edges", len(edges) > 0, f"{len(edges)} edges")
    report("≥3 distinct chunk types (text/table/image/formula)",
           len(chunk_types) >= 3,
           f"types: {sorted(chunk_types)}")

    if "table" not in chunk_types:
        warn("no 'table' chunks — Scene 6's prepared question targets the "
             "BLEU table. Consider pivoting to a text or formula chunk.")
    if "image" not in chunk_types:
        warn("no 'image' chunks — figure-extraction may not have completed "
             "for this doc. The architecture-diagram demo moment may not work.")


def scene_7_mindmap_depth(corpus: dict[str, str]) -> None:
    header("Scene 7", "Mindmap on long CRS doc — does it reach 4 layers?")
    doc_id = find_doc(corpus, "crs_r46795")
    if not doc_id:
        report("crs_R46795 in corpus", False, "filename not found")
        return

    try:
        resp = http_get(f"/documents/{doc_id}/mindmap")
    except Exception as e:
        report("mindmap endpoint responds", False, f"error: {e}")
        return

    tree = resp.get("tree", {})
    branches = tree.get("branches", [])
    cached = resp.get("cached", False)

    report("mindmap returns a tree", bool(branches),
           f"{len(branches)} top branches; cached={cached}")

    def max_depth(node: dict, current: int = 1) -> int:
        children = node.get("children")
        if not children:
            return current
        return max(max_depth(c, current + 1) for c in children)

    if branches:
        deepest = max(max_depth(b) for b in branches)
        report("at least one branch reaches depth 4 (G3 trigger)",
               deepest >= 4,
               f"max depth: {deepest}")
        if deepest < 4:
            warn("mindmap stayed at 3 layers. To force regeneration: "
                 f"delete data/mindmaps/{doc_id}.json and reopen the "
                 "mindmap. Or fall back to quantum_shell_model_2023.pdf.")


def scene_8_save_collection(corpus: dict[str, str]) -> None:
    header("Scene 8", "Save-as-collection round-trip")
    # Pick 2 docs to combine.
    doc_ids = []
    for sub in ("section230", "eo2023"):
        d = find_doc(corpus, sub)
        if d:
            doc_ids.append(d)
    if len(doc_ids) < 2:
        report("≥2 docs available for collection", False,
               "missing one of the AI-policy docs")
        return

    name = f"smoke-test-{int(time.time())}"
    try:
        resp = http_post("/documents/collections/save", {
            "name": name,
            "doc_ids": doc_ids,
            "mode": "new",
        })
    except Exception as e:
        report("save endpoint succeeds", False, f"error: {e}")
        return

    report("collection created", resp.get("name") == name,
           f"name={resp.get('name')!r}, added={resp.get('added')}, "
           f"total_docs={resp.get('total_docs_in_collection')}")

    # Verify retrieval scoping works.
    try:
        scoped = http_get("/documents", params={"collection": name})
        scoped_ids = {d["doc_id"] for d in scoped["documents"]}
    except Exception as e:
        report("collection lookup succeeds", False, f"error: {e}")
        return

    report("docs retrievable via ?collection=",
           scoped_ids == set(doc_ids),
           f"expected {sorted(doc_ids)}, got {sorted(scoped_ids)}")


# ─── Main ────────────────────────────────────────────────────────────────


def main() -> int:
    print("MEINRAG demo smoke test — checking each scene's wow moment lands\n")
    print(f"  Backend: {BASE}")
    print(f"  User:    {USER}")

    # Backend reachable?
    try:
        health = http_get("/health")
        print(f"  Health:  {health.get('status')!r} | "
              f"docs={health.get('document_count')} | "
              f"vs={health.get('vector_store')}")
    except Exception as e:
        print(f"\n{RED}backend not reachable: {e}{RESET}")
        return 1

    # Verify G1 fields are live (i.e. backend has today's code).
    try:
        graph_doc = http_get("/graph/documents")
        if graph_doc.get("edges"):
            sample = graph_doc["edges"][0]
            if "mean_score" not in sample or "supporting_pairs" not in sample:
                print(f"\n{RED}backend serving STALE code — restart uvicorn{RESET}")
                return 1
            print(f"  G1 live: edges={len(graph_doc['edges'])} with "
                  f"mean_score + supporting_pairs ✓")
        else:
            warn("no cross-doc edges yet — corpus may be too small or "
                 "edge-builder hasn't run")
    except Exception as e:
        print(f"\n{YELLOW}graph endpoint check failed: {e}{RESET}")

    corpus = fetch_corpus()
    print(f"  Corpus:  {len(corpus)} docs indexed")

    scene_1_smart_search(corpus)
    scene_3_multimodal_citations(corpus)
    scene_4_cross_language(corpus)
    scene_5_refusal(corpus)
    scene_6_graph_view(corpus)
    scene_7_mindmap_depth(corpus)
    scene_8_save_collection(corpus)

    print(f"\n{'=' * 70}")
    print("  Done. Eyeball the FAIL / WARN lines above.")
    print(f"{'=' * 70}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
