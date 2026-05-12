"""Multi-doc mindmap — synthesises one concept tree across N documents.

Lives next to app/services/mindmap.py (the single-doc equivalent). The
shape is the same recursive tree, but leaves cite chunks via
``chunks_by_doc: {doc_id: [chunk_indices]}`` so the renderer can derive
per-doc coverage in O(1) and draw the colour blocks that visualise
"do all N docs cover this concept?".

Cache: one file per (sorted) doc-id set at
``data/mindmaps_multi/<sha16>.json``. Invalidated by
``invalidate_caches_for_doc(doc_id)`` when a single doc is deleted.

Consumed by GET /graph/mindmap-multi in app/routers/graph.py.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel

from app.models.schemas import (
    MultiMindmapNode, MultiMindmapTree, MultiMindmapResponse,
)
from app.rag.prompts import MULTI_MINDMAP_TREE_PROMPT
from app.services.mindmap import MINDMAPS_CACHE_DIR

logger = logging.getLogger(__name__)

# Separate cache dir from single-doc mindmaps. Sits alongside it so
# clean-up can sweep both with the same pattern when the user deletes
# everything.
MULTI_MINDMAPS_CACHE_DIR = Path("data/mindmaps_multi")
MULTI_MINDMAP_MAX_DEPTH = 4

# Limit how many chunks we feed the LLM per doc. Generous enough that
# we capture the doc's structure but bounded enough that 10 docs × this
# stays under gpt-4o-mini's comfortable input window.
CHUNKS_PER_DOC_CAP = 60

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _cache_key(doc_ids: list[str]) -> str:
    """Order-independent hash of the doc-id set. Adding a new doc to the
    selection produces a different cache key."""
    canonical = ",".join(sorted(doc_ids))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _cache_path(doc_ids: list[str]) -> Path:
    return MULTI_MINDMAPS_CACHE_DIR / f"{_cache_key(doc_ids)}.json"


def _load_cached(doc_ids: list[str]) -> MultiMindmapTree | None:
    path = _cache_path(doc_ids)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return MultiMindmapTree.model_validate(data)
    except Exception as e:
        logger.warning("Failed to read multi-mindmap cache %s: %s", path.name, e)
        return None


def _save_cached(doc_ids: list[str], tree: MultiMindmapTree) -> None:
    MULTI_MINDMAPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(doc_ids)
    # Also persist the doc_id set as part of the file so a future cleanup
    # job can identify which docs each cache covers without re-deriving.
    payload = tree.model_dump()
    payload["__doc_ids"] = sorted(doc_ids)
    path.write_text(json.dumps(payload), encoding="utf-8")


def invalidate_caches_for_doc(doc_id: str) -> int:
    """Remove every multi-doc mindmap cache that includes ``doc_id`` in
    its doc set. Called from the single-doc delete handler so a stale
    tree referencing a removed doc never resurfaces. Returns the number
    of files removed (mostly for logging)."""
    if not MULTI_MINDMAPS_CACHE_DIR.exists():
        return 0
    removed = 0
    for path in MULTI_MINDMAPS_CACHE_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if doc_id in (payload.get("__doc_ids") or []):
                path.unlink()
                removed += 1
        except Exception as e:
            logger.warning("Skipping unreadable cache %s: %s", path.name, e)
    if removed:
        logger.info("Invalidated %d multi-mindmap cache(s) referencing %s",
                    removed, doc_id)
    return removed


def _format_chunks_for_prompt(
    doc_chunks: dict[str, list[Document]],
) -> str:
    """Render chunks as ``[doc_id::index] summary`` lines for the LLM.
    Caps each doc at CHUNKS_PER_DOC_CAP — drops by chunk_index order so
    we keep the doc's beginning + middle structure intact."""
    lines: list[str] = []
    for doc_id, chunks in doc_chunks.items():
        # Sort by chunk_index for deterministic top-N selection.
        sorted_chunks = sorted(
            chunks,
            key=lambda c: (c.metadata or {}).get("chunk_index", 0),
        )
        for chunk in sorted_chunks[:CHUNKS_PER_DOC_CAP]:
            meta = chunk.metadata or {}
            idx = meta.get("chunk_index", "?")
            summary = (meta.get("summary") or chunk.page_content or "").strip()
            if not summary:
                summary = "(no summary)"
            if len(summary) > 200:
                summary = summary[:197] + "..."
            lines.append(f"[{doc_id}::{idx}] {summary}")
    return "\n".join(lines)


def _format_doc_menu(filename_by_doc_id: dict[str, str]) -> str:
    return "\n".join(f"  {filename} → {doc_id}"
                     for doc_id, filename in filename_by_doc_id.items())


def _parse_node(
    raw,
    valid_indices_by_doc: dict[str, set[int]],
    depth: int,
) -> MultiMindmapNode | None:
    """Recursively parse one multi-doc mindmap node. Returns None if
    malformed (no name) so caller can drop it.

    Depth contract identical to single-doc: at depth >= MAX_DEPTH-1 the
    node is forced to be a leaf (children dropped) so a runaway LLM can't
    produce 5+ levels.
    """
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name", "")).strip()
    if not name:
        return None

    raw_children = raw.get("children")
    can_recurse = depth < MULTI_MINDMAP_MAX_DEPTH - 1
    if can_recurse and isinstance(raw_children, list) and raw_children:
        parsed_children = [
            _parse_node(c, valid_indices_by_doc, depth + 1)
            for c in raw_children
        ]
        parsed_children = [p for p in parsed_children if p is not None]
        if parsed_children:
            return MultiMindmapNode(
                name=name, chunks_by_doc=None, children=parsed_children,
            )

    raw_chunks = raw.get("chunks_by_doc") or {}
    validated: dict[str, list[int]] = {}
    if isinstance(raw_chunks, dict):
        for doc_id, idxs in raw_chunks.items():
            # Doc id must be in the requested set — LLM hallucinated ids
            # would otherwise leak through.
            valid = valid_indices_by_doc.get(doc_id)
            if valid is None or not isinstance(idxs, list):
                continue
            kept = [i for i in idxs if isinstance(i, int) and i in valid]
            if kept:
                validated[doc_id] = kept
    return MultiMindmapNode(
        name=name, chunks_by_doc=validated or None, children=None,
    )


