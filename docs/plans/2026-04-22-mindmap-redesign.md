# Mindmap Redesign — Tree Mode + Graph Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the misnamed "mindmap" (which was really a per-doc force graph) with a TRUE hierarchical mind map (LLM-derived concept tree + radial layout), while keeping the force-graph view reachable as a second mode. Users get both views, explicitly labeled.

**Architecture:** The existing `/documents/:id/mindmap` endpoint gets renamed to `/documents/:id/graph` (its data is chunks+edges — a graph). A NEW `/documents/:id/mindmap` endpoint returns an LLM-derived hierarchical tree (central theme + branches + sub-concepts → chunk_indices). Frontend page has a mode toggle: **Mind Map** (tree, default) vs **Graph** (force graph). Dashboard exposes both as separate entry points. LLM cost ~$0.002/doc, cached to `data/mindmaps/{doc_id}.json`.

**Tech Stack:** Python 3.11 + FastAPI + Pydantic + LangChain (backend). React 19 + Tailwind + react-d3-tree (new dep) + react-force-graph-2d (existing, kept for Graph mode) + react-i18next (frontend).

**Predecessor context:** Builds on 2026-04-22 evening's mindmap v0 (commit `61bf14e`). That shipped the force-graph as "mindmap" — this plan repositions it as "Graph mode" and adds the real hierarchical mind map as "Mind Map mode."

---

## File Structure

**Backend — modified (rename):**
- `app/routers/documents.py` — rename route `/documents/{doc_id}/mindmap` → `/documents/{doc_id}/graph` (keep handler, just change path + function name)
- `app/services/mindmap.py` — rename `build_mindmap` → `build_doc_graph`; add new `build_mindmap_tree` function with LLM + caching
- `app/models/schemas.py` — rename Mindmap* → DocGraph*; add MindmapTree* schemas
- `app/rag/prompts.py` — add `MINDMAP_TREE_PROMPT`
- `tests/test_mindmap.py` — update existing tests for renamed names; add tests for tree service + route

**Backend — created:**
- No new files. Everything extends existing locations.

**Frontend — modified:**
- `frontend/src/lib/api.js` — rename `fetchMindmap` → `fetchDocGraph`; add new `fetchMindmap` (tree)
- `frontend/src/hooks/useMindmap.js` — rename to reflect split: `useDocGraph` + `useMindmap` (tree)
- `frontend/src/pages/MindmapPage.jsx` — add mode toggle, render tree or graph based on `?mode=` query param
- `frontend/src/components/MindmapNodePanel.jsx` — adapt to show either chunk detail (graph mode) or concept leaf + supporting chunks (tree mode)
- `frontend/src/pages/DashboardPage.jsx` — add TWO entry-point icons instead of one
- `frontend/src/i18n/locales/en.json` — add keys for mode toggle + tree-specific strings
- `frontend/src/i18n/locales/zh.json` — same in Chinese

**Frontend — created:**
- `frontend/src/components/MindmapTree.jsx` — radial tree renderer using react-d3-tree
- `frontend/src/hooks/useDocGraph.js` — new hook for graph data

**Frontend — package:**
- `frontend/package.json` — add `react-d3-tree` dependency

**NOT modified:** `app/db/repositories.py` (EdgeRepository.get_edges_in_doc stays — still used by graph endpoint), `app/services/router.py`, `app/services/retrieval.py`, `frontend/src/components/MindmapGraph.jsx` (keeps rendering the graph mode), `frontend/src/components/MindmapLegend.jsx` (used in graph mode), `frontend/src/router.jsx` (route path `/mindmap/:docId` stays, mode switching happens via `?mode=` param).

---

## Task 1: Backend — rename Mindmap* → DocGraph* for the existing graph endpoint

This task renames today's `/documents/:id/mindmap` to `/documents/:id/graph` and all associated schema/service names. No logic changes; just reflecting that this endpoint serves the force-graph data, not a true mind map.

**Files:**
- Modify: `app/models/schemas.py` (rename 4 classes)
- Modify: `app/services/mindmap.py` (rename function + imports)
- Modify: `app/routers/documents.py` (rename route path + handler function)
- Modify: `tests/test_mindmap.py` (update test imports + endpoint path in `TestMindmapRoute`)

- [ ] **Step 1: Rename schemas in `app/models/schemas.py`**

Find these 4 class names at the end of `app/models/schemas.py` and rename them:

| Old | New |
|---|---|
| `MindmapNode` | `DocGraphNode` |
| `MindmapEdge` | `DocGraphEdge` |
| `MindmapStats` | `DocGraphStats` |
| `MindmapResponse` | `DocGraphResponse` |

Also update the internal references within those classes (e.g., `MindmapResponse.nodes: list[MindmapNode]` → `list[DocGraphNode]`).

Update docstrings: replace "mind map" with "document graph" where the classes describe themselves (e.g., `MindmapResponse` docstring says "Full response for GET /documents/{doc_id}/mindmap"; change to "Full response for GET /documents/{doc_id}/graph").

Leave the existing `Mindmap*Page` and frontend references untouched in this task; other files will update in later steps.

- [ ] **Step 2: Rename service + imports in `app/services/mindmap.py`**

In `app/services/mindmap.py`:

Change the import block:
```python
from app.models.schemas import (
    MindmapNode, MindmapEdge, MindmapStats, MindmapResponse,
)
```
to:
```python
from app.models.schemas import (
    DocGraphNode, DocGraphEdge, DocGraphStats, DocGraphResponse,
)
```

