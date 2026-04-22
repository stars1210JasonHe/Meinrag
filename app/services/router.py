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
        title = d.get("filename") or d.get("source_file") or d.get("title") or did
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
