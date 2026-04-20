"""RAG credibility test — upload 46-doc corpus ONCE, then run 36 queries
at two top_k values, measure 5 metrics per query, write report.

Persistent DB + vector store on disk at data/test_queries/ so we can
iterate on query/threshold tuning without re-uploading every run.

Requires: OPENAI_API_KEY.
Run:
    uv run pytest tests/test_query_credibility.py -v -s
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import Settings, ParseMode
from app.db.models import Base, UserModel
from app.db.repositories import UserRepository
from app.dependencies import (
    get_settings, get_vector_store, get_db, get_llm,
    get_embeddings, get_summary_store,
)
from app.llm.provider import create_chat_model, create_embeddings
from app.main import create_app
from app.vectorstore.chroma_store import ChromaStoreManager
from tests.conftest import online


# ── Paths ────────────────────────────────────────────────────────────────────
TEST_DATA_DIR = Path("data/test_queries")
TEST_DB_PATH = TEST_DATA_DIR / "query_test.db"
CHROMA_DIR = TEST_DATA_DIR / "query_test_chroma"
UPLOAD_DIR = TEST_DATA_DIR / "query_test_uploads"
CORPUS_ROOT = Path("data/test_classification")
QUERY_SET = TEST_DATA_DIR / "query_test_set.json"
RESULTS_JSON = TEST_DATA_DIR / "query_results.json"
REPORT_MD = TEST_DATA_DIR / "query_report.md"


# ── Keyword matching ────────────────────────────────────────────────────────

def _matches_spec(text: str, spec) -> bool:
    """A spec is either a string (must-appear) or a list of strings (any-of).
    Case-insensitive substring match.
    """
    if isinstance(spec, str):
        return spec.lower() in text.lower()
    if isinstance(spec, list):
        return any(item.lower() in text.lower() for item in spec)
    return False


def _all_match(text: str, must_contain: list) -> tuple[bool, list[str]]:
    """Every spec in must_contain must match. Returns (all_match, missing_specs)."""
    missing = [str(spec) for spec in must_contain if not _matches_spec(text, spec)]
    return len(missing) == 0, missing


def _any_forbidden(text: str, must_not_contain: list[str]) -> list[str]:
    """Return list of forbidden keywords that DID appear."""
    return [k for k in must_not_contain if k.lower() in text.lower()]


# ── LLM judge for groundedness ──────────────────────────────────────────────

JUDGE_PROMPT = """You are a strict fact-checker. Read the SOURCES and the ANSWER below.

Your task: determine if every factual claim in the ANSWER is supported by the SOURCES.
- "Supported" means the claim appears in the sources (possibly paraphrased).
- "Unsupported" means the answer contains facts that are not in the sources.
- General statements ("the paper discusses X") are supported if X is mentioned in sources.
- Specific numbers, names, dates must appear in sources.

SOURCES:
{sources}

ANSWER:
{answer}

