"""Context-budget evaluation: a reproducible query set, a top_k sweep over /query, two judges.

Why: the budget ratios and the per-doc cap were tuned in April on 36 questions whose set and
report never entered the repository, at top_k=10 while the chat path ran 8 and the API 4.
Nothing in the tree could say whether 8 was better or worse than 10. This script makes that
answerable and keeps the answer in git: the query set lives in data/eval/, every run writes a
JSON + Markdown report to data/eval/reports/, and the report records the server's runtime
flags (GET /health/config) so two reports can be compared cell by cell.

Usage (from the repo root, against a running backend that has its LLM key):
    uv run python scripts/eval_context_sweep.py --generate 40 --seed 7 --collection legal
    uv run python scripts/eval_context_sweep.py --dry-run --top-k 4,8,12,16,24
    uv run python scripts/eval_context_sweep.py --top-k 4,8,12,16,24 --label rerank-on

Per query and top_k: POST /query, then
  retrieval hit   the query's source chunk (doc_id, chunk_index) is among the returned sources;
                  "same document" is reported separately
  correctness     two judges (default gpt-4o-mini and gpt-4.1-mini, run from THIS process with
                  OPENAI_API_KEY) each say YES/NO to "does the answer state the expected fact";
                  a query counts as correct only when both say YES; splits are reported, not hidden
  context         context_used_tokens / chunks_included from the response, and wall-clock latency
Cost is estimated and printed before anything runs; --dry-run stops there.
Generation (--generate): a seeded sample of chunks of at least 200 characters; the LLM writes one
factual question the chunk answers, in the chunk's language, plus the expected answer. Read the
generated set before trusting it - it is a starting point, not ground truth.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

REQUIRED = ("id", "question", "doc_id", "chunk_index", "expected")
PRICE_IN, PRICE_OUT = 0.15 / 1e6, 0.60 / 1e6          # gpt-4o-mini
SERVER_TOKENS_PER_QUERY = 3000                        # classification + answer, measured order of magnitude
JUDGE_TOKENS = 400

JUDGE_PROMPT = (
    "You are grading a retrieval-augmented answer.\n"
    "Question: {question}\n"
    "Expected fact (ground truth): {expected}\n"
    "Model answer: {answer}\n\n"
    "Does the model answer state the expected fact (same facts and numbers; extra correct material is fine; "
    "a refusal or a different fact is NO)? Reply with YES or NO as the first word, then one short reason."
)
GEN_PROMPT = (
    "Below is one passage from a document. Write ONE factual question, in the passage's own language, that this "
    "passage answers directly and that a reader of the whole document might ask, and the expected answer in at most "
    "30 words taken from the passage. Reply as JSON: {{\"question\": ..., \"expected\": ...}}\n\nPassage:\n{passage}"
)


# ---------------------------------------------------------------- pure helpers (tested)

def load_queries(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("query set must be a non-empty JSON list")
    for i, q in enumerate(data):
        missing = [k for k in REQUIRED if k not in q]
        if missing:
            raise ValueError("query %d is missing %s" % (i, missing))
    return data


def is_hit(sources: list[dict], doc_id: str, chunk_index: int) -> tuple[bool, bool]:
    """(exact chunk among sources, same document among sources)."""
    exact = any(s.get("doc_id") == doc_id and s.get("chunk_index") == chunk_index for s in sources)
    same_doc = any(s.get("doc_id") == doc_id for s in sources)
    return exact, same_doc


def parse_verdict(text: str | None) -> bool | None:
    if not text:
        return None
    first = re.match(r"\s*\**\s*(yes|no)\b", text, re.I)
    return None if not first else first.group(1).lower() == "yes"


def vote(verdicts: list[bool | None]) -> tuple[str, bool]:
    """Label and agreement. Any abstaining judge -> "no reading" (never silently a NO)."""
    if not verdicts or any(v is None for v in verdicts):
        return "no reading", False
    if all(verdicts):
        return "correct", True
    if not any(verdicts):
        return "wrong", True
    return "split", False


def estimate_cost(n_queries: int, n_cells: int, n_judges: int) -> float:
    calls = n_queries * n_cells
    server = calls * (SERVER_TOKENS_PER_QUERY * PRICE_IN + 300 * PRICE_OUT)
    judges = calls * n_judges * (JUDGE_TOKENS * PRICE_IN + 30 * PRICE_OUT)
    return server + judges


def summarize(records: list[dict]) -> list[dict]:
    """One row per top_k: counts and medians. Records carry top_k, hit_exact, hit_doc, label, latency_s,
    context_used_tokens, chunks_included."""
    rows = []
    for k in sorted({r["top_k"] for r in records}):
        rs = [r for r in records if r["top_k"] == k]
        n = len(rs)
        rows.append({
            "top_k": k, "n": n,
            "hit_exact": sum(1 for r in rs if r["hit_exact"]),
            "hit_doc": sum(1 for r in rs if r["hit_doc"]),
            "correct": sum(1 for r in rs if r["label"] == "correct"),
            "split": sum(1 for r in rs if r["label"] == "split"),
            "no_reading": sum(1 for r in rs if r["label"] == "no reading"),
            "ctx_tokens_median": statistics.median([r["context_used_tokens"] for r in rs if r.get("context_used_tokens") is not None] or [0]),
            "chunks_median": statistics.median([r["chunks_included"] for r in rs if r.get("chunks_included") is not None] or [0]),
            "latency_p50": statistics.median([r["latency_s"] for r in rs] or [0]),
        })
    return rows


def render_table(rows: list[dict]) -> str:
    head = "| top_k | N | hit (chunk) | hit (doc) | correct (both judges) | split | no reading | ctx tokens (median) | chunks (median) | p50 s |\n|---|---|---|---|---|---|---|---|---|---|\n"
    body = "".join("| %d | %d | %d | %d | %d | %d | %d | %d | %d | %.1f |\n" % (
        r["top_k"], r["n"], r["hit_exact"], r["hit_doc"], r["correct"], r["split"], r["no_reading"],
        r["ctx_tokens_median"], r["chunks_median"], r["latency_p50"]) for r in rows)
    return head + body


# ---------------------------------------------------------------- I/O

async def fetch_config(client: httpx.AsyncClient, api: str) -> dict:
    try:
        r = await client.get(api + "/health/config", timeout=30)
        return r.json() if r.status_code == 200 else {"unavailable": r.status_code}
    except Exception as e:  # older servers have no such route
        return {"unavailable": type(e).__name__}


async def generate_set(args, client: httpx.AsyncClient, headers: dict) -> list[dict]:
    from openai import AsyncOpenAI
    llm = AsyncOpenAI()
    rng = random.Random(args.seed)
    docs, off = [], 0
    while True:
        params = {"limit": 200, "offset": off}
        if args.collection:
            params["collection"] = args.collection
        page = (await client.get(args.api + "/documents", params=params, headers=headers, timeout=120)).json()
        items = page.get("documents") or page.get("items") or []
        if not items:
            break
        docs += [it.get("doc_id") or it.get("id") for it in items]
        off += len(items)
        if len(items) < 200:
            break
    rng.shuffle(docs)
    out = []
    for did in docs:
        if len(out) >= args.generate:
            break
        chunks = (await client.get(args.api + "/documents/%s/chunks" % did, headers=headers, timeout=120)).json().get("chunks", [])
        cands = [c for c in chunks if (c.get("chunk_type") or "text") == "text" and len(c.get("content") or "") >= 200]
        if not cands:
            continue
        c = rng.choice(cands)
        r = await llm.chat.completions.create(model="gpt-4o-mini", temperature=0, max_tokens=300,
                                              messages=[{"role": "user", "content": GEN_PROMPT.format(passage=c["content"][:2000])}])
        txt = r.choices[0].message.content or ""
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            j = json.loads(m.group(0))
            out.append({"id": "q%03d" % (len(out) + 1), "question": j["question"], "expected": j["expected"],
                        "doc_id": did, "chunk_index": c.get("chunk_index"), "kind": "fact", "seed": args.seed})
        except Exception:
            continue
    return out


async def judge(llm, model: str, q: dict, answer: str) -> bool | None:
    try:
        r = await llm.chat.completions.create(model=model, temperature=0, max_tokens=60, messages=[
            {"role": "user", "content": JUDGE_PROMPT.format(question=q["question"], expected=q["expected"], answer=answer[:4000])}])
        return parse_verdict(r.choices[0].message.content)
    except Exception:
        return None


async def run(args) -> int:
    headers = {"X-User-Id": args.user, "Content-Type": "application/json"}
    qpath = Path(args.queries)
    async with httpx.AsyncClient() as client:
        if args.generate:
            qs = await generate_set(args, client, headers)
            qpath.parent.mkdir(parents=True, exist_ok=True)
            qpath.write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
            print("generated %d queries -> %s (read them before trusting them)" % (len(qs), qpath))
            return 0
        queries = load_queries(qpath)
        top_ks = [int(x) for x in args.top_k.split(",")]
        judges = [j for j in args.judges.split(",") if j]
        cost = estimate_cost(len(queries), len(top_ks), len(judges))
        print("queries=%d cells(top_k)=%s judges=%s -> ~%d /query calls, estimated ~$%.2f" % (
            len(queries), top_ks, judges, len(queries) * len(top_ks), cost))
        if args.dry_run:
            return 0
        config = await fetch_config(client, args.api)
        from openai import AsyncOpenAI
        llm = AsyncOpenAI()
        sem = asyncio.Semaphore(args.concurrency)
        records: list[dict] = []

        async def one(q: dict, k: int):
            body = {"question": q["question"], "top_k": k}
            if args.collection:
                body["collection"] = args.collection
            async with sem:
                t0 = time.time()
                try:
                    r = await client.post(args.api + "/query", json=body, headers=headers, timeout=args.timeout)
                    resp = r.json() if r.status_code == 200 else {"answer": "", "sources": [], "error": r.status_code}
                except Exception as e:
                    resp = {"answer": "", "sources": [], "error": type(e).__name__}
                latency = time.time() - t0
            answer = resp.get("answer") or ""
            hit_exact, hit_doc = is_hit(resp.get("sources") or [], q["doc_id"], q["chunk_index"])
            verdicts = await asyncio.gather(*[judge(llm, m, q, answer) for m in judges]) if answer else [None] * len(judges)
            label, agree = vote(list(verdicts))
            records.append({"id": q["id"], "top_k": k, "hit_exact": hit_exact, "hit_doc": hit_doc,
                            "label": label, "agree": agree, "verdicts": list(verdicts), "latency_s": round(latency, 2),
                            "context_used_tokens": resp.get("context_used_tokens"), "chunks_included": resp.get("chunks_included"),
                            "error": resp.get("error")})

        await asyncio.gather(*[one(q, k) for q in queries for k in top_ks])

    rows = summarize(records)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    out_dir = Path(args.reports)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "context-sweep-%s%s" % (ts, ("-" + args.label) if args.label else "")
    report = {"utc": ts, "label": args.label, "api": args.api, "collection": args.collection, "queries": str(qpath),
              "n_queries": len(queries), "top_ks": top_ks, "judges": judges, "server_config": config,
              "estimated_cost_usd": round(cost, 3), "rows": rows, "records": records}
    (out_dir / (stem + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    md = "# Context sweep %s\n\nserver config: `%s`\n\n%s" % (stem, json.dumps(config, ensure_ascii=False), render_table(rows))
    (out_dir / (stem + ".md")).write_text(md, encoding="utf-8")
    print(md)
    print("written:", out_dir / (stem + ".json"))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default=os.environ.get("MEINRAG_API", "http://localhost:8000"))
    p.add_argument("--user", default="admin")
    p.add_argument("--collection", default=None)
    p.add_argument("--queries", default="data/eval/context_sweep_queries.json")
    p.add_argument("--reports", default="data/eval/reports")
    p.add_argument("--generate", type=int, default=0, help="build a query set of N questions from the corpus, then exit")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--top-k", default="4,8,12,16,24")
    p.add_argument("--judges", default="gpt-4o-mini,gpt-4.1-mini")
    p.add_argument("--label", default="")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
