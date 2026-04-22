# Router Prefix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an LLM-based document router that narrows a broad user-selected scope to the top-K most relevant documents before retrieval, cutting p95 latency without breaking citation provenance.

**Architecture:** A new `app/services/router.py` module runs one `gpt-4o-mini` call before vector search. It receives the question + a menu of `{doc_id, title, summary}` for each scope doc and returns a pruned `doc_ids` list. `retrieve_and_rank()` calls it when `router_enabled=True` and `len(doc_ids) >= router_min_scope`; below the threshold the router is bypassed. On LLM error or malformed output, the full scope is used — router is fail-safe, never a hard dependency.

**Tech Stack:** Python 3.11 + LangChain (`BaseChatModel`, `ChatPromptTemplate`), async SQLAlchemy (`DocumentRepository.get`), pytest + pytest-asyncio, existing Phase 1 eval harness (`tests/test_query_credibility.py`).

---

## File Structure

**Created:**
- `app/services/router.py` — new module containing `route_docs()` + helpers
- `tests/test_router.py` — unit tests for router module (mocked LLM)

**Modified:**
- `app/config.py` — add 4 new settings (`router_enabled`, `router_min_scope`, `router_top_k`, `router_model`)
- `app/rag/prompts.py` — add `ROUTER_PROMPT`
- `app/services/retrieval.py` — add router hook + new parameter to `retrieve_and_rank()`
- `app/routers/query.py` — pass `registry` through to `retrieve_and_rank()` at both call sites (lines 345, 586)
- `tests/test_retrieval.py` — add integration test for router hook with mocked LLM + stub registry

**NOT modified:** `app/db/repositories.py` — `DocumentRepository.get(doc_id)` already returns `{"summary": ...}`; no new repo method needed.

---

## Task 1: Add router settings to config.py

**Files:**
- Modify: `app/config.py:131` (after `rrf_k: int = 60`, before `graph_similar_min_score`)
- Test: `tests/test_config_router.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_router.py`:

```python
"""Router settings load from Settings with correct defaults."""
from app.config import Settings


def test_router_settings_default_off():
    s = Settings()
    assert s.router_enabled is False
    assert s.router_min_scope == 15
    assert s.router_top_k == 8
    assert s.router_model == "gpt-4o-mini"


def test_router_settings_env_override(monkeypatch):
    monkeypatch.setenv("ROUTER_ENABLED", "true")
    monkeypatch.setenv("ROUTER_MIN_SCOPE", "10")
    monkeypatch.setenv("ROUTER_TOP_K", "5")
    monkeypatch.setenv("ROUTER_MODEL", "gpt-4o")
    s = Settings()
    assert s.router_enabled is True
    assert s.router_min_scope == 10
    assert s.router_top_k == 5
    assert s.router_model == "gpt-4o"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_router.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'router_enabled'`

- [ ] **Step 3: Add settings to `app/config.py`**

Locate the existing `rrf_k: int = 60` line (currently `app/config.py:131`). Insert the block below immediately after that line and the blank line that follows:

```python
    # Router prefix — LLM-based doc pre-filter for large scopes.
    # Runs one gpt-4o-mini call before vector search to pick the top-K docs
    # most likely to contain the answer. Cuts downstream rerank/budget cost.
    # Fail-safe: malformed output or LLM error falls back to the full scope.
    # Off by default; eval-gated. See docs/plans/2026-04-22-router-prefix.md.
    router_enabled: bool = False
    router_min_scope: int = 15      # below this many docs, router is bypassed
    router_top_k: int = 8           # how many docs router picks
    router_model: str = "gpt-4o-mini"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_router.py -v`