Rename `_chunk_to_node` return type: `-> MindmapNode` → `-> DocGraphNode` (keep function name the same — it's generic).

Rename `_build_edges_and_stats` return types:
- Old: `tuple[list[MindmapEdge], MindmapStats]`
- New: `tuple[list[DocGraphEdge], DocGraphStats]`

Inside, change `MindmapEdge(...)` → `DocGraphEdge(...)` and `MindmapStats(...)` → `DocGraphStats(...)`.

Rename the main function: `async def build_mindmap(...)` → `async def build_doc_graph(...)`. Keep signature identical.

Inside, change `return MindmapResponse(...)` → `return DocGraphResponse(...)`.

Update the module docstring to reflect: this is the doc-graph (force-graph) builder, not the true mind map.

- [ ] **Step 3: Update route in `app/routers/documents.py`**

Find the route handler. Update these pieces:

Change import:
```python
from app.models.schemas import MindmapResponse
from app.services.mindmap import build_mindmap
```
to:
```python
from app.models.schemas import DocGraphResponse
from app.services.mindmap import build_doc_graph
```

Change the decorator path and function name:
```python
@router.get(
    "/{doc_id}/mindmap",
    response_model=MindmapResponse,
)
async def get_document_mindmap(
    ...
) -> MindmapResponse:
    ...
    return await build_mindmap(doc_id, doc, vector_store, edge_repo)
```
to:
```python
@router.get(
    "/{doc_id}/graph",
    response_model=DocGraphResponse,
)
async def get_document_graph(
    ...
) -> DocGraphResponse:
    ...
    return await build_doc_graph(doc_id, doc, vector_store, edge_repo)
```

Update the handler docstring: "Return the doc-graph data (nodes + edges + stats) for one doc. Chunks become graph nodes; chunk_edges rows become graph edges. For a hierarchical mind map, see the `/mindmap` endpoint."

- [ ] **Step 4: Update tests in `tests/test_mindmap.py`**

Find `TestMindmapSchemas` class and update all schema references:
- `from app.models.schemas import MindmapNode` → `DocGraphNode`
- `MindmapNode(...)` → `DocGraphNode(...)`
- Same for `MindmapEdge`, `MindmapStats`, `MindmapResponse`

Rename the class: `TestMindmapSchemas` → `TestDocGraphSchemas`.

Find `TestBuildMindmap` class and update:
- Import: `from app.services.mindmap import _chunk_to_node` — keep (_chunk_to_node kept name in step 2)
- All `_chunk_to_node` tests: NO changes needed, they test the helper which still returns DocGraphNode (Pydantic accepts the same construction args)
- Tests that construct `MindmapNode`/`MindmapEdge`/`MindmapStats`: update class names

Rename class: `TestBuildMindmap` → `TestBuildDocGraph`. And the import for `build_mindmap` → `build_doc_graph`.

Find `TestMindmapRoute` class and update:
- Change URL in test requests: `"/documents/d1/mindmap"` → `"/documents/d1/graph"`
- Rename class: `TestMindmapRoute` → `TestDocGraphRoute`

- [ ] **Step 5: Run tests to verify**

Run:
```bash
uv run pytest tests/test_mindmap.py -v
```
Expected: 18 PASSED (all existing tests renamed and still passing).

If any test fails, the rename missed a spot. Fix and re-run.

- [ ] **Step 6: Commit**

```bash
git add app/models/schemas.py app/services/mindmap.py app/routers/documents.py tests/test_mindmap.py
git commit -m "$(cat <<'EOF'
refactor(mindmap): rename Mindmap* -> DocGraph* for the force-graph endpoint

The existing /documents/{id}/mindmap endpoint returned chunks + edges —
that's a graph, not a mind map. Rename to /documents/{id}/graph with
matching schema names. A true hierarchical mind map endpoint will be
added next at /documents/{id}/mindmap.

No behavior change, pure rename.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Backend — tree schemas

Add the Pydantic schemas for the hierarchical mind map (tree structure).

**Files:**
- Modify: `app/models/schemas.py` (append 4 new schemas)
- Test: `tests/test_mindmap.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mindmap.py`:

```python
class TestMindmapTreeSchemas:
    def test_mindmap_leaf(self):
        from app.models.schemas import MindmapLeaf

        leaf = MindmapLeaf(name="Attention mechanism", chunk_indices=[3, 5, 7])
        assert leaf.name == "Attention mechanism"
        assert leaf.chunk_indices == [3, 5, 7]

    def test_mindmap_branch(self):
        from app.models.schemas import MindmapBranch, MindmapLeaf

        branch = MindmapBranch(
            name="Architecture",
            children=[
                MindmapLeaf(name="Attention", chunk_indices=[3]),
                MindmapLeaf(name="Feed-forward", chunk_indices=[4, 6]),
            ],
        )
        assert branch.name == "Architecture"
        assert len(branch.children) == 2
        assert branch.children[0].name == "Attention"

    def test_mindmap_tree(self):
        from app.models.schemas import MindmapTree, MindmapBranch, MindmapLeaf

        tree = MindmapTree(
            central="A paper on attention in transformers",
            branches=[
                MindmapBranch(
                    name="Architecture",
                    children=[MindmapLeaf(name="QKV", chunk_indices=[3])],
                ),
            ],
        )
        assert tree.central == "A paper on attention in transformers"
        assert len(tree.branches) == 1

    def test_mindmap_tree_response(self):
        from app.models.schemas import MindmapTreeResponse

        resp = MindmapTreeResponse(
            doc_id="d1",
            filename="paper.pdf",
            cached=False,
            tree={
                "central": "test",
                "branches": [],
            },
        )
        assert resp.doc_id == "d1"
        assert resp.cached is False
        assert resp.tree.central == "test"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mindmap.py::TestMindmapTreeSchemas -v`
Expected: FAIL with `ImportError: cannot import name 'MindmapLeaf' from 'app.models.schemas'`

- [ ] **Step 3: Add schemas to `app/models/schemas.py`**

Append at the end of the file (after the renamed DocGraph* classes):

```python
class MindmapLeaf(BaseModel):
    """Leaf node in the hierarchical mind map — a concept backed by chunks."""
    name: str
    chunk_indices: list[int]  # indices of chunks that support this concept


class MindmapBranch(BaseModel):
    """Main branch in the mind map: a top-level theme with sub-concept leaves."""
    name: str
    children: list[MindmapLeaf]


class MindmapTree(BaseModel):
    """The LLM-derived hierarchical structure for one document."""
    central: str              # central theme (1-line)
    branches: list[MindmapBranch]


class MindmapTreeResponse(BaseModel):
    """Full response for GET /documents/{doc_id}/mindmap (tree mode)."""
    doc_id: str
    filename: str
    cached: bool              # True if served from data/mindmaps/ cache
    tree: MindmapTree
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mindmap.py::TestMindmapTreeSchemas -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add app/models/schemas.py tests/test_mindmap.py
git commit -m "$(cat <<'EOF'
feat(mindmap): tree schemas for the hierarchical mind map endpoint

MindmapLeaf -> MindmapBranch -> MindmapTree -> MindmapTreeResponse.
Each leaf concept is backed by chunk_indices, so clicking a leaf in
the frontend can resolve back to the source chunks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Backend — tree service with LLM + file cache

The core of the new feature: LLM extracts a concept hierarchy from chunk summaries, cached to disk.

**Files:**
- Modify: `app/rag/prompts.py` (add `MINDMAP_TREE_PROMPT`)
- Modify: `app/services/mindmap.py` (add `build_mindmap_tree` function + helpers)
- Test: `tests/test_mindmap.py` (extend with `TestBuildMindmapTree`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mindmap.py`:

```python
from pathlib import Path
import tempfile
import json as json_lib


class TestBuildMindmapTree:
    def _chunks(self):
        """Fixture: 4 minimal chunks with summaries."""
        return [
            Document(page_content="x", metadata={
                "doc_id": "d1", "chunk_index": 0,
                "summary": "Introduction to attention",
            }),
            Document(page_content="x", metadata={
                "doc_id": "d1", "chunk_index": 1,
                "summary": "Query-Key-Value mechanism",
            }),
            Document(page_content="x", metadata={
                "doc_id": "d1", "chunk_index": 2,
                "summary": "Experimental results",
            }),
            Document(page_content="x", metadata={
                "doc_id": "d1", "chunk_index": 3,
                "summary": "Conclusion",
            }),
        ]

    @pytest.mark.asyncio
    async def test_llm_happy_path(self, tmp_path, monkeypatch):
        from app.services.mindmap import build_mindmap_tree

        # Force cache into a temp dir
        monkeypatch.setattr(
            "app.services.mindmap.MINDMAPS_CACHE_DIR", tmp_path,
        )

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=json_lib.dumps({
            "central": "Attention in transformers",
            "branches": [
                {
                    "name": "Architecture",
                    "children": [
                        {"name": "QKV", "chunk_indices": [1]},
                    ],
                },
                {
                    "name": "Experiments",
                    "children": [
                        {"name": "Results", "chunk_indices": [2]},
                    ],
                },
            ],
        })))

        vector_store = MagicMock()
        vector_store.get_chunks_by_doc = MagicMock(return_value=self._chunks())

        resp = await build_mindmap_tree(
            doc_id="d1",
            doc={"filename": "paper.pdf", "summary": "..."},
            vector_store=vector_store,
            llm=llm,
        )

        assert resp.doc_id == "d1"
        assert resp.filename == "paper.pdf"
        assert resp.cached is False
        assert resp.tree.central == "Attention in transformers"
        assert len(resp.tree.branches) == 2
        # Cache file created
        assert (tmp_path / "d1.json").exists()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_llm(self, tmp_path, monkeypatch):
        from app.services.mindmap import build_mindmap_tree

        monkeypatch.setattr(
            "app.services.mindmap.MINDMAPS_CACHE_DIR", tmp_path,
        )

        # Pre-write a cache file
        cached_tree = {
            "central": "Cached theme",
            "branches": [{"name": "Cached", "children": []}],
        }
        (tmp_path / "d1.json").write_text(
            json_lib.dumps(cached_tree), encoding="utf-8",
        )

        llm = AsyncMock()
        # Should NEVER be called
        llm.ainvoke = AsyncMock(side_effect=AssertionError("LLM must not be called on cache hit"))

        vector_store = MagicMock()
        # Should NOT be called when cache hits
        vector_store.get_chunks_by_doc = MagicMock(side_effect=AssertionError("Chunks not needed on cache hit"))

        resp = await build_mindmap_tree(
            doc_id="d1",
            doc={"filename": "paper.pdf"},
            vector_store=vector_store,
            llm=llm,
        )

        assert resp.cached is True
        assert resp.tree.central == "Cached theme"

    @pytest.mark.asyncio
    async def test_empty_doc_returns_empty_tree(self, tmp_path, monkeypatch):
        from app.services.mindmap import build_mindmap_tree

        monkeypatch.setattr(
            "app.services.mindmap.MINDMAPS_CACHE_DIR", tmp_path,
        )

        llm = AsyncMock()  # must not be called
        llm.ainvoke = AsyncMock(side_effect=AssertionError("LLM must not be called for empty doc"))

        vector_store = MagicMock()
        vector_store.get_chunks_by_doc = MagicMock(return_value=[])

        resp = await build_mindmap_tree(
            doc_id="d1",
            doc={"filename": "empty.pdf"},
            vector_store=vector_store,
            llm=llm,
        )

        assert resp.cached is False
        assert resp.tree.central == ""
        assert resp.tree.branches == []

    @pytest.mark.asyncio
    async def test_malformed_llm_response_falls_back(self, tmp_path, monkeypatch):
        from app.services.mindmap import build_mindmap_tree

        monkeypatch.setattr(
            "app.services.mindmap.MINDMAPS_CACHE_DIR", tmp_path,
        )

        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content="not json"))

        vector_store = MagicMock()
        vector_store.get_chunks_by_doc = MagicMock(return_value=self._chunks())

        resp = await build_mindmap_tree(
            doc_id="d1",
            doc={"filename": "paper.pdf"},
            vector_store=vector_store,
            llm=llm,
        )

        # Fallback: return empty tree, don't crash
        assert resp.cached is False
        assert resp.tree.branches == []
        # Cache file NOT written (we don't want to cache failures)
        assert not (tmp_path / "d1.json").exists()

    @pytest.mark.asyncio
    async def test_invalid_chunk_indices_filtered(self, tmp_path, monkeypatch):
        from app.services.mindmap import build_mindmap_tree

        monkeypatch.setattr(
            "app.services.mindmap.MINDMAPS_CACHE_DIR", tmp_path,
        )

        llm = AsyncMock()
        # LLM returns chunk_index=99 which doesn't exist (only 0-3 do)
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=json_lib.dumps({
            "central": "Paper",
            "branches": [
                {
                    "name": "Branch",
                    "children": [
                        {"name": "Concept", "chunk_indices": [1, 99, 2]},
                    ],
                },
            ],
        })))

        vector_store = MagicMock()
        vector_store.get_chunks_by_doc = MagicMock(return_value=self._chunks())

        resp = await build_mindmap_tree(
            doc_id="d1",
            doc={"filename": "paper.pdf"},
            vector_store=vector_store,
            llm=llm,
        )

        # Invalid index 99 dropped; 1 and 2 kept
        concept = resp.tree.branches[0].children[0]
        assert concept.chunk_indices == [1, 2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mindmap.py::TestBuildMindmapTree -v`
Expected: FAIL with `ImportError: cannot import name 'build_mindmap_tree' from 'app.services.mindmap'`

- [ ] **Step 3: Add `MINDMAP_TREE_PROMPT` to `app/rag/prompts.py`**

Append to `E:\MEINRAG\app\rag\prompts.py` (after `ROUTER_PROMPT`):

```python
# Mind map tree — LLM extracts concept hierarchy from chunk summaries.
# Output MUST be a JSON object matching the schema. Caller parses +
# validates chunk_indices (out-of-range ones are dropped).
MINDMAP_TREE_SYSTEM_PROMPT = """\
You are building a hierarchical mind map for a single document.

Document filename: {filename}

Below are the chunks from the document, each labeled by its index and
summarized in one line. Your task: produce a concept hierarchy that
captures what the document is about.

Rules:
1. Return ONLY a JSON object. No prose, no markdown fences.
2. Schema:
{{
  "central": "<one-line theme capturing the document's essence>",
  "branches": [
    {{
      "name": "<top-level theme, 1-5 words>",
      "children": [
        {{"name": "<sub-concept, 1-8 words>", "chunk_indices": [<int>, ...]}}
      ]
    }}
  ]
}}
3. 3-6 top-level branches. Each branch has 2-5 sub-concept leaves.
4. Each leaf's chunk_indices lists 1-5 chunks that support that concept.
5. A chunk index may appear in multiple leaves (ideas cross-cut).
6. Output language: match the document's predominant language.

Chunks:
{chunks}
"""

MINDMAP_TREE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", MINDMAP_TREE_SYSTEM_PROMPT),
    ("human", "Generate the mind map now."),
])
```

- [ ] **Step 4: Add `build_mindmap_tree` to `app/services/mindmap.py`**

Add these imports near the top of `app/services/mindmap.py` (below the existing imports):

```python
import logging
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from app.models.schemas import (
    MindmapLeaf, MindmapBranch, MindmapTree, MindmapTreeResponse,
)
from app.rag.prompts import MINDMAP_TREE_PROMPT