def _parse_tree_response(
    text: str,
    valid_indices_by_doc: dict[str, set[int]],
) -> tuple[str, list[MultiMindmapNode]]:
    """Parse LLM output into (central, branches). Returns empty branches
    if parsing fails — caller decides whether to cache."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("Multi-mindmap LLM returned invalid JSON: %s", e)
        return "", []

    central = parsed.get("central", "")
    if not isinstance(central, str):
        return "", []

    branches: list[MultiMindmapNode] = []
    for b in parsed.get("branches", []):
        node = _parse_node(b, valid_indices_by_doc, depth=1)
        if node is not None:
            branches.append(node)
    return central, branches


def _resolve_doc_palette(doc_ids: list[str]) -> dict[str, str]:
    """Read each doc's cached single-doc mindmap and pull palette.central.
    Falls back to a deterministic hash colour for docs that have no
    mindmap cached yet. Never triggers an LLM call — the multi-doc tree
    is already paying for one and the doc identity colour can degrade
    gracefully.
    """
    FALLBACK_HUES = [
        "#6b8fd6", "#d4a64a", "#4ade80", "#f472b6", "#a78bfa",
    ]
    palette: dict[str, str] = {}
    for doc_id in doc_ids:
        single_path = MINDMAPS_CACHE_DIR / f"{doc_id}.json"
        chosen: str | None = None
        if single_path.exists():
            try:
                payload = json.loads(single_path.read_text(encoding="utf-8"))
                central = (payload.get("palette") or {}).get("central")
                if isinstance(central, str) and _HEX_RE.match(central):
                    chosen = central
            except Exception:
                pass
        if chosen is None:
            # Deterministic fallback: hash → bucket.
            bucket = sum(ord(c) for c in doc_id) % len(FALLBACK_HUES)
            chosen = FALLBACK_HUES[bucket]
        palette[doc_id] = chosen
    return palette


async def build_multi_mindmap(
    doc_ids: list[str],
    docs_by_id: dict[str, dict],
    vector_store,
    llm: BaseChatModel,
) -> MultiMindmapResponse:
    """Return the synthesised mindmap for ``doc_ids``.

    Cache-first: hits ``data/mindmaps_multi/<key>.json`` if present, else
    calls the LLM with chunks from all docs (capped per doc) and writes
    the cache.

    Precondition: caller has filtered doc_ids to ones the user owns and
    that exist. ``docs_by_id`` maps each doc_id to the registry dict
    (used for filename rendering in the prompt).
    """
    sorted_ids = sorted(doc_ids)
    if not sorted_ids:
        return MultiMindmapResponse(
            doc_ids=[], cached=False,
            tree=MultiMindmapTree(central="", branches=[], palette={}),
        )

    cached = _load_cached(sorted_ids)
    if cached is not None:
        return MultiMindmapResponse(
            doc_ids=sorted_ids, cached=True, tree=cached,
        )

    # Gather chunks per doc.
    doc_chunks: dict[str, list[Document]] = {}
    valid_indices_by_doc: dict[str, set[int]] = {}
    for doc_id in sorted_ids:
        chunks = vector_store.get_chunks_by_doc(doc_id) or []
        doc_chunks[doc_id] = chunks
        valid_indices_by_doc[doc_id] = {
            (c.metadata or {}).get("chunk_index")
            for c in chunks
            if (c.metadata or {}).get("chunk_index") is not None
        }

    if not any(doc_chunks.values()):
        # Every doc was empty — return a stub tree, don't cache.
        return MultiMindmapResponse(
            doc_ids=sorted_ids, cached=False,
            tree=MultiMindmapTree(central="", branches=[], palette={}),
        )

    filename_by_doc_id = {
        doc_id: (docs_by_id.get(doc_id) or {}).get("filename", doc_id)
        for doc_id in sorted_ids
    }

    palette = _resolve_doc_palette(sorted_ids)

    try:
        messages = MULTI_MINDMAP_TREE_PROMPT.format_messages(
            doc_menu=_format_doc_menu(filename_by_doc_id),
            chunks=_format_chunks_for_prompt(doc_chunks),
        )
        response = await llm.ainvoke(messages)
        text = response.content if hasattr(response, "content") else str(response)
        central, branches = _parse_tree_response(text, valid_indices_by_doc)
    except Exception as e:
        logger.warning("Multi-mindmap LLM call failed: %s", e)
        central, branches = "", []

    tree = MultiMindmapTree(
        central=central, branches=branches, palette=palette,
    )

    if branches:
        try:
            _save_cached(sorted_ids, tree)
        except Exception as e:
            logger.warning("Failed to cache multi-mindmap: %s", e)

    return MultiMindmapResponse(
        doc_ids=sorted_ids, cached=False, tree=tree,
    )