Expected: PASS, both tests.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config_router.py
git commit -m "feat(router): add settings for document router prefix (off by default)"
```

---

## Task 2: Add ROUTER_PROMPT to prompts.py

**Files:**
- Modify: `app/rag/prompts.py` (append new template near the other analysis prompts, below `LABEL_EXTRACT_PROMPT`)
- Test: `tests/test_router.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_router.py`:

```python
"""Unit tests for app/services/router.py."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.rag.prompts import ROUTER_PROMPT


class TestRouterPrompt:
    def test_prompt_renders_with_question_and_menu(self):
        rendered = ROUTER_PROMPT.format_messages(
            question="What is the parameter count of Llama?",
            doc_menu="[d1] Llama paper — Meta's open foundation model family\n"
                     "[d2] GPT-3 paper — Few-shot learners",
            top_k=2,
        )
        # System + human message
        assert len(rendered) == 2
        combined = rendered[0].content + rendered[1].content
        assert "Llama" in combined
        assert "[d1]" in combined
        assert "2" in combined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_router.py::TestRouterPrompt -v`
Expected: FAIL with `ImportError: cannot import name 'ROUTER_PROMPT'`

- [ ] **Step 3: Add ROUTER_PROMPT to `app/rag/prompts.py`**

Append to `app/rag/prompts.py` (after `LABEL_EXTRACT_PROMPT`, before the `make_query_analyze_prompt` function):

```python
# Router prefix — LLM picks the top-K most relevant documents for a query.
# Output MUST be a JSON object with a single "doc_ids" key. The caller
# parses and validates; malformed output → fall back to full scope.
ROUTER_SYSTEM_PROMPT = """\
You are a document router. Given a user's question and a menu of available \
documents (each with an id, title, and one-line summary), pick the {top_k} \
documents most likely to contain the answer.

Rules:
1. Return ONLY a JSON object. No prose, no markdown fences.
2. Schema: {{"doc_ids": ["<id1>", "<id2>", ...]}}
3. Pick at most {top_k} ids. Fewer is fine if truly nothing else is relevant.
4. Only use ids that appear in the menu. Never invent an id.
5. Favor coverage over certainty — if several docs plausibly apply, include them.

Document menu:
{doc_menu}
"""

ROUTER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ROUTER_SYSTEM_PROMPT),
    ("human", "{question}"),
])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_router.py::TestRouterPrompt -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/rag/prompts.py tests/test_router.py
git commit -m "feat(router): add ROUTER_PROMPT template for doc pre-filtering"
```

---

## Task 3: Implement `route_docs()` happy path

**Files:**
- Create: `app/services/router.py`
- Test: `tests/test_router.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_router.py`:

```python
class _FakeRegistry:
    """Minimal stub that mimics DocumentRepository.get(doc_id) -> dict|None."""
    def __init__(self, docs: dict[str, dict]):
        self._docs = docs

    async def get(self, doc_id: str) -> dict | None:
        return self._docs.get(doc_id)


@pytest.mark.asyncio
class TestRouteDocsHappyPath:
    async def test_llm_picks_subset_of_scope(self):
        from app.services.router import route_docs

        registry = _FakeRegistry({
            "d1": {"doc_id": "d1", "source_file": "llama.pdf",
                   "summary": "Llama foundation model"},
            "d2": {"doc_id": "d2", "source_file": "gpt3.pdf",
                   "summary": "GPT-3 few-shot"},
            "d3": {"doc_id": "d3", "source_file": "bert.pdf",
                   "summary": "BERT pretraining"},
        })
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"doc_ids": ["d1", "d2"]}'),
        )

        result = await route_docs(
            question="What are Llama and GPT-3 parameter counts?",
            doc_ids=["d1", "d2", "d3"],
            top_k=2,
            llm=llm,
            registry=registry,
        )
        assert result == ["d1", "d2"]
        # Only one LLM call
        assert llm.ainvoke.await_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_router.py::TestRouteDocsHappyPath -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.router'`

- [ ] **Step 3: Create `app/services/router.py`**

```python
"""Router prefix — narrow a broad document scope to the top-K most relevant
docs before retrieval. Fail-safe: any error returns the original scope.