logger = logging.getLogger(__name__)

# Cache directory — override in tests via monkeypatch
MINDMAPS_CACHE_DIR = Path("data/mindmaps")
```

Append these functions at the END of `app/services/mindmap.py`:

```python
def _format_chunks_for_prompt(chunks: list[Document]) -> str:
    """Render chunks as numbered summaries for the mind-map LLM prompt."""
    lines = []
    for chunk in chunks:
        meta = chunk.metadata or {}
        idx = meta.get("chunk_index", "?")
        summary = (meta.get("summary") or chunk.page_content or "").strip()
        if not summary:
            summary = "(no summary)"
        # Keep each line short so prompt token count stays reasonable
        if len(summary) > 200:
            summary = summary[:197] + "..."
        lines.append(f"[{idx}] {summary}")
    return "\n".join(lines)


def _parse_tree_response(text: str, valid_indices: set[int]) -> MindmapTree:
    """Parse LLM output into a MindmapTree. Strips markdown fences,
    validates chunk_indices against the known set. Returns an empty
    tree if parsing fails — caller decides whether to cache."""
    import json as _json

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = _json.loads(text)
    except (ValueError, _json.JSONDecodeError) as e:
        logger.warning("Mindmap LLM returned invalid JSON: %s", e)
        return MindmapTree(central="", branches=[])

    central = parsed.get("central", "")
    if not isinstance(central, str):
        return MindmapTree(central="", branches=[])

    branches = []
    for b in parsed.get("branches", []):
        if not isinstance(b, dict):
            continue
        children = []
        for c in b.get("children", []):
            if not isinstance(c, dict):
                continue
            raw_indices = c.get("chunk_indices", [])
            validated = [
                i for i in raw_indices
                if isinstance(i, int) and i in valid_indices
            ]
            children.append(MindmapLeaf(
                name=str(c.get("name", "")),
                chunk_indices=validated,
            ))
        branches.append(MindmapBranch(
            name=str(b.get("name", "")),
            children=children,
        ))

    return MindmapTree(central=central, branches=branches)