Respond in JSON (no other text):
{{"grounded": true|false, "reason": "brief explanation"}}
"""


def _judge_grounded(answer: str, source_chunks: list[dict], llm) -> tuple[bool, str]:
    """Call LLM at temperature=0 to judge groundedness. Returns (grounded, reason)."""
    if not answer or not source_chunks:
        return False, "no answer or no sources"

    sources_text = "\n\n---\n\n".join(
        f"[{c.get('source_file', 'unknown')}] {c.get('content', '')[:1500]}"
        for c in source_chunks[:10]
    )
    prompt = JUDGE_PROMPT.format(sources=sources_text[:12000], answer=answer[:3000])

    try:
        # llm is a LangChain BaseChatModel; invoke with a string returns a response
        # Force temperature=0 for determinism
        response = llm.invoke(prompt, temperature=0)
        raw = response.content if hasattr(response, "content") else str(response)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip().rstrip("`").strip()
        judgment = json.loads(raw)
        return bool(judgment.get("grounded", False)), str(judgment.get("reason", ""))[:300]
    except Exception as e:
        return False, f"judge error: {type(e).__name__}: {str(e)[:100]}"


# ── Source-relevance metrics ────────────────────────────────────────────────

def _compute_source_metrics(
    returned_filenames: set[str], expected_filenames: set[str],
) -> tuple[float, float]:
    """Return (recall, precision). Expected is fuzzy — filenames basename-matched."""
    if not expected_filenames:
        # For impossible queries, no expectation — recall undefined. Precision = 0 is ideal.
        return 1.0, 0.0 if returned_filenames else 1.0

    returned_base = {Path(f).name for f in returned_filenames}
    expected_base = {Path(f).name for f in expected_filenames}

    intersection = returned_base & expected_base
    recall = len(intersection) / len(expected_base) if expected_base else 0.0
    precision = len(intersection) / len(returned_base) if returned_base else 0.0
    return recall, precision


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def persistent_env():
    """Persistent SQLite + Chroma. Create once, reuse across test runs."""
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    settings = Settings()
    settings.upload_dir = UPLOAD_DIR
    settings.user_isolation = "all"
    settings.summary_enabled = False
    # Default parse mode to avoid docling's 30-60s per file
    settings.parse_mode = ParseMode.DEFAULT

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=CHROMA_DIR)
    store.initialize(embeddings)
    llm = create_chat_model(settings)

    db_url = f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}"
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def test_lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        # Ensure admin user exists
        async with session_factory() as session:
            user_repo = UserRepository(session)
            if not await user_repo.exists("admin"):
                await user_repo.add("admin", "Admin")
            await session.commit()
        yield

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.router.lifespan_context = test_lifespan
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_embeddings] = lambda: embeddings
    app.dependency_overrides[get_summary_store] = lambda: None

    with TestClient(app, raise_server_exceptions=False) as client:
        yield {
            "client": client,
            "settings": settings,
            "store": store,
            "llm": llm,
        }

    app.dependency_overrides.clear()
    # Do NOT rmtree — this is persistent, survives between runs


@pytest.fixture(scope="session")
def query_set():
    with open(QUERY_SET, encoding="utf-8") as f:
        data = json.load(f)
    return data["queries"]


# ── Tests ───────────────────────────────────────────────────────────────────

@online
class TestCorpusUpload:
    """Upload corpus if not already present. Idempotent via file_hash dedup."""

    def test_upload_corpus(self, persistent_env):
        client = persistent_env["client"]

        # How many docs already uploaded?
        resp = client.get("/documents", headers={"X-User-Id": "admin"})
        assert resp.status_code == 200
        already_uploaded = resp.json()["total"]
        print(f"\n[upload] {already_uploaded} docs already in test DB")

        corpus_files = []
        for ext in (".pdf", ".htm", ".html", ".txt"):
            corpus_files.extend(sorted(CORPUS_ROOT.rglob(f"*{ext}")))
        corpus_files = [f for f in corpus_files if f.name != "ground_truth.json"]

        print(f"[upload] {len(corpus_files)} corpus files found on disk")

        uploaded = 0
        skipped = 0
        failed = 0
        for i, path in enumerate(corpus_files, 1):
            guess, _ = mimetypes.guess_type(path.name)
            mime = guess or "application/octet-stream"
            try:
                with open(path, "rb") as f:
                    resp = client.post(
                        "/documents/upload?auto_suggest=true",
                        files={"file": (path.name, f, mime)},
                        headers={"X-User-Id": "admin"},
                    )
            except Exception as e:
                failed += 1
                print(f"  [{i}/{len(corpus_files)}] {path.name} ... EXCEPTION {type(e).__name__}")
                continue

            if resp.status_code == 200:
                uploaded += 1
                print(f"  [{i}/{len(corpus_files)}] {path.name} ... ok")
            elif resp.status_code == 409:
                skipped += 1  # dedup — already uploaded
                print(f"  [{i}/{len(corpus_files)}] {path.name} ... skip (dedup)")
            else:
                failed += 1
                print(f"  [{i}/{len(corpus_files)}] {path.name} ... FAIL {resp.status_code}: {resp.text[:120]}")

        print(f"\n[upload] uploaded={uploaded}, skipped={skipped}, failed={failed}")

        # At least some docs in the DB
        resp = client.get("/documents", headers={"X-User-Id": "admin"})
        total = resp.json()["total"]
        print(f"[upload] total docs in test DB: {total}")
        assert total > 0, "no docs in test DB — cannot run queries"


@online
class TestQueryCredibility:
    """Run every query at top_k=4 AND top_k=10, evaluate 5 metrics."""

    def test_run_all_queries(self, persistent_env, query_set):
        client = persistent_env["client"]
        llm = persistent_env["llm"]

        results: list[dict] = []
        top_k_values = [4, 10]

        for i, query in enumerate(query_set, 1):
            for top_k in top_k_values:
                print(f"\n[{i}/{len(query_set)}] {query['id']} (top_k={top_k})")
                print(f"  Q: {query['question'][:100]}")

                req_body = {"question": query["question"], "top_k": top_k}
                if query.get("collection"):
                    req_body["collection"] = query["collection"]

                resp = client.post(
                    "/query", json=req_body,
                    headers={"X-User-Id": "admin"},
                )
                if resp.status_code != 200:
                    results.append({
                        "id": query["id"], "top_k": top_k,
                        "error": resp.text[:300], "status": resp.status_code,
                    })
                    print(f"  FAIL {resp.status_code}")
                    continue

                data = resp.json()
                answer = data.get("answer", "")
                sources = data.get("sources", [])
                confidence_tier = data.get("confidence_tier")

                # ── metrics ──
                returned_filenames = {s.get("source_file", "") for s in sources}
                expected_filenames = set(query.get("expected_sources", []))

                recall, precision = _compute_source_metrics(
                    returned_filenames, expected_filenames,
                )

                must_ok, missing = _all_match(answer, query.get("must_contain", []))
                forbidden_found = _any_forbidden(answer, query.get("must_not_contain", []))
                answer_correct = must_ok and not forbidden_found

                # For impossible queries — invert: answer is "correct" if it says "don't know".
                # Skip the must_not_contain check entirely because a faithful refusal
                # naturally echoes the question's topic ("does not contain information
                # about <topic>"), which would otherwise trip the forbidden-phrase trap.
                if query["type"] == "impossible":
                    uncertainty_markers = [
                        "don't know", "do not know", "no information", "not mentioned",
                        "cannot find", "does not cover", "does not contain",
                        "do not contain", "do not address", "does not address",
                        "unable to", "not discussed", "no mention", "not in the",
                        "no relevant", "not contain information", "not covered",
                    ]
                    answer_correct = any(m in answer.lower() for m in uncertainty_markers)
                    forbidden_found = []  # intentionally cleared for impossible queries

                # LLM judge for groundedness
                grounded, judge_reason = _judge_grounded(answer, sources, llm)

                # Confidence calibration: does returned tier match expected?
                expected_conf = query.get("expected_confidence", "moderate")
                conf_ok = (confidence_tier == expected_conf)

                # Attribute failure: retrieval vs generation
                if recall == 0.0 and expected_filenames:
                    failure_type = "retrieval"
                elif not answer_correct and recall > 0.0:
                    failure_type = "generation"
                elif not answer_correct:
                    failure_type = "unknown"
                else:
                    failure_type = "none"

                result = {
                    "id": query["id"],
                    "type": query["type"],
                    "top_k": top_k,
                    "question": query["question"][:150],
                    "answer_preview": answer[:300],
                    "returned_sources": sorted(returned_filenames)[:8],
                    "expected_sources": sorted(expected_filenames),
                    "recall": round(recall, 3),
                    "precision": round(precision, 3),
                    "answer_correct": answer_correct,
                    "missing_keywords": missing,
                    "forbidden_hit": forbidden_found,
                    "grounded": grounded,
                    "judge_reason": judge_reason,
                    "confidence_tier": confidence_tier,
                    "expected_confidence": expected_conf,
                    "confidence_calibrated": conf_ok,
                    "failure_type": failure_type,
                }
                results.append(result)

                print(f"  recall={recall:.2f} prec={precision:.2f} correct={answer_correct} "
                      f"grounded={grounded} conf={confidence_tier}/{expected_conf} fail={failure_type}")

        # Save raw results
        RESULTS_JSON.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nRaw results: {RESULTS_JSON}")

        # Write markdown report
        _write_report(results, query_set)


def _write_report(results: list[dict], query_set: list[dict]):
    """Write readable markdown report with aggregates."""
    lines = [
        f"# RAG Credibility Report",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"Queries: {len(query_set)} × 2 top_k values = {len(results)} runs",
        "",
    ]

    # Aggregate by type × top_k
    by_bucket: dict[tuple[str, int], list[dict]] = {}
    for r in results:
        if "error" in r:
            continue
        key = (r["type"], r["top_k"])
        by_bucket.setdefault(key, []).append(r)

    lines.append("## Aggregate metrics (by type × top_k)")
    lines.append("")
    lines.append("| Type | top_k | N | Recall | Precision | Correct | Grounded | Calibrated | Retrieval-fail | Gen-fail |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for (qtype, tk), rows in sorted(by_bucket.items()):
        n = len(rows)
        recall = sum(r["recall"] for r in rows) / n if n else 0
        prec = sum(r["precision"] for r in rows) / n if n else 0
        correct = sum(1 for r in rows if r["answer_correct"]) / n if n else 0
        grounded = sum(1 for r in rows if r["grounded"]) / n if n else 0
        calibrated = sum(1 for r in rows if r["confidence_calibrated"]) / n if n else 0
        ret_fail = sum(1 for r in rows if r["failure_type"] == "retrieval") / n if n else 0
        gen_fail = sum(1 for r in rows if r["failure_type"] == "generation") / n if n else 0
        lines.append(
            f"| {qtype} | {tk} | {n} | {recall:.2f} | {prec:.2f} | {correct:.0%} | "
            f"{grounded:.0%} | {calibrated:.0%} | {ret_fail:.0%} | {gen_fail:.0%} |"
        )

    lines.append("")
    lines.append("## Per-query results")
    lines.append("")
    lines.append("| ID | top_k | Type | Recall | Prec | Correct | Grounded | Calib | Failure | Missing keywords |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(results, key=lambda x: (x.get("id", ""), x.get("top_k", 0))):
        if "error" in r:
            lines.append(f"| {r.get('id')} | {r.get('top_k')} | — | — | — | ERR | — | — | — | {r['error'][:80]} |")
            continue
        lines.append(
            f"| `{r['id']}` | {r['top_k']} | {r['type']} | "
            f"{r['recall']:.2f} | {r['precision']:.2f} | "
            f"{'✅' if r['answer_correct'] else '❌'} | "
            f"{'✅' if r['grounded'] else '❌'} | "
            f"{'✅' if r['confidence_calibrated'] else '❌'} | "
            f"{r['failure_type']} | "
            f"{', '.join(r['missing_keywords'])[:80] if r['missing_keywords'] else '—'} |"
        )

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {REPORT_MD}")