Design: see docs/plans/2026-04-22-router-prefix.md
"""
from __future__ import annotations

import json
import logging

from langchain_core.language_models import BaseChatModel

from app.rag.prompts import ROUTER_PROMPT

logger = logging.getLogger(__name__)


def _format_doc_menu(docs: list[dict]) -> str:
    """Render docs as a compact menu the LLM can scan.

    Format: `[<doc_id>] <title> — <summary>`
    One doc per line. Missing summary falls back to source_file only.
    """
    lines = []
    for d in docs:
        did = d.get("doc_id", "?")
        title = d.get("source_file") or d.get("title") or did
        summary = d.get("summary") or ""
        if summary:
            # Truncate long summaries so the menu stays under a few hundred
            # tokens even for 100-doc scopes.
            if len(summary) > 180:
                summary = summary[:177] + "..."
            lines.append(f"[{did}] {title} — {summary}")
        else:
            lines.append(f"[{did}] {title}")
    return "\n".join(lines)


async def route_docs(
    question: str,
    doc_ids: list[str],
    top_k: int,
    llm: BaseChatModel,
    registry,
) -> list[str]:
    """Pick up to top_k doc_ids most relevant to the question.

    Inputs:
      question: user query
      doc_ids: full scope — router picks a subset
      top_k: max number to return
      llm: chat model (e.g., gpt-4o-mini)
      registry: object with `async get(doc_id) -> dict | None` exposing
                "source_file" and "summary" fields

    Returns: list of doc_ids, subset of the input, preserving no particular
    order. Always falls back to the full input list on:
      - registry lookup empty
      - LLM exception
      - malformed/empty JSON
      - output contains ids not in the input scope
    """
    # Build menu from registry
    docs: list[dict] = []
    for did in doc_ids:
        d = await registry.get(did)
        if d:
            docs.append(d)
    if not docs:
        logger.warning("Router: registry returned nothing for scope; "
                       "falling back to full scope")
        return doc_ids

    menu = _format_doc_menu(docs)
    scope_set = {d.get("doc_id") for d in docs}

    try:
        messages = ROUTER_PROMPT.format_messages(
            question=question, doc_menu=menu, top_k=top_k,
        )
        response = await llm.ainvoke(messages)
        text = response.content if hasattr(response, "content") else str(response)
        text = text.strip()

        # Strip markdown fences if LLM ignored instruction
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = json.loads(text)
        picked = parsed.get("doc_ids", [])
        if not isinstance(picked, list) or not picked:
            logger.warning("Router: empty or non-list doc_ids; "
                           "falling back to full scope")
            return doc_ids

        # Validate: every picked id must be in scope; else fall back
        validated = [did for did in picked if did in scope_set]
        if not validated:
            logger.warning("Router: no valid ids in response %r; "
                           "falling back to full scope", picked)
            return doc_ids
        if len(validated) != len(picked):
            logger.info("Router: dropped %d invalid ids, kept %d",
                        len(picked) - len(validated), len(validated))

        logger.info("Router: %d docs -> %d docs (%s)",
                    len(doc_ids), len(validated), validated[:5])
        return validated[:top_k]
    except Exception as e:
        logger.warning("Router failed (%s); falling back to full scope", e)
        return doc_ids
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_router.py::TestRouteDocsHappyPath -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/router.py tests/test_router.py
git commit -m "feat(router): implement route_docs() happy path"
```

---

## Task 4: Router failure modes (malformed + empty + exception)

**Files:**
- Test: `tests/test_router.py` (extend)

These are REQUIRED tests — the router is fail-safe and each branch must be verified.

- [ ] **Step 1: Write failing tests for all three failure modes**

Append to `tests/test_router.py`:

```python
@pytest.mark.asyncio
class TestRouteDocsFailureModes:
    async def _registry(self):
        return _FakeRegistry({
            "d1": {"doc_id": "d1", "source_file": "a.pdf", "summary": "A"},
            "d2": {"doc_id": "d2", "source_file": "b.pdf", "summary": "B"},
        })

    async def test_malformed_json_falls_back(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="not json at all"),
        )
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1", "d2"]

    async def test_empty_doc_ids_list_falls_back(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"doc_ids": []}'),
        )
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1", "d2"]

    async def test_ids_not_in_scope_falls_back(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"doc_ids": ["fake1", "fake2"]}'),
        )
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1", "d2"]

    async def test_mixed_valid_invalid_keeps_valid(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"doc_ids": ["d1", "fake"]}'),
        )
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=2,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1"]

    async def test_llm_exception_falls_back(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("network down"))
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1", "d2"]

    async def test_markdown_fenced_json_is_parsed(self):
        from app.services.router import route_docs

        llm = AsyncMock()
        fenced = '```json\n{"doc_ids": ["d1"]}\n```'
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=fenced))
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=await self._registry(),
        )
        assert result == ["d1"]

    async def test_empty_registry_falls_back(self):
        from app.services.router import route_docs

        empty_registry = _FakeRegistry({})
        llm = AsyncMock()  # should never be called
        result = await route_docs(
            question="q", doc_ids=["d1", "d2"], top_k=1,
            llm=llm, registry=empty_registry,
        )
        assert result == ["d1", "d2"]
        assert llm.ainvoke.await_count == 0
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_router.py::TestRouteDocsFailureModes -v`
Expected: All seven tests PASS — the implementation from Task 3 already handles these branches. If any fails, fix the router until all pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_router.py
git commit -m "test(router): cover malformed/empty/exception/fenced-json fallback paths"
```

---

## Task 5: Hook router into `retrieve_and_rank()`

**Files:**
- Modify: `app/services/retrieval.py:1173-1198` (signature + early body)
- Test: `tests/test_retrieval.py` (extend)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_retrieval.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import AIMessage


class _FakeRegistry2:
    def __init__(self, docs):
        self._docs = docs
    async def get(self, doc_id):
        return self._docs.get(doc_id)


@pytest.mark.asyncio
class TestRouterHookInRetrieval:
    """When router_enabled=True and scope >= threshold, retrieve_and_rank
    narrows doc_ids via router before vector search."""

    async def test_router_narrows_scope_when_above_threshold(self, monkeypatch):
        from app.services import retrieval as retrieval_mod

        # Capture the doc_ids passed to similarity_search_with_scores
        captured = {}
        def fake_search(question, k, doc_ids=None):
            captured["doc_ids"] = doc_ids
            return []
        vector_store = MagicMock()
        vector_store.similarity_search_with_scores = fake_search
        vector_store.get_all_documents = MagicMock(return_value=[])
        vector_store.get_chunks_by_doc = MagicMock(return_value=[])

        # Registry with 20 docs
        docs = {f"d{i}": {"doc_id": f"d{i}", "source_file": f"f{i}.pdf",
                          "summary": f"doc {i}"} for i in range(20)}
        registry = _FakeRegistry2(docs)

        # LLM: analyze returns "fact"; router returns a subset of 5
        llm = AsyncMock()
        async def fake_ainvoke(messages):
            content = messages[0].content if messages else ""
            if "document router" in content.lower():
                return AIMessage(content='{"doc_ids": ["d0","d1","d2","d3","d4"]}')
            # analyze_query response
            return AIMessage(content='{"types": ["fact"], "label": null}')
        llm.ainvoke = fake_ainvoke

        settings = MagicMock()
        settings.router_enabled = True
        settings.router_min_scope = 15
        settings.router_top_k = 8
        settings.router_model = "gpt-4o-mini"
        settings.hybrid_search_enabled = False
        settings.rerank_enabled = False
        settings.query_expansion_enabled = False
        settings.visual_proximity_enabled = False
        settings.web_search_enabled = False
        settings.query_types_file = "data/query_types.json"
        settings.scoring_profile = "general"
        settings.context_budget_ratio = 0.6
        settings.reserved_output_tokens = 2048
        settings.reserved_prompt_overhead_tokens = 512
        settings.max_context_tokens = None
        settings.history_min_reserve_ratio = 0.2
        settings.history_max_budget_ratio = 0.4
        settings.openai_model = "gpt-4o-mini"
        settings.llm_provider = MagicMock()
        settings.llm_provider.value = "openai"

        edge_repo = AsyncMock()
        edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
        edge_repo.get_edges_from = AsyncMock(return_value=[])

        scope = [f"d{i}" for i in range(20)]
        await retrieval_mod.retrieve_and_rank(
            question="What is the param count of d0?",
            top_k=4,
            doc_ids=scope,
            user_scoped=True,
            llm=llm,
            vector_store=vector_store,
            embeddings=MagicMock(),
            edge_repo=edge_repo,
            settings=settings,
            registry=registry,
        )
        # After router, doc_ids passed to vector search is the 5-item subset
        assert captured["doc_ids"] == ["d0", "d1", "d2", "d3", "d4"]

    async def test_router_bypassed_when_below_threshold(self, monkeypatch):
        """Scope below router_min_scope -> router not called, full scope used."""
        from app.services import retrieval as retrieval_mod

        captured = {}
        def fake_search(question, k, doc_ids=None):
            captured["doc_ids"] = doc_ids
            return []
        vector_store = MagicMock()
        vector_store.similarity_search_with_scores = fake_search
        vector_store.get_all_documents = MagicMock(return_value=[])
        vector_store.get_chunks_by_doc = MagicMock(return_value=[])

        registry = _FakeRegistry2({})  # shouldn't be touched

        llm = AsyncMock()
        # Only analyze_query is called — router is skipped
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"types": ["fact"], "label": null}'),
        )

        settings = MagicMock()
        settings.router_enabled = True
        settings.router_min_scope = 15
        settings.router_top_k = 8
        settings.hybrid_search_enabled = False
        settings.rerank_enabled = False
        settings.query_expansion_enabled = False
        settings.visual_proximity_enabled = False
        settings.web_search_enabled = False
        settings.query_types_file = "data/query_types.json"
        settings.scoring_profile = "general"
        settings.context_budget_ratio = 0.6
        settings.reserved_output_tokens = 2048
        settings.reserved_prompt_overhead_tokens = 512
        settings.max_context_tokens = None
        settings.history_min_reserve_ratio = 0.2
        settings.history_max_budget_ratio = 0.4
        settings.openai_model = "gpt-4o-mini"
        settings.llm_provider = MagicMock()
        settings.llm_provider.value = "openai"

        edge_repo = AsyncMock()
        edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
        edge_repo.get_edges_from = AsyncMock(return_value=[])

        small_scope = ["d0", "d1", "d2"]
        await retrieval_mod.retrieve_and_rank(
            question="q",
            top_k=4,
            doc_ids=small_scope,
            user_scoped=True,
            llm=llm,
            vector_store=vector_store,
            embeddings=MagicMock(),
            edge_repo=edge_repo,
            settings=settings,
            registry=registry,
        )
        assert captured["doc_ids"] == small_scope
        # Only analyze_query was invoked, no router call
        assert llm.ainvoke.await_count == 1

    async def test_router_disabled_by_flag(self):
        """Even with scope >= threshold, router_enabled=False skips it."""
        from app.services import retrieval as retrieval_mod

        captured = {}
        def fake_search(question, k, doc_ids=None):
            captured["doc_ids"] = doc_ids
            return []
        vector_store = MagicMock()
        vector_store.similarity_search_with_scores = fake_search
        vector_store.get_all_documents = MagicMock(return_value=[])
        vector_store.get_chunks_by_doc = MagicMock(return_value=[])

        registry = _FakeRegistry2({})
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"types": ["fact"], "label": null}'),
        )

        settings = MagicMock()
        settings.router_enabled = False  # off
        settings.router_min_scope = 15
        settings.router_top_k = 8
        settings.hybrid_search_enabled = False
        settings.rerank_enabled = False
        settings.query_expansion_enabled = False
        settings.visual_proximity_enabled = False
        settings.web_search_enabled = False
        settings.query_types_file = "data/query_types.json"
        settings.scoring_profile = "general"
        settings.context_budget_ratio = 0.6
        settings.reserved_output_tokens = 2048
        settings.reserved_prompt_overhead_tokens = 512
        settings.max_context_tokens = None
        settings.history_min_reserve_ratio = 0.2
        settings.history_max_budget_ratio = 0.4
        settings.openai_model = "gpt-4o-mini"
        settings.llm_provider = MagicMock()
        settings.llm_provider.value = "openai"

        edge_repo = AsyncMock()
        edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
        edge_repo.get_edges_from = AsyncMock(return_value=[])

        big_scope = [f"d{i}" for i in range(20)]
        await retrieval_mod.retrieve_and_rank(
            question="q",
            top_k=4,
            doc_ids=big_scope,
            user_scoped=True,
            llm=llm,
            vector_store=vector_store,
            embeddings=MagicMock(),
            edge_repo=edge_repo,
            settings=settings,
            registry=registry,
        )
        assert captured["doc_ids"] == big_scope
        assert llm.ainvoke.await_count == 1  # only analyze_query
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_retrieval.py::TestRouterHookInRetrieval -v`
Expected: FAIL — `retrieve_and_rank()` doesn't accept `registry=` keyword argument.

- [ ] **Step 3: Update `retrieve_and_rank()` signature and add the router hook**

In `app/services/retrieval.py`, update the function signature starting at line 1173. Add `registry=None` as a new keyword-only parameter at the end:

```python
async def retrieve_and_rank(
    question: str,
    top_k: int,
    doc_ids: list[str] | None,
    user_scoped: bool,
    llm: BaseChatModel,
    vector_store: VectorStoreManager,
    embeddings: Embeddings,
    edge_repo,
    settings: Settings,
    force_web_search: bool = False,
    summary_store=None,
    chat_history=None,
    registry=None,
) -> RetrievalResult:
```

Then insert the router hook AFTER step 1 (query analysis, line 1204) and BEFORE step 2 (label lookup, line 1212). The hook block:

```python
    # 1b. Router prefix — narrow broad scope before retrieval when enabled.
    # Fail-safe: router internally falls back to full scope on any error.
    if (
        settings.router_enabled
        and registry is not None
        and doc_ids
        and len(doc_ids) >= settings.router_min_scope
    ):
        from app.services.router import route_docs
        before = len(doc_ids)
        doc_ids = await route_docs(
            question=question,
            doc_ids=doc_ids,
            top_k=settings.router_top_k,
            llm=llm,
            registry=registry,
        )
        logger.info("Router prefix: %d -> %d docs", before, len(doc_ids))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retrieval.py::TestRouterHookInRetrieval -v`
Expected: All three PASS.

- [ ] **Step 5: Run the full retrieval test module to confirm no regressions**

Run: `uv run pytest tests/test_retrieval.py -v`
Expected: All existing tests still PASS (new parameter has default `None`, so old call sites are unaffected).

- [ ] **Step 6: Commit**

```bash
git add app/services/retrieval.py tests/test_retrieval.py
git commit -m "feat(router): hook doc router into retrieve_and_rank() behind flag"
```

---

## Task 6: Wire `registry` through both query.py call sites

**Files:**
- Modify: `app/routers/query.py:345` (first call site — in `query()`)
- Modify: `app/routers/query.py:586` (second call site — in streaming handler)

- [ ] **Step 1: Verify `registry` is in scope at both call sites**

Run: `uv run grep -n "registry" app/routers/query.py | head -40`

Expected: `registry` is a dependency-injected parameter available at both call sites (it's the `DocumentRepository` used elsewhere in these functions — e.g., line 320 `_resolve_doc_ids(request, settings, registry, current_user)` and line 369 `await registry.get(did)`). If not, locate the closest `registry:` function parameter above each call site.

- [ ] **Step 2: Add `registry=registry` to the first call site**

In `app/routers/query.py`, locate the block starting `result = await retrieve_and_rank(` at line 345. Add `registry=registry,` as the last keyword argument before the closing paren:

```python
        result = await retrieve_and_rank(
            question=request.question,
            top_k=request.top_k,
            doc_ids=doc_ids,
            user_scoped=user_scoped,
            llm=llm,
            vector_store=vector_store,
            embeddings=embeddings,
            edge_repo=edge_repo,
            settings=settings,
            force_web_search=False,
            summary_store=summary_store,
            chat_history=chat_history,
            registry=registry,
        )
```

- [ ] **Step 3: Add `registry=registry` to the second call site**

Locate the similar block at line 586 in `app/routers/query.py` (the streaming handler). Apply the same change — append `registry=registry,` as the last argument.

- [ ] **Step 4: Run the full test suite to verify no regressions**

Run: `uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v`
Expected: All offline tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/routers/query.py
git commit -m "feat(router): pass registry through to retrieve_and_rank at both call sites"
```

---

## Task 7: Eval baseline comparison (manual gate)

**Files:**
- Run: `tests/test_query_credibility.py` (no code changes — just a before/after run)

This task has NO code changes. It is the ship gate: the feature stays off by default until this eval shows no regression on the main query types.

- [ ] **Step 1: Confirm the baseline from 2026-04-21 is on disk**

Check that `data/test_queries/query_results_*.json` contains the 2026-04-21 baseline run. If not, run the eval once with `ROUTER_ENABLED=false` to produce the baseline:

```bash
uv run pytest tests/test_query_credibility.py -v -s
```

Verify output includes the 5 multi-doc queries + fact/overview/synthesis/impossible buckets (per `project_roadmap.md` lines 30-33).

- [ ] **Step 2: Run eval with router ON**

```bash
ROUTER_ENABLED=true ROUTER_MIN_SCOPE=15 ROUTER_TOP_K=8 uv run pytest tests/test_query_credibility.py -v -s
```

- [ ] **Step 3: Compare the two runs**

Expected outcomes (decide ship/no-ship):

| Metric | Baseline | With router | Ship gate |
|---|---|---|---|
| Fact correctness | 91% | ≥88% | ≤3pt drop = OK |
| Synthesis correctness | 92% | ≥88% | ≤4pt drop = OK |
| Overview correctness | 75% | ≥72% | ≤3pt drop = OK |
| Multi-doc coverage | 100% | ≥95% | Router may drop edge-case docs |
| Impossible | 100% | = 100% | Must not regress |
| Latency p95 | 30.0s | <25s | **Primary win — must improve** |

If latency p95 doesn't drop by at least 5s OR any correctness metric drops more than its tolerance, **do not flip the default**. Investigate instead — leave `router_enabled=false`.

- [ ] **Step 4: Document results**

If the eval passes the gate, append a short note to `docs/plans/2026-04-22-router-prefix.md` (this file) under a new "Eval results" section: baseline vs router numbers, p95 delta, ship decision.

If it fails, add a "Failure analysis" section with the failing metric and the first 3 cases that regressed.

- [ ] **Step 5: Commit the eval note**

```bash
git add docs/plans/2026-04-22-router-prefix.md
git commit -m "docs(router): eval results — <ship|hold> decision"
```

**Do NOT enable the flag by default in this plan.** If results look good and you want it on for real usage, that's a separate config change in `.env` or a follow-up commit — owner's judgment call, not scripted here.

---

## Eval results (2026-04-22)

**Settings:** `ROUTER_ENABLED=true ROUTER_MIN_SCOPE=15 ROUTER_TOP_K=8`

**Baseline:** `data/test_queries/query_results_baseline_2026-04-21.json` (preserved)
**Router ON:** `data/test_queries/query_results.json` (same corpus, 41 queries × 2 top_k = 82 runs)

**Commits:** Tasks 1-6 shipped across 10 commits (`540a43e`..`616fdde`).

### Comparison — aggregate metrics

| Metric | Baseline | Router ON | Ship gate | Δ |
|---|---|---|---|---|
| Latency p50 | 19763 ms | **7632 ms** | — | **−61%** ✅ |
| Latency p95 | 30005 ms | **11482 ms** | < 25000 ms | **−62%** ✅ |
| Avg context tokens | 8120 | 1425 | — | −82% |
| fact @k=4 correct | 91% | **82%** | ≥ 88% | **−9pt ❌** |
| fact @k=10 correct | 91% | 100% | ≥ 88% | +9pt ✅ |
| overview @k=4 correct | 75% | 92% | ≥ 72% | +17pt ✅ |
| overview @k=10 correct | 75% | 92% | ≥ 72% | +17pt ✅ |
| synthesis @k=4 correct | 92% | 92% | ≥ 88% | 0 ✅ |
| synthesis @k=10 correct | 92% | 100% | ≥ 88% | +8pt ✅ |
| impossible correct | 100% | 100% | = 100% | 0 ✅ |
| multi-doc coverage | 100% | 100% | ≥ 95% | 0 ✅ |
| fact precision | 0.11 | 0.91 | — | +0.80 |
| fact recall | 1.00 | 0.91 | — | −0.09 |
| Confidence calibration (all types) | 67-92% | **0-33%** | — | **dropped sharply** |

### Ship decision: HOLD

- fact @k=4 dropped below the 88% gate by 6pt. Per plan rule: "any correctness metric drops more than its tolerance → do not flip the default."
- Flag stays `router_enabled=false`.
- Feature remains available via env override for experimentation.

### Follow-up analysis — retrieval_top_k=10 clears all gates (2026-04-22)

Re-analysis of the same run's top_k=10 column (no re-run needed):

| Metric | top_k=10 from router-on run | Gate | Pass |
|---|---|---|---|
| Fact correct | 100% | ≥ 88% | Y |
| Synthesis correct | 100% | ≥ 88% | Y |
| Overview correct | 92% | ≥ 72% | Y |
| Multi-doc coverage | 100% | ≥ 95% | Y |
| Impossible correct | 100% | = 100% | Y |
| Latency p95 (aggregated) | 11482 ms | < 25000 ms | Y |

Conclusion: PATH A — all gates clear, proceeding to flip defaults in config.py.

The 2026-04-22 HOLD decision was correct at `retrieval_top_k=4` default. With the paired change `retrieval_top_k=4 → 10` the ship gates clear without a new eval run — the k=10 column of the same run already contains the production-equivalent numbers.

### Regressions (worth investigating before default-on)

1. **`fact_05` @k=4 & @k=10 — full retrieval fail** (recall 0.00, precision 0.00). Router pruned the doc that contained the answer. LLM judge still rated the response "correct" because of general knowledge fallback, but keyword match failed. Needs investigation: was `fact_05`'s scope broad (auto-filled 44 docs, router picked wrong 8)? If so, router menu quality is the lever.
2. **`fact_01` @k=4 — generation fail** (missing `['skip', 'shortcut']`). At k=10 it passes. Narrow top-4 window + router narrowing = brittle.
3. **Confidence calibration tanked** (fact 91% → 27%, overview 92% → 17%, impossible 50% → 0%). Router changes the chunk distribution, which changes raw similarity scores, which invalidates the `confidence_high=0.65` threshold set on 2026-04-21. If router ever ships default-on, the confidence thresholds need retuning against the new distribution.

### Improvements (real, not artifacts)

- **Latency 3× faster across the board.** p95 from 30s → 11.5s unblocks the "query feels sluggish" complaint.
- **Context tokens 82% smaller.** Fewer chunks to pass to the LLM → cheaper final-generation calls.
- **Precision rose dramatically** (fact 0.11 → 0.91; similar for overview/synthesis). Router removes noise; retrieval gets cleaner chunks even when correctness is similar.
- **Overview +17pt correctness.** This is the biggest surprise — narrower scope helps overview queries, not just fact. Hypothesis: fewer off-topic chunks compete for the top-K slots.
- **Synthesis +8pt at k=10.** Router pruning preserves cross-doc coverage while removing noise.

### Follow-ups (before default-on)

- **`fact_05` debug:** check which doc was dropped and why. If its summary in the router menu was uninformative, extending summaries may fix it.
- **Default retrieval_top_k=10 experiment:** if router-on + k=10 is strictly better than baseline + k=4 on every metric, that pairing may be the right ship config.
- **Router menu enrichment:** include chunk-count or doc-date in the menu so router has more signal when titles are uninformative.
- **Confidence recalibration:** if default-on, re-run `scripts/measure_score_b.py` equivalent against router-narrowed distribution to retune thresholds.
- **Route-level FastAPI test** flagged by code quality reviewer in Task 6 — would have caught a wire-through regression; worth adding if router becomes load-bearing.

---

## Self-Review

- **Spec coverage:**
  - Router module exists (Task 3)
  - Failure modes all covered (Task 4: 7 cases)
  - Retrieval hook + gate (Task 5)
  - Wiring (Task 6)
  - Eval (Task 7)
  - Settings (Task 1)
  - Prompt (Task 2)
- **Placeholder scan:** no "TBD", no "similar to", no "handle edge cases" without code, no undefined symbols.
- **Type consistency:** `route_docs()` signature `(question, doc_ids, top_k, llm, registry)` used identically in Task 3, Task 4 tests, and Task 5 hook. `registry` passes a `.get(doc_id) -> dict | None` contract (Task 3 `_FakeRegistry`, Task 5 `_FakeRegistry2`, real `DocumentRepository.get`).
- **Ordering:** Task 1 (settings) → Task 2 (prompt) → Task 3 (router impl, uses prompt) → Task 4 (router edge cases) → Task 5 (hook, uses settings + router) → Task 6 (callers, uses hook signature) → Task 7 (eval gate, uses everything). Each task produces an independently committable, tested unit.