def _load_cached_tree(doc_id: str) -> MindmapTree | None:
    """Return cached tree for this doc, or None if absent/unreadable."""
    import json as _json
    path = MINDMAPS_CACHE_DIR / f"{doc_id}.json"
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        return MindmapTree.model_validate(data)
    except Exception as e:
        logger.warning("Failed to read mindmap cache for %s: %s", doc_id, e)
        return None


def _save_cached_tree(doc_id: str, tree: MindmapTree) -> None:
    """Persist the tree to the cache file."""
    MINDMAPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = MINDMAPS_CACHE_DIR / f"{doc_id}.json"
    path.write_text(tree.model_dump_json(), encoding="utf-8")


async def build_mindmap_tree(
    doc_id: str,
    doc: dict,
    vector_store,
    llm: BaseChatModel,
) -> MindmapTreeResponse:
    """Return the hierarchical mind map for a doc.

    Cache-first: reads `data/mindmaps/{doc_id}.json` if present; else calls
    the LLM to derive a concept hierarchy from chunk summaries, writes the
    cache, returns the fresh result.

    Fail-safe: empty chunks -> empty tree (no LLM call). LLM failure -> empty
    tree, no cache write (retry on next request).

    Precondition: caller has verified the user owns this doc.
    """
    cached = _load_cached_tree(doc_id)
    if cached is not None:
        return MindmapTreeResponse(
            doc_id=doc_id,
            filename=doc.get("filename", "unknown"),
            cached=True,
            tree=cached,
        )

    chunks = vector_store.get_chunks_by_doc(doc_id)
    if not chunks:
        return MindmapTreeResponse(
            doc_id=doc_id,
            filename=doc.get("filename", "unknown"),
            cached=False,
            tree=MindmapTree(central="", branches=[]),
        )

    valid_indices = {
        (c.metadata or {}).get("chunk_index") for c in chunks
        if (c.metadata or {}).get("chunk_index") is not None
    }

    try:
        messages = MINDMAP_TREE_PROMPT.format_messages(
            filename=doc.get("filename", "unknown"),
            chunks=_format_chunks_for_prompt(chunks),
        )
        response = await llm.ainvoke(messages)
        text = response.content if hasattr(response, "content") else str(response)
        tree = _parse_tree_response(text, valid_indices)
    except Exception as e:
        logger.warning("Mindmap LLM call failed: %s", e)
        tree = MindmapTree(central="", branches=[])

    # Only cache if we got actual content (empty tree = failure)
    if tree.branches:
        try:
            _save_cached_tree(doc_id, tree)
        except Exception as e:
            logger.warning("Failed to cache mindmap for %s: %s", doc_id, e)

    return MindmapTreeResponse(
        doc_id=doc_id,
        filename=doc.get("filename", "unknown"),
        cached=False,
        tree=tree,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mindmap.py::TestBuildMindmapTree -v`
Expected: 5 PASSED.

- [ ] **Step 6: Run full mindmap file to check for regressions**

Run: `uv run pytest tests/test_mindmap.py -v 2>&1 | tail -10`
Expected: all tests pass (18 from Task 1 renames + 4 from Task 2 schemas + 5 from Task 3 = 27 total).

- [ ] **Step 7: Commit**

```bash
git add app/rag/prompts.py app/services/mindmap.py tests/test_mindmap.py
git commit -m "$(cat <<'EOF'
feat(mindmap): LLM-based tree builder with file cache

build_mindmap_tree() takes chunk summaries, calls gpt-4o-mini once per
doc, parses a concept hierarchy (central theme -> branches -> leaves
with chunk_indices). Caches to data/mindmaps/{doc_id}.json so repeated
views are free. Malformed LLM output -> empty tree, no cache write.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Backend — route handler for `/documents/:id/mindmap` (tree) + integration tests

Now the true mind map endpoint can be exposed.

**Files:**
- Modify: `app/routers/documents.py` (add new route)
- Test: `tests/test_mindmap.py` (extend with `TestMindmapTreeRoute`)

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/test_mindmap.py`:

```python
class TestMindmapTreeRoute:
    def test_happy_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.services.mindmap.MINDMAPS_CACHE_DIR", tmp_path,
        )

        app, stubs = _build_test_app()
        stubs["registry"].get.return_value = {
            "doc_id": "d1", "filename": "paper.pdf",
            "summary": "A paper about X", "user_id": "admin",
        }
        stubs["vector_store"].get_chunks_by_doc = MagicMock(return_value=[
            Document(page_content="x", metadata={
                "doc_id": "d1", "chunk_index": 0, "summary": "intro",
            }),
        ])

        # Override the LLM dependency to return a canned tree
        from app.dependencies import get_llm
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AIMessage(content=json_lib.dumps({
            "central": "Test paper",
            "branches": [{"name": "Topic", "children": [
                {"name": "Sub", "chunk_indices": [0]},
            ]}],
        })))
        app.dependency_overrides[get_llm] = lambda: llm

        with TestClient(app) as client:
            resp = client.get(
                "/documents/d1/mindmap",
                headers={"X-User-Id": "admin"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == "d1"
        assert data["cached"] is False
        assert data["tree"]["central"] == "Test paper"
        assert len(data["tree"]["branches"]) == 1

    def test_404_for_missing_doc(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.services.mindmap.MINDMAPS_CACHE_DIR", tmp_path,
        )
        app, stubs = _build_test_app()
        stubs["registry"].get.return_value = None

        with TestClient(app) as client:
            resp = client.get(
                "/documents/nonexistent/mindmap",
                headers={"X-User-Id": "admin"},
            )
        assert resp.status_code == 404

    def test_403_for_wrong_user(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "app.services.mindmap.MINDMAPS_CACHE_DIR", tmp_path,
        )
        app, stubs = _build_test_app()
        stubs["registry"].get.return_value = {
            "doc_id": "d1", "filename": "paper.pdf",
            "summary": "...", "user_id": "alice",
        }
        from app.dependencies import get_current_user
        app.dependency_overrides[get_current_user] = lambda: "bob"

        with TestClient(app) as client:
            resp = client.get(
                "/documents/d1/mindmap",
                headers={"X-User-Id": "bob"},
            )
        assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mindmap.py::TestMindmapTreeRoute -v`
Expected: FAIL. Most likely `404` on the route (it doesn't exist yet).

- [ ] **Step 3: Add the new route handler in `app/routers/documents.py`**

Near the top of `documents.py`, update imports:

Add to the existing `app.models.schemas` import:
```python
from app.models.schemas import DocGraphResponse, MindmapTreeResponse
```

Add to existing `app.services.mindmap` import:
```python
from app.services.mindmap import build_doc_graph, build_mindmap_tree
```

Verify `get_llm` is in the `app.dependencies` imports at top — it should be, since other routes use it.

Add the new route handler NEXT TO `get_document_graph` (the one renamed in Task 1):

```python
@router.get(
    "/{doc_id}/mindmap",
    response_model=MindmapTreeResponse,
)
async def get_document_mindmap_tree(
    doc_id: str,
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    current_user: str = Depends(get_current_user),
) -> MindmapTreeResponse:
    """Return the hierarchical mind map (tree) for one doc.

    LLM-derived concept hierarchy, cached per-doc to disk. For the
    force-graph view of the same doc, see /documents/{id}/graph.
    """
    doc = await registry.get(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if (
        settings.user_isolation != "none"
        and doc.get("user_id") != current_user
    ):
        raise HTTPException(
            status_code=403, detail="Not authorized for this document",
        )

    return await build_mindmap_tree(doc_id, doc, vector_store, llm)
```

Verify `BaseChatModel` is imported at top of file; if not, add `from langchain_core.language_models import BaseChatModel`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mindmap.py::TestMindmapTreeRoute -v`
Expected: 3 PASSED.

- [ ] **Step 5: Full mindmap file + regression check**

Run:
```bash
uv run pytest tests/test_mindmap.py tests/test_router.py tests/test_retrieval.py tests/test_config_router.py -v 2>&1 | tail -10
```
Expected: all pass (~100+ tests total).

- [ ] **Step 6: Commit**

```bash
git add app/routers/documents.py tests/test_mindmap.py
git commit -m "$(cat <<'EOF'
feat(mindmap): GET /documents/{doc_id}/mindmap (tree endpoint)

New hierarchical mind map endpoint alongside /documents/{id}/graph.
Same auth pattern, delegates to build_mindmap_tree. Respects
user_isolation. 404 for missing doc, 403 for wrong user.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Frontend — install react-d3-tree + MindmapTree component

**Files:**
- Modify: `frontend/package.json` + `frontend/package-lock.json` (via `npm install`)
- Modify: `frontend/src/lib/api.js` (split graph/mindmap helpers)
- Create: `frontend/src/hooks/useDocGraph.js`
- Modify: `frontend/src/hooks/useMindmap.js` (change to fetch tree)
- Create: `frontend/src/components/MindmapTree.jsx`

- [ ] **Step 1: Install `react-d3-tree`**

From the repo root:
```bash
cd frontend && npm install react-d3-tree
```

Expected: package added to `dependencies` in `package.json`. Verify with:
```bash
grep react-d3-tree frontend/package.json
```

- [ ] **Step 2: Split API helpers in `frontend/src/lib/api.js`**

Find the existing `fetchMindmap` export (around line 91):
```javascript
// Mindmap
export const fetchMindmap = (docId, userId) =>
  apiFetch(`/documents/${docId}/mindmap`, { headers: headers(userId) })
```

Replace with:
```javascript
// Doc graph (chunks + edges, force-directed)
export const fetchDocGraph = (docId, userId) =>
  apiFetch(`/documents/${docId}/graph`, { headers: headers(userId) })

// Mindmap (hierarchical tree)
export const fetchMindmap = (docId, userId) =>
  apiFetch(`/documents/${docId}/mindmap`, { headers: headers(userId) })
```

- [ ] **Step 3: Create `frontend/src/hooks/useDocGraph.js`**

```javascript
import { useQuery } from '@tanstack/react-query'
import { fetchDocGraph } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Fetches the force-graph data (chunks + edges) for one doc.
 */
export function useDocGraph(docId) {
  return useQuery({
    queryKey: ['doc-graph', docId],
    queryFn: () => fetchDocGraph(docId, USER_ID),
    staleTime: 5 * 60 * 1000,
    enabled: !!docId,
  })
}
```

- [ ] **Step 4: Update `frontend/src/hooks/useMindmap.js` to fetch tree**

Current file fetches the graph endpoint. Replace its contents with:

```javascript
import { useQuery } from '@tanstack/react-query'
import { fetchMindmap } from '@/lib/api'

const USER_ID = 'admin'

/**
 * Fetches the hierarchical mind map tree for one doc.
 * LLM-derived, cached on the backend per-doc.
 */
export function useMindmap(docId) {
  return useQuery({
    queryKey: ['mindmap', docId],
    queryFn: () => fetchMindmap(docId, USER_ID),
    staleTime: 5 * 60 * 1000,
    enabled: !!docId,
  })
}
```

- [ ] **Step 5: Create `frontend/src/components/MindmapTree.jsx`**

```jsx
import { useMemo } from 'react'
import Tree from 'react-d3-tree'

/**
 * Radial tree visualization for the hierarchical mind map.
 *
 * Props:
 *  - tree: { central, branches: [{ name, children: [{ name, chunk_indices }] }] }
 *  - onLeafClick: (leaf, branchName) => void, triggered when a leaf concept is clicked
 */
export default function MindmapTree({ tree, onLeafClick }) {
  // Transform to react-d3-tree shape: one root, recursive children
  const d3Data = useMemo(() => {
    if (!tree) return null
    return {
      name: tree.central || '...',
      _kind: 'central',
      children: (tree.branches || []).map(b => ({
        name: b.name,
        _kind: 'branch',
        children: (b.children || []).map(leaf => ({
          name: leaf.name,
          _kind: 'leaf',
          _chunk_indices: leaf.chunk_indices,
          _branch_name: b.name,
          attributes: { chunks: leaf.chunk_indices?.length || 0 },
        })),
      })),
    }
  }, [tree])

  if (!d3Data) return null

  const handleNodeClick = (node) => {
    const data = node.data
    if (data._kind === 'leaf' && onLeafClick) {
      onLeafClick({
        name: data.name,
        chunk_indices: data._chunk_indices,
        branch_name: data._branch_name,
      })
    }
  }

  const renderNode = ({ nodeDatum, toggleNode }) => {
    const kind = nodeDatum._kind
    const fill =
      kind === 'central' ? '#3b82f6' :
      kind === 'branch' ? '#6366f1' :
      '#10b981'
    const radius =
      kind === 'central' ? 12 :
      kind === 'branch' ? 8 :
      5
    return (
      <g onClick={toggleNode}>
        <circle r={radius} fill={fill} stroke="#fff" strokeWidth={1.5} />
        <text
          fill="currentColor"
          strokeWidth="0"
          x={radius + 6}
          y={4}
          fontSize={kind === 'central' ? 14 : 12}
          fontWeight={kind === 'central' ? 600 : 400}
          style={{ fontFamily: 'inherit' }}
        >
          {nodeDatum.name}
        </text>
      </g>
    )
  }

  return (
    <Tree
      data={d3Data}
      orientation="horizontal"
      translate={{ x: 200, y: 400 }}
      pathFunc="diagonal"
      separation={{ siblings: 1, nonSiblings: 1.3 }}
      renderCustomNodeElement={renderNode}
      onNodeClick={handleNodeClick}
      collapsible={false}
      zoom={0.9}
      scaleExtent={{ min: 0.3, max: 2 }}
    />
  )
}
```

- [ ] **Step 6: Verify build**

```bash
cd frontend && npm run build 2>&1 | tail -6
```
Expected: build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/lib/api.js frontend/src/hooks/useDocGraph.js frontend/src/hooks/useMindmap.js frontend/src/components/MindmapTree.jsx
git commit -m "$(cat <<'EOF'
feat(mindmap): add react-d3-tree MindmapTree component + split hooks

fetchMindmap / useMindmap now target the hierarchical tree endpoint.
fetchDocGraph / useDocGraph target the force-graph endpoint. The new
MindmapTree component renders a radial tree with central/branch/leaf
node styling; clicking a leaf fires onLeafClick with chunk_indices.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Frontend — MindmapPage mode toggle + NodePanel adaptation

The page now handles two modes, selected via `?mode=` URL param.

**Files:**
- Modify: `frontend/src/pages/MindmapPage.jsx` (mode toggle + dual-mode render)
- Modify: `frontend/src/components/MindmapNodePanel.jsx` (show leaf concept + chunk refs in tree mode)
- Modify: `frontend/src/i18n/locales/en.json` (new keys)
- Modify: `frontend/src/i18n/locales/zh.json` (new keys)

- [ ] **Step 1: Add i18n keys in both locale files**

In `E:\MEINRAG\frontend\src\i18n\locales\en.json`, find the existing `mindmap` section. Add these keys to it:

```json
    "modeTree": "Mind Map",
    "modeGraph": "Graph",
    "cached": "cached",
    "concept": "Concept",
    "supportingChunks": "Supporting chunks",
    "openChunk": "Open chunk",
    "emptyTree": "No mind map yet. It will generate on first view."
```

In `zh.json`, add the Chinese equivalents:

```json
    "modeTree": "思维导图",
    "modeGraph": "图谱",
    "cached": "缓存",
    "concept": "概念",
    "supportingChunks": "相关片段",
    "openChunk": "打开片段",
    "emptyTree": "还没有思维导图。首次访问时会自动生成。"
```

Validate JSON:
```bash
uv run python -c "import json; json.load(open('frontend/src/i18n/locales/en.json', encoding='utf-8'))"
uv run python -c "import json; json.load(open('frontend/src/i18n/locales/zh.json', encoding='utf-8'))"
```
Both should complete silently.

- [ ] **Step 2: Rewrite `frontend/src/pages/MindmapPage.jsx`**

Replace the entire file contents with:

```jsx
import { useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Brain, Network } from 'lucide-react'
import { useMindmap } from '@/hooks/useMindmap'
import { useDocGraph } from '@/hooks/useDocGraph'
import MindmapTree from '@/components/MindmapTree'
import MindmapGraph from '@/components/MindmapGraph'
import MindmapLegend from '@/components/MindmapLegend'
import MindmapNodePanel from '@/components/MindmapNodePanel'

const DEFAULT_EDGE_TYPES = new Set(['follows', 'describes', 'references'])

function ModeToggle({ mode, setMode, t }) {
  const btnCls = (active) =>
    `px-3 py-1.5 text-sm border flex items-center gap-2 transition ${
      active
        ? 'bg-[var(--border-strong)] text-[var(--fg)]'
        : 'opacity-70 hover:opacity-100'
    }`
  return (
    <div className="inline-flex rounded overflow-hidden border border-[var(--border-strong)]">
      <button
        type="button"
        className={btnCls(mode === 'tree')}
        onClick={() => setMode('tree')}
      >
        <Brain className="h-4 w-4" />
        {t('mindmap.modeTree')}
      </button>
      <button
        type="button"
        className={btnCls(mode === 'graph')}
        onClick={() => setMode('graph')}
      >
        <Network className="h-4 w-4" />
        {t('mindmap.modeGraph')}
      </button>
    </div>
  )
}

export default function MindmapPage() {
  const { docId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const mode = searchParams.get('mode') === 'graph' ? 'graph' : 'tree'
  const setMode = (m) => {
    setSearchParams(p => {
      const np = new URLSearchParams(p)
      np.set('mode', m)
      return np
    })
  }

  const navigate = useNavigate()
  const { t } = useTranslation()

  const treeQuery = useMindmap(mode === 'tree' ? docId : null)
  const graphQuery = useDocGraph(mode === 'graph' ? docId : null)

  const active = mode === 'tree' ? treeQuery : graphQuery
  const { data, isLoading, error } = active

  const [selectedNode, setSelectedNode] = useState(null)
  const [selectedLeaf, setSelectedLeaf] = useState(null)
  const [enabledEdgeTypes, setEnabledEdgeTypes] = useState(
    new Set(DEFAULT_EDGE_TYPES),
  )

  const toggleEdgeType = (type) => {
    setEnabledEdgeTypes(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const openInPdf = () => {
    const target = selectedNode
    if (!target) return
    const params = new URLSearchParams()
    if (target.page != null) params.set('page', target.page)
    params.set('chunk', target.chunk_index)
    navigate(`/pdf/${docId}?${params.toString()}`)
  }

  const openChunkInPdf = (chunkIndex) => {
    const params = new URLSearchParams()
    params.set('chunk', chunkIndex)
    navigate(`/pdf/${docId}?${params.toString()}`)
  }

  // Tree mode: on leaf click we stash the leaf + its chunk_indices for the side panel
  const onTreeLeafClick = (leaf) => {
    setSelectedLeaf(leaf)
    setSelectedNode(null)
  }

  // Graph mode: on node click we stash the node
  const onGraphNodeClick = (node) => {
    setSelectedNode(node)
    setSelectedLeaf(null)
  }

  // Content area
  let content
  if (isLoading) {
    content = <div className="p-8 opacity-70">{t('mindmap.loading')}</div>
  } else if (error) {
    content = <div className="p-8 text-red-400">{t('mindmap.error')}</div>
  } else if (!data) {
    content = null
  } else if (mode === 'tree') {
    if (!data.tree || !data.tree.branches || data.tree.branches.length === 0) {
      content = <div className="p-8 opacity-70 text-center">{t('mindmap.emptyTree')}</div>
    } else {
      content = (
        <div className="h-full">
          <MindmapTree tree={data.tree} onLeafClick={onTreeLeafClick} />
        </div>
      )
    }
  } else {
    if (!data.nodes || data.nodes.length === 0) {
      content = <div className="p-8 opacity-70 text-center">{t('mindmap.empty')}</div>
    } else {
      const visibleEdges = (data.edges || []).filter(
        e => enabledEdgeTypes.has(e.relation),
      )
      content = (
        <MindmapGraph
          nodes={data.nodes}
          edges={visibleEdges}
          onNodeClick={onGraphNodeClick}
          selectedId={selectedNode?.id}
        />
      )
    }
  }

  const filename = data?.filename || ''
  const docSummary = mode === 'tree' ? data?.tree?.central : data?.doc_summary

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col min-w-0">
        <header className="p-4 border-b border-[var(--border-strong)] flex items-center gap-4">
          <button
            type="button"
            onClick={() => navigate(-1)}
            aria-label={t('mindmap.back')}
            className="p-2 rounded hover:bg-[var(--border-strong)] transition"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="text-lg font-semibold truncate">{filename}</h1>
            {docSummary && (
              <p className="text-sm opacity-70 line-clamp-1">{docSummary}</p>
            )}
          </div>
          <ModeToggle mode={mode} setMode={setMode} t={t} />
        </header>

        <main className="flex-1 relative">{content}</main>
      </div>

      <aside className="w-80 border-l border-[var(--border-strong)] overflow-y-auto">
        {mode === 'graph' && data?.stats && (
          <MindmapLegend
            stats={data.stats}
            enabledEdgeTypes={enabledEdgeTypes}
            onToggleEdgeType={toggleEdgeType}
          />
        )}
        {mode === 'graph' && selectedNode && (
          <MindmapNodePanel
            node={selectedNode}
            onOpenInPdf={openInPdf}
            onClose={() => setSelectedNode(null)}
          />
        )}
        {mode === 'tree' && selectedLeaf && (
          <MindmapNodePanel
            leaf={selectedLeaf}
            onOpenChunk={openChunkInPdf}
            onClose={() => setSelectedLeaf(null)}
          />
        )}
      </aside>
    </div>
  )
}
```

- [ ] **Step 3: Update `frontend/src/components/MindmapNodePanel.jsx` to support both modes**

Replace entire file contents with:

```jsx
import { useTranslation } from 'react-i18next'
import { X, ExternalLink } from 'lucide-react'

/**
 * Dual-purpose panel.
 * - Graph mode: pass `node` (a MindmapGraph node) + `onOpenInPdf`
 * - Tree mode: pass `leaf` (a tree leaf with name + chunk_indices + branch_name)
 *              + `onOpenChunk(chunkIndex)`
 */
export default function MindmapNodePanel({
  node,
  leaf,
  onOpenInPdf,
  onOpenChunk,
  onClose,
}) {
  const { t } = useTranslation()

  if (leaf) {
    return (
      <div className="p-4 border-t border-[var(--border-strong)]">
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-medium">{t('mindmap.concept')}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1 rounded hover:bg-[var(--border-strong)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <p className="text-sm font-medium mb-2">{leaf.name}</p>
        {leaf.branch_name && (
          <p className="text-xs opacity-70 mb-3">↳ {leaf.branch_name}</p>
        )}
        <h4 className="text-xs font-medium mb-2 opacity-70 uppercase tracking-wide">
          {t('mindmap.supportingChunks')}
        </h4>
        <div className="space-y-1">
          {(leaf.chunk_indices || []).map(idx => (
            <button
              key={idx}
              type="button"
              onClick={() => onOpenChunk(idx)}
              className="w-full flex items-center justify-between px-2 py-1.5 text-sm rounded hover:bg-[var(--border-strong)] transition"
            >
              <span>{t('mindmap.chunk')} {idx}</span>
              <ExternalLink className="h-3 w-3 opacity-60" />
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (!node) return null

  return (
    <div className="p-4 border-t border-[var(--border-strong)]">
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-medium">
          {t('mindmap.chunk')} {node.chunk_index}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="p-1 rounded hover:bg-[var(--border-strong)]"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex gap-2 mb-3 flex-wrap">
        <span className="text-xs px-2 py-0.5 rounded bg-[var(--border-strong)]">
          {node.chunk_type}
        </span>
        {node.section_type && (
          <span className="text-xs px-2 py-0.5 rounded border border-[var(--border-strong)]">
            {node.section_type}
          </span>
        )}
        {node.page != null && (
          <span className="text-xs px-2 py-0.5 rounded border border-[var(--border-strong)]">
            {t('mindmap.page')}{node.page}
          </span>
        )}
      </div>
      <p className="text-sm mb-4 whitespace-pre-wrap opacity-90">
        {node.full_summary || node.label}
      </p>
      <button
        type="button"
        onClick={onOpenInPdf}
        className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded bg-[var(--border-strong)] hover:opacity-80 transition"
      >
        <ExternalLink className="h-4 w-4" />
        {t('mindmap.openInPdf')}
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Verify frontend builds**

```bash
cd frontend && npm run build 2>&1 | tail -6
```
Expected: build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/MindmapPage.jsx frontend/src/components/MindmapNodePanel.jsx frontend/src/i18n/locales/en.json frontend/src/i18n/locales/zh.json
git commit -m "$(cat <<'EOF'
feat(mindmap): dual-mode page — Mind Map (tree) + Graph (force)

MindmapPage now renders either the hierarchical tree or the force
graph based on the ?mode= URL param. Mode toggle in the header.
NodePanel adapts: tree mode shows selected concept + supporting
chunks (each clickable to open PDF); graph mode shows chunk details
(original behavior).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Frontend — Dashboard entry with both modes + final push

Update the Dashboard to surface both views as separate entry points (user's explicit ask), then ship.

**Files:**
- Modify: `frontend/src/pages/DashboardPage.jsx` (add a second entry point + relabel existing)

- [ ] **Step 1: Find the existing mindmap entry point in DashboardPage**

Open `E:\MEINRAG\frontend\src\pages\DashboardPage.jsx`. Find the existing mindmap button — it was added in the last mindmap task and uses the `Waypoints` icon and navigates to `/mindmap/${doc_id}`.

Look for something like:
```jsx
import { Waypoints } from 'lucide-react'
// ...
<button ... onClick={() => navigate(`/mindmap/${doc.doc_id}`)} ...>
  <Waypoints className="h-4 w-4" />
</button>
```

Note the exact pattern (icon-button vs dropdown item) so the second entry matches.

- [ ] **Step 2: Make both modes reachable**

Replace the single mindmap entry with TWO entries. Use `Brain` icon for Mind Map (tree) and keep `Waypoints` or switch to `Network` for Graph.

If the existing action pattern is icon-only buttons, add two side-by-side:
```jsx
import { Brain, Network } from 'lucide-react'
// ...
<button
  type="button"
  onClick={() => navigate(`/mindmap/${doc.doc_id}?mode=tree`)}
  title={t('mindmap.modeTree')}
  aria-label={t('mindmap.modeTree')}
  className="<match existing action button classes>"
>
  <Brain className="h-4 w-4" />
</button>
<button
  type="button"
  onClick={() => navigate(`/mindmap/${doc.doc_id}?mode=graph`)}
  title={t('mindmap.modeGraph')}
  aria-label={t('mindmap.modeGraph')}
  className="<match existing action button classes>"
>
  <Network className="h-4 w-4" />
</button>
```

If the existing pattern is a dropdown menu, add two menu items:
```jsx
<DropdownMenuItem onClick={() => navigate(`/mindmap/${doc.doc_id}?mode=tree`)}>
  <Brain className="h-4 w-4 mr-2" />
  {t('mindmap.modeTree')}
</DropdownMenuItem>
<DropdownMenuItem onClick={() => navigate(`/mindmap/${doc.doc_id}?mode=graph`)}>
  <Network className="h-4 w-4 mr-2" />
  {t('mindmap.modeGraph')}
</DropdownMenuItem>
```

Also update the context menu (the right-click menu on graph nodes) if it was added by the previous mindmap task — same structure, two items.

Remove the existing `Waypoints` icon usage if it duplicates one of the new entries.

- [ ] **Step 3: Verify builds**

```bash
cd frontend && npm run build 2>&1 | tail -6
```
Expected: build succeeds.

- [ ] **Step 4: Run focused tests one more time**

```bash
uv run pytest tests/test_mindmap.py tests/test_router.py tests/test_retrieval.py tests/test_config_router.py -v 2>&1 | tail -10
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/DashboardPage.jsx
git commit -m "$(cat <<'EOF'
feat(mindmap): Dashboard surfaces both Mind Map and Graph as separate entries

Users can now pick which view they want when entering from a doc —
Mind Map (tree) or Graph (force-directed). Both go to the same
page; mode is carried via ?mode= URL param.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Push**

```bash
git push origin main
```

- [ ] **Step 7: Report**

Status: DONE | BLOCKED
- Final HEAD SHA
- Commit count between predecessor (`61bf14e`) and HEAD
- Confirm both Mind Map and Graph entry points visible on Dashboard

---

## Self-Review

**Spec coverage:**
- Tree endpoint with LLM + cache → Tasks 2, 3, 4 ✓
- Graph endpoint renamed (was `/mindmap`, now `/graph`) → Task 1 ✓
- Frontend tree renderer with react-d3-tree → Task 5 ✓
- Mode toggle in UI → Task 6 ✓
- Dashboard exposes both entries → Task 7 ✓
- User's explicit ask ("we can choose to view") → Task 7 + Task 6 (in-page toggle too)

**Placeholder scan:**
- No "TBD" / "implement later" — all steps have exact code
- One spot in Task 7 Step 2 has `<match existing action button classes>` in the example — this is because the Dashboard's exact styling isn't known. The operator reads the file to match existing pattern — same as we did in mindmap v0's Task 8. Not a plan failure.
- All imports are real (`BaseChatModel` from `langchain_core.language_models`, `get_llm` from `app.dependencies`, `useSearchParams` from `react-router-dom`).

**Type consistency:**
- `build_mindmap_tree(doc_id, doc, vector_store, llm) -> MindmapTreeResponse` — Task 3 definition matches Task 4 route use.
- `MindmapTree.central`, `MindmapTree.branches` → `MindmapBranch.children` → `MindmapLeaf.chunk_indices` — consistent across tasks 2, 3, 5 (tree component).
- Route renames in Task 1 are echoed in frontend Task 5 (`fetchDocGraph` hits `/documents/:id/graph`).
- `?mode=tree` vs `?mode=graph` — Tasks 6, 7 agree.

**Risks called out:**
- Task 5 Step 1: `react-d3-tree` is a new dependency; confirmed with user (Q2 yes).
- Task 3: LLM costs ~$0.002 per doc, cached per-doc; confirmed with user (Q1 yes).
- Task 3 file cache at `data/mindmaps/{doc_id}.json` — directory created on first cache write. Gitignore-relevant: `data/mindmaps/` should probably be in `.gitignore` like other `data/` caches. If already in `.gitignore` via a broader `data/` rule, fine.
- Task 7: Dashboard structure unknown at plan time — instructions tell operator to read the file and match the pattern. Same pattern as mindmap v0.

**What this plan does NOT do (intentional v0 scope):**
- No cache invalidation hook on doc re-upload (cache gets stale; user manually deletes `data/mindmaps/{doc_id}.json` or re-uploads forces new chunks which will still hit the stale cache unless we add invalidation). Flag for a follow-up task if doc re-uploads are common in practice.
- No language-specific tuning of the LLM prompt (it says "match the document's predominant language" but doesn't detect it explicitly).
- No streaming of the LLM generation (waits for full response — 1-3s wait on first view of each doc).
